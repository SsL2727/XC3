"""Automatic check detection for the Xenoblade AP clients: reads the running game's save/flag memory out of the emulator.

Windows only, ctypes only (the frozen Archipelago Python has no pymem/psutil).  Supports Ryujinx and the yuzu family (Eden, yuzu, Citron, Sudachi ...): the guest RAM is
ordinary RW mapped memory inside the emulator process, so the game's in-memory save struct can be found by its signature.

A `Probe` knows one game's save layout:  find() -> attach and locate the live save copies, read() -> a FlagView, and the detector
table (location name -> {"t": type, "i": id}) says how each location is read from that view.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import struct
import time
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OP = 0x0008
TH32CS_SNAPPROCESS = 0x2
MEM_COMMIT = 0x1000
MEM_MAPPED = 0x40000


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260)]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", wt.DWORD),
                ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


def _start_time(pid: int) -> int:
    """FILETIME the process started, as a raw 64-bit int (0 if it cannot be queried - e.g. already exited); used to prefer the newest
    matching process when several are running (a stale leftover emulator from earlier must never outrank the one actually in front of
    the player - it can hold an unrelated, far-advanced save in memory that reads as 'plausible' and floods checks that were never done).
    Sets its own argtypes/restype: this may run before any Memory() has (attach() calls find_processes() first), and OpenProcess's 64-bit
    HANDLE return must never be read back through ctypes' default (32-bit) int type."""
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.GetProcessTimes.argtypes = [wt.HANDLE, ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME),
                                         ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME)]
    h = kernel32.OpenProcess(PROCESS_QUERY, False, pid)
    if not h:
        return 0
    try:
        creation = wt.FILETIME()
        exit_t, kernel_t, user_t = wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        if not kernel32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_t), ctypes.byref(kernel_t), ctypes.byref(user_t)):
            return 0
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(h)


