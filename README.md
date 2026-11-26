# Mustart MT Portable EVSE → Home Assistant (firmware mod, no cloud)

Local, cloud-free telemetry and crash-hardening for a sealed **Mustart MT** portable EV charger,
built around an **STM32F030C8T6** MCU. The result: live voltage / current / power / energy / pilot /
temperature in **Home Assistant** over the charger's *own* factory UART traces (no kludgy jumper
wires), plus firmware patches that make the unit far more robust — all with the factory calibration
left untouched.

> **This is a reverse-engineering + firmware-modding writeup.** It documents what we found and the
> method we used. It does **not** redistribute Mustart's firmware — you dump your own unit and run
> the scripts here against it.

---

## ⚠️ Safety & disclaimer — read this first

- **Mains voltage and a charged HV cap.** The control board has an offline flyback with a ~400 V
  bulk cap. Treat it as live until proven discharged. **Never** work on the board with mains connected;
  bench-power the logic from a 5 V supply into the regulator with the mains connector unplugged.
- **This voids your warranty and can brick or destroy the charger, your car, or worse.** EV charging
  equipment is safety-critical. Everything here is provided **as-is, no warranty, at your own risk.**
- **It voids the unit's safety certification.** The charger ships ETL/Intertek-listed; opening and
  modifying it invalidates that listing, which may affect your insurance, local electrical-code
  compliance, and liability if anything goes wrong. Understand that before returning a modified unit to service.
- **We never weaken safety.** The mod only *adds* protection (watchdog, fault-reset) and *lowers* the
  default offered current. It never increases current beyond what the user selects, and it never
  touches the contactor / pilot / charge-control logic or the factory calibration page.
- The telemetry link is **read-only** — it only ever sends the charger's `cmd 0x01` "read values"
  frame. The write commands (factory-reset, charge start/stop, calibration) are documented so you can
  **avoid** them. Don't send them.
- Not affiliated with or endorsed by Mustart. All trademarks belong to their owners.

---

## What you get

- 📡 **Live telemetry in Home Assistant** (ESPHome, local push API — no Mustart cloud):
  mains voltage, current, power, session energy (kWh), control-pilot voltage, temperature, J1772 state,
  plus link-health diagnostics.
- 🧵 **No jumper wires** — the ESP talks to the MCU over the board's existing **M1-module UART traces**
  (ESP hardware UART0 on GPIO1/GPIO3 → MCU USART1 on PA9/PA10).
- 🛡️ **Crash-hardening** — an independent watchdog (IWDG), HardFault→reset (the stock handler is a dead
  loop), a USART overrun-flag fix, and an out-of-bounds length clamp in the frame parser.
- ⚡ **Safer boot default** — the unit boots at **12 A** instead of 16 A (safe on a 15 A / 120 V adapter);
  one button press still selects 16 A.
- 🔌 **SWD stays alive** at runtime (the final build restores PA14→SWCLK), so you can inspect/flash
  without the connect-under-reset dance.

---

## How it works (architecture)

```
   240/120 V mains ─► EVSE PSU ─► 3.3 V ─► STM32F030C8 (charge control, J1772, display, measurement)
                                    │                 ▲
                                    │ USART1 (PA9 TX / PA10 RX, 9600 8N1)   ◄── our firmware patch
                                    ▼                 │  (factory M1-module traces, pins 30/31)
                           ESP-12F (ESP8266, ESPHome) │
                            GPIO3 RX ◄────────────────┘
                            GPIO1 TX ─────────────────► PA10
                            WiFi ─► Home Assistant (native API)
```

- The STM32 speaks a **custom framed UART protocol** on USART2 (the factory service/debug header) —
  `0xEB` start, `0x90` end, `0x27` escape, 16-bit checksum. `cmd 0x01` returns a 33-byte reply with a
  table of measurements.
- Stock firmware **never initializes USART1** (the WiFi-module port) — so our patch brings it up and
  makes it answer the exact same `cmd 0x01` reply there too. The ESP decoder is unchanged.
- The ESP runs **ESPHome**, polls `cmd 0x01`, parses the reply, and publishes entities to Home Assistant.

See [`firmware/FINDINGS.md`](firmware/FINDINGS.md) for the full protocol + pin map, and
[`firmware/FIRMWARE_MAP.md`](firmware/FIRMWARE_MAP.md) for the annotated firmware architecture.

---

## The patches

All patches are **additive, surgical, and reversible** (full backup + RDP level 0 + connect-under-reset).
The calibration/config page (`0x0800FC00`) is **never** written.

