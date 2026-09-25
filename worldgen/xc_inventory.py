"""Add items to the running game's inventory (Ryujinx memory).

XC2: the save's ItemBox (live struct + 0xE98E8) holds 18 boxes of 12-byte entries: u32 {id:13, type:6, qty:10, flags:3}, u32 elapse time,
u32 {serial:26, unk:6}.  Each box has a serial counter in `Serials` (box k uses Serials[k+1]); a new entry takes counter+1.
Stackable boxes (crystals, pouch items, materials ...) add to an existing entry with the same id; accessories / aux cores are one entry each.
"""
from __future__ import annotations

import struct
from typing import Dict, Optional

XC2_ITEMBOX = 0xE98E8
XC2_SERIALS = 0x122A0
# name -> (index, offset, slots, type value, stackable, max qty)
XC2_BOXES: Dict[str, tuple] = {
    "corechip": (0, 0x0, 200, 1, True, 99),
    "accessory": (1, 0x960, 900, 2, False, 1),
    "auxcore": (2, 0x3390, 500, 3, False, 1),
    "cylinder": (3, 0x4B00, 200, 5, True, 99),
    "keyitem": (4, 0x5460, 500, 6, True, 1),
    "info": (5, 0x6BD0, 200, 14, True, 1),
    "collectible": (7, 0x79E0, 500, 7, True, 99),
    "treasure": (8, 0x9150, 200, 8, True, 99),
    "unrefaux": (9, 0x9AB0, 500, 9, False, 1),
    "pouch": (10, 0xB220, 500, 10, True, 99),
    "corecrystal": (11, 0xC990, 200, 11, True, 99),
}


# ItemBox entries store `row id - base` (the ITM_* table's $id minus its base): crystals 45000, pouch items 40000, accessories 0.
# corechip/auxcore added 2026-09-23: ITM_HanaRole starts at 56001, ITM_HanaAssist at 60001 - both well past the iid
# field's 13-bit range (max 8191), so without a base subtracted here the packed entry silently wraps (id truncated
# mod 8192, and the overflow bits corrupt the adjacent type/qty fields via the plain OR in xc2_add_item) - the item
# never shows up as anything recognizable in-game. Confirmed missing live 2026-09-23 (Aux Cores not appearing).
XC2_BASE: Dict[str, int] = {"corecrystal": 45000, "pouch": 40000, "accessory": 0, "keyitem": 25000,
                            "corechip": 56000, "auxcore": 60000}


def _unpack(w0: int):
    return w0 & 0x1FFF, (w0 >> 13) & 0x3F, (w0 >> 19) & 0x3FF


def xc2_count_item(mem, live_base: int, box: str, row_id: int) -> Optional[int]:
    """Quantity of the ITM_* row `row_id` in the named box (None when the memory cannot be read)."""
    idx, off, slots, typ, stackable, qmax = XC2_BOXES[box]
    raw = mem.read(live_base + XC2_ITEMBOX + off, 12 * slots)
    if raw is None:
        return None
    want, total = row_id - XC2_BASE.get(box, 0), 0
    for i in range(slots):
        iid, t, q = _unpack(struct.unpack_from("<I", raw, i * 12)[0])
        if iid == want and t == typ and q:
            total += q
    return total


def xc2_add_item(mem, live_base: int, box: str, row_id: int, qty: int = 1) -> bool:
    """Add `qty` of the ITM_* row `row_id` to the named box; returns True when the memory was updated."""
    idx, off, slots, typ, stackable, qmax = XC2_BOXES[box]
    item_id = row_id - XC2_BASE.get(box, 0)
    ib = live_base + XC2_ITEMBOX
    raw = mem.read(ib + off, 12 * slots)
    ser = mem.read(ib + XC2_SERIALS + 4 * (idx + 1), 4)
    if raw is None or ser is None:
        return False
    empty: Optional[int] = None
    for i in range(slots):
        w0 = struct.unpack_from("<I", raw, i * 12)[0]
        iid, t, q = _unpack(w0)
        if iid == item_id and t == typ and stackable:
            new_q = min(q + qty, qmax)
            if new_q == q:
                return True                                   # already full
            w0 = (w0 & ~(0x3FF << 19)) | (new_q << 19)
            return mem.write(ib + off + i * 12, struct.pack("<I", w0))
        if w0 == 0 and empty is None:
            empty = i
    if empty is None:
        return False                                          # box full
    serial = struct.unpack("<I", ser)[0] + 1
    entry = struct.pack("<III", item_id | (typ << 13) | (min(qty, qmax) << 19), 0, serial & 0x3FFFFFF)
    ok = mem.write(ib + off + empty * 12, entry)
    return ok and mem.write(ib + XC2_SERIALS + 4 * (idx + 1), struct.pack("<I", serial))


