#!/usr/bin/env python3
"""Fuzz the Mustart firmware's USART2 receive path (DMA + IDLE interrupt + parser) in Unicorn.

Models the hardware the firmware relies on:
  - DMA1 channel 5 (RX): each received byte goes to rx_buf[100 - CNDTR], CNDTR--, and at 0 it
    raises TCIF5 and runs DMA1_Ch4_5_IRQ (the firmware restarts the channel).
  - USART2 IDLE: after each burst, ISR.IDLE is set and USART2_IRQ runs.
  - Main loop poll FUN_08001EE8 runs after each burst.
A reply is detected when the firmware starts TX DMA (writes channel-4 CNDTR).
Also flags any flash/flash-controller write (must never happen for junk input).

usage: emu_link_fuzz.py <firmware.bin> [trials]
"""
import sys, random, struct
from unicorn import *
from unicorn.arm_const import *

FW = open(sys.argv[1], 'rb').read()
TRIALS = int(sys.argv[2]) if len(sys.argv) > 2 else 500
FLASH, RAM, STOP, MAIN = 0x08000000, 0x20000000, 0x00100000, 0x08004D70
RX = 0x200002BA
USART2 = 0x40004400; U_ISR, U_ICR = USART2 + 0x1C, USART2 + 0x20
DMA_ISR, DMA_IFCR = 0x40020000, 0x40020004
CH4_CNDTR = 0x40020048
CH5_CCR, CH5_CNDTR = 0x40020058, 0x4002005C
F_USART2_IRQ, F_DMA45_IRQ, F_POLL, F_INIT = 0x08003A2C, 0x080019D4, 0x08001EE8, 0x080018C4
GOOD = bytes.fromhex('EB0A0001000B00011700 90'.replace(' ', ''))

class Crash(Exception):
    pass

class Rig:
    def __init__(self):
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        mu.mem_map(FLASH, 0x10000); mu.mem_write(FLASH, FW)
        mu.mem_map(RAM, 0x2000); mu.mem_map(0x1FFFE000, 0x2000)
        mu.mem_map(0x40000000, 0x30000); mu.mem_map(0x48000000, 0x2000)
        mu.mem_map(0xE0000000, 0x100000); mu.mem_map(STOP, 0x1000)
        mu.reg_write(UC_ARM_REG_SP, 0x20001260)
        mu.reg_write(UC_ARM_REG_LR, STOP | 1)
        mu.emu_start(0x080000B4 | 1, MAIN, count=5_000_000)
        mu.reg_write(UC_ARM_REG_SP, 0x20001200)
        self.call(F_INIT)
        self.replies, self.writes = 0, []
        mu.hook_add(UC_HOOK_MEM_WRITE, self.on_write)

    def on_write(self, mu, access, addr, size, value, _):
        if addr == CH4_CNDTR and value:
            self.replies += 1
        elif addr == U_ICR:                       # write-1-to-clear
            isr = self.r32(U_ISR); mu.mem_write(U_ISR, struct.pack('<I', isr & ~value))
        elif addr == DMA_IFCR:
            isr = self.r32(DMA_ISR); mu.mem_write(DMA_ISR, struct.pack('<I', isr & ~value))
        elif FLASH <= addr < FLASH + 0x10000 or 0x40022000 <= addr < 0x40022400:
            self.writes.append(hex(addr))

    def r32(self, a): return struct.unpack('<I', self.mu.mem_read(a, 4))[0]
    def w32(self, a, v): self.mu.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def call(self, fn, limit=2_000_000):
        self.mu.reg_write(UC_ARM_REG_SP, 0x20001200)
        self.mu.reg_write(UC_ARM_REG_LR, STOP | 1)
        try:
            self.mu.emu_start(fn | 1, STOP, count=limit)
        except UcError as e:
            pc = self.mu.reg_read(UC_ARM_REG_PC)
            raise Crash(f'{e} pc=0x{pc:08x} fn=0x{fn:08x}')

    def burst(self, data):
        """Bytes arrive back-to-back, then the line goes idle."""
        for b in data:
            if not (self.r32(CH5_CCR) & 1):
                continue                          # DMA disabled: byte lost (overrun)
            n = self.r32(CH5_CNDTR) & 0xFFFF
            if n == 0:
                continue
            self.mu.mem_write(RX + (100 - n), bytes([b]))
            n -= 1; self.w32(CH5_CNDTR, n)
            if n == 0:
                self.w32(DMA_ISR, self.r32(DMA_ISR) | (1 << 16) | (1 << 17))
                self.call(F_DMA45_IRQ)
        if data:
            self.w32(U_ISR, self.r32(U_ISR) | 0x10)  # IDLE
            self.call(F_USART2_IRQ)
        self.call(F_POLL)

    def ask(self):
        before = self.replies
        self.burst(GOOD)
        return self.replies > before

def junk(rnd):
    kind = rnd.random()
    if kind < 0.3:  return bytes(rnd.randrange(256) for _ in range(rnd.randint(1, 10)))     # short noise
    if kind < 0.5:  return bytes(rnd.randrange(256) for _ in range(rnd.randint(11, 130)))   # long noise
    if kind < 0.65: return GOOD[:rnd.randint(1, 10)]                                       # truncated frame
    if kind < 0.8:  return bytes([0x00] * rnd.randint(1, 3))                               # break-like zeros
    if kind < 0.9:  return bytes(rnd.randrange(256) for _ in range(rnd.randint(1, 5))) + GOOD   # junk glued in front
    return GOOD + bytes(rnd.randrange(256) for _ in range(rnd.randint(1, 5)))              # junk glued after

if __name__ == '__main__':
    rig = Rig()
    print('baseline reply:', rig.ask(), rig.ask())
    rnd = random.Random(1)
    stuck, writes = [], 0
    crashes = []
    for t in range(TRIALS):
        seq = [junk(rnd) for _ in range(rnd.randint(1, 6))]
        try:
            for i, s in enumerate(seq):
                rig.burst(s)
            ok = [rig.ask() for _ in range(3)]
            if not any(ok):
                stuck.append((t, [s.hex() for s in seq]))
        except Crash as c:
            crashes.append((t, str(c), [x.hex() for x in seq[:i + 1]]))
            rig = Rig()
    print(f'trials: {TRIALS}, never-recovered-within-3-polls: {len(stuck)}, flash/ctrl writes: {len(rig.writes)}')
    print(f'CRASHES (would HardFault the real MCU): {len(crashes)}')
    for t, c, seq in crashes[:8]:
        print(' trial', t, c)
        print('   inputs:', seq)
    for t, seq in stuck[:10]:
        print(' stuck after trial', t, seq)
    # first-poll-after-junk failure rate (recovers on next poll)
