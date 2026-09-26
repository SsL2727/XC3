"""Build the Open World starting save for Xenoblade Chronicles 3.

Open World starts the player on a real, game-made save that has the whole story done except the final battle (scenario
1537, late chapter 7), instead of forcing story flags into a running game. The base is a 100% save (see
detect/xc3_open_world_base.sav.gz); everything an Archipelago check is detected by is reset so the checks can be done
again. Save layout per roccodev/recordkeeper (lib/src/save/mod.rs, flags.rs, enemy.rs): a raw struct, no checksum or
compression; the flag region is the same one the client reads live (xc_autotrack.XC3Probe).
"""
from __future__ import annotations

import struct
from typing import Dict, Iterable

SAVE_MAGIC = bytes([0x6A, 0xFA, 0x68, 0xB3])
FLAG1_BASE = 0x710
FLAG2_BASE = 0x2710
FLAG16_BASE = 0x9710
TOMB_BASE = 0x183000
TOMB_STRIDE = 20
TOMB_DEFEATED = 3

SCENARIO_FLAG16 = 1
GAME_CLEAR_FLAG1 = 6879          # the client's goal detector waits for this to rise
SECRET_COUNT_FLAG16 = 1944
LANDMARK_COUNT_FLAG16 = 1945
CATEGORY_SECRET = 1
CATEGORY_LANDMARK = 2

# One fast-travel point stays unlocked (and is removed from the item pool), otherwise the save would load with nowhere
# to fast travel to. Must be a location with a MapJumpID (a real fast-travel point).
HOME_LOCATION = "Colony 9 Assembly Square"
RESET_KINDS = ("location", "container", "tombstone")   # quests are left as-is: Open World removes quest checks instead


def _set_f1(buf: bytearray, i: int, v: int) -> None:
    p = FLAG1_BASE + (i >> 3)
    buf[p] = (buf[p] & ~(1 << (i & 7))) | ((v & 1) << (i & 7))


def _get_f1(buf: bytes, i: int) -> int:
    return (buf[FLAG1_BASE + (i >> 3)] >> (i & 7)) & 1


def _set_f16(buf: bytearray, i: int, v: int) -> None:
    struct.pack_into("<H", buf, FLAG16_BASE + 2 * i, v)


def get_f16(buf: bytes, i: int) -> int:
    return struct.unpack_from("<H", buf, FLAG16_BASE + 2 * i)[0]


def build(base: bytes, locations: Dict[str, dict], categories: Dict[str, int], keep: Iterable[str] = (HOME_LOCATION,)) -> bytes:
    """base: the untouched base save. locations: detect.json "locations". categories: location flag -> CategoryPriority."""
    if base[:4] != SAVE_MAGIC:
        raise ValueError("not an XC3 game save (bad magic)")
    keep = set(keep)
    missing = keep - set(locations)
    if missing:
        raise ValueError(f"keep locations not in detect data: {sorted(missing)}")
    buf = bytearray(base)
    for name, det in locations.items():
        kind = det["src"].split(":")[0]
        if kind not in RESET_KINDS or name in keep:
            continue
        if det["t"] == "f1":
            _set_f1(buf, det["i"], 0)
        elif det["t"] == "tb":
            buf[TOMB_BASE + det["i"] * TOMB_STRIDE + TOMB_DEFEATED] = 0
        else:
            raise ValueError(f"{name}: unexpected detector type {det['t']!r} for a {kind} check")
    for name in keep:
        _set_f1(buf, locations[name]["i"], 1)
    _set_f1(buf, GAME_CLEAR_FLAG1, 0)
    # recordkeeper keeps these two counters in step with the visited flags of landmarks / secret areas; recompute them
    # from what is still unlocked rather than decrementing (the base save's own counts are off by one or two)
    landmarks = sum(1 for f, c in categories.items() if c == CATEGORY_LANDMARK and _get_f1(buf, int(f)))
    secrets = sum(1 for f, c in categories.items() if c == CATEGORY_SECRET and _get_f1(buf, int(f)))
    _set_f16(buf, LANDMARK_COUNT_FLAG16, landmarks)
    _set_f16(buf, SECRET_COUNT_FLAG16, secrets)
    return bytes(buf)