| Patch | What it does |
|---|---|
| **USART2 ORE-clear** | ISR only ack'd the IDLE flag; a line-noise overrun could wedge RX forever. Clear ORE/NE/FE too. |
| **Frame-length clamp** | Parser checksummed over an unchecked 16-bit length → OOB read → HardFault. Clamp to the RX buffer size. |
| **HardFault → reset** | Stock handler is an infinite loop (any crash = dead until power-cycle). Repoint to `NVIC_SystemReset`. Also opens the contactor on a mid-charge fault. |
| **IWDG watchdog** | ~2.9 s independent watchdog, inited at boot and kicked in the main loop. Recovers from *any* hang. |
| **Reset counter / cause** | Bookkeeping block in RAM (magic + total + RCC_CSR cause + per-cause counts), readable over SWD. |
| **12 A safe-default boot** | Clamp the stored default offered-current to ≤12 A at boot. Runtime 12↔16 button toggle still works. |
| **USART1 telemetry mirror** | Init USART1 (PA9/PA10 AF1, 9600, internal pull-up on RX), answer `cmd 0x01` with a byte-identical reply. Final build also restores PA14→SWCLK. |

### The bug that mattered (and a lesson)

Six iterations of the USART1 mirror rebooted the MCU, and **emulation passed every time**. The culprit:
```asm
ldrb r4, [r6, #0x24]    ; byte-load, offset 36 (> 31) ...
```
Offset 36 can't encode as 16-bit Thumb, so the assembler silently emitted the **32-bit `ldrb.w`** — an
instruction the **Cortex-M0 (ARMv6-M) cannot execute**. Undefined-instruction → HardFault every time the
UART data register was read. Unicorn runs Thumb-2 happily, so it never caught it. Fix: a register-offset
load, plus a build-time guard that **rejects any non-16-bit instruction**. Moral: when targeting M0,
verify every instruction is 16-bit (or a legal wide one: `bl`, `dsb`, `dmb`, `isb`, `msr`, `mrs`).

Another non-obvious one: high RAM (`0x20001260`–`0x20002000`) is **live firmware memory** (display
framebuffer / stack) — not free. The working build borrows the firmware's **idle USART2 TX buffer**
(`0x20000256`) for its reply and uses a byte-matcher (no RX buffer) so it needs essentially no RAM.

---

## Reproduce it on your own unit

You need: an **ST-Link V2** (clone is fine), an FTDI/USB-serial adapter (3.3 V), a soldering iron, a
meter, and Python with `keystone-engine`, `capstone`, `unicorn`, `pyserial`. **Read the safety section.**

1. **Identify the header.** The 7-pin edge header is the SWD + service UART (square pad = pin 1):
   `1=3V3, 2=SWDIO (PA13), 3=NRST, 5=GND, 6=SWCLK/USART2-TX (PA14), 7=USART2-RX (PA15)`.
2. **Dump your firmware** (read-only; RDP is level 0). The firmware repurposes PA14 as USART2 TX, so you
   must **connect under reset** — jumper pin 3→pin 5 to hold NRST low, arm halt-on-reset, release, dump.
   See [`firmware/PATCH_PLAN.md`](firmware/PATCH_PLAN.md).
3. **Build the patched image** from your dump with the scripts in [`firmware/tools/`](firmware/tools/)
   (each emits a patched image + the 1 KB flash pages; nothing hardcodes the OEM binary).
4. **Flash** the changed pages via OpenOCD held-reset (the `flash_*_held_reset.cfg` pattern). The
   calibration page is never in the set. Verify, keep your backup.
5. **Solder the ESP** into the M1 footprint (or wire an ESP-12F), flash
   [`esphome/mustart-evse-usart1.yaml`](esphome/mustart-evse-usart1.yaml), and point it at your HA.

> Binaries (your dump, patched images, flash pages, calibration) are intentionally **git-ignored** —
> they're OEM-derived and unit-specific. You generate them locally from your own dump.

---

## Repo layout

```
README.md                      ← you are here
HOME_ASSISTANT_AGENT.md        ← handoff for a Home-Assistant AI agent (entities, quirks, do's/don'ts)
esphome/
  mustart-evse-usart1.yaml     ← final config: ESP hardware UART0 on GPIO1/3 → USART1 (no jumpers)
  mustart-evse.yaml            ← earlier bit-bang config (GPIO5/4 → header pins 7/6) kept for reference
firmware/
  FINDINGS.md                  ← protocol, pin map, command set, reliability findings (the deep notes)
  FIRMWARE_MAP.md              ← annotated firmware architecture (subsystems, addresses)
  PATCH_PLAN.md                ← patch designs, flashing procedure, bench tests, rollback
  tools/                       ← patch build scripts (keystone), capture/flash helpers (Python + OpenOCD)
evse-handoff/
  HANDOFF.md                   ← the full chronological dev log (the whole journey, warts and all)
```

---

## Status

**Working and validated on hardware** (Nov 2025): telemetry live in Home Assistant over the factory
traces, crash-protection running, 12 A safe default, calibration intact, on 120 V and 240 V. The only
thing left is a passive confirmation of the current/power slots during a real charge.

Built collaboratively by the owner (all hands-on hardware work) with Claude (analysis, patches, debugging).
