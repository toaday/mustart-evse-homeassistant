# Mustart EVSE Wi-Fi Mod — Handoff

Session date: night of Sun Nov 22 → Mon Nov 23, 2026
Owner: the owner (does all hands-on work; Claude advises)
Photos: `photos/` (numbered, referenced below as [P01] etc.)

---

## 0. HARD RULES (read first)

1. **Never risk bricking the charger.** No erasing, unlocking, mass-erasing, writing, or programming the STM32. No changing option bytes. No "disable read-out protection." Any MCU work is **read-only**. If the chip is read-protected, **stop** and report.
   - Forbidden examples: `st-flash erase`, `st-flash write`, OpenOCD `stm32f0x unlock`, `stm32f0x mass_erase`, `flash write_image`, `program`, STM32CubeProgrammer "RDP → AA", any option-byte write.
   - Allowed: `st-info --probe`, reading memory/registers (`mdw`), `st-flash read` (read only), `dump_image`.
2. **No faking button presses** (the owner said no to driving the capacitive touch buttons).
3. **Mains safety:** never work with mains connected. Bench testing is done with the control board's 2-pin mains connector **unplugged** and 5V injected from a bench supply. The control board has an offline flyback with a **400V 10µF cap** — treat as live until discharged.
4. **Iron off the board when powered.** Bench supply OFF while soldering (happened once by accident tonight; no damage seen).
5. **Enclosure plastic melts** next to M1 — board is now out of the shell; keep it out for soldering.
6. **Communication style:** the owner wants short messages, not too much at once. In voice: **one step at a time**, wait for them. When a login page appears, tell them and they log in themselves.

---

## 1. Goal

Primary goal (as clarified at the end): **see charge rate (kW/A) and energy added to the car (kWh)** in Home Assistant. Original plan was to add Wi-Fi via the board's empty module footprint (TuyaMCU style). Control (setting amps) is a nice-to-have, not required.

the owner runs **Home Assistant with ESPHome**. Linux workstation.

---

## 2. Hardware identified

### Charger
- Brand **Mustart**, model **MT**, portable J1772 EVSE, input/output 110–250V AC 50/60Hz, IP65 box, ETL/FCC, serial/date sticker `202304100250` [P02].
- Front: status LEDs (Fault yellow / Power green / Charging red), 2 touch buttons, small display window [P01]. Front logo window cracked (cosmetic).
- Status LED table from label [P02]:

| State | Fault (Y) | Power (G) | Charging (R) |
|---|---|---|---|
| Ready | Off | On | Off |
| EV Connected | Off | Slow flash | Off |
| CP Error | Off | Fast flash | Off |
| Charging | Off | Pulsing | On |
| Charge Complete | Off | Flash | Off |
| Fault | Flash | Off | Off |

### Control board — `XBYSJDV1A 20220803` [P03, P04, P11, P12]
- **MCU: STM32F030C8T6** (ST, Cortex-M0, 64KB flash, 8KB RAM, LQFP48) [P14]. Firmware is in internal flash only — **no external flash/EEPROM** found.
- 8.000 MHz crystal (YXC) next to MCU [P13].
- **AMS1117-3.3** (SOT-223, date 2227) powers the MCU's 3.3V rail [P13].
- Offline flyback supply on-board (EE13 transformer, 400V 10µF bulk cap). Mains enters via a **white 2-pin connector**; a **multi-pin connector (6-ish pin, ribbon)** goes to the power board.
- Analog section: **MCP6002** dual op-amp [P16] (likely CT/RCD signal conditioning) and **TL082I** dual op-amp (ST, marked `082I`) [P17] (likely J1772 ±12V pilot drive/sense). Neither is memory.
- Other SOT-89/SOT-223 parts marked **D882** (transistors), a **78L05**-style part, misc.
- **M1**: empty 16-pad module footprint (ESP-12 / Tuya WB3S-style, 8 pads per side, antenna keep-out) [P09, P10].
- **Empty SOT-223 footprint** right next to M1 = missing AMS1117-3.3 for the Wi-Fi module; its caps are populated [P09].
- **7-pin through-hole header** on the board edge (white silkscreen box, square pad = pin 1) — now has male pins soldered in [P15, P21].

### Control board back side (display side) [P26, P27]
*Corrected Nov 23:* this is **not a separate display board**. P26/P27 show the back of the control board itself, with the OLED and touch springs mounted directly on it. Orientation: flipped top-to-bottom relative to [P22]. The 7-pin header joints are along the bottom edge (square pad on the left), the flyback pins are on the right, and M1 is in the top-left corner behind the first touch spring.
- 7-pin **SPI OLED** module, pins labelled `GND VCC SCK SDA RES DC CS`.
- Capacitive touch pads with coil springs (2 buttons).
- Status LEDs on a small board attached at the right end.
- The "7-pin through-hole row" along the bottom edge is **the same 7-pin header** the owner soldered (§8). It is separate from the OLED's own 7 labelled pins, so it is **not** an alternate display connector. SWD or UART remain the likely functions.

### Power board [P05, P06]
- 2 relays, terminals **NO / PE1 / IN / LN**.
- Large black toroid = **RCD / ground-fault sensor** (sticker in Chinese ≈ "single-phase Type A, touch scheduling/current switching, 12–16A, Fahrenheit, 2023-4-12").
- **Blue current transformer** = load-current sensor (this is the CT the owner wants to tap).
- Cable is UL-marked.

---

## 3. M1 footprint pinout (ESP-12F mapping)

**Reference orientation = [P20]: M1 with antenna end pointing DOWN, empty regulator above it.** All "top/left/right" below use this view.

| Left column (top→bottom) | Right column (top→bottom) |
|---|---|
| 1. **GND** | 1. **VCC (3.3V)** |
| 2. **GPIO15** | 2. GPIO13 |
| 3. **GPIO2** | 3. GPIO12 |
| 4. **GPIO0** | 4. GPIO14 |
| 5. GPIO4 | 5. GPIO16 |
| 6. GPIO5 | 6. EN (CH_PD) — tied to VCC by a board trace |
| 7. **RXD (GPIO3)** | 7. ADC |
| 8. **TXD (GPIO1)** | 8. **RST** |

