# Mustart EVSE firmware: static analysis findings (Nov 23, 2026)

Target: `stm32f030c8_fw_dump1.bin` (64 KB, SHA-256 `09bb83f3…ec0f28b`), read via SWD at RDP level 0.
Tooling: Ghidra 12.2 headless, `ARM:LE:32:Cortex` (Thumb), base `0x08000000`, with an STM32F030 memory map and vector-table function seeding.
Full decompilation is in `ghidra_export/decomp.c`; function list in `ghidra_export/functions.txt`.
(REA's Ghidra bridge was tried first, but it only supports generic ARM mode, not Thumb/Cortex-M, so it wasn't used for conclusions.)

Everything below is **static analysis**: the code was read, not run. "Observed" means seen directly in the code or bytes; "inferred" means an interpretation.

## 1. USART1, the port wired to M1 (PA9/PA10, MCU pins 30/31), is never used. *Observed.*
- Its interrupt vector points to the shared default handler (an infinite loop at `0x080000fc`). Real handlers exist only for USART2, TIM3, TIM14, TIM16, DMA1 Ch1 and DMA1 Ch4/5.
- The USART1 clock is never enabled. The only writes to `RCC_APB2ENR` are `0x200` (ADC), via `FUN_0800321c`, plus the standard CMSIS startup code enabling SYSCFG in the boot-from-system-memory case.
- `USART_Init` (`FUN_08003b3c`, ST Standard Peripheral Library) is called exactly **once**, with USART2. The single USART1 address in the image is inside that library function's clock-source lookup.

**Conclusion:** this firmware has no code that talks on the M1 footprint. Theory 1 is confirmed. A model-select resistor (theory 3) cannot help, because there is no USART1/Wi-Fi code for it to switch on.

## 2. The firmware does run a serial port: USART2 on PA14/PA15, 9600 baud. *Observed.*
- `FUN_080017c0(0x2580)` sets up USART2 at **9600 baud**: 8N1, TX+RX (mode `0xC`), RXNE/IDLE handling, with DMA receive. `FUN_08001ea4` calls it with a 100-byte buffer.
- Pin setup (`FUN_08001714`): GPIOA pins **14 and 15** switched to alternate function 1 (`0xC000` mask) = **USART2_TX on PA14, USART2_RX on PA15**.
- **PA14 is SWCLK (header pin 6).** Taking it over for USART2 is why SWD stops working after boot.
- PA15 is MCU **pin 38**. Which header pin it reaches (4 or 7?) has not been checked yet.
- The receive path uses DMA plus the USART2 IDLE interrupt (`USART2_IRQ` at `0x08003a2c`). A complete frame of more than 10 bytes is parsed in `FUN_08002158`.

## 3. The USART2 protocol is not Tuya. *Observed framing; purpose inferred.*
- Byte stuffing with escape byte `0x27`: `27 15` → `EB`, `27 70` → `90`, `27 D9` → `27`. So the frames likely start with `0xEB` and end with `0x90`. *(Inferred from the escape table.)*
- Header: byte 1 must be `0x0A` or `0x08`, and byte 2 must be `0x00` (addressing). Bytes 1–2 and 3–4 are swapped in the reply (source/destination). Bytes 5–6 hold a 16-bit length. Byte 7 is the command.
- Checksum: 16-bit sum of bytes 1 … len-4, stored little-endian just before the end byte (`FUN_08003c3e`).
- Commands seen in the dispatcher (`FUN_08002158` → `FUN_0800224c` / `FUN_08001f08`):
  - `0x07`: sub-command 1/3 replies with 12 bytes from a config block. Sub-command 2/3 with `'P','P'` and `'U'` markers **writes** 12 bytes into config and saves it (`FUN_08002a8c(..., 0x17)`; *inferred* to be a flash/config save).
  - `0x55`-class requests with `'P','P'` magic: sub-commands `0x97` and `0x98` **write** several 16-bit parameters (`FUN_08001cfc(3/4/5)`) and reply with values. `0xAF` replies `55 AA` plus a 0x17-halfword config block.
