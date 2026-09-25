"""Locate the XC2 scenario counter in the live save struct by diffing snapshots.
usage: python find_scenario.py snap <name>      (take a snapshot of the live struct, first 0x118000 bytes)
       python find_scenario.py diff <a> <b>      (u32 values that rose by 1..40 between the snapshots and lie in 1001..10100)"""
import os, struct, sys
sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a

D = r"F:\XCAP\work\scen"
os.makedirs(D, exist_ok=True)
if sys.argv[1] == "snap":
    p = a.XC2Probe()
    assert p.attach()
    open(os.path.join(D, sys.argv[2] + ".bin"), "wb").write(p.mem.read(p.live_bases()[0], 0x118000))
    print("saved", sys.argv[2])
else:
    A = open(os.path.join(D, sys.argv[2] + ".bin"), "rb").read()
    B = open(os.path.join(D, sys.argv[3] + ".bin"), "rb").read()
    for i in range(0, min(len(A), len(B)) - 4, 4):
        x, y = struct.unpack_from("<I", A, i)[0], struct.unpack_from("<I", B, i)[0]
        if 1001 <= x <= 10100 and 1 <= y - x <= 40:
            print(hex(i), x, "->", y)
