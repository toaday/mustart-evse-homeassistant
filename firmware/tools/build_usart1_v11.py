#!/usr/bin/env python3
"""v11 = v3 + USART1 telemetry mirror, NO high RAM, SWD kept alive.

Root cause of v5-v10 reboots: their RX/TX buffers at 0x20001C00-0x20001F14 landed in
LIVE firmware RAM (display framebuffer / relocated stack) and corrupted it. v11 fixes this:
  * Uses NO RAM at/above 0x20001000. Reuses the firmware's OWN (now idle) USART2 TX buffer
    region at 0x20000256 for the reply frame + 3 control words.
  * No RX buffer at all: detects the incoming poll with a byte-matcher (MATCHCNT state word).
  * No DMA, no interrupt (polled, like v6) -> cannot storm/freeze.
  * Restores PA14 = SWCLK so the SWD debug port stays alive while running.
  * No USART2 debug trace (PA14/USART2-TX is now SWCLK).
Build on mustart_patched_v3.bin -> mustart_patched_v11.bin."""
import struct, hashlib
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB); cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB)

FL=0x08000000; BASE=0x0800A000
U1=0x40013800; U2=0x40004400; APB2=0x40021018
MODER=0x48000000; PUPDR=0x4800000C; AFRH=0x48000024
C74=0x08000C74; CKS=0x0800249C; EE8=0x08001EE8
HOOK_LOOP=0x080058F4
# --- RAM: reuse idle USART2 TX buffer region (firmware's own), NO high RAM ---
REPLY   =0x20000256   # reply frame built here (<=57 B after escaping). halfword-aligned (0x...56)
MATCHCNT=0x20000290   # poll-match position (persists across calls)
TXLEN   =0x20000294   # reply length for FUN_0800249C
ANSWERS =0x20000298   # count of polls answered (readable via SWD)
POLL=[0xEB,0x0A,0x00,0x01,0x00,0x0B,0x00,0x01,0x17,0x00,0x90]  # 11-byte poll to match

def asm1(t,a):
    enc,c=ks.asm(t,a)
    if enc is None or c!=1: raise SystemExit(f"asm fail {t!r}@{a:#x}")
    return bytes(enc)
def build(base,toks):
    def sz(t):
        k=t[0]
        if k=="L": return 0
        if k=="d": return len(t[1])
        if k in("bl","bll"): return 4
        if k in("b","c"): return 2
        return len(asm1(t[1],0))
    addr=base; labels={}; consts=[]
    for t in toks:
        if t[0]=="L": labels[t[1]]=addr
        if t[0]=="c" and t[2] not in consts: consts.append(t[2])
        addr+=sz(t)
    pool=(addr+3)&~3
    def cval(c): return labels[c] if isinstance(c,str) else c
    pa={c:pool+4*i for i,c in enumerate(consts)}; end=pool+4*len(consts)
    out=bytearray(); addr=base
    for t in toks:
        if t[0]=="L": b=b""
        elif t[0]=="d": b=bytes(t[1])
        elif t[0]=="i": b=asm1(t[1],addr)
        elif t[0]=="b":
            mn="b" if t[1]=="al" else "b"+t[1]; b=asm1(f"{mn} #{labels[t[2]]:#x}",addr)
        elif t[0]=="bll": b=asm1(f"bl #{labels[t[1]]:#x}",addr)
        elif t[0]=="bl": b=asm1(f"bl #{t[1]:#x}",addr)
        elif t[0]=="c":
            off=pa[t[2]]-((addr+4)&~3); b=asm1(f"ldr {t[1]}, [pc, #{off}]",addr)
        if t[0]=="i" and len(b)!=2:
            raise SystemExit(f"non-16-bit (Thumb-2) instr on ARMv6-M: {t[1]!r} -> {len(b)} bytes @ {addr:#x}")
        out+=b; addr+=len(b)
    while (base+len(out))&3: out+=b"\x00"
    for c in consts: out+=struct.pack("<I",cval(c))
    assert base+len(out)==end
    return bytes(out),labels

