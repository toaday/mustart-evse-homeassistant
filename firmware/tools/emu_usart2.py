#!/usr/bin/env python3
"""Emulate the Mustart STM32F030 firmware's USART2 frame handling with Unicorn.

Nothing touches real hardware: the firmware image is loaded into an emulated
Cortex-M0, a request frame is placed in the RX buffer, and the firmware's own
parser/dispatcher runs. Reports the reply frame and flags any attempt to write
flash, touch the FLASH controller, or change GPIO outputs (relay control).

usage: emu_usart2.py <firmware.bin> <hex frame> [<hex frame> ...]
"""
import sys, struct
from unicorn import *
from unicorn.arm_const import *

FW = open(sys.argv[1], 'rb').read()
FLASH, RAM, STOP = 0x08000000, 0x20000000, 0x00100000
MAIN = 0x08004D70            # from __main: ldr r0,=0x08004d71; bx r0
RX, TX = 0x200002BA, 0x20000256
CTRL = 0x20000316            # rx+0x5c: +8 = rx byte count, +0x11 = frame-ready flag
REPLY_LEN = 0x20000322       # rx+0x68 (u16)

def fresh():
    mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    mu.mem_map(FLASH, 0x10000); mu.mem_write(FLASH, FW)
    mu.mem_map(RAM, 0x2000)
    mu.mem_map(0x1FFFE000, 0x2000)              # system memory / option bytes
    mu.mem_map(0x40000000, 0x30000)             # APB/AHB1 peripherals (as plain RAM)
    mu.mem_map(0x48000000, 0x2000)              # GPIO
    mu.mem_map(0xE0000000, 0x100000)            # SCS
    mu.mem_map(STOP, 0x1000)
    mu.mem_write(STOP, b'\xfe\xe7' * 8)         # b . (never reached; we stop on fetch)
    return mu

events = []
def on_write(mu, access, addr, size, value, _):
    if FLASH <= addr < FLASH + 0x10000:
        events.append(f'!! FLASH WRITE attempt @0x{addr:08x} = 0x{value:x}')
    elif 0x40022000 <= addr < 0x40022400:
        events.append(f'!! FLASH controller reg write @0x{addr:08x} = 0x{value:x}')
    elif 0x48000000 <= addr < 0x48002000 and (addr & 0x3FF) in (0x14, 0x18, 0x28):
        events.append(f'!! GPIO output change @0x{addr:08x} (port {"ABCDEF"[(addr>>10)&7]} reg 0x{addr&0x3ff:x}) = 0x{value:x}')

def call(mu, fn, args=(), limit=2_000_000):
    for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        mu.reg_write(r, v)
    mu.reg_write(UC_ARM_REG_LR, STOP | 1)
    mu.emu_start(fn | 1, STOP, count=limit)

def setup():
    mu = fresh()
    mu.reg_write(UC_ARM_REG_SP, 0x20001260)
    mu.reg_write(UC_ARM_REG_LR, STOP | 1)
    # C runtime init (__main -> scatterload), stop at main
    mu.emu_start(0x080000B4 | 1, MAIN, count=5_000_000)
    assert mu.reg_read(UC_ARM_REG_PC) == MAIN, hex(mu.reg_read(UC_ARM_REG_PC))
    mu.reg_write(UC_ARM_REG_SP, 0x20001200)
    call(mu, 0x080018C4)   # protocol/init: struct pointers, USART2 init, config copy from 0x0800FC00
    mu.hook_add(UC_HOOK_MEM_WRITE, on_write)
    return mu

for hx in sys.argv[2:]:
    frame = bytes.fromhex(hx.replace(' ', ''))
    events.clear()
    mu = setup()
    mu.mem_write(RX, frame + b'\x00' * (100 - len(frame)))
    mu.mem_write(REPLY_LEN, b'\x00\x00')
    mu.mem_write(CTRL + 8, struct.pack('<H', len(frame)))
    mu.mem_write(CTRL + 0x11, b'\x01')
    mu.mem_write(TX, b'\x00' * 100)
    call(mu, 0x08001EE8)   # main-loop poll: parse + dispatch + build reply
    n = struct.unpack('<H', mu.mem_read(REPLY_LEN, 2))[0]
    tx = bytes(mu.mem_read(TX, max(n, 1)))
    print(f'request : {frame.hex(" ")}')
    print(f'reply   : {tx.hex(" ") if n else "(none)"}  [{n} bytes]')
    for e in events: print('  ' + e)
    if not events: print('  no flash / flash-controller / GPIO-output writes')
    print()
