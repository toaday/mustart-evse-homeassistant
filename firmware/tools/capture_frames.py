#!/usr/bin/env python3
"""LISTEN-ONLY full-frame capture on the MCU TX line (header pin 6).
Prints a line only when the reply CHANGES, and marks which u16 slots changed.
Great for correlating a setting (amps, timer) to a telemetry field.
Wire: FT232 RX -> pin 6, GND -> pin 5.  FT232 TX DISCONNECTED. (Leave the ESP connected too; both can listen.)
Usage: python3 tools/capture_frames.py [/dev/ttyUSB0] [seconds]
"""
import sys, time
try:
    import serial
except ImportError:
    sys.exit("pyserial not installed: pip install --user pyserial")
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0

def unescape(raw):
    out=bytearray(); i=0
    while i < len(raw):
        b=raw[i]
        if b==0x27 and i+1 < len(raw):
            n=raw[i+1]; out.append(0xEB if n==0x15 else 0x90 if n==0x70 else 0x27 if n==0xD9 else n); i+=2
        else:
            out.append(b); i+=1
    return bytes(out)

def slots(f):
    # 11 u16 little-endian data slots starting at f[8]
    return [f[8+2*k] | (f[9+2*k]<<8) for k in range(11)]

try:
    s = serial.Serial(PORT, 9600, timeout=0.2)
except Exception as e:
    sys.exit(f"could not open {PORT}: {e}")
print(f"capturing full frames on {PORT} for {SECS:.0f}s. Change the setting during the run.\n")
print("time     slots: [0]pilot [1]temp [2] [3] [4]volts [5]amps [6] [7] [8] [9] [10]   (changed=*)")
t0=time.time(); buf=bytearray(); last=None; nframes=0
while time.time()-t0 < SECS:
    b=s.read(64)
    if b: buf+=b
    # extract EB ... 90 frames
    while 0xEB in buf:
        i=buf.index(0xEB)
        if i>0: del buf[:i]
        if 0x90 not in buf[1:]: break
        j=buf.index(0x90,1)
        raw=bytes(buf[:j+1]); del buf[:j+1]
        f=unescape(raw)
        if len(f)!=33 or f[7]!=0x01: continue
        nframes+=1
        sl=slots(f)
        mark=['*' if (last and sl[k]!=last[k]) else ' ' for k in range(11)]
        if last is None or sl!=last:
            ts=time.strftime('%H:%M:%S')
            cells=' '.join(f"{v:5d}{m}" for v,m in zip(sl,mark))
            print(f"{ts} {cells}")
            print(f"           raw: {f.hex(' ')}")
            last=sl
s.close()
print(f"\n{nframes} frames seen. (Lines appear only when something changed.)")
