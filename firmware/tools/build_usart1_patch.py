#!/usr/bin/env python3
"""Build the USART1 telemetry-mirror patch on top of mustart_patched_v3.bin (v2+amps) -> v4.
Adds: USART1 init (PA9/PA10 AF1, 9600, RXNEIE), USART1 ISR (frame capture), superloop service
(validate cmd-01, build 33B reply via reused FUN_08000C74 + FUN_0800249C, polled TX w/ timeout).
Additive only: USART2/charge/calibration untouched. Code @0x0800A000, buffers @0x20001E00.
"""
import struct, sys
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB); cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
FL=0x08000000
# ---- addresses ----
BASE=0x0800A000
U1=0x40013800; APB2=0x40021018; GPIOA=0x48000000; AFRH=0x48000024; ISER=0xE000E100
C74=0x08000C74; CKS=0x0800249C; EE8=0x08001EE8
RXBUF=0x20001E00; RXIDX=0x20001E40; FRDY=0x20001E44; TXBUF=0x20001E48; TXLEN=0x20001E94
HOOK_LOOP=0x080058F4      # bl FUN_08001ee8  -> bl svc_tramp
VEC_U1=0x080000AC         # USART1 IRQ vector -> usart1_isr|1

def asm1(t,a):
    enc,c=ks.asm(t,a)
    if enc is None or c!=1: raise SystemExit(f"asm fail {t!r} @{a:#x}: {enc} {c}")
    return bytes(enc)

# two-pass assembler. tokens:
#  ("L",name) label ; ("i","text") plain ; ("b",cond,label) ; ("bl",absaddr) ; ("bll",label) ; ("c",reg,const)
def build(base, toks):
    # pass1: sizes/addresses/labels/consts
    def sz(t):
        k=t[0]
        if k=="L": return 0
        if k in("b","c"): return 2
        if k in("bl","bll"): return 4
        if k=="i": return len(asm1(t[1],0))
    addr=base; labels={}; consts=[]
    for t in toks:
        if t[0]=="L": labels[t[1]]=addr
        if t[0]=="c" and t[2] not in consts: consts.append(t[2])
        addr+=sz(t)
    pool=(addr+3)&~3
    pa={c:pool+4*i for i,c in enumerate(consts)}
    end=pool+4*len(consts)
    # pass2
    out=bytearray(); addr=base
    for t in toks:
        if t[0]=="L": b=b""
        elif t[0]=="i": b=asm1(t[1],addr)
        elif t[0]=="b":
            mn="b" if t[1]=="al" else "b"+t[1]
            b=asm1(f"{mn} #{labels[t[2]]:#x}",addr)
        elif t[0]=="bll": b=asm1(f"bl #{labels[t[1]]:#x}",addr)
        elif t[0]=="bl": b=asm1(f"bl #{t[1]:#x}",addr)
        elif t[0]=="c":
            off=pa[t[2]]-((addr+4)&~3)
            b=asm1(f"ldr {t[1]}, [pc, #{off}]",addr)
        out+=b; addr+=len(b)
    while (base+len(out))&3: out+=b"\x00"
    for c in consts: out+=struct.pack("<I",c)
    assert base+len(out)==end
    return bytes(out)

