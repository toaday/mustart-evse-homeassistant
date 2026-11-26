// Post-analysis: dump decompiled C for every function, plus a function list with sizes.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class ExportAll extends GhidraScript {
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        PrintWriter c = new PrintWriter(new FileWriter(out + "/decomp.c"));
        PrintWriter l = new PrintWriter(new FileWriter(out + "/functions.txt"));
        int n = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            n++;
            l.println(f.getEntryPoint() + "\t" + f.getBody().getNumAddresses() + "\t" + f.getName());
            DecompileResults r = d.decompileFunction(f, 60, monitor);
            c.println("// ===== " + f.getName() + " @ " + f.getEntryPoint() + " =====");
            if (r != null && r.decompileCompleted()) c.println(r.getDecompiledFunction().getC());
            else c.println("// decompile failed: " + (r == null ? "null" : r.getErrorMessage()));
        }
        c.close(); l.close();
        println("exported " + n + " functions");
    }
}