Board traces seen from photos: EN tied to VCC; TX and RX routed toward the MCU (RX by a top trace from pad 7; TX drops through a via at pad 8, runs a short trace on the back [P26], and comes back up through the via beside pad 6 (GPIO5), then continues toward the MCU on top); GND connected. GPIO5 itself appears unconnected. GPIO15 had **no** pull-down on the board (Tuya footprint doesn't need one).

Continuity confirmed tonight:
- Empty regulator **tab pad → M1 VCC**.
- Empty regulator **top small pad = GND**, **bottom small pad = VIN**, middle small pad = VOUT.
- Existing AMS1117 (it's mounted rotated): **left pin = VIN**, **middle = VOUT 3.3V**, **right pin = GND**.
- Existing AMS1117 VIN ↔ empty regulator VIN pad: **same net** [P18, P19].
- GND confirmed on: existing AMS1117 right pin, empty-reg top small pad, M1 top-left pad.
- **Mounting screws are NOT grounded.**

---

## 4. Current bench state (as left tonight)

- Control board **removed from the shell**, power board/ribbon and **mains connector unplugged** [P22].
- **Bench supply: 5.0V, 500mA current limit** → existing AMS1117 **left pin (VIN)**; supply GND → existing AMS1117 **right pin** [P23].
  - Note: supply had been bumped down to **4.4V** for part of the session (explains 3.16V readings). Reset to 5.0V. Re-check before next power-up.
  - Brief confusion mid-session about whether the 5V lead was on the tab. Subsequent readings (3.27V rails) are consistent with 5V on VIN. **Verify visually before powering.**
- *(Removed Nov 23)* **Temporary jumper**: existing AMS1117 middle pin (3.3V out) → empty regulator footprint's tab pad (→ M1 VCC) [P24]. Remove when the new AMS1117 is fitted.
- **Nov 23: new AMS1117-3.3 fitted** in the empty footprint (marked `AMS1117 3.3 DXG91`, tab soldered) [P29]. **Temporary jumper removed.** The through-hole 10k on GPIO15 has been replaced with an **SMD 10k, GPIO15 → GND** (the owner confirmed 10k) [P30]. **The GPIO0 1k pull-up has been removed** (the owner judged it wasn't doing anything). Plan: boot without it, and refit a pull-up neatly only if boots turn out unreliable. Use 1k–10k, **not** the 100 Ω `1000` parts. **First power-up on the new regulator (Nov 23): OK.** 130 mA at 5 V. The ROM log shows `rst cause:1, boot mode:(3,5)` (normal flash boot), so **GPIO0 needs no pull-up**. Tasmota boots and answers ping at 192.168.x.x. At 115200 on ESP TXD it sends `55aa 0003 0001 03 06` (Wi-Fi status), `55aa 0001 0000 00` (product query), then heartbeats `55aa 0000 0000 ff` about every 10 s. Still no MCU reply seen. **Caution:** after a reboot Tasmota also sent `55aa 0006 0005 01 01 0001 00 0d` (a Tuya command setting **dpID 1 = ON**; Tasmota restores the 'power' state at boot), plus a time sync (`0x1c`). The MCU ignores these now. But if it ever starts talking, Tasmota would be **sending unknown commands to the charger**. Before then, stop Tasmota from sending dp commands (or switch to ESPHome with no outputs mapped) and only observe.
- **ESP-12F (ESP8266MOD) soldered onto M1**, antenna down, all 16 pads [P25].
- *(Superseded Nov 23: now SMD 10k, see the Nov 23 entry above)* **10k (brown-black-orange) GPIO15 → GND** (M1 left pad 2 → left pad 1). Had a cold joint; reflowed; now measures ~10k.
- *(Superseded Nov 23: removed, see the Nov 23 entry above)* **1k (brown-black-red) on GPIO0 → 3.3V** (M1 left pad 4). *Corrected Nov 23:* an earlier note said it landed on GPIO2. Counting pads in [P25] (antenna on the left, so the top row from the antenna end is TXD, RXD, GPIO5, GPIO4, **GPIO0**, GPIO2, GPIO15, GND) shows it on GPIO0, and the GPIO2 pad is bare. **Keep it**: it's the intended GPIO0 boot pull-up. It can be swapped for a 10k if the load is a concern (see §7). The earlier 10k pull-up on GPIO0 was removed in the swap.
- **Reading [P25]:** the module is turned 90° clockwise from the [P20] reference. The M1 left column is the top row and the right column is the bottom row; pad 1 (GND / VCC) is at the end away from the antenna.
- USB-serial adapter wires are soldered on as movable probes. the owner moves them between pads depending on what they're monitoring. In [P25] orange is on TXD (GPIO1) and yellow on RXD (GPIO3), but that is only one snapshot. Check the current state, and make sure only the adapter's **RX** lead is on a pad. Adapter GND goes to bench GND.
- Male header pins soldered into the 7-pin edge header.
- Current draw at 5V: ~60–100mA, jumpy (normal).
- Front panel with power-only bench supply: orange/yellow **fault LED blinking**, display shows **16A** — expected, since RCD/relay board isn't connected.

Measured voltages (5V in): ESP VCC ~3.16V (at 4.4V in) / header rail 3.27V. RST pad 3.20V. GPIO2 3.15V. **GPIO0 1.76V (mid-rail — never resolved, see §7).** GPIO15 ~2mV. M1 RX pad (MCU→ESP line) idles ~3.5V with flicker on the meter.

---

## 5. ESP firmware state

- Module was already flashed with **Tasmota 11.1.0** (from a previous project).
- Hostname `tasmota-xxxxxx`, IP **192.168.x.x**, SSID `your-ssid`.
- Module set to **Tuya MCU (54)**. GPIO1 = Tuya Tx, GPIO3 = Tuya Rx (swap was tried and reverted).
- **`SetOption97 1`** is currently set (TuyaMCU at **115200**). `SetOption97 0` returns to 9600.
- `weblog 4` used to see `TYA:` lines.
- Plan B firmware: ESPHome with `tuya:` component, `logger: baud_rate: 0`, `uart: tx GPIO1, rx GPIO3`. Web flasher works with the owner's ESP-12 clamp jig (hold FLASH, tap RESET).

---

## 6. What happened tonight (chronological)

1. Teardown and identification (boards, MCU, op-amps, regulator).
2. Found empty M1 footprint + empty AMS1117 footprint. Decided on ESP-12F (the owner had several plus a clamp programmer [P07]).
3. Mapped regulator pins and grounds by continuity; set up safe bench power (5V on AMS1117 VIN, no mains).
4. Board powered at 5V, MCU booted (fault LED, "16A") — 30–75mA.
5. Found existing ESP already on Tasmota 11.1.0; set module Tuya MCU (54).
6. Soldered ESP-12F to M1 (pre-tinned pads; melted a bit of enclosure plastic). IPA clean.
7. Jumpered 3.3V to M1 VCC. VCC–GND not shorted. ESP didn't join Wi-Fi.
8. Added GPIO15 pull-down (10k). Still didn't boot. Measured RST 3.2V (OK), GPIO0 1.76V, GPIO2 3.15V.
9. Tried 10k then 1k pull-up for GPIO0 → still 1.77V (the 1k is on GPIO0 per [P25]; earlier notes wrongly said GPIO2). GPIO0 measured ~10k to GND with power off.
10. Hooked USB-serial to ESP TX @74880: boot log showed **`rst cause:1, boot mode:(7,5)`** → GPIO15 seen HIGH (SDIO boot). Measured GPIO15 → GND = 5MΩ → **cold joint on the 10k**. Reflowed → ~10k. **ESP then booted Tasmota and joined Wi-Fi.**
11. Tasmota console (weblog 4): ESP sends heartbeats `55aa00000000ff` and product/config queries — **MCU never replies**. Tried 9600 and 115200 (`SetOption97 1`). Tried swapping Tuya TX/RX in Tasmota. Reflowed GPIO1/GPIO3. Still nothing.
12. Moved USB-serial RX to the **M1 RX pad** (MCU's output toward the ESP): **no data at 9600 or 115200**. Line idles high.
13. Removed board from shell; soldered male pins into the 7-pin header. Mapped header (see §8). No serial output on any header pin at 9600/115200 (one burst of garble was traced to wire contact, not data).
14. Web research (see §9). Ordered tools (see §10).

---

### Nov 23 logic-analyzer capture
- 2-minute capture at 1 MS/s through power-up: **CH0 = ESP TXD**, **CH1 = ESP RXD (MCU → ESP)**. Tools: sigrok-cli + fx2lafw (Saleae clone, `0925:3881`). Plug the analyzer **directly into the laptop**: the external VIA hub failed to enumerate it and dropped the CH340.
- **TXD:** ROM boot log, then Tasmota frames decoded at 115200: dp1 = ON (`55aa 0006 ...`), Wi-Fi status 02 then 03, product query, a time sync (`0x1c`), and heartbeats every ~10 s.
- **RXD: zero edges for the whole 2 minutes**, including MCU power-up. 1 MS/s would catch any common baud rate, so the MCU transmits nothing on this line, at any speed.
- **CH1 probe confirmed:** the owner measured ~0 Ω from the CH1 probe point to the MCU leg, so the silent RXD result is real.
- **M1 UART lines reach MCU pins 30 and 31 = PA9 / PA10 = USART1** (continuity, Nov 23). By the datasheet PA9 = USART1_TX, so it should go to ESP RXD, and PA10 = USART1_RX to ESP TXD. Which pad goes to which pin is not yet confirmed. The direct trace path also rules out theory 4 (missing part in the path).
  - For the firmware dump: look for USART1 (base `0x40013800`, RCC APB2ENR bit 14) being set up. If the code never enables USART1 or never configures PA9/PA10 as alternate function, the Wi-Fi code isn't there (or is gated before that point).
  - Note: PA9/PA10 are also the STM32's **built-in ROM bootloader UART** (used when BOOT0 is high). Not part of the plan (SWD is), and the bootloader's read command is blocked by readout protection anyway.
- Caveat (resolved by the continuity check above): the clone's inputs also read high when floating (they read high with the board off), so a solid high doesn't prove the probe was on the pad. Confirm the CH1 probe contact before treating this as final.

## 7. Conclusions & open questions

**Conclusions**
- ESP side is working: boots, on Wi-Fi, sends TuyaMCU frames out GPIO1 (proven: the ROM boot log comes out the same pad).
- The STM32 is **silent on the M1 RX line** at both common baud rates, even when heartbeated.

**Theories (ranked)**
1. **CONFIRMED (firmware analysis, Nov 23):** this firmware has no Wi-Fi/Tuya code. USART1 is never enabled. See `../firmware/FINDINGS.md`.
2. ~~The Wi-Fi SKU uses a non-Tuya protocol~~ **Ruled out (Nov 23):** the owner confirmed the Wi-Fi Mustart versions use **Tuya**. In TuyaMCU the module speaks first and a Tuya-enabled MCU answers the heartbeat almost immediately, so total silence means the Tuya code is either **missing (theory 1)** or **switched off (theory 3)**. The M1 and regulator footprints being on this board suggests the Wi-Fi model shares it, which supports theory 3 (vendors often load one firmware image on every board).
3. **Model-select resistor ("SKU strap")** (*added Nov 23; the owner's main hope*). The firmware might contain the Wi-Fi code but read an MCU input pin at startup that's strapped high or low by a resistor fitted only on the Wi-Fi model. On this board the resistor would be missing, so the Wi-Fi/UART code stays off. If so, fitting one resistor could enable it **with no MCU writes**. How to hunt, in order:
   1. Look for **empty 0603/0402 resistor footprints** whose traces reach an MCU pin, especially in pairs (one pad to 3.3V, one to GND). None seen right around the MCU in [P14]; check further out. Higher-resolution shots of both sides would help.
   2. Find photos of a **Wi-Fi version** of the Mustart or the `XBYSJDV1A` board and compare which parts are fitted.
   3. **Read-only firmware dump** (if not read-protected): in the early startup code, look for a GPIO input read that decides whether the M1 UART gets set up. That pin is the strap. If no UART setup for the M1 pins exists at all, theory 1 is confirmed. Then move to the current-sensor tap or a panel meter (§11 step 6).
4. ~~A component in the TX/RX path is unpopulated~~ **Unlikely:** in [P22] the TX/RX traces appear to run to the MCU without a break, and the series resistors near M1 (marked 301/101, [P10]/[P20]) are fitted. A quick unpowered continuity check of M1 RX pad → pin 30/12 and the TX via → pin 31/13 would close this out (expect a beep or ~100–300 Ω).
5. MCU waits for an extra signal from the module (a GPIO handshake/enable line) before talking. No candidate line found: the GPIO5 via is TX routing (see below).
6. Baud rates other than 9600/115200 (less likely).

Note: under the read-only rule, a firmware dump can't add Wi-Fi support. Its value is finding something fixable in hardware (a model-select resistor) or confirming there's nothing to find.

**Open questions**
- Why GPIO0 sits at ~1.76V even with a **1k pull-up** on it (~10k to GND measured unpowered). A 1k should hold it near 3.3V unless something sinks ~1.5mA or switches it. [P20] shows **no visible top-side trace** to the GPIO0 pad, so the most likely cause is Tasmota switching GPIO0 as an output, with the DMM showing the average. Check Tasmota's GPIO0 config and look at it on the logic analyzer. Still continuity-test the pad unpowered to rule out a bottom-side connection.
- [P20] shows top-side traces only on VCC, EN (tied to VCC), left pad 7 (RXD) and a via at left pad 8 (TXD). There's also a **via beside left pad 6 (GPIO5)** with a trace running toward the MCU. **Mostly resolved from [P26]:** on the back, that via is joined by a short trace to the via at the TXD pad, so it's most likely just the **TX line passing through the back**, not a GPIO5 connection. That leaves theory 5 (handshake line) with no candidate line. Confirm unpowered: ESP TXD pin ↔ that via should beep; ESP GPIO5 pin ↔ that via should not. Annotated close-up: `P26-M1-back-vias.png`.
- ~~Which MCU pins M1 TX/RX reach~~ **Answered: pins 30/31, PA9/PA10, USART1** (see the Nov 23 capture notes).
- 7-pin header function (SWD? UART?). Not the OLED connector: the OLED has its own pins on the back of the board ([P26]).

**STM32F030C8T6 LQFP48 pins of interest** (verify against the datasheet before relying on them):

| Pin | Signal | Notes |
|---|---|---|
| 7 | NRST | |
| 12 / 13 | PA2 / PA3 | USART2 TX / RX |
| 30 / 31 | PA9 / PA10 | USART1 TX / RX |
| 34 | PA13 | SWDIO |
| 37 | PA14 | SWCLK |
| 44 | BOOT0 | |
| 1, 24, 48 / 23, 47 | VDD / VSS | |

Continuity-test the 7-pin header and the M1 TX/RX/GPIO0 pads against these with the board **unpowered**.

---

## 8. 7-pin edge header (square pad = pin 1) [P21]

**IDENTIFIED (Nov 23, continuity to the MCU). This is the SWD programming header:**

| Header pin | Signal | MCU pin |
|---|---|---|
| 1 (square) | 3.3 V | — |
| 2 | **SWDIO** | 34 (PA13) |
| 3 | **NRST** | 7 |
| 4 | unknown (idles high) | — |
| 5 | **GND** | — |
| 6 | **SWCLK** during reset / **USART2_TX (PA14)** once the firmware runs: MCU *transmits* here | 37 |
| 7 | **USART2_RX (PA15)**: MCU *receives* here, 9600 baud | 38 |

Pins 4 and 7 rise with the rail and show no activity. Possibly a spare UART or GPIOs; not needed for SWD. Neither can be BOOT0 held high, because the MCU boots its own firmware normally.

MCU pin numbering with the board held so the **dot is top-right**: pins 1–12 run right→left along the top, 13–24 down the left side, 25–36 left→right along the bottom, 37–48 up the right side.

Numbered "top to bottom" as the owner held it (confirm which end is the square pad):

| # | Unpowered | Powered (5V in) |
|---|---|---|
| 1 (top) | beeps to 3.3V (AMS1117 tab) | 3.278V |
| 2 | — | 3.275V |
| 3 | — | 3.274V |
| 4 | — | 3.275V |
| 5 | **GND** ("third from bottom") | 0V |
| 6 | — | 3.274V |
| 7 (bottom) | — | 3.274V |

**Nov 23 power-up capture** (logic analyzer CH0–CH4 = header pins 2, 3, 4, 6, 7; GND = pin 5; 1 MS/s): with the board off all five read low. At power-up, **pins 2, 4, 6 and 7 rose together with the 3.3 V rail** (within ~0.1 ms). **Pin 3 rose ~3.3 ms later.** That delay matches the STM32's power-on reset holding NRST low, so **pin 3 is probably NRST** (confirm: pin 3 ↔ MCU pin 7). No pin showed any further activity: no serial data and no pin going low after reset. STM32 SWCLK has an internal pull-down, so if SWCLK is on this header it must have an external pull-up. Remaining check: continuity from MCU pin 37 (SWCLK, top-edge corner) and pin 34 (SWDIO) to header pins 2, 4, 6, 7.

All non-ground pins idle high. On SWD, SWCLK usually idles low, so this may **not** be plain SWD — could be UART/other, or SWD with external pull-ups. No serial output seen on pins 2, 3, 4, 6, 7 at 9600 or 115200 on power-up. **Identify by continuity to MCU pins (table above) before connecting the ST-Link.**

---

## 9. Research findings

- No public teardown/mod found for Mustart or board `XBYSJDV1A`. the owner may be first.
- Closest analogue: **Feyree** portable EVSE on Elektroda — Tuya module (WBR3) swapped for ESP-12E, TuyaMCU at **9600**, ESPHome config + OpenBeken dpID map (status enum dp101, working mode dp14, amps dp115 min 8A, etc.). Their board shipped with Wi-Fi populated, so the MCU firmware supported it.
  - https://www.elektroda.com/rtvforum/topic4085036.html
  - https://www.elektroda.com/rtvforum/topic4085036-30.html
- Tuya EV chargers are supported by `make-all/tuya-local` and evcc (Feyree template). Relevant once the MCU talks, since the Wi-Fi Mustart is Tuya. **Checked by the owner (Nov 23): no Mustart in `tuya-local`.** Not a blocker: if the MCU ever talks, Tasmota's `weblog 4` shows every dpID and value the MCU reports, so the map can be built by watching it while charging. Tuya EVSEs from different brands often share firmware, so compare against the Feyree dpIDs (Elektroda thread above) and tuya-local's other EV charger configs.
- Not all Chinese Wi-Fi EVSEs use Tuya (e.g. the EVSE Master app uses its own BT/Wi-Fi protocol), but **the Mustart Wi-Fi versions do** (confirmed by the owner).
- the owner has seen many Wi-Fi Mustart listings but **no inside photos** of any. One photo of a Wi-Fi board around the MCU and M1 would settle theory 3.
- Tasmota "TuyaMCU Devices" page (https://tasmota.github.io/docs/TuyaMCU-Devices/) reviewed: flashing and pin-assignment notes only, nothing on silent MCUs. Its one "EV charger" entry (Costco Charging Essentials) is unreliable (it reads like copied dimmer text). Not useful here.
- Published research exists on extracting firmware from read-protected (RDP level 1) STM32F0 without erasing it — advanced; only if the owner wants to go there. RDP level 2 = permanently locked.

---

## 10. Parts / tools ordered (Amazon, arriving Mon Nov 23)

- **ST-Link V2** clone (~$8).
- **AMS1117 SOT-223 kit** (Chanzon 70 pcs, 7 values) — **check each part is marked 3.3** before fitting; the kit has other voltages in identical packages.
- **USB logic analyzer**, 24MHz 8-channel (Saleae clone, fx2lafw). Works on Linux with sigrok/**PulseView**; install sigrok udev rules for non-root access.

Already on hand: 10k/1k resistors, flux, Kapton, header pins, USB-serial adapter (was COM3 on Windows/PuTTY), CH341A (not useful here — no external flash), bench supply, ESP-12 clamp jig.

---

## 11. Next steps (in order)

> **✅ RESOLVED (Nov 25). Link works; MCU patch flashed & live-validated.** Root cause of the dead telemetry link was a **cold/lifted solder joint on ESP GPIO4 (RX)** — the bit-bang tap pad lifted, so the MCU's replies never reached the ESP (RX Bytes stuck at 0 with a *healthy* MCU and steady display). Localized cleanly: FT232 direct on header pins 6/7 (`firmware/tools/ft232_poll.py`) returned perfect 33-byte replies → MCU + header + patched firmware all proven good → fault isolated to the ESP tap → visual inspection found GPIO4 (RX) lifted. Resoldered → **Link OK = ON, Bad Frames = 0**, V = 123.3 (on the 120 V relay-plug rig), pilot 11.8 V, temp 30.8 °C, current 0 (no car). ESP is at 192.168.x.x; relay plug (ESPHome) at 192.168.x.x, switch id "Mustart EVSE Plug".
> **MCU firmware patch v2 is FLASHED** (`firmware/mustart_patched_v2.bin`): USART2 ISR ORE/NE/FE clear (Patch A), frame-length clamp (Patch B), HardFault→NVIC reset, IWDG watchdog (~2.9 s), reset counter/cause block @ `0x20001F00`. Flashed via the **held-reset** method because the clone ST-Link can't drive NRST: jumper header pin 3 → pin 5, run `openocd -f interface/stlink.cfg -f target/stm32f0x.cfg -f firmware/flash_v2/flash_held_reset.cfg` (from `firmware/`), pull the jumper at the 15 s prompt. All 5 pages verified; **calibration page `0x0800FC00` confirmed untouched** (live_predump byte-matches backup; pre-flash dump matched the original SHA-256). Telemetry decodes clean post-patch, so the crash-protection is running under a working link.
> **Open (optional, not urgent):** (1) **USART1 / traces route** — patch the MCU to *also* service USART1 (PA9/PA10 = MCU pins 30/31) and switch the ESP to hardware UART0 (GPIO1/GPIO3), to permanently eliminate the fragile bit-bang tap pads (one just lifted). USART1 is currently dead in firmware (FINDINGS §15); the patch is **not yet built**. the owner wants off bit-banging, so this is the likely next build. (2) **Real charge test** (needs a car) — the final proof that Patch A's ORE-clear survives the charge-time line noise that killed the link ~1 min in on Nov 23.

> **NOV 24 PM (deeper RE, FINDINGS §11): NO remote recovery exists** — no software-reset code, no watchdog, dead-loop HardFault handler. A hung MCU can only be revived by mains power-cycle or an NRST pulse; nothing over UART works. **Recommended sealed-unit fix: a smart plug / relay upstream of the charger, auto power-cycled by HA when Link OK stays off** (external watchdog). Measurement = TIM3-driven ADC → 12-slot table; display uses a glyph font (digit table 0x08004510). No encryption (plain Thumb, RDP 0).
>
> **NOV 24 PM:** Confirmed **no watchdog** (IWDG/WWDG unused) and the HardFault handler is an infinite loop (FINDINGS §10) — so any crash/hang is permanent until power-cycle or NRST pulse. Makes the **ESP→NRST wire the top hardware fix.** Persistent Ghidra analysis now in `firmware/analysis/` (survives reboots). **Current state:** after a 10 s power-cycle the charger still sent 0 bytes over 2+ min with the ESP healthy — not yet recovered. Added a **60 s post-boot poll delay** to the ESPHome YAML (flash it). Next: longer power-cycle (30–60 s); if still silent, put the FTDI back on header 6/7 to test whether the charger or the ESP RX wire is at fault.
>
> **ROOT CAUSE FOUND (Nov 24, FINDINGS §9).** Two modes: (1) **temporary dropouts** — the ESP rebooted every 15 min until added to HA (fixed), plus the USART2 ISR never clears ORE/NE/FE (noise can stall RX until the next clean frame). This explains the overnight behaviour (link recovered itself, 1.58 kWh logged). (2) **Rare permanent death** — a real **out-of-bounds read** in the frame validator `FUN_08003C3E` (@0x08003CCA): it checksums over the frame's own unchecked 16-bit length field, so a >10-byte malformed frame (byte1∈{0A,08}, byte2=00, big length) reads past RAM → HardFault → dead until power-cycle. Code-confirmed + 12/200 emulator crashes; NOT silicon-confirmed, and **our well-formed cmd-1 poll never triggers it** (only line noise can). Mitigations: hardware UART0 or 30 s polling; RC filter on pin 7; the NRST-reset wire for clean recovery.
>
> **NOV 24 ANALYSIS STATUS:** main() polls the serial port on every loop pass. USART2 enables only the IDLE interrupt and never handles error flags. RX DMA runs in normal mode and is restarted by the IDLE handler (when more than 10 bytes arrived) or by the DMA transfer-complete IRQ. The link is **intermittent** (it recovered by itself overnight; 1.58 kWh logged), not a permanent lock-up. The ESP was rebooting every 15 min until it was added to HA (now done). In an emulator run (`firmware/tools/emu_link_fuzz.py`, first pass), **one junk input sequence made the firmware's parser read past the end of RAM**. On real hardware that would be a HardFault, and the default handler loops forever. **This is not yet confirmed**, and the exact input wasn't captured. That line of work is paused.
>
> **IDEAS FROM THE OWNER (Nov 24), not started:**
> 1. **ESP-controlled MCU reset:** wire an ESP GPIO (GPIO12: high-Z at ESP boot, so no spurious resets) as **open-drain** to header pin 3 (NRST). Pulse it low only when the link is dead. Caveat: a reset mid-charge drops the relays, and the car may not resume on its own, so gate it on state or keep it as a manual HA button.
> 2. **Deeper firmware analysis of the lockup:** which USART2 interrupts and error flags are enabled, how the DMA is set up (normal vs circular) and restarted, how TX-DMA completion is handled, and whether the main loop can stop calling the dispatcher. Reproduce candidate failure modes in the emulator (ORE set, short/garbled frame, frame during TX).
> 3. **Alternatives:** use the ESP's **hardware UART0 on GPIO1/3** (tied to MCU PA9/PA10, which look unconfigured; verify first) instead of software serial to remove timing jitter; an RC filter on pin 7; slower polling; a long logic-analyzer capture on header pins 6/7 during a charge to catch the moment it dies.
> 4. **Patching and reflashing the MCU firmware** (e.g. clearing ORE in the USART2 IRQ). **Currently forbidden by the hard rules.** It's only possible if the owner explicitly changes the rule. It's restorable in principle: there's a verified full dump plus option bytes, and SWD access via connect-under-reset is proven.
>
> **RESUME HERE (paused Nov 23 ~23:00).** Charger is reassembled and on mains, running ESPHome YAML v2 (`esphome/mustart-evse.yaml`, config hash 0x88927fa6). **Open issue:** about a minute into a real charge, the charger's USART2 stopped answering. After an ESP reboot, RX Bytes stays 0, so the problem is **on the charger side** (likely the uncleared ORE/noise flag; FINDINGS §8). **Next steps:** (1) stop charging, power-cycle the charger (10 s off mains), and confirm RX Bytes / Good Frames rise again. (2) See whether it locks up again during charging and how soon. (3) If it does: add an RC filter (~1 kΩ series plus ~1 nF to GND at header pin 7), shorten or twist the wires, and/or poll less often (e.g. 30 s). The fix has to be on the hardware/ESP side, since the MCU firmware is read-only by rule.
>
> **REAL CHARGE TEST (Nov 23 ~22:45): slots confirmed** (FINDINGS §8). Slot 4 = A×10, slot 5 = V×10, slot 2 = pilot V×10, slot 1 ≈ °C×10. ESPHome YAML v2 publishes Volts/Amps/kW/kWh/Pilot/State/Temp plus link diagnostics and a Restart button. **Open issue:** the link went silent about a minute into charging; diagnose with v2's RX Bytes counter (rising = charger still talking; flat = charger's UART stuck → power-cycle the charger).
>
> **ESPHOME WORKING ON THE BENCH (Nov 23 ~22:20).** ESP-12F on ESPHome 2026.11.0 (`mustart-evse`, 192.168.x.x; flashed from Tasmota via a gzipped `.bin.gz` upload, because the plain 406 KB `.bin` was "Not enough space"). Wiring: blue = GPIO5 (TX) → header pin 7, purple = GPIO4 (RX) → header pin 6. Web UI shows **Link OK = ON, Bad Frames = 0**, Slot 1 = 241–242 (varies), Slot 2 = 9, Slot 5 = 14, slots 3/4/10/11 = 0 (bench: no mains, no car). **Next: a real charge test** to work out which slot is current/power (the owner's call; needs mains).
>
> **ESPHOME PLAN (Nov 23 late).** Config: `../esphome/mustart-evse.yaml`. It polls **only** cmd 0x01 every 10 s over software UART: **ESP GPIO5 (TX) → header pin 7, ESP GPIO4 (RX) ← header pin 6 (changed from 14/13 at the owner's request; GPIO5 has the TX-routing via beside it, so watch for bridges)**. GPIO1/3 can't be used (they're hard-wired to the unused MCU USART1); GPIO15 is unsuitable (boot strap vs the MCU RX pull-up). Publishes raw slots 1, 2, 3, 4, 5, 10, 11 plus a bad-frame count and a link-OK sensor. Not yet compiled (no local ESPHome CLI; build it in HA). Uses the existing HA secrets: `wifi_ssid`, `wifi_password`, `fallback_password`, `ota_password`, `web_server_password` (same style as the garage CO2 sensor config).
>
> **FIRST LIVE READ WORKED (Nov 23 ~22:00).** `tools/evse_query.py live --send` over FT232R (3.0 V logic: TX→hdr 7, RX→hdr 6, GND→hdr 5). Reply checksum OK: slot2=9, slot1=237, slot5=14 (≈0 V, no mains), others 0. Slot meanings still need a real charge to pin down. See FINDINGS §7.
>
> **USART2 PROTOCOL MAPPED (Nov 23).** See `../firmware/FINDINGS.md` §5. **Command `0x01` is read-only and returns 7 live measurements** (slot 5 is most likely mains voltage; current is expected among the others). Commands `0x00`, `0x03`, `0x07` sub 2 and `0x55` **write calibration/config to flash or control charging. NEVER send them.** Candidate request: `EB 0A 00 01 00 0B 00 01 17 00 90` to header pin 7 (9600 8N1), reply on pin 6. **Not sent yet.** **Emulator-validated (FINDINGS §6): the frame is accepted, the reply is 33 B, no writes.** Next: send it once on hardware with the owner's OK.
>
> **FIRMWARE ANALYSED (Nov 23, late evening). See `../firmware/FINDINGS.md`.** Headline: **USART1 (the M1/Wi-Fi port) is never clocked, set up or given an interrupt handler. There is no Tuya code. Theory 1 is confirmed, and theory 3 (model-select resistor) is ruled out.** The firmware does run **USART2 at 9600 on PA14 (TX = SWCLK = header pin 6) and PA15 (RX = MCU pin 38 = **header pin 7**, confirmed)**, using a custom framed protocol (escape byte `0x27`, likely `0xEB`…`0x90`, 16-bit sum). Some of its commands **write config**. Taking PA14 for this UART is why SWD dies after boot. Header pin 7 confirmed as PA15. Next: work out from the firmware which USART2 commands only read, before anything is ever sent.
>
> **FIRMWARE DUMPED (Nov 23, ~21:00), read-only, nothing written.** RDP = **level 0** (option byte `0x1FFFF800` = `0x00FF55AA`; FLASH_OBR = `0xFFFFFF00`). DBGMCU_IDCODE = `0x20006440` (STM32F030x8, rev 0x2000), flash size register = 64 KB. Files are in `../firmware/`: `stm32f030c8_fw_dump1.bin` and `..._dump2.bin` (identical, SHA-256 `09bb83f3…ec0f28b`) and `stm32f030c8_optbytes.bin`.
> **How it was done (repeatable):** normal SWD connects fail because **the firmware turns off the SWD pins after boot**. The clone ST-Link's RST pin doesn't help. Method: jumper header pin 3 (NRST) to pin 5 (GND) to hold reset → `openocd -f interface/stlink.cfg -f target/stm32f0x.cfg -c 'adapter speed 100' -c 'reset_config none' -c init` connects → write the debug registers only: DHCSR `0xE000EDF0` = `0xA05F0003` (halt) and DEMCR `0xE000EDFC` = `0x01000001` (halt on reset) → remove the jumper → the core halts at the reset vector (pc `0x080000cc`) → `dump_image`. Afterwards clear DEMCR and `resume` (the firmware then turns SWD off again, as expected). Helper with a read-only guard: scratchpad `ocd.py`.
> First look: vector table SP `0x20001260`, reset handler `0x080000cd`; data runs to `0x0FD4F` (the top pages may be an EEPROM-emulation/config area); no readable text strings; literal pool refs: USART1 ×1, USART2 ×3, GPIOB ×13, ADC ×2, RCC ×9. Next: Ghidra (ARM Cortex-M0, little-endian, base `0x08000000`). Look for USART1 setup (enable bit RCC_APB2ENR bit 14, PA9/PA10 alternate function), any GPIO input read that decides it (theory 3, model-select resistor), and Tuya frame handling (`0x55`/`0xAA` compares).
>
> **UPDATE Nov 23 evening:** header mapped (§8): pin 2 = SWDIO, 3 = NRST, 5 = GND, 6 = SWCLK. Next is the ST-Link read-only probe.
>
> **RESUME HERE (paused Nov 23, afternoon):** Steps 1–3 are done: regulator fitted, M1 UART traced to MCU pins 30/31 (USART1), logic analyzer shows the MCU silent on RXD, header pin 3 is probably NRST. **Next action:** board **off**, meter on continuity: MCU **pin 37** (SWCLK, top-edge corner pin, dot at top-left) against header pins 2, 4, 6, 7. Then MCU **pin 34** (SWDIO, right side, 3rd from top). Then confirm header pin 3 ↔ MCU pin 7 (NRST). After that: ST-Link **read-only** (step 4). `stlink-tools` and `openocd` are now installed. Analyzer and USB-serial adapter must be plugged **straight into the laptop**, not the VIA hub. The analyzer was last clipped to header pins 2,3,4,6,7 (CH0–CH4) with GND on pin 5, but was unplugged during cleanup. Before the MCU could ever start talking, stop Tasmota from sending dp commands (see §4).


1. **Fit AMS1117-3.3** in the empty footprint (verify "3.3" marking; tab = VOUT, check orientation by continuity: tab→M1 VCC, GND pad, VIN pad). Remove the temporary 3.3V jumper.
2. **Unpowered continuity mapping** (no risk):
   - M1 TX pad and RX pad → which STM32 pin? Any empty pads in the path?
   - M1 GPIO0 pad → where does it go?
   - 7-pin header pins 2,3,4,6,7 → STM32 pins 7, 34, 37, 44, 30/31, 12/13.
3. **Logic analyzer** on M1 TX + RX (+ header pins) during power-up and while Tasmota heartbeats. Look for any MCU activity, any baud. Also capture OLED SPI (SCK/SDA/DC/CS) for later.
4. **ST-Link, read-only**, only after SWDIO/SWCLK/GND/NRST are positively identified. Keep bench supply powering the board; connect only GND, SWDIO, SWCLK (+NRST). Don't power from the ST-Link 3.3V.
   ```bash
   sudo apt install stlink-tools openocd
   st-info --probe                      # chip ID, flash size
   # Check RDP via OpenOCD (read only):
   openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
     -c "init; reset halt; mdw 0x1FFFF800 1; mdw 0x4002201C 1; shutdown"
   #   0x1FFFF800 low byte: 0xAA = RDP level 0 (unlocked), 0xCC = level 2, anything else = level 1
   #   FLASH_OBR (0x4002201C) bits [2:1] RDPRT
   # ONLY if level 0:
   st-flash read fw.bin 0x08000000 0x10000
   ```
   If level 1 or 2 → **STOP**, report to the owner. Never unlock.
5. If a dump is obtained: `strings`, search for `55 AA`, UART init (USART1/2 base 0x40013800 / 0x40004400, BRR values), font tables, display layout. Ghidra: ARM Cortex-M little-endian, base 0x08000000, vector table at start.
6. **Fallback for the real goal (rate + kWh):** tap the existing **CT signal** after op-amp conditioning (blue CT → ribbon → op-amp → STM32 ADC pin). Read it with the ESP's ADC (ESP-12F ADC range **0–1V** → needs divider), high-impedance tap so the MCU's reading isn't disturbed, assume nominal voltage (or find a voltage-sense line), calibrate against the car app. Plus read the 3 status LEDs on GPIOs for state. OLED SPI sniffing (needs glyph decoding; ESP32 better suited) is a later option, and firmware font tables would make it much easier.

---

## 12. Photo index

| # | File | What it shows |
|---|---|---|
| P01 | 01-charger-front-display-leds.jpg | Front of control box |
| P02 | 02-charger-rear-label-specs.jpg | Rear label: specs, LED table, model MT |
| P03 | 03-control-board-component-side-M1-top.jpg | Control board in shell, M1 at top |
| P04 | 04-control-board-component-side-M1-bottom.jpg | Same, rotated |
| P05 | 05-enclosure-open-control-and-power-boards.jpg | Both halves open |
| P06 | 06-power-board-relays-rcd-ct.jpg | Power board: relays, RCD toroid, blue CT |
| P07 | 07-esp12f-modules-and-programming-jig.jpg | ESP-12F reel + clamp programmer |
| P08 | 08-esp12f-test-fit-on-M1.jpg | Test fit — perfect footprint match |
| P09 | 09-M1-footprint-and-empty-regulator-closeup.jpg | M1 pads + empty SOT-223 |
| P10 | 10-M1-footprint-traces-closeup.jpg | Traces at M1 (EN→VCC etc.) |
| P11 | 11-control-board-overview-a.jpg | Overview |
| P12 | 12-control-board-overview-b.jpg | Overview |
| P13 | 13-existing-AMS1117-3.3-and-8MHz-crystal.jpg | MCU regulator AMS1117-3.3 |
| P14 | 14-MCU-STM32F030C8T6-closeup.jpg | MCU marking |
| P15 | 15-analog-section-soic8-chips-and-7pin-header-pads.jpg | SOIC-8s and 7-pin header pads |
| P16 | 16-opamp-MCP6002.jpg | MCP6002 |
| P17 | 17-opamp-TL082I-marked-082I.jpg | TL082I |
| P18 | 18-existing-AMS1117-VIN-pin-probe.jpg | Existing reg VIN pin |
| P19 | 19-empty-regulator-VIN-pad-probe.jpg | Empty footprint VIN pad (same net) |
| P20 | 20-ORIENTATION-REFERENCE-M1-antenna-down.jpg | **Reference orientation for all pin directions** |
| P21 | 21-7pin-header-ground-probe.jpg | Header pin mapping (GND) |
| P22 | 22-bench-setup-overview-esp-soldered.jpg | Current bench state |
| P23 | 23-existing-regulator-bench-wiring.jpg | Bench supply wiring on AMS1117 |
| P24 | 24-empty-regulator-footprint-3v3-jumper.jpg | Temporary 3.3V jumper |
| P25 | 25-esp12f-soldered-with-pullup-pulldown-resistors.jpg | ESP soldered (antenna left): 10k GPIO15→GND, 1k GPIO0→3.3V; orange/yellow probe wires on TXD/RXD |
| P26 | 26-display-board-back-oled-touch-leds-a.jpg | **Back of the control board** (flipped top-to-bottom vs P22): SPI OLED, touch springs, LED board, 7-pin header joints, M1 corner top-left. Highest-res view of the back. |
| P27 | 27-display-board-back-oled-touch-leds-b.jpg | Same |
| P28 | nov23/28-board-overview-new-regulator.jpg | Nov 23 overview with the new regulator fitted |
| P29 | nov23/29-new-AMS1117-3.3-fitted.jpg | New AMS1117-3.3 in the M1 regulator footprint |
| P30 | nov23/30-esp-top-row-smd-part.jpg | ESP top row close-up: SMD part at the GPIO15/GND end |
| — | P26-M1-back-vias.png | P26 zoomed on the M1 corner; marks the two linked vias (TXD routing) |
| — | P25-toprow-zoom.png | P25 zoomed on the ESP top row; shows the 1k on GPIO0 and the 10k on GPIO15/GND |

> **🎉 USART1 TELEMETRY MIRROR WORKING — JUMPERS GONE (Nov 25, v11).** The ESP now talks to the
> charger over the **factory traces (ESP GPIO1/GPIO3 hardware UART0 → MCU USART1 PA10/PA9, pins
> 31/30)** — no bit-bang jumper wires. Verified live: ESP **Link OK=ON, Good Frames climbing,
> Bad Frames=0**, V=123.9 / pilot 11.8 / temp 29.9 (byte-identical reply, decoder unchanged). MCU
> `ANSWERS` counter (0x20000298) climbs; `CR1`=0x0d. Image: `firmware/mustart_patched_v11.bin`;
> flash `firmware/flash_v11/flash_v11_held_reset.cfg`. ESP config: `esphome/mustart-evse-usart1.yaml`.
>
> **THE BUG THAT DEFEATED v5–v10 (and why emulation missed it):** `ldrb r4,[r6,#0x24]` — a byte
> load with offset 36 (>31) can't encode as 16-bit Thumb, so keystone silently emitted the 32-bit
> `ldrb.w`. **Cortex-M0 (ARMv6-M) can't execute Thumb-2** → undefined-instruction HardFault every
> time the USART RDR was read → the reboots. Unicorn ran it fine (lenient), so it passed every
> emulation. Fix: register-offset load (`movs r3,#0x24; ldrb r4,[r6,r3]`) + a build guard rejecting
> any non-16-bit instruction. (The "interrupt storm" and "RAM corruption" theories were red herrings.)
> Also: the borrowed buffer base 0x20000256 is only halfword-aligned, so reply header uses `strh`
> not `str` (M0 faults on unaligned word access).
>
> **RAM:** high RAM 0x20001260–0x20002000 is LIVE firmware memory (display framebuffer / relocated
> stack) — NOT free; buffers there corrupt the firmware. v2's 0x20001F00 survived only by luck
> (harmless pixels). v11 uses the firmware's own **idle USART2 TX buffer at 0x20000256** (ESP left
> USART2, so it's unused): REPLY=0x20000256, MATCHCNT=0x20000290, TXLEN=0x20000294, ANSWERS=0x20000298.
> RX needs no buffer — a byte-matcher against the fixed 11-byte poll.
>
> **SWD now stays alive at runtime:** v11's init restores **PA14→SWCLK** (the firmware normally
> repurposes it as USART2 TX, killing SWD). So the ST-Link attaches to the *running* firmware — no
> FT232, no held-reset dance for inspection. Debug read: `firmware/tools/attach_debug_v11.cfg`
> (reads CR1 / ANSWERS / MATCHCNT live). Future flashing is also easier (SWD generally available).
>
> **POWER GOTCHA:** the ESP's own AMS1117 regulator is fed from the mains/5V rail, **not** header
> pin 1 (which is only the MCU 3.3V). Power the board from the EVSE PSU (or bench 5V into the ESP
> reg input); powering via pin 1 runs the MCU but leaves the ESP dead. ST-Link does SWD only (no 3.3V).
>
> **Full firmware stack now on the chip (v11), calibration page 0x0800FC00 untouched, RDP 0, full
> backups in firmware/):** v2 crash-protection (IWDG watchdog, HardFault→reset, USART2 ORE-clear,
> OOB length clamp, reset counter @0x20001F00) + 12 A safe-default boot + USART1 telemetry mirror.
>
> **Open/optional:** (1) ESP poll interval is 3 s (diagnostic) — dial back to ~10–30 s for production
> in the yaml. (2) A real charge test with a car (confirm current/power slots + 12 A offer). (3) The
> debug 'U'/'A' USART2 trace is gone in v11 (PA14 is SWCLK now) — use the SWD attach instead.
