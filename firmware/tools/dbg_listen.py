#!/usr/bin/env python3
"""Listen on USART2 TX (header pin 6) for the v5 debug trace. FT232 RX->pin6, GND->pin5 (TX off).
Expect 'U' once at boot (USART1 init ran, no storm), then 'A' each time it answers an ESP poll.
Usage: python3 tools/dbg_listen.py [/dev/ttyUSB0] [seconds]"""
import sys,time,serial
PORT=sys.argv[1] if len(sys.argv)>1 else "/dev/ttyUSB0"
SECS=float(sys.argv[2]) if len(sys.argv)>2 else 30
s=serial.Serial(PORT,9600,timeout=0.2)
print(f"listening {SECS:.0f}s on {PORT} (pin 6 / USART2 TX)...  U=init-ok  A=answered-poll")
t0=time.time()
while time.time()-t0<SECS:
    b=s.read(64)
    for x in b:
        c=chr(x) if 32<=x<127 else '.'
        print(f"  +{time.time()-t0:5.1f}s  0x{x:02x} '{c}'")
s.close()