def find_processes(names: Iterable[str]) -> List[int]:
    """Matching PIDs, newest process first (see _start_time)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out = []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    lowered = [n.lower() for n in names]
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            exe = entry.szExeFile.decode("mbcs", "replace").lower()
            if any(exe.startswith(n) for n in lowered):
                out.append(entry.th32ProcessID)
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    out.sort(key=_start_time, reverse=True)
    return out


YUZU_FAMILY = ("eden", "yuzu", "citron", "sudachi", "suyu", "torzu")


def process_exe(pid: int) -> str:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    name = ""
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            if entry.th32ProcessID == pid:
                name = entry.szExeFile.decode("mbcs", "replace").lower()
                break
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    return name


class Memory:
    def __init__(self, pid: int):
        self.pid = pid
        self.exe = process_exe(pid)
        self.yuzu_family = self.exe.startswith(YUZU_FAMILY)
        kernel32.OpenProcess.restype = wt.HANDLE
        self.h = kernel32.OpenProcess(PROCESS_QUERY | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OP, False, pid)
        if not self.h:
            raise OSError(f"cannot open process {pid}")
        kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]

    def close(self):
        kernel32.CloseHandle(self.h)

    def alive(self) -> bool:
        code = wt.DWORD()
        return bool(kernel32.GetExitCodeProcess(self.h, ctypes.byref(code))) and code.value == 259

    def read(self, addr: int, size: int) -> Optional[bytes]:
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)) or n.value != size:
            return None
        return buf.raw

    def write(self, addr: int, data: bytes) -> bool:
        n = ctypes.c_size_t()
        return bool(kernel32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n)))

    def big_regions(self, count: int = 3) -> List[Tuple[int, int]]:
        """The largest committed RW *mapped* regions - the emulated guest RAM lives in these."""
        regs = []
        addr = 0
        mbi = MBI()
        while kernel32.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == MEM_COMMIT and mbi.Type == MEM_MAPPED and mbi.Protect & 0x4 and size >= 256 * 2 ** 20:
                regs.append((base, size))
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break
        regs.sort(key=lambda r: -r[1])
        return regs[:count]

    def read_sparse(self, addr: int, size: int) -> Optional[bytes]:
        """Like read(), but pages that cannot be read count as zeros (the yuzu family leaves guest pages the game never touched inaccessible).
        None when the first page is unreadable or more than a quarter of the pages are."""
        data = self.read(addr, size)
        if data is not None:
            return data
        out = bytearray()
        bad = 0
        pos = 0
        while pos < size:
            step = min(0x1000 - ((addr + pos) & 0xFFF), size - pos)
            piece = self.read(addr + pos, step)
            if piece is None:
                if pos == 0:
                    return None
                bad += step
                piece = bytes(step)
            out += piece
            pos += step
        return bytes(out) if bad * 4 <= size else None

    def view_regions(self, min_size: int = 64 * 1024, max_size: int = 1 << 30) -> List[Tuple[int, int]]:
        """Runs of address-adjacent readable mapped regions (the yuzu family maps guest memory as many small views; guest RAM is contiguous there,
        while the big backing file it is mapped from is not)."""
        regs = []
        addr = 0
        mbi = MBI()
        while kernel32.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == MEM_COMMIT and mbi.Type == MEM_MAPPED and mbi.Protect in (0x2, 0x4, 0x20, 0x40):
                regs.append((base, size))
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break
        runs: List[Tuple[int, int]] = []
        for base, size in regs:
            if runs and runs[-1][0] + runs[-1][1] == base:
                runs[-1] = (runs[-1][0], runs[-1][1] + size)
            else:
                runs.append((base, size))
        return [r for r in runs if min_size <= r[1] <= max_size]

    def find_all(self, pattern: bytes, regions: List[Tuple[int, int]], chunk: int = 64 * 2 ** 20) -> List[int]:
        hits: List[int] = []
        for base, size in regions:
            off = 0
            while off < size:
                data = self.read(base + off, min(chunk + len(pattern), size - off))
                if data is None:                       # a sparse hole: fall back to smaller reads
                    data = b""
                    sub = 0
                    while sub < min(chunk, size - off):
                        piece = self.read(base + off + sub, min(2 * 2 ** 20, size - off - sub))
                        data += piece if piece is not None else b"\0" * min(2 * 2 ** 20, size - off - sub)
                        sub += 2 * 2 ** 20
                i = data.find(pattern)
                while i >= 0:
                    hits.append(base + off + i)
                    i = data.find(pattern, i + 1)
                off += chunk
        return hits


# --------------------------------------------------------------------------------------------------------------------------
# Flag views
# --------------------------------------------------------------------------------------------------------------------------

class FlagView:
    """Flag arrays of one game as a raw bytes snapshot; subclasses decode widths."""

    def __init__(self, blob: bytes, layout: Dict[int, Tuple[int, int]], extra: Optional[Dict[str, int]] = None):
        self.blob = blob
        self.layout = layout       # width -> (offset in blob, size in bytes)
        self.extra = extra or {}   # named scalar values outside the flag arrays (clear counters ...)
        self.tomb_off = 0          # enemy tombstone table (XC3): offset of entry 0 in blob, entry stride, defeated byte
        self.tomb_stride = 0
        self.tomb_count = 0
        self.save_buf = False      # this copy is the file-shaped save-time buffer, not the live struct (see XC3Probe.locate) -
                                    # its flag block may be mid-write or at a different offset than the live layout, so only
                                    # detectors that specifically need it (tombstones) should trust it

    def tomb(self, i: int) -> int:
        if not self.tomb_stride or i >= self.tomb_count:
            return 0
        return self.blob[self.tomb_off + i * self.tomb_stride + 3]

    def f(self, width: int, i: int) -> int:
        off, size = self.layout[width]
        if width == 1:
            p = off + (i >> 3)
            return (self.blob[p] >> (i & 7)) & 1 if p < off + size else 0
        if width == 2:
            p = off + (i >> 2)
            return (self.blob[p] >> ((i & 3) * 2)) & 3 if p < off + size else 0
        if width == 4:
            p = off + (i >> 1)
            return (self.blob[p] >> ((i & 1) * 4)) & 15 if p < off + size else 0
        if width == 8:
            p = off + i
            return self.blob[p] if p < off + size else 0
        if width == 16:
            p = off + 2 * i
            return struct.unpack_from("<H", self.blob, p)[0] if p + 2 <= off + size else 0
        if width == 32:
            p = off + 4 * i
            return struct.unpack_from("<I", self.blob, p)[0] if p + 4 <= off + size else 0
        raise ValueError(width)


class Probe:
    game = ""
    processes = ("ryujinx", "ryubing", "eden", "yuzu", "citron", "sudachi", "suyu", "torzu")
    RESCAN = 90.0
    STALE_POLLS = 20      # ~40s at the client's 2s poll interval - see true_locations()

    def __init__(self):
        self.mem: Optional[Memory] = None
        self.copies: List[int] = []      # addresses of flag blocks (all live/loaded copies)
        self.last_scan = 0.0
        self.baseline: Dict[str, int] = {}
        self.rise_base: Optional[Set[str]] = None
        self.copy_activity: Dict[int, Tuple[Optional[frozenset], int]] = {}  # copy addr -> (last detector fingerprint, consecutive unchanged polls)

    # -- to override -----------------------------------------------------------------------------------------------------
    def locate(self, mem: Memory) -> List[int]:
        raise NotImplementedError

    def read_view(self, mem: Memory, addr: int) -> Optional[FlagView]:
        raise NotImplementedError

    def valid(self, mem: Memory, addr: int) -> bool:
        """Is a located copy still a live save struct (the game may free / move it when a save is loaded)?"""
        return True

    def evaluate(self, det: dict, view: FlagView) -> bool:
        t = det["t"]
        if view.save_buf and t != "tb":                # the save-time buffer is only trustworthy for tombstones (see FlagView.save_buf)
            return False
        if t == "tb":                                  # enemy tombstone: defeated
            return bool(view.tomb(det["i"]))
        if t == "x":                                   # a named scalar that must have risen above its value at attach time
            k = det["k"]
            return view.extra.get(k, 0) > self.baseline.get(k, 0)
        if t == "f1":
            return bool(view.f(1, det["i"]))
        if t == "f2":
            return view.f(2, det["i"]) >= det.get("v", 1)
        if t == "f8":
            return view.f(8, det["i"]) >= det.get("v", 1)
        if t == "f16":
            return view.f(16, det["i"]) >= det.get("v", 1)
        if t == "f32":
            return view.f(32, det["i"]) >= det.get("v", 1)
        return False

    def is_save_buffer(self, mem: Memory, addr: int) -> bool:
        """Is this copy the file-shaped save-time buffer rather than the live struct? False unless overridden."""
        return False

    # -- driver ------------------------------------------------------------------------------------------------------------
    def attach(self) -> bool:
        if self.mem is not None and self.mem.alive() and self.copies:
            return True
        self.detach()
        for pid in find_processes(self.processes):
            try:
                mem = Memory(pid)
            except OSError:
                continue
            copies = self.locate(mem)
            if copies:
                self.mem, self.copies, self.last_scan = mem, copies, time.time()
                return True
            mem.close()
        return False

    def detach(self):
        self.rise_base = None
        self.copy_activity = {}
        if self.mem is not None:
            try:
                self.mem.close()
            except Exception:
                pass
        self.mem, self.copies = None, []

    def true_locations(self, detectors: Dict[str, dict]) -> Optional[Set[str]]:
        """Names of every detector that is currently true in any copy; None when the game is not reachable."""
        if self.mem is None or not self.mem.alive():
            return None
        self.copies = [a for a in self.copies if self.valid(self.mem, a)]
        if time.time() - self.last_scan > self.RESCAN and self.copies:       # the game may allocate a new save buffer (XC3)
            self.last_scan = time.time()
            for a in self.locate(self.mem):
                if a not in self.copies:
                    self.copies.append(a)
        if not self.copies:
            return None
        views = []
        for a in self.copies:
            v = self.read_view(self.mem, a)
            if v is not None:
                v.save_buf = self.is_save_buffer(self.mem, a)
                views.append((a, v))
        if not views:
            return None
        if not self.baseline:
            self.baseline = {k: max(v.extra.get(k, 0) for _, v in views) for k in views[0][1].extra}
        # ---- per-copy "signal fingerprint": which detectors evaluate true in THIS copy right now. Several
        # genuinely different save-shaped regions can coexist in the emulator's memory at once (not just aliases
        # of one struct) - e.g. a cached preview of a different save slot, or a leftover from an earlier session
        # left resident after restarting/reloading. A raw byte hash of the whole copy is too sensitive - a stray
        # counter/timer field unrelated to real progress can keep "changing" one forever (live-confirmed
        # 2026-09-22: 2 stale bytes ticking every poll in an otherwise frozen 56KB block) - so compare fingerprints
        # made of only what detectors actually care about instead. A copy whose fingerprint hasn't changed in a
        # long time while at least one sibling copy's HAS is very likely one of those stale regions, not the save
        # actually being played (live-confirmed 2026-09-22, XC2: 2 of 6 simultaneous copies matched a location the
        # player had not reached). Only treated as stale after a long unchanged run, and never excluding every
        # copy at once (e.g. the game itself paused) - a briefly-idle real save must never get excluded.
        fps = []
        for a, v in views:
            fp = frozenset(name for name, det in detectors.items() if self.evaluate(det, v))
            last_fp, unchanged = self.copy_activity.get(a, (None, 0))
            unchanged = unchanged + 1 if last_fp == fp else 0
            self.copy_activity[a] = (fp, unchanged)
            fps.append((fp, unchanged))
        chosen = [fp for fp, unchanged in fps if unchanged < self.STALE_POLLS] or [fp for fp, _ in fps]
        result = set().union(*chosen)
        if self.rise_base is None:                     # "rise" detectors (game clear ...) only count when they change after attach
            self.rise_base = {n for n in result if detectors[n].get("rise")}
        return result - self.rise_base


# --------------------------------------------------------------------------------------------------------------------------
# Xenoblade Chronicles 2 (v2.1.0 save layout, flags block per XC2SaveNETThingy + version shift)
# --------------------------------------------------------------------------------------------------------------------------

class XC2Probe(Probe):
    game = "Xenoblade Chronicles 2"
    SIG = bytes.fromhex("5ba10300f3f3f3f3")            # save magic + constant
    FLAG_BASES = (0xFCE00, 0xFCE08)                     # file layout / in-memory layout
    FLAG_SIZE = 0xDC20
    CLEAR_COUNT_OFF = 0x109B3C - 0x1097F4            # GameClearCount, relative to the end of the flag block
    LAYOUT = {1: (0, 0x2000), 2: (0x2000, 0x4000), 4: (0x6000, 0x1000), 8: (0x7000, 0x2000), 16: (0x9000, 0x1800), 32: (0xA800, 0x3420)}

    def locate(self, mem: Memory) -> List[int]:
        regions = mem.big_regions(3)
        found: List[int] = []
        for hit in mem.find_all(self.SIG, regions):
            for fb in self.FLAG_BASES:
                tail = mem.read(hit + fb + self.FLAG_SIZE + 0xC, 8)      # the Map block starts with the map name ("maNNa")
                if tail is not None and re.match(rb"ma\d\d", tail):
                    found.append(hit + fb)
                    break
        return found

    def valid(self, mem: Memory, addr: int) -> bool:
        tail = mem.read(addr + self.FLAG_SIZE + 0xC, 4)
        return tail is not None and re.match(rb"ma\d\d", tail) is not None

    def is_save_buffer(self, mem: Memory, addr: int) -> bool:
        """Is this copy the file-shaped save-time buffer (a stale, separately-maintained mirror of a save file -
        can sit at a very different point in the game than what is actually being played, live-confirmed
        2026-09-22: one showed 271 locations true and clear_count 1 while the real save was a brand new character
        at level 2) rather than the live struct? live_bases() already derives+checks this same relationship for
        delivery; true_locations() needs the same signal per-copy to keep FlagView.save_buf out of the OR (see
        Probe.evaluate) - this was only ever wired up for XC3 before."""
        base = addr - 0xFCE08 if (addr - 0xFCE08) % 16 == 0 else addr - 0xFCE00
        return mem.read(base, 8) == self.SIG

    def live_bases(self) -> List[int]:
        """Struct bases of the LIVE copies (no file header): the save is one struct, drivers/blades sit before the flag block."""
        out = []
        for c in self.copies:
            base = c - 0xFCE08 if (c - 0xFCE08) % 16 == 0 else c - 0xFCE00
            if self.mem is not None and self.mem.read(base, 8) != self.SIG:
                out.append(base)
        return out

    def read_view(self, mem: Memory, addr: int) -> Optional[FlagView]:
        blob = mem.read(addr, self.FLAG_SIZE + self.CLEAR_COUNT_OFF + 4)
        if blob is None:
            return None
        clears = struct.unpack_from("<I", blob, self.FLAG_SIZE + self.CLEAR_COUNT_OFF)[0]
        return FlagView(blob, self.LAYOUT, {"clear_count": clears})


# --------------------------------------------------------------------------------------------------------------------------
# Xenoblade Chronicles 3 (save v10; layout per recordkeeper: flags at +0x710, same flag engine as XC2, tombstones at +0x183000)
# --------------------------------------------------------------------------------------------------------------------------

class XC3Probe(Probe):
    """XC3 keeps the flag arrays live in a save-shaped struct (same offsets as the save file) but stamps no header on it, so it is found
    by an anchor: 8-bit flags 2704..2709 hold 0xFF from the start of every game and the 906 flags before them are never used (identical
    in a new game and in a 90 h save).  Enemy tombstones / inventory are only filled into the struct when the game writes a save
    (the game then builds a full save image, with header, in a buffer) - that buffer is a second, slightly stale copy."""
    game = "Xenoblade Chronicles 3"
    SIG = bytes.fromhex("6afa68b30a000000")            # save-file magic + version 10 (present on the save-time buffer only)
    ANCHOR = bytes(906) + bytes([0xFF]) * 6
    ANCHOR_REL = 0x710 + 0x7000 + 2704 - 906           # offset of ANCHOR start from the struct start
    FLAG_BASE = 0x710
    TOMB_BASE = 0x183000
    TOMB_STRIDE = 20
    TOMB_COUNT = 200
    READ = 0x184000                                     # bytes read per poll (flags + tombstones)
    LAYOUT = {1: (0x710, 0x2000), 2: (0x2710, 0x4000), 4: (0x6710, 0x1000), 8: (0x7710, 0x2000), 16: (0x9710, 0x1800),
              32: (0xAF10, 0x3420)}

    def _plausible(self, mem: Memory, base: int) -> bool:
        head = mem.read(base, 0x700)
        if head is None:
            return False
        play = struct.unpack_from("<I", head, 0x10)[0]
        if head[4:8] == bytes([0xFF]) * 4:                                    # the pristine new-game template image
            return False
        if not (play < 3600 * 2000 and head[0x40:0x660].count(0) > 900):
            return False
        flags = mem.read(base + self.FLAG_BASE, 0xDC20)
        if flags is None:
            return False
        # a real flag block is sparse: few 0xFF bytes (bogus hits are FF-filled buffers) and mostly zero - always
        # required now (previously only checked once the line below already passed, so an early-game struct that
        # failed that line was never even given the chance to prove itself via its flags)
        other = 0xDC20 - flags.count(0) - flags.count(0xFF)
        if flags.count(0xFF) >= 3000 or flags.count(0) <= 0xDC20 * 0.85:
            return False
        # a random-looking 16-byte prefix (Ryujinx) or a running play time (yuzu family, whose live struct has a
        # zero prefix) confirms it; the all-zero pristine new-game template has neither. But very early in a fresh
        # yuzu-family game (live-confirmed 2026-09-22: mid-tutorial-battle, seconds after "New Game") the playtime
        # counter can still read 0 with an all-zero prefix too, indistinguishable from the template by this alone -
        # so also accept a real, clearly non-blank flag block (the template's flag block is uniformly zero/0xFF;
        # this one already passed the sparse check above with real variety, i.e. bytes that are neither) as proof
        # on its own that it is live, not just untouched
        return head[:16].count(0) < 12 or play > 0 or other > 500

    def locate(self, mem: Memory) -> List[int]:
        # Ryujinx: the guest RAM is one big contiguous mapping.  yuzu family: that big mapping is only the (fragmented) backing file - the game's structs are
        # contiguous in the many small views of the guest address space, so those are scanned instead (and the backing file is skipped: its aliases of the
        # same struct would be read across unrelated pages).
        regions = mem.view_regions() if mem.yuzu_family else mem.big_regions(3)
        found: List[int] = []
        for hit in mem.find_all(self.ANCHOR, regions):
            base = hit - self.ANCHOR_REL
            if base % 16 == 0 and base not in found and self._plausible(mem, base):
                found.append(base)
        found += [h for h in mem.find_all(self.SIG, regions) if h not in found]      # the save-time buffer (tombstones)
        return found

    def live_bases(self) -> List[int]:
        """Live save-shaped struct(s): the copies without the file magic (the save-time buffer carries it)."""
        return [c for c in self.copies if self.mem is not None and self.mem.read(c, 4) != self.SIG[:4]]

    def valid(self, mem: Memory, addr: int) -> bool:
        if mem.read(addr, 8) == self.SIG:
            return True
        return mem.read(addr + self.ANCHOR_REL, len(self.ANCHOR)) == self.ANCHOR

    def is_save_buffer(self, mem: Memory, addr: int) -> bool:
        return mem.read(addr, 4) == self.SIG[:4]

    def read_view(self, mem: Memory, addr: int) -> Optional[FlagView]:
        blob = mem.read_sparse(addr, self.READ)
        if blob is None:
            return None
        v = FlagView(blob, self.LAYOUT)
        v.tomb_off, v.tomb_stride, v.tomb_count = self.TOMB_BASE, self.TOMB_STRIDE, self.TOMB_COUNT
        return v


PROBES = {"Xenoblade Chronicles 2": XC2Probe, "Xenoblade Chronicles 3": XC3Probe}
