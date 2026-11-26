# Mustart EVSE MCU firmware patch — plan & procedure

Goal: stop the telemetry link from dying, by fixing the MCU's USART2 receiver so a line-noise
overrun no longer wedges it permanently.

## Patches

### Patch A — USART2 overrun/error-flag clear  ✅ BUILT, recommended first and alone
- **Root cause:** `USART2_IRQ` (0x08003A2C) acknowledges only the IDLE flag. Its clear helper
  `FUN_08003A7C` writes its argument to **USART2_ICR** (0x40004420); the ISR passes **0x10**
  (IDLECF only). An overrun (ORE) is therefore never cleared, so after a noisy burst the receiver
  stalls until the chip is reset — exactly the "link dies but display still works" symptom.
- **Fix:** change the ICR write mask from `0x10` → `0x1F` (also clears PE/FE/NE/**ORE**). On the
  next idle period the ISR now clears the overrun and RX resumes.
- **Byte change:** flash `0x08003A3A`, `movs r1,#0x10` (`10 21`) → `movs r1,#0x1F` (`1F 21`).
  **One byte.** No added code, no free flash needed.
- **Safety:** writing 1s to ICR status bits only acknowledges flags — no effect on TX, data, the
  contactor, pilot, or charge logic. None of those code paths are touched.
- **Artifacts:** `mustart_patched_v1_A.bin` (full image, 1 byte diff) and
  `patch_page14_0x08003800.bin` (just the 1 KB flash page that changed).

### CORRECTION — flash is NOT full (Nov 24)
Earlier note said "flash is full." Wrong: that scan looked for erased `0xFF`. The free space is
`0x00`-filled. There is a verified-unused contiguous block **`0x08008CE8`–`0x0800FBFF` (~28 KB)** below
the config page — all zeros, referenced only by an end-of-data boundary marker at `0x08000A80`, never
read or executed. Usable for added code after erasing each 1 KB page to `0xFF`. So Patches B/C/HardFault
are all feasible. Added code executes in place from flash (it is not `.data`, so the boundary marker is
irrelevant to it).

### Patch B — frame-length clamp (OOB-read crash)  ⚠️ OPTIONAL
- `FUN_08003C3E` checksum loop reads `frame[1..len-3]` where `len = frame[5]|frame[6]<<8` is never
  clamped (asm: len built at 0x08003CC4, loop at 0x08003CCA). A huge length walks off the 100-byte
  RX buffer → HardFault → permanent hang (no watchdog).
- Prevents the known crash at source, but the patch site is mid-function (2-byte slot, long-range
  detour) = the riskiest edit. With the watchdog + HardFault→reset below, the crash already
  auto-recovers, so B is lower priority. Emulator-validate with crafted frames before use.

### Patch C — crash recovery: IWDG watchdog + HardFault→reset  ✅ FEASIBLE (recommended for crash protection)
- **IWDG watchdog:** init (~2 s) just before the main loop and refresh each loop. Recovers from ANY
  hang (the OOB HardFault dead-loop and any other). Implemented by **repointing existing `bl` calls**
  to veneers in free flash (clean: the call site is already a 4-byte `bl`, so only the offset changes;
  the veneer does its work then tail-calls the original) — no risky mid-function surgery.
- **HardFault→reset:** repoint the HardFault vector (0x0800000C) to a stub in free flash that does
  NVIC_SystemReset (write 0x05FA0004 to SCB->AIRCR 0xE000ED0C). Instant recovery from any fault.
  Also fixes a latent hazard: in stock firmware the fault handler is an infinite loop, so a crash
  **during charging** leaves PA11/PA12 latched CLOSED and TIM1 pilot PWM still running — unsupervised
  charging continues until power is pulled. Resetting on fault opens the contactor and stops the pilot.

## Flashing procedure (ST-Link + OpenOCD) — preserves calibration

The ST-Link connects to the 7-pin header: 3V3, GND, SWDIO (PA13), SWCLK (PA14), NRST. The firmware
repurposes PA14, so **connect under reset** (same as when we dumped). The config/calibration page
(0x0800FC00) is in a different flash page and is **not** written by this procedure.

1. **Back up the live chip first** (captures current calibration, in case it changed since Nov 23):
   ```
   openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
     -c "init; reset halt; dump_image live_predump.bin 0x08000000 0x10000; shutdown"
   ```
   Compare `live_predump.bin` config page to `backups/backup_config_page_0800FC00.bin`. If it differs,
   splice our one-byte change into `live_predump.bin` instead and flash that page from it.

2. **Flash only the changed 1 KB page** (leaves everything else, incl. calibration, physically intact):
   ```
   openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
     -c "init; reset halt; \
         flash erase_address 0x08003800 0x400; \
         flash write_image patch_page14_0x08003800.bin 0x08003800; \
         verify_image patch_page14_0x08003800.bin 0x08003800; \
         reset run; shutdown"
   ```

3. **Verify the byte** (optional explicit check):
   ```
   openocd ... -c "init; reset halt; mdb 0x08003a3a 1; shutdown"   # expect 0x1f
   ```

## Bench test BEFORE mains / car
- Power the board on the bench (no mains AC, no vehicle).
- With SWD halted, read **GPIOA_ODR** `mdw 0x48000014` and confirm bits 11 & 12 are **0** (PA11/PA12
  LOW = contactor OPEN). The firmware drives them open at boot (FINDINGS §14); confirm the patch
  didn't disturb that.
- Send one read-only cmd-01 (`EB 0A 00 01 00 0B 00 01 17 00 90`) over the serial port (FTDI or the
  ESP) and confirm a 33-byte reply. Then hammer it / inject noise and confirm it **recovers** instead
  of stalling — that's the whole point of Patch A.
- Only after this passes: reconnect mains and a car, watch for stability.

## Rollback (always available)
- Full restore: `program backups/stm32f030c8_fw_dump1.bin verify reset` (writes the exact original).
- RDP stays **level 0** — never set it. As long as we connect-under-reset, the chip is never bricked.

## Why this is safe
- Verified byte-identical full backup + RDP0 + working SWD ⇒ any result is reversible.
- Patch A touches only the serial ISR's flag acknowledge; contactor/pilot/charge code untouched.
- Calibration page is never written (page-scoped flash) and is backed up regardless.

---
# v2 — BUILT & EMULATOR-VALIDATED (Nov 24)

Image: `mustart_patched_v2.bin`. Builder `tools/build_patch.py` (keystone, two-pass assembler,
no hand-encoding). Validator `tools/validate_patch.py` (unicorn). venv: `tools/patchenv`.

## What's in it
- **A** USART2 ISR error-clear: `0x08003A3A` `movs r1,#0x10`→`#0x1F` (clears ORE/NE/FE, not just IDLE).
- **HardFault→reset**: vector `0x0800000C` → `hf_reset` @ `0x08009001` → `NVIC_SystemReset`
  (AIRCR=0x05FA0004). Any fault now auto-resets instead of dead-looping (also opens the contactor).
- **IWDG watchdog** (~2.9 s, PR=/256, RLR=0x1C2): `boot_veneer` @ `0x08009018` (hooked from main's
  `bl FUN_080055D8`) inits it; `wdt_refresh` @ `0x0800909C` (hooked from main's two `bl FUN_080011CC`)
  reloads it each loop. Veneers tail-call the originals, so behavior is unchanged except the added work.
- **Reset counter + cause**: `boot_veneer` keeps a RAM block (survives warm resets, re-zeros on power loss).

## Reset bookkeeping block @ 0x20001F00 (read over SWD: `mdw 0x20001F00 5`)
| off | word | meaning |
|---|---|---|
| +0x00 | magic `0xB007C0DE` | set on cold boot; its absence = power-on |
| +0x04 | total_count | resets since last power-on |
| +0x08 | last_csr | raw RCC_CSR: bit29 IWDG, bit28 SFT(fault→reset), bit27 POR, bit26 PIN |
| +0x0C | iwdg_count | watchdog-triggered resets |
| +0x10 | fault_count | HardFault→reset events |

## Validation (all PASS)
- hf_reset writes AIRCR=0x05FA0004.
- boot_veneer: cold boot sets magic+count=0+latches CSR+clears flags+full IWDG init+tail-calls init;
  warm boot increments total and the right per-cause counter (IWDG vs fault).
- wdt_refresh writes IWDG=0xAAAA and tail-calls the original.
- cmd-01 telemetry reply is **byte-identical** to the stock image (parser untouched).

## Flashing (ST-Link, connect-under-reset) — calibration never touched
Only 4 pages change; the config page `0x0800FC00` is not in the set.
Files in `flash_v2/`; script `flash_v2/flash_patch_v2.cfg`:
```
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg -f flash_v2/flash_patch_v2.cfg
```
It dumps `live_predump.bin` first (compare its 0x0800FC00 page to backups/ to confirm calibration
unchanged), then erases+writes+verifies pages 0x08000000, 0x08003800, 0x08004C00, 0x08009000.

## Bench test (no mains / no car) BEFORE reconnecting
1. After flashing, `mdw 0x20001F00 5` → expect magic set, total=0 (first cold boot), last_csr shows POR.
2. `mdw 0x48000014 1` → PA11/PA12 (bits 11/12) = 0 (contactor OPEN at idle).
3. Confirm a cmd-01 poll still replies (ESP or FTDI).
4. **Watchdog test:** halt the CPU (`halt`) and leave it halted > 3 s, `resume` — the IWDG should have
   reset the MCU (total_count increments, last_csr bit29 IWDG set). Or set a breakpoint in the main loop
   and stall it.
5. **Fault test:** write a bad USART2 frame with a huge length field to trigger the OOB read → the MCU
   should auto-reset (fault_count increments, last_csr bit28 SFT set) instead of hanging.
6. Only after these pass: reconnect mains + car.

## Rollback
`program backups/stm32f030c8_fw_dump1.bin verify reset` restores the exact original. RDP stays 0.

## v2 update — Patch B (length clamp) ADDED & validated (Nov 24)
- `clamp_veneer` clamps frame length to <=100 (RX buffer) before the checksum loop; hooked by overwriting
  the 4 bytes at `0x08003CC4` (`uxth r5,r0; movs r1,#1`) with `bl clamp_veneer`. FUN_08003C3E saves LR
  (push/pop), so the `bl` detour is safe; the veneer replicates both original instructions and `bx lr`
  back to `0x08003CC8`.
- **Fuzz result:** original firmware = 66 HardFault crashes / 1000 trials; patched = **0 / 1000**. Eliminated.
- Clamp unit test: len 0x9000/0xFF/100 -> 100; len 33/11 -> unchanged; loop counter + return preserved.
- Adds one page to the flash set: now **5 pages** (0x08000000, 0x08003800, 0x08003C00, 0x08004C00, 0x08009000).
  Config page still untouched.