T=[
 # ---------------- svc_tramp (hook target of 0x080058F4) ----------------
 ("L","svc_tramp"),
 ("i","push {lr}"),
 ("bl",EE8),              # original USART2 responder (unchanged behavior)
 ("bll","u1_init"),       # idempotent init (UE-guarded) -> runs once
 ("bll","u1_service"),    # poll frame-ready, reply on USART1
 ("i","pop {pc}"),

 # ---------------- u1_init : configure USART1 once (guard on CR1.UE) ----
 ("L","u1_init"),
 ("i","push {r4, lr}"),
 ("c","r0",U1),
 ("i","ldr r1,[r0]"),             # CR1
 ("i","movs r2,#1"),
 ("i","tst r1,r2"),               # UE already set?
 ("b","ne","u1_init_done"),
 # RCC_APB2ENR |= 1<<14 (USART1EN)
 ("c","r0",APB2), ("i","ldr r1,[r0]"), ("i","movs r2,#1"), ("i","lsls r2,r2,#14"),
 ("i","orrs r1,r2"), ("i","str r1,[r0]"),
 # GPIOA MODER: PA9/PA10 -> AF(10)
 ("c","r0",GPIOA), ("i","ldr r1,[r0]"), ("c","r2",0x003C0000), ("i","bics r1,r2"),
 ("c","r2",0x00280000), ("i","orrs r1,r2"), ("i","str r1,[r0]"),
 # GPIOA AFRH: PA9=AF1, PA10=AF1
 ("c","r0",AFRH), ("i","ldr r1,[r0]"), ("c","r2",0x00000FF0), ("i","bics r1,r2"),
 ("c","r2",0x00000110), ("i","orrs r1,r2"), ("i","str r1,[r0]"),
 # USART1 config
 ("c","r0",U1),
 ("i","movs r1,#0"), ("i","str r1,[r0,#0]"),          # CR1=0 (UE off)
 ("c","r1",0x1388), ("i","str r1,[r0,#0xC]"),         # BRR=5000 (9600@48MHz)
 ("i","movs r1,#0"), ("i","str r1,[r0,#4]"), ("i","str r1,[r0,#8]"),  # CR2=0,CR3=0
 # zero RX state BEFORE enabling IRQ
 ("c","r2",RXIDX), ("i","movs r1,#0"), ("i","str r1,[r2]"),
 ("c","r2",FRDY), ("i","str r1,[r2]"),
 # CR1 = UE|RE|TE|RXNEIE = 0x2D
 ("i","movs r1,#0x2D"), ("i","str r1,[r0,#0]"),
 # NVIC enable IRQ27 (USART1)
 ("c","r0",ISER), ("i","movs r1,#1"), ("i","lsls r1,r1,#27"), ("i","str r1,[r0]"),
 ("L","u1_init_done"),
 ("i","pop {r4, pc}"),

 # ---------------- u1_isr : capture bytes into RXBUF, flag on 0x90 -----
 ("L","u1_isr"),
 ("i","push {r4, r5, lr}"),
 ("c","r3",U1),
 ("i","ldr r0,[r3,#0x1C]"),       # ISR status
 ("i","movs r1,#0x0F"),           # PE|FE|NE|ORE
 ("i","tst r0,r1"),
 ("b","eq","isr_rx"),
 ("i","movs r1,#0x1F"), ("i","str r1,[r3,#0x20]"),   # ICR clear errors
 ("c","r1",RXIDX), ("i","movs r2,#0"), ("i","str r2,[r1]"),  # drop partial
 ("b","al","isr_done"),
 ("L","isr_rx"),
 ("i","movs r1,#0x20"),           # RXNE
 ("i","tst r0,r1"),
 ("b","eq","isr_done"),
 ("i","ldrb r4,[r3,#0x24]"),      # RDR -> r4 (clears RXNE)
 ("c","r1",RXIDX), ("i","ldr r2,[r1]"),
 ("i","cmp r4,#0xEB"), ("b","ne","isr_nostart"), ("i","movs r2,#0"),
 ("L","isr_nostart"),
 ("c","r5",RXBUF), ("i","strb r4,[r5, r2]"), ("i","adds r2,#1"),
 ("i","cmp r2,#63"), ("b","ls","isr_noovf"), ("i","movs r2,#0"),
 ("L","isr_noovf"),
 ("i","str r2,[r1]"),
 ("i","cmp r4,#0x90"), ("b","ne","isr_done"),
 ("c","r1",FRDY), ("i","movs r2,#1"), ("i","str r2,[r1]"),
 ("L","isr_done"),
 ("i","pop {r4, r5, pc}"),

 # ---------------- u1_service : validate + build + polled TX -----------
 ("L","u1_service"),
 ("i","push {r4, r5, r6, r7, lr}"),
 ("c","r1",FRDY), ("i","ldr r0,[r1]"), ("i","cmp r0,#0"), ("b","eq","svc_done"),
 ("i","movs r0,#0"), ("i","str r0,[r1]"),       # clear flag
 ("c","r4",RXBUF),
 ("i","ldrb r0,[r4,#0]"), ("i","cmp r0,#0xEB"), ("b","ne","svc_done"),
 ("i","ldrb r0,[r4,#7]"), ("i","cmp r0,#1"), ("b","ne","svc_done"),
 # header: TXBUF[0..3]=EB 01 00 0A , [4..7]=00 21 00 01
 ("c","r5",TXBUF),
 ("c","r0",0x0A0001EB), ("i","str r0,[r5,#0]"),
 ("c","r0",0x01002100), ("i","str r0,[r5,#4]"),
 # payload slots via FUN_08000C74
 ("i","movs r0,#2"),  ("bl",C74), ("i","strh r0,[r5,#8]"),
 ("i","movs r0,#1"),  ("bl",C74), ("i","strh r0,[r5,#10]"),
 ("i","movs r0,#10"), ("bl",C74), ("i","strh r0,[r5,#12]"),
 ("i","movs r0,#3"),  ("bl",C74), ("i","strh r0,[r5,#14]"),
 ("i","movs r0,#5"),  ("bl",C74), ("i","strh r0,[r5,#16]"),
 ("i","movs r0,#4"),  ("bl",C74), ("i","strh r0,[r5,#18]"),
 ("i","movs r0,#11"), ("bl",C74),
 ("i","strh r0,[r5,#20]"), ("i","strh r0,[r5,#22]"), ("i","strh r0,[r5,#24]"),
 ("i","movs r0,#0"), ("i","strh r0,[r5,#26]"), ("i","strh r0,[r5,#28]"),
 # checksum + 0x90 + escape: FUN_0800249C(TXBUF,&TXLEN), TXLEN=33
 ("c","r1",TXLEN), ("i","movs r0,#33"), ("i","str r0,[r1]"),
 ("i","mov r0,r5"),        # r0=TXBUF ; r1=&TXLEN
 ("bl",CKS),
 # polled TX
 ("c","r6",U1), ("c","r7",TXLEN), ("i","ldr r7,[r7]"), ("i","movs r4,#0"),
 ("L","tx_loop"),
 ("i","cmp r4,r7"), ("b","ge","svc_done"),
 ("c","r2",200000),                       # per-byte timeout spins
 ("L","tx_wait"),
 ("i","ldr r0,[r6,#0x1C]"), ("i","movs r1,#0x80"), ("i","tst r0,r1"),
 ("b","ne","tx_send"),
 ("i","subs r2,#1"), ("b","ne","tx_wait"),
 ("b","al","svc_done"),                   # timeout: abort TX
 ("L","tx_send"),
 ("i","ldrb r0,[r5, r4]"), ("i","str r0,[r6,#0x28]"), ("i","adds r4,#1"),
 ("b","al","tx_loop"),
 ("L","svc_done"),
 ("i","pop {r4, r5, r6, r7, pc}"),
]

