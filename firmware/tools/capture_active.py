#!/usr/bin/env python3
"""Active poll + capture on the FT232 (ESP disconnected). Sends the read-only cmd-01
poll ~1/s and prints a line whenever the 33-byte reply CHANGES, flagging which slot moved.
Wire: FT232 TX -> pin 7, RX -> pin 6, GND -> pin 5.
Usage: python3 tools/capture_active.py [/dev/ttyUSB0] [seconds]
"""
import sys, time
import serial
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
POLL = bytes([0xEB,0x0A,0x00,0x01,0x00,0x0B,0x00,0x01,0x17,0x00,0x90])
def unescape(raw):
    out=bytearray(); i=0
    while i<len(raw):
        b=raw[i]
        if b==0x27 and i+1<len(raw):
            n=raw[i+1]; out.append(0xEB if n==0x15 else 0x90 if n==0x70 else 0x27 if n==0xD9 else n); i+=2
        else: out.append(b); i+=1
    return bytes(out)
def slots(f): return [f[8+2*k]|(f[9+2*k]<<8) for k in range(11)]
s=serial.Serial(PORT,9600,timeout=0.25)
print(f"polling {PORT} for {SECS:.0f}s. Change settings anytime; lines print on change.",flush=True)
print("time      [0]pilot [1]temp  [2]   [3]  [4]volt [5]amp  [6]   [7]   [8]   [9]  [10]",flush=True)
t0=time.time(); last=None; n=0
while time.time()-t0<SECS:
    s.reset_input_buffer(); s.write(POLL); s.flush()
    time.sleep(0.6); raw=s.read(128)
    if not raw: continue
    # pull a frame
    buf=bytearray(raw)
    if 0xEB in buf and 0x90 in buf[buf.index(0xEB)+1:]:
        i=buf.index(0xEB); j=buf.index(0x90,i+1); f=unescape(bytes(buf[i:j+1]))
        if len(f)==33 and f[7]==0x01:
            n+=1; sl=slots(f)
            if sl!=last:
                mk=['*' if (last and sl[k]!=last[k]) else ' ' for k in range(11)]
                print(time.strftime('%H:%M:%S')+" "+" ".join(f"{v:5d}{m}" for v,m in zip(sl,mk)),flush=True)
                print("          raw: "+f.hex(' '),flush=True)
                last=sl
    time.sleep(0.4)
s.close()
print(f"{n} replies seen.",flush=True)
