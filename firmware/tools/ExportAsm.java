// Export disassembly listing (with resolved literal-pool values) for the whole program.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class ExportAsm extends GhidraScript {
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        PrintWriter w = new PrintWriter(new FileWriter(out + "/listing.asm"));
        Listing L = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        InstructionIterator it = L.getInstructions(true);
        Function cur = null;
        while (it.hasNext()) {
            Instruction ins = it.next();
            Function f = fm.getFunctionContaining(ins.getAddress());
            if (f != null && f != cur) { cur = f; w.println(); w.println("; ===== " + f.getName() + " @ " + f.getEntryPoint()); }
            StringBuilder sb = new StringBuilder();
            sb.append(ins.getAddress()).append("  ").append(ins.toString());
            for (Reference r : ins.getReferencesFrom()) {
                Address to = r.getToAddress();
                if (r.getReferenceType().isData() && currentProgram.getMemory().contains(to)) {
                    try {
                        long v = currentProgram.getMemory().getInt(to) & 0xFFFFFFFFL;
                        Symbol s = getSymbolAt(toAddr(v));
                        sb.append("   ; [").append(to).append("]=0x").append(Long.toHexString(v));
                        if (s != null) sb.append(" ").append(s.getName());
                    } catch (Exception e) {}
                } else if (r.getReferenceType().isFlow()) {
                    Function tf = fm.getFunctionAt(to);
                    if (tf != null) sb.append("   ; -> ").append(tf.getName());
                }
            }
            w.println(sb);
        }
        w.close();
        println("asm exported");
    }
}
