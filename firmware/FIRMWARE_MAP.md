# Mustart EVSE — annotated firmware map (STM32F030C8T6)

Companion to `FINDINGS.md`. This is the architectural map: what each subsystem is, which pins/peripherals
it uses, and the key functions. Addresses are flash (base `0x08000000`). Source of truth for decompiled code:
`analysis/decomp.c` (Ghidra auto-analysis) + `analysis/gap_functions.c` (functions Ghidra missed, force-decompiled).

Confidence tags: **[code]** = read directly in the bytes/decomp; **[inf]** = inferred from context.

---

## 1. Chip & memory
- **MCU:** STM32F030C8T6 — Cortex-M0 (Thumb only), 64 KB flash, 8 KB RAM (`0x20000000`–`0x20002000`), LQFP48.
- **RDP:** level 0 (unlocked, no encryption). Dump is plain Thumb. **[code]**
- **Flash config page:** `0x0800FC00` (last 1 KB) — calibration/config saved here by `FUN_08002A8C`
  (erase+program). **[code]**
- **Vector table:** `0x08000000`. Only USART2, TIM1?, TIM3, TIM14, TIM16, DMA1-Ch1, DMA1-Ch4/5 have real
  handlers; everything else points at the dead-loop default handler `0x080000FC`. **[code]**

## 2. Pin / peripheral map (confirmed)
| Pin | Function | Peripheral | Evidence |
|---|---|---|---|
| PA0–PA7 | Analog measurement inputs (V, current/CT, pilot sense, temp, leakage) | ADC1 `0x40012400`, analog mode | `FUN_08000c08` sets MODER=analog, mask 0xFF **[code]** |
| PA2 / PA3 | Configured (mask 0xC); purpose not yet pinned | — | GPIO_Init call **[code/inf]** |
| **PA8** | **J1772 control-pilot PWM out (1 kHz)** | **TIM1_CH1** `0x40012C00`, AF2 | `FUN_08001564` inits PA8 AF2 + TIM1 PWM **[code]** |
| **PA11** | **Contactor/relay control line A** | GPIO out, **active-HIGH = closed** | start/stop paths **[code]** |
| **PA12** | **Contactor/relay control line B** | GPIO out, **active-HIGH = closed** | start/stop paths **[code]** |
| PA13 | SWDIO (debug) — chip default | SWD | — |
| **PA14** | **USART2_TX (telemetry port)** + SWCLK | USART2 `0x40004400`, AF1, 9600 8N1 | `FUN_08001714` **[code]** |
| **PA15** | **USART2_RX (telemetry port)** | USART2, AF1 | continuity-checked = header pin 7 **[code]** |
| (OLED bus) | SSD1306/SH1106-family OLED: DC/RES/CS + data | bit-banged/SPI via `FUN_08002bd0` | init cmd stream in `FUN_08002fd0` **[code]** |
| (3 pins) | 3 indicator LEDs | GPIO out | `FUN_08002d10` 3× GPIO config **[inf]** |

**Contactor polarity (settled, see FINDINGS §14):** GPIO **HIGH = contactor CLOSED** (charging),
**LOW = OPEN** (idle). Proven because boot drives them LOW with no car attached.

## 3. Boot chain **[code]**
```
Reset_Handler 0x080000cc
  -> SystemInit 0x080035d8            (clock tree: HSI/PLL, flash latency)
  -> CMSIS thunk 0x080000b4           (set SP, scatter-load data/bss)
  -> main 0x08004d70                  (reached via pointer table — why Ghidra missed it)
```

## 4. main (`0x08004d70`) — cooperative superloop **[code]**
```c
FUN_080018c4();     // USART2 + telemetry-protocol init
FUN_08001632();     // peripheral inits (see §5)  <-- also drives contactor pins to OPEN
FUN_080055d8();     // display layout: writes the format strings ("%4.1fA","%5.1fKwh", HH:MM:SS...)
cnt=0; while(cnt<1000){ FUN_08000124(cnt,0x14); ... }   // startup sweep / warm-up
for(;;){
  dt = cnt - prev; prev = cnt;
  FUN_080058de(state, dt);   // THE TICK (see §6)
  FUN_080011cc();            // fast service
  if (tick_flag){ tick_flag=0; FUN_08002d94(1); }   // slow task: display push + telemetry refresh
}
```

### 4a. init #2 `FUN_08001632` (what boot actually sets up) **[code]**
Calls, in order: `FUN_08002f24` (stub) · `FUN_08001c74` (ADC read ×1000) · `FUN_08001cac(0x96)` (delay) ·
**`FUN_080059c4`** (contactor pins → output, driven LOW/OPEN) · `FUN_08005c20` · `FUN_08002d10`
(3 LED GPIOs) · **`FUN_08002fd0`** (OLED SSD1306 init) · **`FUN_08001564`** (pilot TIM1 PWM on PA8) ·
`FUN_08000fec(0x3c)` + `FUN_08002984`/`FUN_08000fec` (ADC/meas setup) · `FUN_08005a70` (timer reconfig).