T=[
 # --- trampoline hooked from the superloop ---
 ("L","svc_tramp"),
 ("i","push {lr}"),("bl",EE8),("bll","u1_init"),("bll","u1_service"),("i","pop {pc}"),

 # --- init: idempotent (UE guard). NO DMA, NO interrupt. Restores PA14=SWCLK. ---
 ("L","u1_init"),
 ("i","push {r4, lr}"),
 ("c","r0",U1),("i","ldr r1,[r0]"),("i","movs r2,#1"),("i","tst r1,r2"),("b","ne","u1_init_done"),
 # RCC_APB2ENR |= USART1EN (bit14)
 ("c","r0",APB2),("i","ldr r1,[r0]"),("i","movs r2,#1"),("i","lsls r2,r2,#14"),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # GPIOA MODER: PA9/PA10 -> AF
 ("c","r0",MODER),("i","ldr r1,[r0]"),("c","r2",0x003C0000),("i","bics r1,r2"),("c","r2",0x00280000),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # GPIOA PUPDR: PA10 pull-up
 ("c","r0",PUPDR),("i","ldr r1,[r0]"),("c","r2",0x00300000),("i","bics r1,r2"),("c","r2",0x00100000),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # GPIOA AFRH: PA9/PA10 -> AF1
 ("c","r0",AFRH),("i","ldr r1,[r0]"),("c","r2",0x00000FF0),("i","bics r1,r2"),("c","r2",0x00000110),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # RESTORE PA14 = SWCLK: MODER PA14 -> AF (bits29:28=10)
 ("c","r0",MODER),("i","ldr r1,[r0]"),("c","r2",0x30000000),("i","bics r1,r2"),("c","r2",0x20000000),("i","orrs r1,r2"),("i","str r1,[r0]"),
 # AFRH PA14 nibble (bits27:24) -> 0 (AF0 = SWCLK)
 ("c","r0",AFRH),("i","ldr r1,[r0]"),("c","r2",0x0F000000),("i","bics r1,r2"),("i","str r1,[r0]"),
 # USART1 registers
 ("c","r0",U1),
 ("i","movs r1,#0"),("i","str r1,[r0,#0]"),          # CR1=0
 ("c","r1",0x1388),("i","str r1,[r0,#0xC]"),         # BRR=9600@48MHz
 ("i","movs r1,#0"),("i","str r1,[r0,#4]"),("i","str r1,[r0,#8]"),  # CR2=0, CR3=0
 ("i","movs r1,#0x0D"),("i","str r1,[r0,#0]"),       # CR1=UE|RE|TE (NO RXNEIE, NO DMA)
 # zero MATCHCNT, ANSWERS
 ("c","r0",MATCHCNT),("i","movs r1,#0"),("i","str r1,[r0]"),
 ("c","r0",ANSWERS),("i","str r1,[r0]"),
 ("L","u1_init_done"),
 ("i","pop {r4, pc}"),

 # --- service: poll-drain USART1 RX (bounded), byte-match the poll, answer ---
 ("L","u1_service"),
 ("i","push {r4, r5, r6, r7, lr}"),
 ("c","r6",U1),("i","movs r7,#64"),                  # max drain iterations/call
 ("L","drain"),
 ("i","ldr r0,[r6,#0x1C]"),                          # ISR
 ("i","movs r1,#0x0F"),("i","tst r0,r1"),("b","eq","drain_rx"),
 # error bits set -> clear + reset matcher
 ("i","movs r1,#0x1F"),("i","str r1,[r6,#0x20]"),    # ICR=0x1F
 ("c","r1",MATCHCNT),("i","movs r2,#0"),("i","str r2,[r1]"),
 ("b","al","drain_next"),
 ("L","drain_rx"),
 ("i","movs r1,#0x20"),("i","tst r0,r1"),("b","eq","drain_done"),  # RXNE?
 ("i","movs r3,#0x24"),("i","ldrb r4,[r6,r3]"),      # r4 = byte b (RDR; reg-offset -> 16-bit on M0)
 # --- matcher ---
 ("c","r0",MATCHCNT),("i","ldr r1,[r0]"),            # r1 = mc
 ("c","r2","poll_tbl"),("i","ldrb r3,[r2,r1]"),      # r3 = POLL[mc]
 ("i","cmp r4,r3"),("b","ne","m_mismatch"),
 # match: mc++
 ("i","adds r1,#1"),("i","cmp r1,#11"),("b","ne","m_store"),
 # full poll matched -> build reply + TX; mc=0; ANSWERS++
 ("bll","do_reply"),
 ("i","movs r1,#0"),
 ("c","r0",ANSWERS),("i","ldr r2,[r0]"),("i","adds r2,#1"),("i","str r2,[r0]"),
 ("b","al","m_store"),
 ("L","m_mismatch"),
 ("i","cmp r4,#0xEB"),("b","ne","m_zero"),           # resync on frame start
 ("i","movs r1,#1"),("b","al","m_store"),
 ("L","m_zero"),
 ("i","movs r1,#0"),
 ("L","m_store"),
 ("c","r0",MATCHCNT),("i","str r1,[r0]"),
 ("L","drain_next"),
 ("i","subs r7,#1"),("b","ne","drain"),
 ("L","drain_done"),
 ("i","pop {r4, r5, r6, r7, pc}"),

 # --- do_reply: build reply frame in REPLY, checksum via CKS, polled-TX on USART1 ---
 ("L","do_reply"),
 ("i","push {r4, r5, r6, r7, lr}"),
 ("c","r5",REPLY),
 # header EB 01 00 0A 00 21 00 01 -- halfword stores (REPLY base is halfword-aligned)
 ("c","r0",0x01EB),("i","strh r0,[r5,#0]"),
 ("c","r0",0x0A00),("i","strh r0,[r5,#2]"),
 ("c","r0",0x2100),("i","strh r0,[r5,#4]"),
 ("c","r0",0x0100),("i","strh r0,[r5,#6]"),
 # 11 u16 slots via FUN_08000C74 (indices 2,1,10,3,5,4,11 ; idx-11 into slots 6/7/8 ; 0 into 9/10)
 ("i","movs r0,#2"),("bl",C74),("i","strh r0,[r5,#8]"),
 ("i","movs r0,#1"),("bl",C74),("i","strh r0,[r5,#10]"),
 ("i","movs r0,#10"),("bl",C74),("i","strh r0,[r5,#12]"),
 ("i","movs r0,#3"),("bl",C74),("i","strh r0,[r5,#14]"),
 ("i","movs r0,#5"),("bl",C74),("i","strh r0,[r5,#16]"),
 ("i","movs r0,#4"),("bl",C74),("i","strh r0,[r5,#18]"),
 ("i","movs r0,#11"),("bl",C74),
 ("i","strh r0,[r5,#20]"),("i","strh r0,[r5,#22]"),("i","strh r0,[r5,#24]"),
 ("i","movs r0,#0"),("i","strh r0,[r5,#26]"),("i","strh r0,[r5,#28]"),
 # checksum + 0x90 + escape
 ("c","r1",TXLEN),("i","movs r0,#33"),("i","str r0,[r1]"),
 ("i","mov r0,r5"),("bl",CKS),
 # polled TX TXLEN bytes to USART1 TDR
 ("c","r6",U1),("c","r7",TXLEN),("i","ldr r7,[r7]"),("i","movs r4,#0"),
 ("L","tx_loop"),
 ("i","cmp r4,r7"),("b","ge","rpl_done"),
 ("c","r2",200000),
 ("L","tx_wait"),
 ("i","ldr r0,[r6,#0x1C]"),("i","movs r1,#0x80"),("i","tst r0,r1"),("b","ne","tx_send"),
 ("i","subs r2,#1"),("b","ne","tx_wait"),("b","al","rpl_done"),
 ("L","tx_send"),
 ("i","ldrb r0,[r5, r4]"),("i","str r0,[r6,#0x28]"),("i","adds r4,#1"),("b","al","tx_loop"),
 ("L","rpl_done"),
 ("i","pop {r4, r5, r6, r7, pc}"),

 # --- poll template (data, never executed) ---
 ("L","poll_tbl"),
 ("d",bytes(POLL)),
]

