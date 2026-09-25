"""Softlock-recovery failsafe: a controller button combo that overrides the game to get the player out of a frozen
cutscene - user decision 2026-09-23: "to prevent softlocking the game if the player enters a cutscene without the
necessary progressive story items", with a live-confirmed real example (the Brighid recruitment scene in Torigoth
froze the game when Progressive Story Quest count hadn't caught up yet). Story gating (xc_deliver._open_gates)
already tries to hold cutscenes back until their key item has arrived, but a gap between "the trigger fires" and
"the key item lands" (e.g. a slow/async multiworld) can still hang the game on an unadvanceable cutscene with no
menu access - this is the way out when that happens.

Explicitly NOT the mechanism: force-granting the blocking story/recruitment item early (rejected by user
2026-09-23 - "don't do that"). The actual failure mode this targets is now handled at the root instead: character
recruitment items (Brighid, Morag, Dromarch, ...) were removed from the world entirely (see build_worlds.py,
2026-09-23) since none of them ever had a real delivery mechanism to begin with. What THIS module still needs to
solve is the narrower, already-triggered-cutscene case: skip the frozen cutscene itself without marking its
underlying story beat complete, so it can still fire again later once the player legitimately has what it needs.

Escape mechanism: TBD - see the module's function definitions below for what's implemented so far and what
remains open. The original design (teleport the player via a raw position write) is confirmed NOT viable:
live testing 2026-09-23 proved PLAYER_POS_OFFSET is a read-only mirror the game reverts within <50ms of any
external write (exhaustively confirmed: nearby-offset scan, a full custom Win32 hardware debugger built and
self-validated, two confirmed same-physical-page aliases watched simultaneously, DR7 persistence verified).
Kept below, still inert, in case a genuinely writable position is ever found some other way.

Detecting the combo: read the physical controller directly via the SDL2 GameController API, via ctypes against
SDL2.dll - already bundled next to the Archipelago client (G:\\Archipelago\\lib\\SDL2.dll, confirmed 2026-09-23)
for its own GUI, so this adds no new dependency for the compiled client. Reading the same physical device from a
second process is safe - Windows HID devices are not exclusive-locked by Ryujinx.
"""
from __future__ import annotations

import ctypes
import os
import struct
import sys
import time
from typing import Callable, List, Optional, Tuple

SDL_INIT_GAMECONTROLLER = 0x2000
# SDL_GameControllerButton enum (fixed by SDL2 ABI, not by driver/OS - same values for any controller SDL maps)
BTN_A, BTN_B, BTN_X, BTN_Y = 0, 1, 2, 3
BTN_BACK, BTN_GUIDE, BTN_START = 4, 5, 6
BTN_LEFTSTICK, BTN_RIGHTSTICK = 7, 8
BTN_LEFTSHOULDER, BTN_RIGHTSHOULDER = 9, 10
BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT = 11, 12, 13, 14
# SDL_GameControllerAxis enum - L2/R2 are analog triggers, not digital buttons, so they're read as an axis
# (0..32767) rather than a button (0/1); AXIS_HELD_THRESHOLD is how far in counts as "pressed".
AXIS_TRIGGERLEFT, AXIS_TRIGGERRIGHT = 4, 5
AXIS_HELD_THRESHOLD = 16000

# the failsafe combo: L3 + R3 + L2 + R2 held together (user choice 2026-09-23). Four inputs none of which XC2 uses
# for anything on their own, so this can't be pressed by accident during normal play.
FAILSAFE_COMBO = (BTN_LEFTSTICK, BTN_RIGHTSTICK)                    # digital buttons
FAILSAFE_COMBO_AXES = (AXIS_TRIGGERLEFT, AXIS_TRIGGERRIGHT)         # analog triggers, checked against the threshold
HOLD_SECONDS = 1.5          # must be held this long before it fires - a deliberate action, not a twitch

# XC2 live save-struct base + this = the player's world-position float3 (x, y, z) - for READING only. Live-verified
# 2026-09-23: found by snapshotting a 24MB window around the live base 5 times at 3s intervals while the player
# walked in a straight line, keeping only offsets whose float3 changed by a small, CONSISTENT distance every
# single step (3.8-4.1 units per 3s, i.e. steady walking speed) with Y nearly constant (flat ground) and X/Z doing
# the moving. Reads are accurate and match the game's real, current position exactly.
# WRITES DO NOT STICK: live-tested 2026-09-23 - a +5 nudge on X was gone on the very next read, less than 50ms
# later, and stayed gone (not a gradual smoothing/interpolation snap-back, an immediate hard revert). This is a
# read-only mirror the game re-derives every tick from some other, authoritative transform/physics object -
# writing here cannot move the player. WRITE_WORKS records that finding so write_player_pos() fails loudly
# instead of silently doing nothing; the teleport feature stays wired up (combo detection, landmark-position
# capture using this offset for reads) but the actual warp needs the real authoritative address, not found yet.
PLAYER_POS_OFFSET: Optional[int] = 0xA51C50
WRITE_WORKS = False