## 5. The tick `FUN_080058de(state, dt)` **[code]**
```c
FUN_080051a8(state, dt);   // J1772 charge/pilot state machine + fault dwell counters
FUN_0800357c(state, dt);   // measurement/ADC processing (feeds the 12-slot table)
FUN_08001ee8();            // USART2 poll -> parser/dispatcher -> answers our cmd-0x01 telemetry
FUN_080050f0(state);       // contactor service + relay-retry / fault indication
FUN_08005534(dt);          // periodic (~500-tick) display refresh + <=5 retry counter
```
Telemetry (`FUN_08001ee8`) runs every tick regardless of charge state — why our read works car-or-no-car.

## 6. J1772 pilot subsystem **[code]**
- **Pilot PWM out:** TIM1_CH1 on PA8, init `FUN_08001564`. Duty encodes offered amps.
- **Pilot sense/classify:** `FUN_08000cb0` — takes 32 ADC samples, medians them (`FUN_080056dc`), then
  thresholds the level (stored at struct `+0x0e`) into a state at struct `+0x08`, with debounce:
  - level `< 0x29` → fault/no-pilot (12-count debounce) → `FUN_08005940`
  - `< 0x4c` → state **2** (19-count debounce)
  - `< 0x6a` → state **1**
  - `>= 0x6a` → state **3** (= car charging / J1772 state C)
- Telemetry slot 2 (`0.1 V`: 12/9/6 V ≈ states A/B/C) is this same pilot reading (field-confirmed §8).

## 7. Contactor control **[code]** (polarity per FINDINGS §14)
| Function | Writes | Level | Meaning |
|---|---|---|---|
| `FUN_08005980` (cmd 0x03 payload **0xCC**) | `FUN_08005_b8` → BSRR | **HIGH** | **START** charging (close) |
| `FUN_08005a2c` (cmd 0x03 payload **0x33**) | `FUN_08005_dc` → BRR | **LOW** | **STOP** charging (open) |
| `FUN_080059c4` (boot init) | BRR | **LOW** | init to **OPEN** |
Closing happens only via the start path, reached after the state machine sees pilot state 3 + conditions.

## 8. Measurement pipeline **[code]**
- **TIM3_IRQ** `0x0800371C` drives per-tick sampling.
- ADC read `FUN_08000FEC` / `FUN_08000B50`; results feed the **12×uint16 live table** at `*(*0x2000002C)+10`,
  read by `FUN_08000C74(idx)`.
- Calibration uses floating point (gain/offset from config), hence the **soft-float library**:
  `FUN_080001c0` (mul), `FUN_0800060c` (float→uint), `FUN_08000698`/`FUN_08000798` (conv). **[code]**
- Confirmed slots (field test §8): **4**=current 0.1 A, **5**=mains V 0.1 V, **2**=pilot 0.1 V, **1**≈temp 0.1 °C.

## 9. Telemetry/config protocol (USART2, 9600) — see FINDINGS §5/§6 for full frame + command map
- Parser/dispatcher `FUN_08002158`; validator `FUN_08003C3E` (has the OOB-read bug, FINDINGS §9).
- cmd **0x01** = read live values (what the ESP polls). cmd 0x00/0x03/0x07-02/0x55 write flash/control — never send.

## 10. Display **[code]**
- Controller: SSD1306/SH1106-family OLED. Init stream `FUN_08002fd0` (0xAF display-on, 0x81 contrast,
  0xD5 clock, 0x8D charge-pump, 0xA1/0xC8 remap, 0xDA COM, 0x20 mem-mode, …). Byte sender `FUN_08002bd0`.
- Layout + formatters `FUN_080055d8`; strings at `0x08005690+`: `%03dV`, `%4.1fA`, `%4.1fKw`,
  `%5.1fKwh`, `%02d:%02d:%02d`. So the unit tracks **session kWh** and an **elapsed timer** internally.

## 11. Reliability facts (from FINDINGS)
- **No watchdog** (IWDG/WWDG unused) and **HardFault = infinite loop** → a crash is permanent until power/NRST.
- **No software-reset / no remote-recovery command.** External power-cycle (smart plug) is the only no-open
  recovery = the intended watchdog.
- **Reset mid-charge is safe:** pilot stops (car cuts in ≤100 ms) and the contactor defaults OPEN
  (active-high driver; Hi-Z and GPIO-low both = open; boot re-drives OPEN).

## 12. Remaining unknowns
- **Hardware (not in firmware):** external pull on PA11/PA12 for the sub-ms Hi-Z reset window; the OLED bus
  pin assignment; the 3 LED pins; PA2/PA3 purpose. All resolvable with a meter when the case is open.
- **Firmware (resolvable, low value):** exact pilot duty→amps constant; the config-block field layout at
  `0x0800FC00`; RAM addresses of the session-kWh and elapsed-timer variables (findable via the §10 formatters).

## 13. Coverage
All **192 distinct call targets** in the image now resolve to a decompiled function (0 missed). Remaining
un-disassembled bytes are constant pools and data tables, not code.