- `0x55 … 0xAA` are used as payload markers inside replies. They are not a Tuya header: there's no Tuya heartbeat (`0x00`), product query (`0x01`) or data-point handling anywhere in the image.
- **Inferred purpose:** a factory calibration/configuration port, or an interface for a separate comms daughterboard on the 7-pin header (it carries 3.3 V, GND, NRST, SWD and this UART). **Some commands write settings, so never send anything to it blind.**

## 4. Other observations
- Startup is standard ST CMSIS (`Reset_Handler` → `SystemInit` `0x080035d9` → main `0x080000b5`).
- DMA1 Ch1 handler is present (probably ADC sampling: CT, pilot and RCD). The ADC clock is enabled.
- Timers in use: TIM3, TIM14, TIM16 (pilot PWM, timebase).
- The image runs to `0x0800FD4F`; the top area holds additional code and data (not yet characterised).

## Open questions / next steps
1. ~~Continuity check~~ **Done: PA15 (MCU pin 38) = header pin 7.** The live serial port is **header 6 = MCU TX**, **header 7 = MCU RX**, **header 5 = GND**, **header 1 = 3.3 V**. The Nov 23 analyzer capture saw no activity on either pin for ~84 s after power-up, so the MCU probably only replies when asked.
2. Passive capture of header pin 6 at 9600 baud while the charger runs, to see whether the MCU ever transmits unprompted (e.g. periodic status).
3. Decode in more detail which commands only **read** (e.g. `0xAF`, `0x07` sub-command 1) and what values they return. If they include live current/energy readings, this port could serve the real goal (charge rate and kWh) through the ESP, read-only.
4. The display code (SPI OLED) and ADC scaling could also show where the A/kW/kWh values live in RAM.

## 5. USART2 protocol, fully mapped (Nov 23, step 1)

### Buffers (RAM)
- RX frame buffer `0x200002BA` (100 B, DMA ch5); TX buffer `0x20000256` (100 B, DMA ch4); reply payload starts at `0x2000025E`.
- "Reply pending" flag at `0x20000326` (RX + 0x6C). The dispatcher only sends a reply if the handler set it.
- Config block in RAM (pointer at `*(0x2000002C)+8`), saved to the **flash config page `0x0800FC00`** (last 1 KB page) by `FUN_08002A8C` (an STMFLASH_Write-style routine: erase + program).
- Live measurement table: 12 × uint16 at `*(*(0x2000002C)) + 10`, read through `FUN_08000C74(idx)`.

### Frame format (observed in the parser `FUN_08002158`/`FUN_08003C3E` and builder `FUN_0800249C`)
```
[0] start (0xEB, inferred from the escape table; the parser doesn't check it; the reply echoes it)
[1..2] destination address, little-endian. MUST be 0x000A or 0x0008 (checked before un-escaping)
[3..4] source address (the reply swaps 1-2 and 3-4)
[5..6] total frame length N, little-endian (start byte to end byte, inclusive, after un-escaping)
[7] command
[8..N-4] payload
[N-3..N-2] checksum = 16-bit sum of bytes [1..N-4], little-endian
[N-1] end = 0x90
Escaping inside the frame: 0xEB → 27 15, 0x90 → 27 70, 0x27 → 27 D9
```
A frame is taken when the line goes idle (USART2 IDLE interrupt + DMA count). It must be longer than 10 bytes.

### Command table (dispatcher at `0x08002180`; commands not listed here are ignored)
| Cmd | Handler | What it does | Safety |
|---|---|---|---|
| `0x00` | `FUN_08002338` | If payload[0]==`0xAA`: copies 0x2E bytes of **factory defaults** (`0x080064A8`) over the config and **writes flash** | ❌ **WRITE: factory reset of calibration** |
| `0x01` | `FUN_0800239C` | Replies with live measurements: idx 2, 1, 10, 3, 5, 4, 11, 11, 11 (uint16 LE each) + 4 zero bytes. Reply length 33 | ✅ **READ-ONLY** |
| `0x03` | `FUN_0800246C` | payload `00 33` → `FUN_08005A2C` / payload `00 CC` → `FUN_08005980`. Looks like charge **start/stop** control (inferred). No reply | ❌ **ACTION: controls charging** |
| `0x07` | `FUN_0800224C` | sub `01 03` → replies with 12 bytes of config (+0x14), apparently an ID/serial (read-only). sub `02 03` from source `'PP'` with `'U'` marker → **writes** 12 bytes + flash | ✅ sub 01 read / ❌ sub 02 write |
| `0x55` | `FUN_08001F08` | Only from source address `0x5050` ('PP'). Sub `0x97`/`0x98` set calibration parameters, `0xAF` **saves config to flash** | ❌ **WRITE: calibration tool** |

