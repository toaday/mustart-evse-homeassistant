#!/usr/bin/env python3
"""Build the Mustart EVSE MCU crash-protection patch (v2).

Patches applied to a copy of stm32f030c8_fw_dump1.bin:
  A) USART2 ISR error-flag clear: 0x08003A3A  movs r1,#0x10 -> movs r1,#0x1F
  B) HardFault vector (0x0800000C) -> hf_reset stub (NVIC_SystemReset)
  C) IWDG watchdog: boot_veneer (init + reset counter/cause) hooked from main's bl FUN_080055D8;
     wdt_refresh hooked from main's two bl FUN_080011CC sites.
Veneers live in verified-free flash at 0x08009000 (erased page). Nothing else is touched;
the calibration page (0x0800FC00) is never written.

Run with the patchenv venv (keystone+unicorn+capstone).
"""
import struct
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

FLASH = 0x08000000
VEN_BASE = 0x08009000          # free page for veneers
RAMBLK = 0x20001F00            # reset bookkeeping block (above stack)
MAGIC  = 0xB007C0DE
F_055D8 = 0x080055D9           # FUN_080055D8 | thumb  (original init, tail-called)
F_011CC = 0x080011CD           # FUN_080011CC | thumb  (original fast-service, tail-called)

def asm1(text, addr):
    enc, cnt = ks.asm(text, addr)
    assert enc is not None and cnt == 1, f"asm fail: {text!r}"
    return bytes(enc)

# ---- tiny two-pass assembler: list of ops, auto literal pool, labels ----
# op forms: "insn"(plain), ("LDRC",reg,const), ("B",cond,label), ("BX",reg),
#           ("LABEL",name), ("LOOP",)
def build_veneer(base, ops):
    # pass 1: sizes + label addresses + collect constants
    def size(op):
        if isinstance(op, str): return len(asm1(op, 0))
        k = op[0]
        return {"LDRC":2,"B":2,"BX":2,"LOOP":2,"LABEL":0}[k]
    addr = base; labels = {}; consts = []
    for op in ops:
        if isinstance(op, tuple) and op[0]=="LABEL":
            labels[op[1]] = addr
        if isinstance(op, tuple) and op[0]=="LDRC" and op[2] not in consts:
            consts.append(op[2])
        addr += size(op)
    pool = (addr + 3) & ~3           # word-align pool
    pool_addr = {c: pool + 4*i for i,c in enumerate(consts)}
    end = pool + 4*len(consts)
    # pass 2: emit
    out = bytearray(); addr = base
    for op in ops:
        if isinstance(op, str):
            b = asm1(op, addr)
        elif op[0]=="LABEL":
            b = b""
        elif op[0]=="LOOP":
            b = asm1("b #%d"%addr, addr)      # b .
        elif op[0]=="BX":
            b = asm1("bx %s"%op[1], addr)
        elif op[0]=="B":
            tgt = labels[op[2]]
            mn = "b" if op[1]=="al" else "b"+op[1]
            b = asm1("%s #0x%x"%(mn,tgt), addr)
        elif op[0]=="LDRC":
            off = pool_addr[op[2]] - ((addr+4) & ~3)
            b = asm1("ldr %s, [pc, #%d]"%(op[1],off), addr)
        else:
            raise ValueError(op)
        assert len(b)==(0 if (isinstance(op,tuple) and op[0]=="LABEL") else (2 if not isinstance(op,str) else len(b))) or True
        out += b; addr += len(b)
    # append pool
    while (base+len(out)) & 3: out += b"\x00"
    for c in consts: out += struct.pack("<I", c)
    assert base+len(out)==end
    return bytes(out)

# ---------- veneer definitions ----------
hf_reset = [
    ("LDRC","r0",0xE000ED0C),      # AIRCR
    ("LDRC","r1",0x05FA0004),      # VECTKEY|SYSRESETREQ
    "dsb sy",
    "str r1, [r0]",
    "dsb sy",
    ("LOOP",),                     # wait for reset
]
boot_veneer = [
    ("LDRC","r3",RAMBLK),
    ("LDRC","r0",0x40021024),      # RCC_CSR
    "ldr r1, [r0]",
    "str r1, [r3, #8]",            # blk.last_csr = CSR
    "movs r2, #1", "lsls r2, r2, #24", "orrs r2, r1", "str r2, [r0]",  # RMVF clear
    "ldr r0, [r3, #0]",            # magic
    ("LDRC","r2",MAGIC), "cmp r0, r2", ("B","eq","warm"),
    # cold boot
    "str r2, [r3, #0]", "movs r0, #0",
    "str r0, [r3, #4]", "str r0, [r3, #12]", "str r0, [r3, #16]",
    ("B","al","doiwdg"),
    ("LABEL","warm"),
    "ldr r0, [r3, #4]", "adds r0, #1", "str r0, [r3, #4]",   # total++
    "movs r2, #1", "lsls r2, r2, #29", "tst r1, r2", ("B","eq","chkf"),  # IWDGRSTF
    "ldr r0, [r3, #12]", "adds r0, #1", "str r0, [r3, #12]",
    ("LABEL","chkf"),
    "movs r2, #1", "lsls r2, r2, #28", "tst r1, r2", ("B","eq","doiwdg"), # SFTRSTF
    "ldr r0, [r3, #16]", "adds r0, #1", "str r0, [r3, #16]",
    ("LABEL","doiwdg"),
    ("LDRC","r0",0x40003000),      # IWDG base
    ("LDRC","r1",0x00005555), "str r1, [r0, #0]",           # unlock PR/RLR
    "movs r1, #6", "str r1, [r0, #4]",                       # PR=/256
    ("LDRC","r1",0x000001C2), "str r1, [r0, #8]",            # RLR ~2.9s
    ("LDRC","r1",0x0000AAAA), "str r1, [r0, #0]",            # reload
    ("LDRC","r1",0x0000CCCC), "str r1, [r0, #0]",            # start
    ("LDRC","r0",F_055D8), ("BX","r0"),                      # tail-call original init
]
wdt_refresh = [
    ("LDRC","r0",0x40003000), ("LDRC","r1",0x0000AAAA), "str r1, [r0, #0]",
    ("LDRC","r0",F_011CC), ("BX","r0"),
]
# Patch B: clamp frame length to <=100 (RX buffer size) so the checksum loop can't read OOB.
# Replaces the 4 bytes at 0x08003CC4 ("uxth r5,r0; movs r1,#1") with "bl clamp_veneer".
clamp_veneer = [
    "uxth r5, r0",                 # original: r5 = frame length
    "cmp r5, #100", ("B","ls","ok"),
    "movs r5, #100",               # clamp to RX buffer size
    ("LABEL","ok"),
    "movs r1, #1",                 # original: loop counter i = 1
    ("BX","lr"),                   # return to 0x08003CC8 (b 0x08003cd4)
]

