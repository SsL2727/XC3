"""Log byte changes in the live XC1 DE save image (header/flag area + table area) with bit-level detail. usage: xc1_watch.py <secs> <log>"""
import sys, time
sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a
secs, out = float(sys.argv[1]), sys.argv[2]
mem = a.Memory(a.find_processes(("ryujinx",))[0])
BASES = [0x1c8c4e73040, 0x1c8e454f860, 0x1c8e46ff120]      # candidate live copies (file-shaped images)
RANGES = [(0x0, 0x1300), (0x44000, 0x4a000), (0x149000, 0x14e000), (0x151b40, 0x151b48)]

def log(m):
    open(out, "a", encoding="utf-8").write(f"{time.strftime('%H:%M:%S')} {m}\n")

prev = {}
t0 = time.time()
log("start")
while time.time() - t0 < secs:
    for b in BASES:
        for lo, hi in RANGES:
            d = mem.read(b + lo, hi - lo)
            if d is None:
                continue
            k = (b, lo)
            if k in prev:
                p = prev[k]
                ch = [i for i in range(len(d)) if d[i] != p[i]]
                for i in ch[:200]:
                    x = d[i] ^ p[i]
                    bits = [j for j in range(8) if x >> j & 1]
                    log(f"copy@{b:x} +{lo + i:#x}: {p[i]:02x}->{d[i]:02x} bits {bits}")
            prev[k] = d
    time.sleep(2)
log("end")
