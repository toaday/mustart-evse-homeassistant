#!/usr/bin/env python3
"""v7 = v6 but USART1 RX is via DMA1 Channel 3 (circular) instead of polling the RDR.
Still NO interrupt / NO ISR / NO USART1 vector hook -> page0 stays == v3's page0, and the
DMA cannot storm/freeze the CPU (service drains the circular buffer each tick, bounded).
Everything else identical to v6: PA10 pull-up, debug trace ('U' once at init, 'A' per answered
poll on USART2 TX), polled TX of the reply, byte-identical reply build (header + 11 slots via
FUN_08000C74 + FUN_0800249C checksum/escape), superloop hook 0x080058F4 -> svc_tramp.
Build on mustart_patched_v3.bin -> mustart_patched_v8.bin."""
import struct
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB); cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
FL=0x08000000; BASE=0x0800A000
U1=0x40013800; U2=0x40004400; APB2=0x40021018; AHBENR=0x40021014
GPIOA=0x48000000; AFRH=0x48000024; MODER=0x48000000; PUPDR=0x4800000C
# DMA1 Channel 3 (hardwired USART1_RX, no remap)
CCR3=0x40020030; CNDTR3=0x40020034; CPAR3=0x40020038; CMAR3=0x4002003C
RDR=0x40013824
C74=0x08000C74; CKS=0x0800249C; EE8=0x08001EE8
# RAM map (unused block 0x20001260..0x20001EFF; stack grows DOWN from 0x20001260)
DMABUF=0x20001C00; FRAMEBUF=0x20001C80; RD_IDX=0x20001CC0; FRAME_IDX=0x20001CC4
FRDY=0x20001CC8; TXBUF=0x20001CCC; TXLEN=0x20001D14
HOOK_LOOP=0x080058F4
def asm1(t,a):
    enc,c=ks.asm(t,a)
    if enc is None or c!=1: raise SystemExit(f"asm fail {t!r}@{a:#x}")
    return bytes(enc)
