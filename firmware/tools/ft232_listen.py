#!/usr/bin/env python3
"""LISTEN-ONLY on the MCU TX line (header pin 6). Sends NOTHING.
Lets the ESP do the polling while we watch whether the MCU actually replies.
Wire: FT232 RX -> pin 6, GND -> pin 5.  Leave FT232 TX DISCONNECTED.
Usage: python3 tools/ft232_listen.py [/dev/ttyUSB0] [seconds]
"""
import sys, time
try:
    import serial
except ImportError:
    sys.exit("pyserial not installed: pip install --user pyserial")
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
try:
    s = serial.Serial(PORT, 9600, timeout=0.2)
except Exception as e:
    sys.exit(f"could not open {PORT}: {e}")
print(f"listening on {PORT} @ 9600 for {SECS:.0f}s (sending nothing)...\n")
t0=time.time(); total=0; frames=0; buf=bytearray()
while time.time()-t0 < SECS:
    b=s.read(64)
    if not b: continue
    total+=len(b); buf+=b
    print(f"  +{time.time()-t0:5.1f}s  {len(b):2d}B  {b.hex(' ')}")
    # try to spot a 33-byte EB..90 frame
    while 0xEB in buf:
        i=buf.index(0xEB)
        if 0x90 in buf[i+1:]:
            j=buf.index(0x90, i+1)
            if j-i+1==33: frames+=1
            del buf[:j+1]
        else:
            break
s.close()
print(f"\n== {total} bytes total, {frames} full 33-byte frame(s) ==")
print("MCU IS REPLYING to the ESP's polls  -> the ESP's poll reaches the MCU (GPIO5->pin7 OK);"
      "\n   fault is the ESP's RX side: it isn't hearing pin 6 (GPIO4 input/solder/config)." if total
      else "MCU SILENT while ESP polls  -> the ESP's poll is NOT reaching the MCU (GPIO5->pin7 / ESP TX);"
      "\n   the MCU never gets asked, so never answers.")
