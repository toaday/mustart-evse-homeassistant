#!/usr/bin/env python3
"""Talk to the Mustart EVSE's USART2 port (header pin 7 = MCU RX, pin 6 = MCU TX, 9600 8N1).

SAFETY: only read-only commands are allowed (see firmware/FINDINGS.md §5/§6):
  cmd 0x01            live measurements
  cmd 0x07 sub 01 03  read config thresholds
Anything else is refused. Commands 0x00, 0x03, 0x07/02 and 0x55 write flash or control charging.

usage:
  evse_query.py listen [seconds]        passive: print anything the MCU sends
  evse_query.py live   [--send]         build cmd-1 request; transmits only with --send
  evse_query.py config [--send]         build cmd-7 01 03 request; transmits only with --send
"""
import sys, time, serial

PORT = '/dev/ttyUSB0'
DST, SRC = 0x000A, 0x0001
ALLOWED = {(0x01, b''), (0x07, b'\x01\x03')}

def build(cmd, payload=b''):
    assert (cmd, payload) in ALLOWED, 'REFUSED: not a read-only command'
    n = 1 + 2 + 2 + 2 + 1 + len(payload) + 2 + 1
    body = DST.to_bytes(2, 'little') + SRC.to_bytes(2, 'little') + n.to_bytes(2, 'little') + bytes([cmd]) + payload
    s = sum(body) & 0xFFFF
    raw = body + s.to_bytes(2, 'little')
    esc = bytearray()
    for b in raw:                     # byte stuffing (start/end bytes are not escaped)
        esc += {0xEB: b'\x27\x15', 0x90: b'\x27\x70', 0x27: b'\x27\xd9'}.get(b, bytes([b]))
    return b'\xeb' + bytes(esc) + b'\x90'

def unescape(f):
    out, i = bytearray(), 0
    while i < len(f):
        if f[i] == 0x27 and i + 1 < len(f):
            out.append({0x15: 0xEB, 0x70: 0x90, 0xD9: 0x27}.get(f[i+1], f[i+1])); i += 2
        else:
            out.append(f[i]); i += 1
    return bytes(out)

def decode(f):
    f = unescape(f)
    if len(f) < 11 or f[-1] != 0x90:
        return f'unparsed: {f.hex(" ")}'
    n = int.from_bytes(f[5:7], 'little')
    ok = (sum(f[1:n-3]) & 0xFFFF) == int.from_bytes(f[n-3:n-1], 'little')
    cmd, pl = f[7], f[8:n-3]
    s = f'cmd 0x{cmd:02x} len {n} checksum {"OK" if ok else "BAD"}\n  payload: {pl.hex(" ")}'
    if cmd == 0x01 and len(pl) >= 18:
        idx = [2, 1, 10, 3, 5, 4, 11, 11, 11]
        vals = [int.from_bytes(pl[i*2:i*2+2], 'little') for i in range(9)]
        s += '\n  ' + '  '.join(f'slot{i}={v}' for i, v in zip(idx, vals))
    return s

def read_for(ser, seconds):
    end, buf = time.time() + seconds, bytearray()
    while time.time() < end:
        buf += ser.read(256)
    return bytes(buf)

if __name__ == '__main__':
    mode = sys.argv[1]
    ser = serial.Serial(PORT, 9600, timeout=0.1)
    if mode == 'listen':
        secs = float(sys.argv[2]) if len(sys.argv) > 2 else 10
        data = read_for(ser, secs)
        print(f'received {len(data)} bytes: {data.hex(" ")}')
        sys.exit()
    frame = build(0x01) if mode == 'live' else build(0x07, b'\x01\x03')
    print('request:', frame.hex(' '))
    if '--send' not in sys.argv:
        print('(not sent: dry run)'); sys.exit()
    ser.reset_input_buffer()
    ser.write(frame); ser.flush()
    data = read_for(ser, 1.5)
    print(f'reply {len(data)} bytes: {data.hex(" ")}')
    if data:
        print(decode(data))
