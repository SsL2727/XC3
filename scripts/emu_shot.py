"""Screenshot / window list of an emulator process this toolkit launched (never anything else).

usage: python emu_shot.py <pid file> <out.png> [list]
  Fronts the process's biggest window (topmost) and grabs exactly its rectangle, like ryu_tools.shot.
"""
import sys

import ryu_tools as R


def main(pid_file, out, mode="shot"):
    R.PID_FILE = pid_file
    ws = R._windows_of(R.pid())
    if mode == "list":
        for h, title, rect in ws:
            print(hex(h), repr(title), rect)
        return
    if mode == "click":                               # out = "x,y" relative to the main window's top-left
        import ctypes
        w = R.front()
        x, y = (int(v) for v in out.split(","))
        ctypes.windll.user32.SetCursorPos(w[2][0] + x, w[2][1] + y)
        ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
        return
    print(R.shot(out))


main(*sys.argv[1:])