# ---------------------------------------------------------------------------------------------------------------------- XC3
# The live save data keeps its item arrays (16-byte entries {u16 item id, u16 index, u32 type, u32 serial, u16 qty, u16 flags}) at
# live base + XC3_SHIFT + (offset the same array has in the save file); the next serial number is a separate u32 (live base + XC3_COUNTER).
# flags: 1 = seen, 5 = new (shows the NEW dot).  Gems are single instances (type 2); accessories stack per id (type 5).
XC3_SHIFT = 0x7FF68
XC3_COUNTER = 0xE5B4C
XC3_ARRAYS: Dict[str, tuple] = {           # name -> (save-file offset, type, capacity, stackable)
    "gem": (0x53DA0, 2, 300, False),
    "collection": (0x55060, 3, 2300, True),
    "accessory": (0x5E020, 5, 1500, True),
    "precious": (0x63DE0, 7, 100, True),
}
XC3_ENTRY = struct.Struct("<HHIIHH")


def xc3_layout_ok(mem, live_base: int) -> bool:
    """True when the arrays sit where expected: every non-empty entry matches its array's type / index, at least one array has entries
    and the serial counter is not below any serial in use."""
    top, used = 0, 0
    for name, (off, typ, cap, _st) in XC3_ARRAYS.items():
        raw = mem.read(live_base + XC3_SHIFT + off, 16 * min(cap, 400))
        if raw is None:
            return False
        for i in range(len(raw) // 16):
            item, idx, t, serial, qty, _fl = XC3_ENTRY.unpack_from(raw, i * 16)
            if item == 0 and t == 0 and serial == 0:
                break
            if t != typ or idx != i or qty == 0:
                return False
            used += 1
            top = max(top, serial)
    counter = mem.read(live_base + XC3_COUNTER, 4)
    return used > 0 and counter is not None and top <= struct.unpack("<I", counter)[0] < 5_000_000


def xc3_add_item(mem, live_base: int, kind: str, item_id: int, qty: int = 1) -> bool:
    """Add `qty` of the ITM_* row `item_id` (12001.. gems, 1.. accessories) to the named array; True when the memory was updated."""
    off, typ, cap, stackable = XC3_ARRAYS[kind]
    base = live_base + XC3_SHIFT + off
    raw = mem.read(base, 16 * cap)
    counter_raw = mem.read(live_base + XC3_COUNTER, 4)
    if raw is None or counter_raw is None:
        return False
    empty = None
    for i in range(cap):
        item, idx, t, serial, q, fl = XC3_ENTRY.unpack_from(raw, i * 16)
        if item == 0 and t == 0 and serial == 0:
            empty = i
            break
        if stackable and item == item_id and t == typ:
            return mem.write(base + i * 16 + 12, struct.pack("<HH", min(q + qty, 999), fl | 4))
    if empty is None:
        return False                                          # array full
    serial = struct.unpack("<I", counter_raw)[0] + 1
    ok = mem.write(base + empty * 16, XC3_ENTRY.pack(item_id, empty, typ, serial, qty if stackable else 1, 5))
    return ok and mem.write(live_base + XC3_COUNTER, struct.pack("<I", serial))


def xc3_remove_placeholders(mem, live_base: int, kind: str, item_ids) -> list:
    """Take every entry whose item id is in `item_ids` out of the named array; the array stays dense (the last entry moves into the hole, index fixed).
    Returns the removed item ids."""
    off, typ, cap, _st = XC3_ARRAYS[kind]
    base = live_base + XC3_SHIFT + off
    raw = mem.read(base, 16 * cap)
    if raw is None:
        return []
    entries = []
    for i in range(cap):
        e = XC3_ENTRY.unpack_from(raw, i * 16)
        if e[0] == 0 and e[2] == 0 and e[3] == 0:
            break
        entries.append(list(e))
    removed = []
    i = 0
    while i < len(entries):
        item, idx, t, serial, qty, fl = entries[i]
        if item in item_ids and t == typ:
            removed.append(item)
            last = entries.pop()
            if i < len(entries):                                   # move the last entry into the hole
                last[1] = i
                entries[i] = last
                mem.write(base + i * 16, XC3_ENTRY.pack(*last))
            mem.write(base + len(entries) * 16, bytes(16))
            continue
        i += 1
    return removed
