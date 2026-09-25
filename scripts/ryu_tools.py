"""Helpers for driving an ISOLATED Ryujinx instance: window capture, key injection, process memory access.

Only ever attach to the pid stored in F:/XCAP/work/ryu_pid.txt (the instance this toolkit launched).
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import subprocess
import time

from PIL import ImageGrab

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()

RYUJINX = r"D:\Emulators\ryujinx-1.3.3-win_x64\publish\Ryujinx.exe"
ROOT = r"F:\XCAP\work\ryu_root"
PID_FILE = r"F:\XCAP\work\ryu_pid.txt"


# ----------------------------------------------------------------------------------------------------------------- process
def launch(game: str, root: str = ROOT) -> int:
    p = subprocess.Popen([RYUJINX, "-r", root, game], stdout=open(r"F:\XCAP\work\ryu_stdout.log", "wb"), stderr=subprocess.STDOUT)
    open(PID_FILE, "w").write(str(p.pid))
    return p.pid


def pid() -> int:
    return int(open(PID_FILE).read().strip())


def alive() -> bool:
    try:
        h = kernel32.OpenProcess(0x1000, False, pid())
        if not h:
            return False
        code = wt.DWORD()
        kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        kernel32.CloseHandle(h)
        return code.value == 259
    except Exception:
        return False


def kill():
    subprocess.run(["taskkill", "/PID", str(pid()), "/F"], capture_output=True)


# ------------------------------------------------------------------------------------------------------------------ windows
def _windows_of(p: int):
    out = []
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(h, _):
        wp = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(wp))
        if wp.value == p and user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            r = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            out.append((h, buf.value, (r.left, r.top, r.right, r.bottom)))
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    return out


def main_window():
    ws = [w for w in _windows_of(pid()) if w[2][2] - w[2][0] > 200]
    ws.sort(key=lambda w: -(w[2][2] - w[2][0]) * (w[2][3] - w[2][1]))
    return ws[0] if ws else None


def front():
    w = main_window()
    if w:
        user32.ShowWindow(w[0], 9)
        user32.SetWindowPos(w[0], wt.HWND(-1), 0, 0, 0, 0, 0x0043)   # topmost, no move/size
        user32.SetForegroundWindow(w[0])
    return w


def shot(path: str, front_first: bool = True):
    w = front() if front_first else main_window()
    if not w:
        return None
    time.sleep(0.3)
    r = wt.RECT()
    user32.GetWindowRect(w[0], ctypes.byref(r))
    im = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    im.save(path)
    return w[1], im.size


# -------------------------------------------------------------------------------------------------------------------- keys
SCAN = {  # Ryujinx default keyboard: A=Z B=X X=C Y=V L=E R=U ZL=Q ZR=O Plus/Minus, arrows, WASD stick
    "Z": 0x2C, "X": 0x2D, "C": 0x2E, "V": 0x2F, "E": 0x12, "U": 0x16, "Q": 0x10, "O": 0x18, "W": 0x11, "A": 0x1E, "S": 0x1F, "D": 0x20,
    "I": 0x17, "K": 0x25, "J": 0x24, "L": 0x26, "F": 0x21, "H": 0x23, "MINUS": 0x0C, "PLUS": 0x0D,
    "UP": 0x48, "DOWN": 0x50, "LEFT": 0x4B, "RIGHT": 0x4D, "ENTER": 0x1C, "ESC": 0x01,
}
EXT = {"UP", "DOWN", "LEFT", "RIGHT"}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(scan: int, up: bool, ext: bool):
    flags = 0x0008 | (0x0002 if up else 0) | (0x0001 if ext else 0)      # SCANCODE | KEYUP | EXTENDEDKEY
    i = INPUT(type=1)
    i.ki = KEYBDINPUT(0, scan, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def key(name: str, hold: float = 0.12, wait: float = 0.25):
    """Press a Switch button (by its default Ryujinx keyboard key). The Ryujinx window must be foreground."""
    n = name.upper()
    _send(SCAN[n], False, n in EXT)
    time.sleep(hold)
    _send(SCAN[n], True, n in EXT)
    time.sleep(wait)


def keys(seq: str, hold: float = 0.12, wait: float = 0.3):
    for k in seq.split():
        key(k, hold, wait)


# -------------------------------------------------------------------------------------------------------------------- memory
PROCESS_ALL = 0x1F0FFF


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", wt.DWORD),
                ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


class Mem:
    def __init__(self, p: int = None):
        self.h = kernel32.OpenProcess(PROCESS_ALL, False, p or pid())
        if not self.h:
            raise OSError("OpenProcess failed")
        kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]

    def read(self, addr: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)):
            raise OSError(f"read failed @ {addr:#x}")
        return buf.raw[:n.value]

    def try_read(self, addr: int, size: int):
        try:
            return self.read(addr, size)
        except OSError:
            return None

    def write(self, addr: int, data: bytes):
        n = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n)):
            raise OSError(f"write failed @ {addr:#x}")

    def regions(self, min_size: int = 0, committed_only: bool = True):
        addr = 0
        mbi = MBI()
        while kernel32.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if (not committed_only or mbi.State == 0x1000) and size >= min_size:
                yield base, size, mbi.Protect, mbi.Type, mbi.AllocationBase or 0
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break

    def find(self, pattern: bytes, start: int = 0, end: int = 0x7FFFFFFFFFFF, chunk: int = 1 << 24, writable_only: bool = False):
        hits = []
        for base, size, prot, typ, _ab in self.regions():
            if base + size < start or base > end or prot & 0x101:      # skip NOACCESS / GUARD
                continue
            if writable_only and not prot & 0xCC:
                continue
            off = 0
            while off < size:
                n = min(chunk + len(pattern), size - off)
                data = self.try_read(base + off, n)
                if data:
                    i = data.find(pattern)
                    while i >= 0:
                        hits.append(base + off + i)
                        i = data.find(pattern, i + 1)
                off += chunk
        return hits
