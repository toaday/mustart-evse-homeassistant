#!/usr/bin/env python3
"""Send the read-only cmd-01 poll to the MCU over an FT232 and print any reply.
SAFETY: only ever sends the one read-only frame (cmd 0x01). Never any write command.
Usage:  python3 tools/ft232_poll.py [/dev/ttyUSB0]
"""
import sys, time
try:
    import serial
except ImportError:
    sys.exit("pyserial not installed. Run:  pip install --user pyserial   (or use a venv)")

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
POLL = bytes([0xEB,0x0A,0x00,0x01,0x00,0x0B,0x00,0x01,0x17,0x00,0x90])  # read-only cmd 0x01

try:
    s = serial.Serial(PORT, 9600, timeout=0.3)
except Exception as e:
    sys.exit(f"could not open {PORT}: {e}")

print(f"port {PORT} @ 9600 8N1.  Sending cmd-01 poll 5x, listening 2s each.\n")
any_rx = False
for i in range(5):
    s.reset_input_buffer()
    s.write(POLL); s.flush()
    t0 = time.time(); buf = bytearray()
    while time.time() - t0 < 2.0:
        b = s.read(64)
        if b: buf += b
    if buf:
        any_rx = True
        print(f"poll {i+1}: RX {len(buf)} byte(s): {buf.hex(' ')}")
    else:
        print(f"poll {i+1}: (silence)")
s.close()
print("\n== RESULT ==")
print("MCU IS REPLYING  -> MCU + pin-6 TX are healthy; the fault is the ESP's RX wire/joint." if any_rx
      else "MCU SILENT       -> no reply even to a known-good serial master; fault is MCU-TX (pin6/PA14) or firmware.")
