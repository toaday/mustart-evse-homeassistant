// Pre-analysis: add STM32F030 memory map and create functions from the vector table.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;

public class Stm32Setup extends GhidraScript {
    void blk(String name, long start, long len, boolean vol) throws Exception {
        Memory m = currentProgram.getMemory();
        Address a = toAddr(start);
        if (m.getBlock(a) != null) return;
        MemoryBlock b = m.createUninitializedBlock(name, a, len, false);
        b.setRead(true); b.setWrite(true); b.setExecute(false); b.setVolatile(vol);
    }
    void lbl(long addr, String name) throws Exception {
        createLabel(toAddr(addr), name, true, SourceType.USER_DEFINED);
    }
    public void run() throws Exception {
        blk("RAM", 0x20000000L, 0x2000, false);
        blk("SYSMEM", 0x1FFFEC00L, 0x1000, false);
        blk("APB", 0x40000000L, 0x18000, true);
        blk("AHB1", 0x40020000L, 0x4400, true);
        blk("AHB2_GPIO", 0x48000000L, 0x1800, true);
        blk("SCS", 0xE000E000L, 0x1000, true);
        // peripheral base labels
        long[][] p = {
            {0x40000000L},{0x40000400L},{0x40002000L},{0x40002800L},{0x40002C00L},{0x40003000L},
            {0x40004400L},{0x40005400L},{0x40007000L},{0x40010000L},{0x40010400L},{0x40012400L},
            {0x40012C00L},{0x40013000L},{0x40013800L},{0x40014000L},{0x40014400L},{0x40014800L},
            {0x40015800L},{0x40020000L},{0x40021000L},{0x40022000L},{0x40023000L},
            {0x48000000L},{0x48000400L},{0x48000800L},{0x48000C00L},{0x48001400L},{0xE000E010L},{0xE000E100L}};
        String[] n = {"TIM2","TIM3","TIM14","RTC","WWDG","IWDG","USART2","I2C1","PWR","SYSCFG","EXTI","ADC",
            "TIM1","SPI1","USART1","TIM15","TIM16","TIM17","DBGMCU","DMA1","RCC","FLASH_IF","CRC",
            "GPIOA","GPIOB","GPIOC","GPIOD","GPIOF","SysTick","NVIC"};
        for (int i = 0; i < n.length; i++) lbl(p[i][0], n[i]);
        String[] vec = {"_estack","Reset_Handler","NMI_Handler","HardFault_Handler","r4","r5","r6","r7","r8","r9","r10",
            "SVC_Handler","r12","r13","PendSV_Handler","SysTick_Handler",
            "WWDG_IRQ","PVD_IRQ","RTC_IRQ","FLASH_IRQ","RCC_IRQ","EXTI0_1_IRQ","EXTI2_3_IRQ","EXTI4_15_IRQ","TSC_IRQ",
            "DMA1_Ch1_IRQ","DMA1_Ch2_3_IRQ","DMA1_Ch4_5_IRQ","ADC_IRQ","TIM1_BRK_UP_IRQ","TIM1_CC_IRQ","TIM2_IRQ","TIM3_IRQ",
            "TIM6_IRQ","TIM7_IRQ","TIM14_IRQ","TIM15_IRQ","TIM16_IRQ","TIM17_IRQ","I2C1_IRQ","I2C2_IRQ","SPI1_IRQ","SPI2_IRQ",
            "USART1_IRQ","USART2_IRQ","USART3_6_IRQ","CEC_IRQ","USB_IRQ"};
        for (int i = 1; i < vec.length; i++) {
            Address va = toAddr(0x08000000L + 4L * i);
            createDWord(va);
            long t = getInt(va) & 0xFFFFFFFFL;
            if ((t & 1) == 0 || t < 0x08000000L || t >= 0x08010000L) continue;
            Address fa = toAddr(t & ~1L);
            disassemble(fa);
            if (getFunctionAt(fa) == null) createFunction(fa, vec[i]);
            else getFunctionAt(fa).setName(vec[i] + "_" + Long.toHexString(t & ~1L), SourceType.USER_DEFINED);
            println("vector " + vec[i] + " -> " + fa);
        }
    }
}
