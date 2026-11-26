#!/usr/bin/env python3
"""v5 = v3 (crash-protection + 12A) + USART1 mirror WITH internal pull-up on PA10 + debug trace.
Fixes the v4 bootloop (floating USART1 RX -> framing-error IRQ storm -> watchdog).
Debug: emits 'U' on USART2 TX (pin 6) once after init, 'A' each time it answers a cmd-01 poll.
Build on mustart_patched_v3.bin -> mustart_patched_v5.bin."""
import struct
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB); cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
FL=0x08000000
BASE=0x0800A000
U1=0x40013800; U2=0x40004400; APB2=0x40021018; GPIOA=0x48000000; AFRH=0x48000024
MODER=0x48000000; PUPDR=0x4800000C; ISER=0xE000E100
C74=0x08000C74; CKS=0x0800249C; EE8=0x08001EE8
RXBUF=0x20001E00; RXIDX=0x20001E40; FRDY=0x20001E44; TXBUF=0x20001E48; TXLEN=0x20001E94
HOOK_LOOP=0x080058F4; VEC_U1=0x080000AC

def asm1(t,a):
    enc,c=ks.asm(t,a)
    if enc is None or c!=1: raise SystemExit(f"asm fail {t!r}@{a:#x}")
    return bytes(enc)
def build(base,toks):
    def sz(t):
        k=t[0]
        return 0 if k=="L" else (4 if k in("bl","bll") else (2 if k in("b","c") else len(asm1(t[1],0))))
    addr=base; labels={}; consts=[]
    for t in toks:
        if t[0]=="L": labels[t[1]]=addr
        if t[0]=="c" and t[2] not in consts: consts.append(t[2])
        addr+=sz(t)
    pool=(addr+3)&~3; pa={c:pool+4*i for i,c in enumerate(consts)}; end=pool+4*len(consts)
    out=bytearray(); addr=base
    for t in toks:
        if t[0]=="L": b=b""
        elif t[0]=="i": b=asm1(t[1],addr)
        elif t[0]=="b":
            mn="b" if t[1]=="al" else "b"+t[1]; b=asm1(f"{mn} #{labels[t[2]]:#x}",addr)
        elif t[0]=="bll": b=asm1(f"bl #{labels[t[1]]:#x}",addr)
        elif t[0]=="bl": b=asm1(f"bl #{t[1]:#x}",addr)
        elif t[0]=="c":
            off=pa[t[2]]-((addr+4)&~3); b=asm1(f"ldr {t[1]}, [pc, #{off}]",addr)
        out+=b; addr+=len(b)
    while (base+len(out))&3: out+=b"\x00"
    for c in consts: out+=struct.pack("<I",c)
    assert base+len(out)==end
    return bytes(out),labels