def build(base,toks):
    def sz(t):
        k=t[0]; return 0 if k=="L" else (4 if k in("bl","bll") else (2 if k in("b","c") else len(asm1(t[1],0))))
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

 # --- init: NO interrupt. CR1=UE|RE|TE (0x0D). DMA1 CH3 circular RX. Keep pull-up. ---
 ("L","u1_init"),
 ("i","push {r4, lr}"),
 ("c","r0",U1),("i","ldr r1,[r0]"),("i","movs r2,#1"),("i","tst r1,r2"),("b","ne","u1_init_done"),
 ("i","movs r0,#0x31"),("bll","dbg"),   # marker '1': init body reached
 # USART1 clock
 ("c","r0",APB2),("i","ldr r1,[r0]"),("i","movs r2,#1"),("i","lsls r2,r2,#14"),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # DMA1 clock: RCC_AHBENR |= bit0
 ("c","r0",AHBENR),("i","ldr r1,[r0]"),("i","movs r2,#1"),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # GPIO PA9/PA10 -> AF, PA10 pull-up
 ("c","r0",MODER),("i","ldr r1,[r0]"),("c","r2",0x003C0000),("i","bics r1,r2"),("c","r2",0x00280000),("i","orrs r1,r2"),("i","str r1,[r0]"),
 ("c","r0",PUPDR),("i","ldr r1,[r0]"),("c","r2",0x00300000),("i","bics r1,r2"),("c","r2",0x00100000),("i","orrs r1,r2"),("i","str r1,[r0]"),
 ("c","r0",AFRH),("i","ldr r1,[r0]"),("c","r2",0x00000FF0),("i","bics r1,r2"),("c","r2",0x00000110),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # USART1 config
 ("c","r0",U1),
 ("i","movs r1,#0"),("i","str r1,[r0,#0]"),          # CR1=0 (disable while configuring)
 ("c","r1",0x1388),("i","str r1,[r0,#0xC]"),         # BRR 9600@48MHz
 ("i","movs r1,#0"),("i","str r1,[r0,#4]"),          # CR2=0
 ("c","r1",0x1040),("i","str r1,[r0,#8]"),            # CR3 = DMAR | OVRDIS (bit6|bit12): no overrun stall
 # DMA1 CH3 setup
 ("c","r0",CCR3),("i","movs r1,#0"),("i","str r1,[r0]"),           # CCR3=0 (disable to configure)
 ("c","r0",CPAR3),("c","r1",RDR),("i","str r1,[r0]"),             # CPAR3 = USART1_RDR
 ("c","r0",CMAR3),("c","r1",DMABUF),("i","str r1,[r0]"),          # CMAR3 = DMABUF
 ("c","r0",CNDTR3),("i","movs r1,#128"),("i","str r1,[r0]"),      # CNDTR3 = 128
 ("c","r0",CCR3),("i","movs r1,#0xA1"),("i","str r1,[r0]"),       # EN|CIRC|MINC, 8-bit, P->M, no IRQ
 # zero RAM state
 ("c","r2",RD_IDX),("i","movs r1,#0"),("i","str r1,[r2]"),
 ("c","r2",FRAME_IDX),("i","str r1,[r2]"),
 ("c","r2",FRDY),("i","str r1,[r2]"),
 # enable USART1 UE|RE|TE (no RXNEIE)
 ("i","movs r0,#0x32"),("bll","dbg"),   # marker '2': GPIO+USART1+DMA config done
 ("c","r0",U1),("i","movs r1,#0x0D"),("i","str r1,[r0,#0]"),
 ("i","movs r0,#0x55"),("bll","dbg"),                # 'U'
 ("L","u1_init_done"),
 ("i","pop {r4, pc}"),

 # --- service: process DMA circular RX buffer, then answer ---
 ("L","u1_service"),
 ("i","push {r4, r5, r6, r7, lr}"),
 ("c","r6",DMABUF),                                  # r6 = DMA buffer base
 ("c","r0",RD_IDX),("i","ldr r4,[r0]"),              # r4 = read_idx
 ("c","r0",CNDTR3),("i","ldr r0,[r0]"),              # r0 = CNDTR3
 ("i","movs r7,#128"),("i","subs r7,r0"),            # r7 = 128 - CNDTR3
 ("i","movs r0,#0x7F"),("i","ands r7,r0"),           # r7 = write_pos (0..127)
 ("i","movs r5,#128"),                               # safety cap (<=128 iters)
 ("L","dma_loop"),
 ("i","cmp r4,r7"),("b","eq","dma_done"),            # while read_idx != write_pos
 ("i","ldrb r0,[r6, r4]"),                           # r0 = DMABUF[read_idx]
 ("i","adds r4,#1"),("i","movs r1,#0x7F"),("i","ands r4,r1"),   # read_idx=(read_idx+1)&127
 ("c","r2",FRAME_IDX),("i","ldr r3,[r2]"),           # r3 = frame_idx
 ("i","cmp r0,#0xEB"),("b","ne","fa_nostart"),("i","movs r3,#0"),
 ("L","fa_nostart"),
 ("c","r1",FRAMEBUF),("i","strb r0,[r1, r3]"),       # FRAMEBUF[frame_idx]=byte
 ("i","adds r3,#1"),
 ("i","cmp r3,#63"),("b","lo","fa_noovf"),("i","movs r3,#0"),   # if frame_idx>=63 -> 0
 ("L","fa_noovf"),
 ("i","str r3,[r2]"),                                # save frame_idx
 ("i","cmp r0,#0x90"),("b","ne","dma_next"),
 ("c","r1",FRDY),("i","movs r2,#1"),("i","str r2,[r1]"),
 ("L","dma_next"),
 ("i","subs r5,#1"),("b","ne","dma_loop"),
 ("L","dma_done"),
 ("c","r0",RD_IDX),("i","str r4,[r0]"),              # save read_idx
 # process frame if ready
 ("c","r1",FRDY),("i","ldr r0,[r1]"),("i","cmp r0,#0"),("b","eq","svc_done"),
 ("i","movs r0,#0"),("i","str r0,[r1]"),
 ("c","r4",FRAMEBUF),
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
 ("i","movs r0,#0x41"),("bll","dbg"),                # 'A'
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

 ("L","dbg"),
 ("i","push {lr}"),("c","r3",U2),("c","r1",50000),
 ("L","dbg_wait"),
 ("i","ldr r2,[r3,#0x1C]"),("i","lsls r2,r2,#24"),("b","mi","dbg_send"),
 ("i","subs r1,#1"),("b","ne","dbg_wait"),("b","al","dbg_done"),
 ("L","dbg_send"),("i","str r0,[r3,#0x28]"),
 ("L","dbg_done"),("i","pop {pc}"),
]
blob,LM=build(BASE,T)
assert BASE+len(blob) < 0x0800A400, f"overflow: {len(blob)}"
img=bytearray(open("mustart_patched_v3.bin","rb").read())
def put(a,d): img[a-FL:a-FL+len(d)]=d
put(BASE,blob)
orig=bytes(img[HOOK_LOOP-FL:HOOK_LOOP-FL+4])
assert orig==asm1(f"bl #{EE8:#x}",HOOK_LOOP)
put(HOOK_LOOP, asm1(f"bl #{LM['svc_tramp']:#x}",HOOK_LOOP))
# NOTE: USART1 vector 0x080000AC left at default (no ISR) -> page0 == v3's page0 (no change)
open("mustart_patched_v8.bin","wb").write(img)
print(f"v7 code {len(blob)} B. entries: init={LM['u1_init']:#x} svc={LM['u1_service']:#x} dbg={LM['dbg']:#x}")
print("DMA RX (DMA1 CH3 circular). No interrupt/ISR/vector. CR1=0x0D CR3=0x1040 +markers 1/2. pull-up kept. U/A kept.")
v3=open("mustart_patched_v3.bin","rb").read()
print("page0 (vectors) unchanged vs v3:", img[0:0x400]==v3[0:0x400])
import hashlib; print("v8 SHA256:", hashlib.sha256(img).hexdigest())
# full disassembly of the blob
print("=== disassembly @0x0800A000 ===")
inv={v:k for k,v in LM.items()}
a=BASE
for ins in cs.disasm(blob, BASE):
    lbl=inv.get(ins.address)
    if lbl: print(f"{lbl}:")
    print(f"  {ins.address:#08x}: {ins.mnemonic:8s} {ins.op_str}")