blob=build(BASE,T)
assert BASE+len(blob) < 0x0800A400, "code overflows the 1KB page!"
# resolve label addrs for hooks (re-run pass1 quickly)
# (rebuild label map)
def labelmap(base,toks):
    def sz(t):
        k=t[0]
        return 0 if k=="L" else (4 if k in("bl","bll") else (2 if k in("b","c") else len(asm1(t[1],0))))
    a=base; m={}
    for t in toks:
        if t[0]=="L": m[t[1]]=a
        a+=sz(t)
    return m
LM=labelmap(BASE,T)

img=bytearray(open("mustart_patched_v3.bin","rb").read())
def put(a,d): img[a-FL:a-FL+len(d)]=d
put(BASE,blob)
# hook superloop: 0x080058F4 bl FUN_08001ee8 -> bl svc_tramp
orig=bytes(img[HOOK_LOOP-FL:HOOK_LOOP-FL+4])
assert orig==asm1(f"bl #{EE8:#x}",HOOK_LOOP), f"loop hook orig unexpected: {orig.hex()}"
put(HOOK_LOOP, asm1(f"bl #{LM['svc_tramp']:#x}",HOOK_LOOP))
# hook USART1 vector 0x080000AC -> u1_isr|1
put(VEC_U1, struct.pack("<I", LM['u1_isr']|1))
open("mustart_patched_v4.bin","wb").write(img)

print("labels:", {k:hex(v) for k,v in LM.items()})
print(f"\ncode 0x{BASE:08x}..0x{BASE+len(blob):08x} ({len(blob)} B)")
print("\n--- disassembly ---")
for i in cs.disasm(blob,BASE):
    print(f" 0x{i.address:08x}: {i.mnemonic:7s} {i.op_str}")
print("\nHOOKS:")
print(f"  superloop 0x{HOOK_LOOP:08x}: {orig.hex(' ')} -> {img[HOOK_LOOP-FL:HOOK_LOOP-FL+4].hex(' ')} (bl svc_tramp {LM['svc_tramp']:#x})")
print(f"  USART1 vec 0x{VEC_U1:08x} -> {struct.unpack('<I',img[VEC_U1-FL:VEC_U1-FL+4])[0]:#010x} (u1_isr|1)")
import hashlib; print("\nv4 SHA256:", hashlib.sha256(img).hexdigest())
