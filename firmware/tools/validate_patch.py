#!/usr/bin/env python3
"""Unit-test each patch veneer in Unicorn: set inputs, run, assert exact register writes.
Validates the NEW code precisely without needing full-firmware peripheral emulation."""
from unicorn import *
from unicorn.arm_const import *
import struct, sys

FW = open("mustart_patched_v2.bin","rb").read()
FLASH=0x08000000
IWDG=0x40003000; RCC_CSR=0x40021024; AIRCR=0xE000ED0C; RAMBLK=0x20001F00
A_HF=0x08009000; A_BOOT=0x08009018            # from build report (will re-read below)

# discover veneer entry addrs from the patched hooks (robust vs layout drift)
def bl_target(site):
    import capstone
    cs=capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    ins=next(cs.disasm(FW[site-FLASH:site-FLASH+4], site)); return int(ins.op_str.lstrip('#'),16)
A_BOOT=bl_target(0x08004D78); A_REF=bl_target(0x08004D92)
A_HF=struct.unpack("<I",FW[0x0c:0x10])[0] & ~1
print(f"entries: hf=0x{A_HF:08x} boot=0x{A_BOOT:08x} refresh=0x{A_REF:08x}")

def rig():
    mu=Uc(UC_ARCH_ARM, UC_MODE_THUMB|UC_MODE_MCLASS)
    mu.mem_map(FLASH,0x10000); mu.mem_write(FLASH,FW)
    mu.mem_map(0x20000000,0x2000)
    mu.mem_map(0x40000000,0x30000)
    mu.mem_map(0xE0000000,0x100000)
    mu.reg_write(UC_ARM_REG_SP,0x20001260)
    return mu

def run(mu,start,stop_pc,maxins=4000):
    W=[]
    mu.hook_add(UC_HOOK_MEM_WRITE, lambda u,a,ad,sz,v,x: W.append((ad,v)))
    hit=[False]
    def ch(u,ad,sz,x):
        if ad==stop_pc: hit[0]=True; u.emu_stop()
    mu.hook_add(UC_HOOK_CODE, ch)
    try: mu.emu_start(start|1,0,count=maxins)
    except UcError: pass
    return W,hit[0]
def w32(W,addr): return [v for a,v in W if a==addr]

ok=True
def check(name,cond):
    global ok
    print(("  PASS " if cond else "  FAIL ")+name); ok=ok and cond

# ---- Test 1: hf_reset -> NVIC_SystemReset ----
print("\n[1] hf_reset (HardFault handler)")
mu=rig(); W,_=run(mu,A_HF,A_HF+0x0e,maxins=50)   # stop at the self-loop
aircr=w32(W,AIRCR)
check("writes AIRCR", len(aircr)>0)
check("AIRCR = 0x05FA0004 (reset request)", aircr and aircr[-1]==0x05FA0004)

# ---- Test 2a: boot_veneer COLD boot (magic absent) ----
print("\n[2a] boot_veneer COLD boot, CSR=PORRSTF")
mu=rig()
mu.mem_write(RAMBLK, struct.pack("<I",0x00000000))      # wrong magic => cold
mu.mem_write(RCC_CSR, struct.pack("<I",0x08000000))     # PORRSTF (bit27)
W,hit=run(mu,A_BOOT,0x080055D8)
check("tail-calls FUN_080055D8", hit)
blk=struct.unpack("<5I", mu.mem_read(RAMBLK,20))
check("magic set", blk[0]==0xB007C0DE)
check("total count = 0 on cold boot", blk[1]==0)
check("last_csr latched (0x08000000)", blk[2]==0x08000000)
check("RCC_CSR RMVF written", any(a==RCC_CSR and (v&(1<<24)) for a,v in W))
check("IWDG unlock 0x5555", 0x5555 in w32(W,IWDG))
check("IWDG start 0xCCCC",  0xCCCC in w32(W,IWDG))
check("IWDG reload 0xAAAA", 0xAAAA in w32(W,IWDG))
check("IWDG PR=6",  6 in w32(W,IWDG+4))
check("IWDG RLR=0x1C2", 0x1C2 in w32(W,IWDG+8))

# ---- Test 2b: boot_veneer WARM boot after a watchdog reset ----
print("\n[2b] boot_veneer WARM boot, CSR=IWDGRSTF, prior total=7")
mu=rig()
mu.mem_write(RAMBLK, struct.pack("<5I",0xB007C0DE,7,0,2,0))  # magic ok, total=7, iwdg=2
mu.mem_write(RCC_CSR, struct.pack("<I",0x20000000))          # IWDGRSTF (bit29)
W,hit=run(mu,A_BOOT,0x080055D8)
blk=struct.unpack("<5I", mu.mem_read(RAMBLK,20))
check("total incremented 7->8", blk[1]==8)
check("iwdg_count incremented 2->3", blk[3]==3)
check("fault_count unchanged (0)", blk[4]==0)
check("last_csr = 0x20000000", blk[2]==0x20000000)

# ---- Test 2c: WARM boot after a fault (software) reset ----
print("\n[2c] boot_veneer WARM boot, CSR=SFTRSTF")
mu=rig()
mu.mem_write(RAMBLK, struct.pack("<5I",0xB007C0DE,8,0,3,0))
mu.mem_write(RCC_CSR, struct.pack("<I",0x10000000))          # SFTRSTF (bit28)
W,hit=run(mu,A_BOOT,0x080055D8)
blk=struct.unpack("<5I", mu.mem_read(RAMBLK,20))
check("total incremented 8->9", blk[1]==9)
check("fault_count incremented 0->1", blk[4]==1)
check("iwdg_count unchanged (3)", blk[3]==3)

# ---- Test 3: wdt_refresh ----
print("\n[3] wdt_refresh")
mu=rig(); W,hit=run(mu,A_REF,0x080011CC)
check("writes IWDG reload 0xAAAA", 0xAAAA in w32(W,IWDG))
check("tail-calls FUN_080011CC", hit)

# ---- Test 4: clamp_veneer (Patch B) ----
print("\n[4] clamp_veneer (length clamp)")
A_CLAMP=bl_target(0x08003CC4)
RET=0x08003CC8
for inlen,exp in [(0x9000,100),(0x00FF,100),(100,100),(33,33),(11,11)]:
    mu=rig(); mu.reg_write(UC_ARM_REG_R0,inlen); mu.reg_write(UC_ARM_REG_LR,RET|1)
    W,hit=run(mu,A_CLAMP,RET,maxins=30)
    r5=mu.reg_read(UC_ARM_REG_R5); r1=mu.reg_read(UC_ARM_REG_R1)
    check(f"len 0x{inlen:x} -> r5={r5} (expect {exp}), r1=1, returns to 0x{RET:08x}",
          r5==exp and r1==1 and hit)

print("\n"+("ALL VENEER TESTS PASSED" if ok else "*** FAILURES ***"))
sys.exit(0 if ok else 1)