### Measurement slots (partly identified)
- **idx 5** (`S+0x14`): calibrated (gain/offset from config +8/+10), smoothed in floating point (`FUN_08000F18`), and compared with config `+0x16` minus 300. If it falls below, charging stops (`FUN_08005A2C`). **Most likely mains voltage.** Under a mode flag at `0x20000095` it's scaled by 58/100.
- **idx 3** (`S+0x10`): median of 32 ADC samples (`FUN_08000E5C`), compared with config `+0x1A`. If it stays over for 1600 counts it raises a fault (`FUN_08000F68`). Likely leakage/RCD or temperature.
- idx 1, 2, 4, 10, 11: not yet identified. The **current (A)** reading is expected among them; confirm by querying while charging and comparing against the car or display.

### Example read-only request (command 1), built from the format above, not yet sent
Destination `0x000A`, source `0x0001`, length 11:
`EB 0A 00 01 00 0B 00 01 17 00 90` (checksum = 0x0A+0x00+0x01+0x00+0x0B+0x00+0x01 = 0x17; no bytes need escaping).
Send it to header pin 7 at 9600 8N1 and listen on header pin 6. The expected reply is 33 bytes (more if escaped).
**Unverified on hardware.** The plan is to validate it in an emulator first (step 3), then send it once.

## 6. Emulator validation (Nov 23, step 3): frame format confirmed
`tools/emu_usart2.py` (Unicorn 2.1.4, in a private venv) loads the dump, runs the C runtime init and the protocol init `FUN_080018C4`, then feeds a frame through the firmware's own poll → parse → dispatch → reply path. It flags any write to flash, the FLASH controller, or GPIO outputs. No hardware is involved.

