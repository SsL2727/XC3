"""Snapshot the live XC1 DE save image and diff against the previous snapshot (label optional).
usage: python xc1_snap.py [label]      first call just stores the baseline."""
import os, pickle, sys, time
sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a
BASE = 0x1c8c4e73040
STORE = r"F:\XCAP\work\xc1_snap.pkl"
mem = a.Memory(a.find_processes(("ryujinx",))[0])
img = mem.read(BASE, 0x153860)
if img is None:
    sys.exit("cannot read live image (address moved?)")
prev = pickle.load(open(STORE, "rb")) if os.path.exists(STORE) else None
pickle.dump(img, open(STORE, "wb"))
if prev is None:
    print("baseline stored"); sys.exit()
NOISY = [(0xe00, 0xf60), (0x149000, 0x14e000), (0x0, 0x10), (0x44000, 0x4a000)]     # counters / tables
ch = [i for i in range(len(img)) if img[i] != prev[i]]
print(f"{len(ch)} bytes changed")
noisy = [i for i in ch if any(lo <= i < hi for lo, hi in NOISY)]
if noisy:
    print("changes in table/counter areas:", [f"{i:#x}:{prev[i]:02x}>{img[i]:02x}" for i in noisy[:60]], "..." if len(noisy) > 60 else "")
for i in ch:
    if any(lo <= i < hi for lo, hi in NOISY):
        continue
    x = img[i] ^ prev[i]
    print(f"+{i:#07x}: {prev[i]:02x}->{img[i]:02x}  set {[b for b in range(8) if x >> b & 1 and img[i] >> b & 1]} cleared {[b for b in range(8) if x >> b & 1 and not img[i] >> b & 1]}")
