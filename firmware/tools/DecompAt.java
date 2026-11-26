// Create functions at the given addresses (if missing) and print their decompilation + disassembly.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import java.io.*;

public class DecompAt extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter w = new PrintWriter(new FileWriter(a[0], true));
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        for (int i = 1; i < a.length; i++) {
            Address ad = toAddr(a[i]);
            disassemble(ad);
            Function f = getFunctionAt(ad);
            if (f == null) f = createFunction(ad, null);
            if (f == null) { w.println("// could not create function at " + ad); continue; }
            w.println("// ===== " + f.getName() + " @ " + f.getEntryPoint() + " =====");
            DecompileResults r = d.decompileFunction(f, 60, monitor);
            w.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// failed " + r.getErrorMessage());
            InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (it.hasNext()) { Instruction ins = it.next(); w.println("//   " + ins.getAddress() + "  " + ins); }
        }
        w.close();
    }
}