| Request | Firmware's reply in emulation | Writes? |
|---|---|---|
| `EB 0A 00 01 00 0B 00 01 17 00 90` (cmd 1, live values) | `EB 01 00 0A 00 21 00 01` + 22 data bytes + `2D 00 90` (33 B; values are 0 because there's no ADC in emulation) | **none** ✅ |
| `EB 0A 00 01 00 0D 00 07 01 03 23 00 90` (cmd 7, sub 01 03) | 28 B: payload `01 03` + config words 2700, 850, 150, 200, 850, 4 + `55`. These are threshold/calibration settings, not a serial number | **none** ✅ |
| `EB 0A 00 01 00 0C 00 00 AA C1 00 90` (cmd 0, control test only) | no reply | **1541 flash-erase/program events** ❌, which confirms cmd 0 is a factory reset that rewrites flash |

Conclusion: the frame format, addressing and checksum are correct. Command 1 is accepted and is read-only in the firmware's own code path.
To read live values on hardware: send the cmd-1 frame **once** to header pin 7 (9600 8N1, 3.3 V logic), listen on pin 6.

## 7. First hardware query (Nov 23, ~22:00): it works
FT232R adapter at 3.0 V logic: TX → header pin 7, RX → header pin 6, GND → pin 5. Board on bench 5 V, **no mains, no relay board, no car**.
- Passive listen for 5 s before sending: 0 bytes (the MCU doesn't transmit unprompted).
- Sent once: `EB 0A 00 01 00 0B 00 01 17 00 90` (cmd 1).
- Reply (33 B, checksum OK): `EB 01 00 0A 00 21 00 01 09 00 ED 00 00 00 00 00 0E 00 00 00 …00 31 01 90`
- Values: **slot2 = 9, slot1 = 237, slot10 = 0, slot3 = 0, slot5 = 14, slot4 = 0, slot11 = 0**.
- Interpretation (tentative): with no mains, slot 5 (voltage) reads near zero (14 ≈ offset/noise). The meanings of slot 1 (237) and slot 2 (9) are unknown; they could be the control pilot, temperature, or the current setting. The current reading is expected to be one of the zero slots (no load).
- Tool: `tools/evse_query.py` (only allows cmd 1 and cmd 7 01 03; dry-run unless `--send`).
- To identify the slots: query during a real charge (mains on, car connected) and compare with the car's or the display's amps and volts. That needs the box powered from mains, which is the owner's call and outside the bench-only rule.

## 8. Slot meanings confirmed during a real charge (Nov 23, ~22:45, Chevy Bolt EUV, 16 A setting)
| Slot | No car | Car connected | Charging | Charger display | Meaning |
|---|---|---|---|---|---|
| 4 | 0 | 0 | 155 → 161 | 16.1 A | **Current, 0.1 A** ✅ |
| 5 | 2467 | 2470 | 2429 / 2427 | 242 V | **Mains voltage, 0.1 V** ✅ |
| 2 | 117 | 87 | 58 | — | **Control pilot, 0.1 V** (12 / 9 / 6 V = J1772 states A / B / C) ✅ |
| 1 | 263 | 283–288 | 291–299 | (°F shown, unclear) | **Temperature, 0.1 °C** (tentative) |
| 3 | 0 | 0–1 | 0 | — | unknown (maybe leakage) |
| 10, 11 | 0 | 0 | 0 | — | unknown |

Power check: 242.7 V × 16.1 A = 3.91 kW; the display shows 3.9 kW.

**Issue seen:** about a minute into charging, replies stopped (Link OK off, Bad Frames 0, ESP still up). The cause isn't known yet: either the ESP's software-serial RX stopped, or the MCU's USART2 locked up. The firmware's IDLE handler only clears IDLE, never ORE/NE/FE, so a noise-induced overrun could stall reception until the charger is power-cycled (inference). The v2 YAML adds RX Bytes / Good Frames counters and a Restart button to tell these apart.

## 9. Root-cause analysis of the dropped link (Nov 24)

### Two distinct failure modes
1. **Temporary dropout (common, self-recovering).** Causes: (a) the ESP rebooting every ~15 min because it wasn't yet added to Home Assistant (now added, so fixed); (b) the USART2 ISR only handles the IDLE flag and never clears ORE/NE/FE, so a noise-induced overrun can stall RX until the next clean frame or DMA restart. Overnight the link recovered on its own and logged 1.58 kWh, which fits this mode.
2. **Permanent death (rare, needs reset).** A genuine out-of-bounds read in the frame validator → HardFault → the default handler loops forever → the charger's whole comms (and likely the MCU) is stuck until power-cycled.

### The out-of-bounds read (code-confirmed, not silicon-confirmed)
- `FUN_08003C3E` (frame validator, called from the dispatcher `FUN_08002158`) computes the checksum over a range taken from the frame's **own 16-bit length field** at bytes [5]/[6]:
  - `0x08003CBC ldrb r0,[r2,#6]` / `0x08003CC0 ldrb r7,[r2,#5]` → `r5 = len`
  - loop `0x08003CCA ldrb r0,[r2,r1]` for `r1 = 1 .. len-3`, reading `rx_buf[r1]`.
- `len` is **never clamped** to the 100-byte buffer or to the actual received count. A frame with a large length field makes the loop read past `rx_buf` (0x200002BA) and off the end of the 8 KB RAM (>0x20002000) → `UC_ERR_READ_UNMAPPED` in emulation = HardFault on hardware.
- Reachability: the dispatcher runs only when **>10 bytes** were received (`FUN_08001EE8`), and `FUN_08002158` first requires byte[1] ∈ {0x0A, 0x08} and byte[2] == 0x00. So the trigger is a >10-byte frame with that header and a big length field — reachable from line noise / corruption, not from our well-formed cmd-1 poll.
- Emulator fuzz (`tools/emu_link_fuzz.py`, seed 1, 200 trials): 12 HardFault-equivalent crashes, all at pc `0x08003CCA`; 0 flash/flash-controller writes from junk input; 0 cases of a stuck-but-not-crashed parser. Caveat: emulation models DMA+IDLE+parser only; not confirmed on the real MCU, and we will not send a malformed frame to confirm (it would crash the charger).

### Our ESP does not trigger this
The cmd-1 request is well-formed (length 0x0B), so polling is safe. The vulnerability matters only as the likely mechanism of a noise-induced permanent lockup, and as the thing a firmware patch would fix (clamp `len` to the received byte count / buffer size).

### Recommended mitigations (ESP/hardware side, firmware stays read-only)
- Move the ESP to its **hardware UART0 (GPIO1/3)** for exact timing (verify GPIO1/3 ↔ MCU PA9/PA10 are truly unconfigured first), or keep software serial but **poll every 30 s** instead of 10 s to cut exposure.
- Add an **RC filter** (~1 kΩ series + ~1 nF to GND) at header pin 7, and keep the wires short/twisted, to suppress noise that could both stall RX and, rarely, craft a malformed frame.
- Add an **ESP→NRST reset** (GPIO12, open-drain, to header pin 3) as the clean recovery from a HardFault without opening the case — gated so it never resets mid-charge unless intended.

## 10. No watchdog — a crash is permanent (Nov 24)
- **IWDG (independent watchdog): not used.** Only one literal `0x40003000` exists in the image and no instruction loads it; no `0xCCCC`/`0xAAAA` writes to IWDG_KR anywhere. (The `0xCCCCCCCD` constant in the image is a divide-by-10 reciprocal, not watchdog-related.)
- **WWDG (window watchdog): not started.** No WWDG register use.
- **HardFault handler** `0x080000F4` = `FE E7` (`b .`), an infinite loop. NMI and the other default handlers are the same.
- **Implication:** the out-of-bounds read (§9) or any hang leaves the MCU stuck with **no automatic recovery** — consistent with the charger being dead for ~54 min with the ESP healthy (Nov 24). The only recovery is removing power (or pulsing NRST). This makes the **ESP→NRST reset wire the single most useful hardware addition**, and strengthens the case for an eventual firmware patch (watchdog + length clamp).

## Persistent analysis location
Ghidra project + exports now live in `firmware/analysis/` (ghidra_proj/, decomp.c, functions.txt, listing.asm) so they survive host reboots. Scripts are in `firmware/analysis/*.java` and `firmware/tools/`. Rebuild command is in `firmware/analysis/ghidra_build.log`.

## 11. Deeper RE pass (Nov 24) — recovery, measurement, display

### No remote recovery exists (decisive for a sealed unit)
- **No software reset:** the image contains no reference to `SCB->AIRCR` (`0xE000ED0C`) and no `0x05FA....` reset key, so the firmware never performs `NVIC_SystemReset` and there is no command that reboots the MCU.
- With **no watchdog** (§10) and a **dead-loop HardFault handler** (§10), a hung/crashed MCU cannot be revived by anything sent over UART. Recovery requires removing power or pulsing NRST.
- **Practical consequence (sealed unit):** add a **smart plug / relay upstream of the charger** and have Home Assistant power-cycle it when `Link OK` stays off for N minutes. This is the only no-open-case recovery and acts as an external watchdog. (The ESP→NRST wire remains the alternative if the case is ever opened.)
- Note: there is no encryption/obfuscation — RDP was level 0, the dump is plain Thumb code.

### Measurement pipeline
- **TIM3_IRQ** (`0x0800371C`) drives sampling each tick: `FUN_08003766` (timer ack), `FUN_08000F9E`, `FUN_08000E5C` (32-sample median → slot 3) etc.
- ADC (`0x40012400`) is read in `FUN_08000FEC` (reads DR at +0x40) and `FUN_08000B50`; conversions feed the 12×uint16 live table at `*(*0x2000002C)+10`, read out by `FUN_08000C74(idx)`.
- Confirmed slot meanings (field test §8): slot4=current(0.1A), slot5=voltage(0.1V), slot2=pilot(0.1V), slot1≈temp(0.1C). Slots 0,3,6-11 not individually identified; slot3 is a 32-sample median compared against a fault threshold (leakage/RCD or thermal).

### Display
- The OLED text is rendered from a glyph/font table, not stored ASCII (so "kWh"/"kW" aren't searchable strings). A digit table `"0123456789..."` lives at `0x08004510`, used by the number formatter around `0x08004458-0x08004472`. That formatter is where on-screen scaling and the session-kWh / elapsed-timer values are produced, if exact confirmation is ever wanted.
- Not yet traced further: locating the session-energy (0.xxx kWh) and elapsed-time variables in RAM. Doable but not needed for the current telemetry goal.

## 12. Contactor control + reset-during-charge safety (Nov 24)

### The main contactor is driven by PA11 + PA12, active-LOW to close (code-confirmed)
- **Start charging** `FUN_080050dc` (called only from the cmd-0x03 start path `FUN_08005A2C`):
  `GPIOA_BRR = 0x1000` then `= 0x800` → drives **PA12 and PA11 LOW**.
- **Stop charging** `FUN_080050b8` (called only from the stop path `FUN_08005980`):
  `GPIOA_BSRR = 0x1000` then `= 0x800` → drives **PA12 and PA11 HIGH**.
- So: **contactor CLOSED (current flowing) = MCU holds PA11/PA12 LOW.** Releasing them to HIGH = open/stop.
- Two lines → almost certainly a 2-pole contactor (both 240 V legs), or contactor + enable.
- These two functions are the ONLY callers; neither runs during boot init. So the pins' level in the
  reset→firmware-config window is set by the chip default + board pulls, not by firmware.

### STM32F030 reset state (hardware fact)
- On NRST / power-on, every GPIO except PA13/PA14 becomes a **floating input (Hi-Z)**; GPIOA ODR resets to 0.
- A UL-listed EVSE is expected to pull PA11/PA12 to the OPEN level (HIGH) so floating = contactor open,
  matching the firmware's stop state. This pull is on the board and cannot be proven from the dump.

### The decisive interlock is the J1772 control pilot, which the MCU generates
- Field test §8 confirmed the MCU both generates and reads the CP (slot2 = 12/9/6 V = states A/B/C).
- When the MCU halts (reset), the pilot PWM stops → the **vehicle** must cease current draw within
  **100 ms** (SAE J1772) and opens its own contactor. This is enforced on the car side, independent of
  the EVSE contactor's fail state.

### Answer: what happens if the MCU is reset during charging
- **Mains power-cycle (the smart-plug watchdog): SAFE.** Electrically identical to a power outage —
  contactor coils de-energize and open, pilot dies, the car stops and opens its contactor. On restore the
  charger cold-boots and the J1772 handshake restarts (A→B→C); the car resumes if still plugged/scheduled.
  EVSEs are designed to survive power loss, so cycling the plug mid-charge is fine. **This is the method to use.**
- **NRST-only pulse (MCU reset, mains still live): messier, avoid mid-charge.** Pilot stops → car stops in
  ≤100 ms, so no energy into a car that has opened its contactor. But PA11/PA12 go Hi-Z and their resting
  level depends on board pull resistors; and on reboot the firmware configures them as outputs with ODR=0
  (= the LOW/"closed" drive level) *before* any stop call, a brief window that only the pilot interlock and
  the (assumed) pull-ups cover. Only pulse NRST when NOT actively charging; otherwise prefer the mains cycle.

### Still unverified (would need the remaining RE pass or a scope)
- The external pull direction on PA11/PA12 (board, not firmware).
- The exact GPIOA init ordering at boot (does it ever briefly drive PA11/PA12 LOW before the state machine
  forces stop?). Tracing the boot GPIO/clock init end-to-end would close this; see the full-RE scoping note.

## 13. Full firmware architecture (Nov 24) — main superloop, tasks, contactor gating

Ghidra auto-analysis had left ~30 regions un-disassembled (main among them). Re-ran the local
Ghidra with `DecompAt.java` to force-decompile the gaps; results in `analysis/gap_functions.c`.

### Boot chain (code-confirmed)
`Reset_Handler (0x080000cc)` → `SystemInit (0x080035d8)` → CMSIS thunk `0x080000b4` → **real main `0x08004d70`**.
(main is reached only through a pointer table, which is why Ghidra hadn't created it.)

### main (`FUN_08004d70`) — a cooperative superloop
```
FUN_080018c4();   // USART2 + protocol init (the telemetry port)
FUN_08001632();   // peripheral inits: ADC, timers, GPIO (NOT the contactor)
FUN_080055d8();   // display layout: writes the format strings below
counter=0; while(counter<1000){ FUN_08000124(counter,0x14); ... }   // ~warm-up/self-test sweep
loop forever {
  dt = counter - prev; prev = counter;
  FUN_080058de(state, dt);   // <-- the state-machine tick (below)
  FUN_080011cc();            // fast service
  if (tick_flag){ tick_flag=0; FUN_08002d94(1); }  // slow/periodic task (display + telemetry push)
}
```

### The state-machine tick `FUN_080058de(state, dt)`
```
FUN_080051a8(state, dt&0xff);  // J1772 charge/pilot state machine (decides start/stop)
FUN_0800357c(state, dt);       // measurement/ADC processing
FUN_08001ee8();                // USART2 poll -> parser/dispatcher (the cmd-0x01 reply path)
FUN_080050f0(state);           // contactor/indicator service + fault/relay-retry logic
FUN_08005534(dt);              // periodic display refresh (every ~500 ticks) + a <=5 retry counter
```
So our read-only cmd-0x01 poll is answered from inside this same loop (`FUN_08001ee8`), independent of
the charge state — consistent with telemetry working whether or not a car is connected.

### Contactor gating — the key reset-safety fact (code-confirmed)
- **No boot/init path configures PA11/PA12.** The boot GPIO inits only set: PA0-7 analog (ADC, `local_10=0xff`
  mode analog in `FUN_08000c08`), PA2/3, and PA14/15 AF1 for USART2 (`FUN_08001714`). None touch 0x800/0x1000.
- PA11/PA12 are configured as **outputs and driven** ONLY inside the charge-entry setup `FUN_080059b2`
  (`GPIO_Init(PA12,PA11)` then `FUN_080050dc` = drive LOW = close), which runs only when the state machine
  commands a charge start (`FUN_08005A2C`, reached from the J1772 handshake reaching state C).
- **Therefore, from reset until a full handshake completes, PA11/PA12 stay at the chip default: high-impedance
  inputs.** The firmware never blind-closes the contactor on boot. My earlier "brief LOW glitch during GPIO
  re-init" worry (§12) is **retracted** — boot does not drive these pins at all.

### Refined answer: MCU reset during an active charge
1. **Mains power-cycle (smart-plug watchdog): safe, unchanged** — coils drop, pilot dies, car stops, clean
   cold-boot + re-handshake on restore.
2. **NRST-only pulse: cleaner than previously stated** — on reset PA11/PA12 go Hi-Z and *remain* Hi-Z through
   the entire boot (firmware never configures them until a new charge is commanded), so the contactor cannot
   be re-energized until the car completes a fresh A→B→C handshake. Combined with the pilot PWM stopping
   (car cuts current in ≤100 ms), reset mid-charge does not deliver uncontrolled current.
3. **The one genuine hardware unknown remains:** the board's pull on PA11/PA12 decides whether Hi-Z = contactor
   open. UL-compliant design requires fail-open; confirm with a meter (pin→contactor-driver) when the case is
   next open. This is not answerable from firmware.

### Display shows energy + timer (format strings at 0x08005690+)
`%03dV`, `%4.1fA`, `%4.1fKw`, `%5.1fKwh`, `%02d:%02d:%02d` — so the unit does track session kWh and an
elapsed HH:MM:SS timer internally; these are produced in the display/number path (`FUN_080055d8` layout +
the formatter near 0x08004458). Locating their RAM sources is now straightforward if we ever want them over UART.

## 14. CORRECTION to §12/§13 — contactor polarity and start/stop were inverted (Nov 24)

While decompiling the remaining missed functions I found two errors above. This section is authoritative;
where it conflicts with §12/§13, believe §14.

### Raw-byte ground truth (not inference)
- `FUN_080050dc`, `FUN_080050c8`, `FUN_080059c4` → write GPIOA **BRR (0x48000028)** = drive PA11/PA12 **LOW**.
- `FUN_080050b8` → writes GPIOA **BSRR (0x48000018)** = drive PA11/PA12 **HIGH**.

### Boot DOES drive the contactor pins (correction to §13)
- `main → FUN_08001632 (init #2) → FUN_080059c4` configures PA11/PA12 as push-pull outputs and drives them
  **LOW**, early in boot. So the §13 claim "no boot/init path configures PA11/PA12" is **wrong** — it does.
- Because this happens at power-on with **no car and no pilot handshake**, LOW must be the **de-energized /
  contactor-OPEN** state. A charger that closed its contactor at boot would be unsellable. So the firmware's
  own behavior proves the relay driver is **active-HIGH**: GPIO HIGH = relay energized = contactor CLOSED,
  GPIO LOW = relay off = contactor OPEN.

### Therefore the start/stop labels in §5/§12/§13 were backwards
- cmd 0x03 payload **0xCC** → `FUN_08005980` → drive HIGH = **START charging (close contactor)**.
- cmd 0x03 payload **0x33** → `FUN_08005A2C` → drive LOW = **STOP charging (open contactor)**.
  (The old handoff had 0x33=start / 0xCC=stop. Reversed.)

### Net effect on the reset-during-charge answer: unchanged, in fact strengthened
- At reset, PA11/PA12 go Hi-Z. With an active-high driver, "off" = OPEN, and the GPIO/ODR default (LOW) is
  also OPEN — so every default state is the safe one. Then boot actively drives LOW (OPEN) within init.
- The contactor only CLOSES when firmware drives HIGH, which happens solely on the start-charge path after
  the state machine (or a 0xCC command) commands it — i.e. after a fresh J1772 handshake. It is never
  blind-closed at boot.
- Mains power-cycle (smart-plug watchdog): still unconditionally safe.
- **Residual hardware unknown (now narrower):** whether PA11/PA12 have an external pulldown guaranteeing OPEN
  during the brief Hi-Z window between NRST release and firmware driving them LOW. The window is sub-ms and
  the pilot is already gone (car stopped), but a meter check pin→driver when the case is open would confirm it.

### Why the earlier state-machine decompile looked garbled
`FUN_080051a8` decompiled with bogus `coprocessor_*`/`unaff_r9` artifacts — Ghidra mis-tracked registers
because the function is entered through the tick dispatcher with live r4/r9 context. Its real body is the
pilot classifier + fault counters (see `FUN_08000cb0`, `FUN_080051f8`). Read those, not the FUN_080051a8 C.

## §15 — ESP traces land on USART1, which is DEAD on the MCU side (Nov 24)

Question: can the factory PCB traces to the on-board ESP footprint replace the kludgy
USART2 jumpers?

Firmware evidence (stm32f030c8_fw_dump1.bin):
- **USART1 (0x40013800) is never initialized or serviced.** The vector table gives only
  USART2 a real handler (no USART1 ISR). The *only* USART1 reference in the image is at
  0x08003b92, inside the stock HAL `UART_SetConfig` clock-select switch (compares the base
  against USART1 / USART2 / 0x40004800 to pick PCLK2 vs PCLK1 for the BRR calc). No caller
  ever passes the USART1 base in to be configured.
- The receive path is hardwired to **USART2 (0x40004400)**: ISR 0x08003a2c, RDR reader
  0x08003c34 (`ldrh [base,#0x24]`). This is the port the jumpers tap (PA14/PA15).

Implication:
- The ESP's native UART0 (GPIO1 TXD0 / GPIO3 RXD0) traces reach MCU **USART1** pins, but the
  MCU will never answer there as shipped. Using those traces requires a firmware patch:
  enable USART1 clock (RCC_APB2ENR bit14) + GPIO AF, and mirror the cmd-01 responder onto
  USART1. Flash room exists (~28 KB free) but it adds an init step + a second RX path, and
  puts the link on the ESP's boot/flash/log UART (ESP-reset boot noise → MCU; survivable with
  Patch A's ORE clear, but not free).
- **Cheaper path:** with the case open for the crash-protection reflash, meter whether any ESP
  trace / spare pad reaches **PA14/PA15 (USART2)**. If so, move the ESP link there → zero MCU
  change. USART1 candidate pins if that's where the traces go: PA9/PA10 (AF1) or PB6/PB7 (AF0).