T=[
 ("L","svc_tramp"),
 ("i","push {lr}"),("bl",EE8),("bll","u1_init"),("bll","u1_service"),("i","pop {pc}"),

 ("L","u1_init"),
 ("i","push {r4, lr}"),
 ("c","r0",U1),("i","ldr r1,[r0]"),("i","movs r2,#1"),("i","tst r1,r2"),("b","ne","u1_init_done"),
 ("c","r0",APB2),("i","ldr r1,[r0]"),("i","movs r2,#1"),("i","lsls r2,r2,#14"),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # MODER: PA9/PA10 -> AF(10)
 ("c","r0",MODER),("i","ldr r1,[r0]"),("c","r2",0x003C0000),("i","bics r1,r2"),("c","r2",0x00280000),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # *** FIX *** PUPDR: PA10 -> pull-up (01), so RX idles high when ESP not driving
 ("c","r0",PUPDR),("i","ldr r1,[r0]"),("c","r2",0x00300000),("i","bics r1,r2"),("c","r2",0x00100000),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # AFRH: PA9/PA10 -> AF1
 ("c","r0",AFRH),("i","ldr r1,[r0]"),("c","r2",0x00000FF0),("i","bics r1,r2"),("c","r2",0x00000110),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # USART1 config
 ("c","r0",U1),
 ("i","movs r1,#0"),("i","str r1,[r0,#0]"),
 ("c","r1",0x1388),("i","str r1,[r0,#0xC]"),
 ("i","movs r1,#0"),("i","str r1,[r0,#4]"),("i","str r1,[r0,#8]"),
 ("c","r2",RXIDX),("i","movs r1,#0"),("i","str r1,[r2]"),
 ("c","r2",FRDY),("i","str r1,[r2]"),
 ("i","movs r1,#0x2D"),("i","str r1,[r0,#0]"),
 ("c","r0",ISER),("i","movs r1,#1"),("i","lsls r1,r1,#27"),("i","str r1,[r0]"),
 ("i","movs r0,#0x55"),("bll","dbg"),      # 'U' = USART1 up
 ("L","u1_init_done"),
 ("i","pop {r4, pc}"),

 ("L","u1_isr"),
 ("i","push {r4, r5, lr}"),
 ("c","r3",U1),("i","ldr r0,[r3,#0x1C]"),
 ("i","movs r1,#0x0F"),("i","tst r0,r1"),("b","eq","isr_rx"),
 ("i","movs r1,#0x1F"),("i","str r1,[r3,#0x20]"),
 ("c","r1",RXIDX),("i","movs r2,#0"),("i","str r2,[r1]"),("b","al","isr_done"),
 ("L","isr_rx"),
 ("i","movs r1,#0x20"),("i","tst r0,r1"),("b","eq","isr_done"),
 ("i","ldrb r4,[r3,#0x24]"),
 ("c","r1",RXIDX),("i","ldr r2,[r1]"),
 ("i","cmp r4,#0xEB"),("b","ne","isr_nostart"),("i","movs r2,#0"),
 ("L","isr_nostart"),
 ("c","r5",RXBUF),("i","strb r4,[r5, r2]"),("i","adds r2,#1"),
 ("i","cmp r2,#63"),("b","ls","isr_noovf"),("i","movs r2,#0"),
 ("L","isr_noovf"),
 ("i","str r2,[r1]"),
 ("i","cmp r4,#0x90"),("b","ne","isr_done"),
 ("c","r1",FRDY),("i","movs r2,#1"),("i","str r2,[r1]"),
 ("L","isr_done"),
 ("i","pop {r4, r5, pc}"),

 ("L","u1_service"),
 ("i","push {r4, r5, r6, r7, lr}"),
 ("c","r1",FRDY),("i","ldr r0,[r1]"),("i","cmp r0,#0"),("b","eq","svc_done"),
 ("i","movs r0,#0"),("i","str r0,[r1]"),
 ("c","r4",RXBUF),
 ("i","ldrb r0,[r4,#0]"),("i","cmp r0,#0xEB"),("b","ne","svc_done"),
 ("i","ldrb r0,[r4,#7]"),("i","cmp r0,#1"),("b","ne","svc_done"),
 ("c","r5",TXBUF),
 ("c","r0",0x0A0001EB),("i","str r0,[r5,#0]"),
 ("c","r0",0x01002100),("i","str r0,[r5,#4]"),
 ("i","movs r0,#2"),("bl",C74),("i","strh r0,[r5,#8]"),
 ("i","movs r0,#1"),("bl",C74),("i","strh r0,[r5,#10]"),
 ("i","movs r0,#10"),("bl",C74),("i","strh r0,[r5,#12]"),
 ("i","movs r0,#3"),("bl",C74),("i","strh r0,[r5,#14]"),
 ("i","movs r0,#5"),("bl",C74),("i","strh r0,[r5,#16]"),
 ("i","movs r0,#4"),("bl",C74),("i","strh r0,[r5,#18]"),
 ("i","movs r0,#11"),("bl",C74),
 ("i","strh r0,[r5,#20]"),("i","strh r0,[r5,#22]"),("i","strh r0,[r5,#24]"),
 ("i","movs r0,#0"),("i","strh r0,[r5,#26]"),("i","strh r0,[r5,#28]"),
 ("c","r1",TXLEN),("i","movs r0,#33"),("i","str r0,[r1]"),
 ("i","mov r0,r5"),("bl",CKS),
 ("i","movs r0,#0x41"),("bll","dbg"),      # 'A' = answered a poll
 ("c","r6",U1),("c","r7",TXLEN),("i","ldr r7,[r7]"),("i","movs r4,#0"),
 ("L","tx_loop"),
 ("i","cmp r4,r7"),("b","ge","svc_done"),
 ("c","r2",200000),
 ("L","tx_wait"),
 ("i","ldr r0,[r6,#0x1C]"),("i","movs r1,#0x80"),("i","tst r0,r1"),("b","ne","tx_send"),
 ("i","subs r2,#1"),("b","ne","tx_wait"),("b","al","svc_done"),
 ("L","tx_send"),
 ("i","ldrb r0,[r5, r4]"),("i","str r0,[r6,#0x28]"),("i","adds r4,#1"),("b","al","tx_loop"),
 ("L","svc_done"),
 ("i","pop {r4, r5, r6, r7, pc}"),

 # debug byte on USART2 TX (polled, with timeout). r0=byte. clobbers r1,r2,r3.
 ("L","dbg"),
 ("i","push {lr}"),
 ("c","r3",U2),("c","r1",50000),
 ("L","dbg_wait"),
 ("i","ldr r2,[r3,#0x1C]"),("i","lsls r2,r2,#24"),("b","mi","dbg_send"),
 ("i","subs r1,#1"),("b","ne","dbg_wait"),("b","al","dbg_done"),
 ("L","dbg_send"),
 ("i","str r0,[r3,#0x28]"),
 ("L","dbg_done"),
 ("i","pop {pc}"),
]
blob,LM=build(BASE,T)
assert BASE+len(blob) < 0x0800A400, f"overflow: {len(blob)} bytes"
img=bytearray(open("mustart_patched_v3.bin","rb").read())
def put(a,d): img[a-FL:a-FL+len(d)]=d
put(BASE,blob)
orig=bytes(img[HOOK_LOOP-FL:HOOK_LOOP-FL+4])
assert orig==asm1(f"bl #{EE8:#x}",HOOK_LOOP)
put(HOOK_LOOP, asm1(f"bl #{LM['svc_tramp']:#x}",HOOK_LOOP))
put(VEC_U1, struct.pack("<I", LM['u1_isr']|1))
open("mustart_patched_v5.bin","wb").write(img)
print(f"code {len(blob)} B @0x{BASE:08x}; entries: init={LM['u1_init']:#x} isr={LM['u1_isr']:#x} svc={LM['u1_service']:#x} dbg={LM['dbg']:#x}")
print("PUPDR fix present + debug 'U'/'A' on USART2 TX.")
import hashlib; print("v5 SHA256:", hashlib.sha256(img).hexdigest())
