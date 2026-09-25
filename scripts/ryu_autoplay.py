"""Crude autoplayer for the isolated Ryujinx: mash A, walk a bit, log screenshots and watch for the first save file.

usage: python ryu_autoplay.py <seconds> <tag> [--keys "Z Z Z X"]
Only touches the emulator process recorded in ryu_pid.txt (my own isolated instance)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ryu_tools as r  # noqa: E402

SECS = float(sys.argv[1])
TAG = sys.argv[2]
SAVE_DIR = r"F:\XCAP\work\ryu_root\bis\user\save"
LOG = rf"F:\XCAP\work\autoplay_{TAG}.log"


def saves():
    out = {}
    for d, _, fs in os.walk(SAVE_DIR):
        for f in fs:
            p = os.path.join(d, f)
            out[p] = (os.path.getsize(p), os.path.getmtime(p))
    return out


def log(msg):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def focused() -> bool:
    """Only send keys while the emulator has focus; if the user tabs out, wait (never type into their other windows)."""
    w = r.main_window()
    return bool(w) and r.user32.GetForegroundWindow() == w[0]


base = saves()
t0 = time.time()
n = 0
while time.time() - t0 < SECS and r.alive():
    if not focused():
        time.sleep(1.0)
        continue
    n += 1
    try:
        r.key("Z", hold=0.1, wait=0.6)
        r.key("X", hold=1.6, wait=0.4)            # hold X = Skip Event in cutscenes
        if n % 5 == 0:
            r.key("W", hold=1.8, wait=0.3)
        if n % 10 == 0:
            r.shot(rf"F:\XCAP\work\auto_{TAG}_{n}.png", front_first=False)
            now = saves()
            changed = [p for p, v in now.items() if base.get(p) != v]
            if changed:
                log(f"n={n} save files changed: {changed[:6]}")
                base = now
            else:
                log(f"n={n} no save changes")
    except Exception as ex:  # window may be busy
        log(f"err {ex!r}")
        time.sleep(2)
log("done")
