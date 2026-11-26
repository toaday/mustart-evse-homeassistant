#!/usr/bin/env python3
"""Send commands to a running OpenOCD over its TCL port (6666) and print replies.

Safety guard: refuses any command that could write flash or option bytes
(project hard rule: MCU access is read-only).
"""
import socket, sys

FORBIDDEN = ('flash', 'erase', 'unlock', 'mass_erase', 'program', 'write_image',
             'load_image', 'option', 'stm32f0x lock', 'stm32f1x', 'mwb', 'mwh')
# mww is allowed ONLY to Cortex-M debug registers (0xE000xxxx), never memory/flash/peripherals.

def check(cmd):
    c = cmd.lower()
    for f in FORBIDDEN:
        if f in c:
            sys.exit(f"REFUSED (read-only rule): {cmd}")
    if c.startswith('mww'):
        addr = int(c.split()[1], 0)
        if not (0xE000ED00 <= addr <= 0xE000EDFF):
            sys.exit(f"REFUSED: mww outside Cortex-M debug registers: {cmd}")

s = socket.create_connection(('127.0.0.1', 6666), timeout=15)
for cmd in sys.argv[1:]:
    check(cmd)
    s.sendall(cmd.encode() + b'\x1a')
    buf = b''
    while not buf.endswith(b'\x1a'):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    print(f"> {cmd}\n{buf.rstrip(b'\x1a').decode(errors='replace').strip()}")