class ControllerCombo:
    """Polls the first attached SDL2 game controller for FAILSAFE_COMBO, independently of whatever Ryujinx itself
    is doing with the same physical device. Call poll() roughly every 100-200ms; it returns True once, the moment
    the combo has been held continuously for HOLD_SECONDS (call again on a later poll to re-arm)."""

    def __init__(self):
        self.sdl = None
        self.controller = None
        self.held_since: Optional[float] = None
        self.fired = False
        self._tried_init = False

    def _ensure_init(self) -> bool:
        if self.controller is not None:
            return True
        if self._tried_init:
            return False
        self._tried_init = True
        try:
            # __file__ is unreliable here (this module loads from inside the zip-packaged .apworld, not a plain
            # directory) - sys.executable is the real, on-disk path to the frozen client exe (e.g.
            # G:\Archipelago\ArchipelagoLauncher.exe), which sits next to lib\SDL2.dll regardless of how this
            # module itself got imported. Falls back to a bare name (default DLL search / PATH) if that's not it.
            candidates = [os.path.join(os.path.dirname(sys.executable), "lib", "SDL2.dll"), "SDL2.dll"]
            dll = next((c for c in candidates if c == "SDL2.dll" or os.path.exists(c)), "SDL2.dll")
            self.sdl = ctypes.CDLL(dll)
            self.sdl.SDL_GameControllerOpen.restype = ctypes.c_void_p
            self.sdl.SDL_GameControllerNameForIndex.restype = ctypes.c_char_p
            if self.sdl.SDL_Init(SDL_INIT_GAMECONTROLLER) != 0:
                return False
            for i in range(self.sdl.SDL_NumJoysticks()):
                if self.sdl.SDL_IsGameController(i):
                    h = self.sdl.SDL_GameControllerOpen(i)
                    if h:
                        self.controller = ctypes.c_void_p(h)
                        return True
            return False
        except OSError:
            return False

    def poll(self) -> bool:
        if not self._ensure_init():
            return False
        self.sdl.SDL_GameControllerUpdate()
        buttons_held = all(self.sdl.SDL_GameControllerGetButton(self.controller, b) for b in FAILSAFE_COMBO)
        self.sdl.SDL_GameControllerGetAxis.restype = ctypes.c_int16
        axes_held = all(self.sdl.SDL_GameControllerGetAxis(self.controller, a) >= AXIS_HELD_THRESHOLD for a in FAILSAFE_COMBO_AXES)
        held = buttons_held and axes_held
        now = time.monotonic()
        if not held:
            self.held_since = None
            self.fired = False
            return False
        if self.held_since is None:
            self.held_since = now
        if not self.fired and now - self.held_since >= HOLD_SECONDS:
            self.fired = True
            return True
        return False


def read_player_pos(mem, live_base: int) -> Optional[Tuple[float, float, float]]:
    """The player's current live world position, or None if PLAYER_POS_OFFSET isn't verified yet / unreadable."""
    if PLAYER_POS_OFFSET is None:
        return None
    raw = mem.read(live_base + PLAYER_POS_OFFSET, 12)
    return struct.unpack("<fff", raw) if raw is not None else None


def write_player_pos(mem, live_base: int, pos: Tuple[float, float, float]) -> bool:
    """Always False right now - see PLAYER_POS_OFFSET's comment. Kept as a real function (not deleted) so the rest
    of the teleport path doesn't need to change shape once a genuinely writable address replaces WRITE_WORKS=False."""
    if PLAYER_POS_OFFSET is None or not WRITE_WORKS:
        return False
    return mem.write(live_base + PLAYER_POS_OFFSET, struct.pack("<fff", *pos))


class LandmarkTracker:
    """Remembers where the player was standing the last time a landmark-category location became true, for the
    teleport failsafe to send them back to. update() takes this poll's true-detector set and the previous poll's,
    diffs them for newly-true landmark locations, and (once PLAYER_POS_OFFSET is verified) snapshots position."""

    def __init__(self, landmark_names: set):
        self.landmark_names = landmark_names
        self.pos: Optional[Tuple[float, float, float]] = None
        self.name: str = ""

    def update(self, mem, live_base: int, true_now: set, true_before: set, log: Callable[[str], None]) -> None:
        newly = (true_now - true_before) & self.landmark_names
        if not newly:
            return
        pos = read_player_pos(mem, live_base)
        name = sorted(newly)[0]
        if pos is not None:
            self.pos, self.name = pos, name
            log(f"Failsafe: remembered position at landmark '{name}' for the teleport failsafe.")
        else:
            log(f"Failsafe: landmark '{name}' activated, but the teleport failsafe can't record position yet "
                f"(player-position offset not live-verified - see xc_failsafe.py).")

    def teleport(self, mem, live_base: int, log: Callable[[str], None]) -> bool:
        if self.pos is None:
            log("Failsafe: no remembered landmark position yet (activate at least one landmark first) - nothing to teleport to.")
            return False
        if write_player_pos(mem, live_base, self.pos):
            log(f"Failsafe: teleported to '{self.name}' ({self.pos[0]:.1f}, {self.pos[1]:.1f}, {self.pos[2]:.1f}).")
            return True
        log("Failsafe: teleport write failed (game not in a writable state right now - try again).")
        return False