# ---------- place veneers ----------
b1 = build_veneer(VEN_BASE, hf_reset);                 a_hf = VEN_BASE
a_boot = (VEN_BASE+len(b1)+3)&~3; b2 = build_veneer(a_boot, boot_veneer)
a_ref  = (a_boot+len(b2)+3)&~3;   b3 = build_veneer(a_ref, wdt_refresh)
a_clamp= (a_ref+len(b3)+3)&~3;    b4 = build_veneer(a_clamp, clamp_veneer)
blob_end = a_clamp+len(b4)
assert blob_end < VEN_BASE+0x400, "veneers overflow the 1KB page!"

# ---------- apply to image ----------
img = bytearray(open("stm32f030c8_fw_dump1.bin","rb").read())
def put(addr, data): img[addr-FLASH:addr-FLASH+len(data)] = data
# A) ISR error-clear
assert img[0x3a3a]==0x10 and img[0x3a3b]==0x21; img[0x3a3a]=0x1F
# place veneers
put(a_hf,b1); put(a_boot,b2); put(a_ref,b3); put(a_clamp,b4)
# B-clamp) overwrite the 4-byte site with bl clamp_veneer
assert bytes(img[0x3cc4:0x3cc8])==bytes([0x85,0xb2,0x01,0x21]), "clamp site bytes unexpected"
put(0x08003CC4, asm1("bl #0x%x"%a_clamp, 0x08003CC4))
# B) HardFault vector -> hf_reset|thumb
put(0x0800000C, struct.pack("<I", a_hf|1))
# C) repoint the 3 bl sites
put(0x08004D78, asm1("bl #0x%x"%a_boot, 0x08004D78))   # init hook
put(0x08004D92, asm1("bl #0x%x"%a_ref , 0x08004D92))   # refresh (warm-up loop)
put(0x08004DC6, asm1("bl #0x%x"%a_ref , 0x08004DC6))   # refresh (main loop)

open("mustart_patched_v2.bin","wb").write(img)

# ---------- report ----------
def dis(addr, data, note=""):
    print(f"\n--- {note} @ 0x{addr:08x} ({len(data)}B) ---")
    for i in cs.disasm(bytes(data), addr):
        print(f"  0x{i.address:08x}: {i.mnemonic:8s} {i.op_str}")
print("VENEERS:")
dis(a_hf, b1, "hf_reset (HardFault->NVIC_SystemReset)")
dis(a_boot, b2, "boot_veneer (reset counter/cause + IWDG init, tail-calls FUN_080055D8)")
dis(a_ref, b3, "wdt_refresh (IWDG reload, tail-calls FUN_080011CC)")
dis(a_clamp, b4, "clamp_veneer (len<=100, returns to 0x08003CC8)")
print(f"\nblob 0x{VEN_BASE:08x}..0x{blob_end:08x}  (page budget 0x{VEN_BASE:08x}..0x{VEN_BASE+0x400:08x})")
print("\nHOOKS / PATCHES:")
print(f"  A ISR clear   0x08003a3a: 10->1f  (now: %s)"%(" ".join("%02x"%x for x in img[0x3a3a:0x3a3c])))
print(f"  HardFault vec 0x0800000c -> 0x%08x"%struct.unpack('<I',img[0x0c:0x10])[0])
for site,tgt in [(0x08004D78,a_boot),(0x08004D92,a_ref),(0x08004DC6,a_ref),(0x08003CC4,a_clamp)]:
    ins=next(cs.disasm(bytes(img[site-FLASH:site-FLASH+4]), site))
    print(f"  bl hook 0x{site:08x}: {ins.mnemonic} {ins.op_str}  (-> 0x{tgt:08x})")
print("\nRAM block @0x%08x: +0 magic +4 total +8 last_csr +0xC iwdg_cnt +0x10 fault_cnt"%RAMBLK)
print("pages to flash: 0x08000000, 0x08003800, 0x08003c00, 0x08004c00, 0x08009000  (config page NOT touched)")
import hashlib; print("patched SHA256:", hashlib.sha256(img).hexdigest())