blob,LM=build(BASE,T)
assert BASE+len(blob) < 0x0800A400, f"overflow: {len(blob)}"
img=bytearray(open("mustart_patched_v3.bin","rb").read())
def put(a,d): img[a-FL:a-FL+len(d)]=d
put(BASE,blob)
orig=bytes(img[HOOK_LOOP-FL:HOOK_LOOP-FL+4])
assert orig==asm1(f"bl #{EE8:#x}",HOOK_LOOP), "hook site not the expected bl FUN_08001EE8"
put(HOOK_LOOP, asm1(f"bl #{LM['svc_tramp']:#x}",HOOK_LOOP))
# USART1 vector left at default -> page0 == v3's page0
open("mustart_patched_v11.bin","wb").write(img)

print(f"v11 code {len(blob)} B. entries: svc_tramp={LM['svc_tramp']:#x} u1_init={LM['u1_init']:#x} "
      f"u1_service={LM['u1_service']:#x} do_reply={LM['do_reply']:#x} poll_tbl={LM['poll_tbl']:#x}")
print("NO high RAM; REPLY=0x20000256, MATCHCNT/TXLEN/ANSWERS=0x290/0x294/0x298; SWCLK restored.")
v3=open("mustart_patched_v3.bin","rb").read()
print("page0 (vectors) unchanged vs v3:", img[0:0x400]==v3[0:0x400])
print("v11 SHA256:", hashlib.sha256(img).hexdigest())

if __name__=="__main__" and "--disasm" in __import__("sys").argv:
    print("=== DISASSEMBLY ===")
    for i in cs.disasm(blob, BASE):
        lab=[n for n,a in LM.items() if a==i.address]
        pre=f"{lab[0]}:" if lab else ""
        print(f"{i.address:#010x} {pre:14s} {i.mnemonic} {i.op_str}")
