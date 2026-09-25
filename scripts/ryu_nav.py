"""Closed-loop 'walk to the objective marker' for XC3 (isolated Ryujinx only).

Finds the big red objective hexagon on the main view, turns the camera with the right stick (J = left, L = right) until it is
centred, then walks forward (left stick W). Sends keys only while the emulator window is foreground; presses A when the marker
is hidden (dialogue / event covering the HUD).   usage: python ryu_nav.py <seconds>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ryu_tools as r  # noqa: E402
from PIL import ImageGrab  # noqa: E402

W, H = 1296, 768


def grab():
    w = r.main_window()
    rc = r.wt.RECT()
    r.user32.GetWindowRect(w[0], r.ctypes.byref(rc))
    return ImageGrab.grab(bbox=(rc.left, rc.top, rc.right, rc.bottom), all_screens=True)


def marker_x(im):
    """screen x (0..1) of the big red objective hexagon, or None (minimap area and bottom-right prompt excluded)"""
    px = im.load()
    xs = n = 0
    for y in range(60, 700, 2):
        for x in range(30, 1270, 2):
            if x > 1040 and y < 290:          # minimap
                continue
            if x > 1030 and y > 690:          # 'Show/Hide Objective' prompt
                continue
            R, G, B = px[x, y][:3]
            if 165 <= R <= 215 and 30 <= G <= 95 and B < 45 and R - G > 85:
                xs += x
                n += 1
    if n < 15:
        return None
    return xs / n / W


def focused():
    w = r.main_window()
    return bool(w) and r.user32.GetForegroundWindow() == w[0]


if __name__ == "__main__":
    t0 = time.time()
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    while time.time() - t0 < secs and r.alive():
        if not focused():
            time.sleep(1)
            continue
        mx = marker_x(grab())
        if mx is None:
            r.key("Z", hold=0.1, wait=0.6)
            print(f"{time.time() - t0:4.0f}s no marker -> A")
            continue
        err = mx - 0.5
        if abs(err) > 0.10:
            r.key("L" if err > 0 else "J", hold=max(0.03, min(0.22, abs(err) * 0.22)), wait=0.35)
            print(f"{time.time() - t0:4.0f}s marker x={mx:.2f} turn {'R' if err > 0 else 'L'}")
        else:
            r.key("W", hold=2.0, wait=0.15)
            print(f"{time.time() - t0:4.0f}s marker x={mx:.2f} walk")
