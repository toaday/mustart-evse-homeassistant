#!/usr/bin/env python3
"""Interactive, stepped frame capture (listen-only on header pin 6).
Prompts you to set each value, waits for Enter, grabs a clean reply, then
diffs the slots so the amps field and timer field reveal themselves.
Wire: FT232 RX -> pin 6, GND -> pin 5 (TX off). Leave the ESP connected (it polls).
Usage: python3 tools/capture_steps.py [/dev/ttyUSB0]
"""
import sys, time
try:
    import serial
except ImportError:
    sys.exit("pyserial not installed: pip install --user pyserial")
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

def unescape(raw):
    out=bytearray(); i=0
    while i<len(raw):
        b=raw[i]
        if b==0x27 and i+1<len(raw):
            n=raw[i+1]; out.append(0xEB if n==0x15 else 0x90 if n==0x70 else 0x27 if n==0xD9 else n); i+=2
        else: out.append(b); i+=1
    return bytes(out)
def slots(f): return [f[8+2*k]|(f[9+2*k]<<8) for k in range(11)]

s = serial.Serial(PORT, 9600, timeout=0.2)

def fresh(timeout=8.0):
    """Discard stale data, then return slots+raw of the next complete cmd-01 frame."""
    s.reset_input_buffer(); buf=bytearray(); t0=time.time()
    while time.time()-t0<timeout:
        b=s.read(64)
        if b: buf+=b
        while 0xEB in buf:
            i=buf.index(0xEB)
            if i>0: del buf[:i]
            if 0x90 not in buf[1:]: break
            j=buf.index(0x90,1); f=unescape(bytes(buf[:j+1])); del buf[:j+1]
            if len(f)==33 and f[7]==0x01: return slots(f), f
    return None, None

STEPS = [
    ("16 A, timer 0 h", "Set the charger to 16 A and timer 0 h"),
    ("12 A, timer 0 h", "Set the charger to 12 A (leave timer 0 h)"),
    ("12 A, timer 1 h", "Set timer to 1 h (leave 12 A)"),
    ("12 A, timer 5 h", "Set timer to 5 h"),
    ("12 A, timer 10 h", "Set timer to 10 h"),
    ("12 A, timer 0 h", "Set timer back to 0 h"),
]
results=[]
print("\nFollow each prompt, set the value on the unit, then press Enter.\n")
for label,instr in STEPS:
    input(f"  ➤ {instr}, then press Enter...")
    sl,f = fresh()
    if sl is None:
        print("     !! no frame captured (ESP polling? FT232 on pin 6?) — retrying once...")
        sl,f = fresh()
    if sl is None:
        print("     !! still nothing; check wiring."); continue
    results.append((label,sl,f))
    print(f"     captured: {sl}")
s.close()

print("\n================ SUMMARY ================")
hdr="slot:       "+" ".join(f"{k:>5d}" for k in range(11))
print(hdr)
for label,sl,f in results:
    print(f"{label:16s} "+" ".join(f"{v:5d}" for v in sl))
print("\n-- changes vs previous step (which slot moved) --")
for n in range(1,len(results)):
    (pl,ps,_),(cl,cs,_)=results[n-1],results[n]
    diffs=[f"slot{k}:{ps[k]}->{cs[k]}" for k in range(11) if ps[k]!=cs[k]]
    print(f"{pl}  ->  {cl}:  "+(", ".join(diffs) if diffs else "(no change)"))
print("\n-- raw frames --")
for label,sl,f in results:
    print(f"{label:16s} {f.hex(' ')}")
