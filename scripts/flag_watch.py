"""Live flag-change logger for an emulated Xenoblade game (read-only).

usage: python flag_watch.py <xc2|xc3> <seconds> <out.log>
Every 2 s: diff the live flag arrays (1/2/4/8/16/32-bit) against the previous poll and log each change with the detector name
it belongs to (when the world's detect table knows it).  Used to validate detectors and to discover flags for unmapped checks.
"""
import json
import os
import sys
import time

sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a  # noqa: E402

game, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
probe = {"xc2": a.XC2Probe, "xc3": a.XC3Probe}[game]()
det = json.load(open(rf"G:\Archipelago\xc-tools\worldgen\detect\{game}.json", encoding="utf-8"))["locations"]
names = {}
for n, d in det.items():
    names[(d["t"], d.get("i"))] = n


def log(msg):
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def decode(view, prev):
    res = []
    for width, (off, size) in view.layout.items():
        if width == 32:
            continue
        for i in range(0, size):
            if view.blob[off + i] != prev.blob[off + i]:
                per = {1: 8, 2: 4, 4: 2, 8: 1, 16: 0.5}[width]
                if width in (8, 16):
                    idx = int(i / (1 if width == 8 else 2))
                    res.append((width, idx, prev.f(width, idx), view.f(width, idx)))
                else:
                    for j in range(int(per)):
                        idx = i * int(per) + j
                        if prev.f(width, idx) != view.f(width, idx):
                            res.append((width, idx, prev.f(width, idx), view.f(width, idx)))
    return res


t0 = time.time()
prev = None
log("watcher start")
while time.time() - t0 < secs:
    try:
        if not probe.attach():
            time.sleep(5)
            continue
        live = None
        for addr in probe.copies:                      # the live copy = the one without file magic (XC3) / first one (XC2)
            v = probe.read_view(probe.mem, addr)
            if v is not None and v.blob[:4] != a.XC3Probe.SIG[:4]:
                live = v
                break
        if live is None:
            time.sleep(3)
            continue
        if prev is not None:
            for width, idx, old, new in decode(live, prev):
                key = ("f1" if width == 1 else "f2" if width == 2 else None, idx)
                nm = names.get(key, "")
                log(f"flag{width}[{idx}] {old}->{new} {nm}")
        prev = live
    except Exception as ex:
        log(f"err {ex!r}")
        probe.detach()
    time.sleep(2)
log("watcher end")
