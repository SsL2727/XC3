"""Item delivery: apply the multiworld items a slot has received to the running game (Ryujinx memory).

Design rules (learned from live tests, see README): only write values the game itself would accept.
Delivery is idempotent: every pass recomputes the desired state from the full list of received items (outfits, flags); items that go
into the inventory are handed over once, tracked in DeliveryState.

XC2 driver Arts (art_cap items, capping WP-bought art levels) were removed entirely 2026-09-23 per user decision - the mechanic
was unreliable in live testing ("Drivers aren't working"). No replacement; art levels are no longer part of AP logic for XC2.
"""
from __future__ import annotations

import json
import math
import os
import struct
from typing import Callable, Dict, List, Optional

class DeliveryState:
    """What has already been handed to the game for this slot (a JSON file next to the client's other data).  Items that end up
    consumed in game (a used crystal, an eaten pouch item) cannot be told from "never delivered" by looking at the game."""

    def __init__(self):
        self.path = ""
        self.given: Dict[str, int] = {}            # item name -> copies already delivered
        self.blades: List[int] = []                # blade ids whose crystal was already delivered

    def bind(self, path: str) -> None:
        if path == self.path:
            return
        self.path = path
        self.given, self.blades = {}, []
        try:
            data = json.load(open(path, encoding="utf-8"))
            self.given = {k: int(v) for k, v in data.get("given", {}).items()}
            self.blades = [int(b) for b in data.get("blades", [])]
        except Exception:
            pass

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"given": self.given, "blades": self.blades}, fh)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def reset(self) -> None:
        self.given, self.blades = {}, []
        self.save()


class XC2Deliverer:
    DRIVER_BASE = 0x3C          # Rex's driver record: id 1 (used by _save_loaded to detect a save is actually loaded)
    # blade records: +0 u16 status, +6 u16 blade id (CHR_Bl row id), +0x34 u32 trust points, +0x38 u32 trust rank (hearts 1-5)
    BLADE_BASE, BLADE_SIZE, BLADE_SLOTS = 0x5A3C, 0x8A4, 140
    TRUST_PTS, TRUST_RANK = 0x34, 0x38
    TRUST_START = {2: 100, 3: 1600, 4: 4600, 5: 10600}       # trust points at which a heart is reached (FLD_ConditionIdea / live saves)

    def __init__(self, table: dict):
        self.items: Dict[str, dict] = table.get("items", {})
        self.vanilla_crystals = {int(k): int(v) for k, v in table.get("vanilla_crystals", {}).items()}
        self.state = DeliveryState()
        self.crystals: Optional[Dict[int, int]] = None   # blade id -> crystal item row id (from the installed mod's marker)
        self.slot_data: Dict[str, object] = {}           # set by the client
        self.blade_slots: Optional[Dict[int, int]] = None  # blade id -> slot in the save's blade array
        self.gates: Optional[Dict[int, int]] = None      # gate tier -> 1-bit flag id
        self.gates_total: int = 0                        # total beat count (gates.json's own "count") - see _open_gates
        self.opened: set = set()
        self.marker_data: Optional[dict] = None
        self.pending_checks: List[str] = []              # shop locations found in the item box, sent by the client
        self.sent_shops: set = set()
        self.seed_name = ""
        self.warned = False

    def _marker(self) -> dict:
        """ap_patch.json of the installed XC2 mod (blade crystals, shop placeholders, ...); {} when there is none."""
        if self.marker_data is None:
            try:
                from . import xc_patch
                self.marker_data = xc_patch.read_marker("Xenoblade Chronicles 2")
            except Exception:
                return {}
        return self.marker_data

    # ---- the installed mod tells which crystal holds which blade
    def _crystal_map(self, log: Callable[[str], None]) -> Dict[int, int]:
        if self.crystals is not None:
            return self.crystals
        mapping: Dict[int, int] = {}
        try:
            from . import xc_patch
            data = xc_patch.read_marker("Xenoblade Chronicles 2")
            mapping = {int(k): int(v) for k, v in data.get("blade_crystals", {}).items()}
            if self.seed_name and data.get("seed_name") and data["seed_name"] != self.seed_name:
                log(f"Delivery: the installed game mod is for seed {data['seed_name']}, this multiworld is {self.seed_name} - run the patcher again.")
                mapping = {}
        except Exception:
            pass
        if not mapping:
            log("Delivery: no patched game mod found (run the Xenoblade Chronicles 2 Patcher on your .apxc2 file) - blades cannot be delivered yet.")
            return {}                                 # look again next pass
        self.crystals = mapping
        log(f"Delivery: {len(mapping)} blade crystals known from the installed mod.")
        return mapping

    @staticmethod
    def _save_loaded(mem, base: int) -> bool:
        head = mem.read(base + XC2Deliverer.DRIVER_BASE + 0x22, 2)          # Rex's driver record: id 1
        return head is not None and struct.unpack("<H", head)[0] == 1

    def apply(self, probe, counts: Dict[str, int], log: Callable[[str], None]) -> int:
        """Deliver blade crystals and filler. Returns the number of memory writes done."""
        mem = probe.mem
        if mem is None:
            return 0
        writes = 0
        bases = probe.live_bases()
        if bases and self._save_loaded(mem, bases[0]):
            writes += self._deliver_inventory(mem, bases[0], counts, log)
            writes += self._cap_trust(mem, bases[0], counts, log)
            writes += self._open_gates(mem, bases[0], counts, log)
            writes += self._watch_shops(mem, bases[0], log)
            writes += self._apply_new_game_plus(mem, bases[0], log)
        return writes

    # ---- New Game Plus (best-effort - see the option's own description): flip GameClearCount 0 -> 1 once per
    # save, the same field XC2Probe already reads for read_view()'s clear_count. FLAG_BASES/FLAG_SIZE/
    # CLEAR_COUNT_OFF are XC2Probe's own layout constants (xc_autotrack.py) - duplicated here rather than
    # importing the class, since only the offsets are needed, not a full Probe instance.
    NGP_FLAG_BASE, NGP_FLAG_SIZE, NGP_CLEAR_COUNT_OFF = 0xFCE08, 0xDC20, 0x109B3C - 0x1097F4

    def _apply_new_game_plus(self, mem, base: int, log: Callable[[str], None]) -> int:
        if not self.slot_data or not self.slot_data.get("new_game_plus") or self.state.given.get("__ngp_applied"):
            return 0
        addr = base + self.NGP_FLAG_BASE + self.NGP_FLAG_SIZE + self.NGP_CLEAR_COUNT_OFF
        raw = mem.read(addr, 4)
        if raw is None:
            return 0
        current = struct.unpack("<I", raw)[0]
        if current > 0:
            self.state.given["__ngp_applied"] = 1     # already cleared for real - nothing to do, don't touch it again
            self.state.save()
            return 0
        if mem.write(addr, struct.pack("<I", 1)):
            self.state.given["__ngp_applied"] = 1
            self.state.save()
            log("Delivery: New Game Plus - GameClearCount set to 1.")
            return 1
        return 0

    # ---- shop checks: every shop slot sells its own placeholder pouch item; buying one is the check, then the item is taken out again
    def _watch_shops(self, mem, base: int, log: Callable[[str], None]) -> int:
        mode = self.slot_data.get("shop_checks") if self.slot_data else 0
        placeholders = self._marker().get("shop_placeholders") if mode else None
        if not placeholders:
            return 0
        from .xc_inventory import XC2_BOXES, XC2_BASE, XC2_ITEMBOX
        idx, off, slots, typ, _st, _qm = XC2_BOXES["pouch"]
        raw = mem.read(base + XC2_ITEMBOX + off, 12 * slots)
        if raw is None:
            return 0
        writes = 0
        for i in range(slots):
            w0 = struct.unpack_from("<I", raw, i * 12)[0]
            if not w0 or ((w0 >> 13) & 0x3F) != typ:
                continue
            info = placeholders.get(str(XC2_BASE["pouch"] + (w0 & 0x1FFF)))
            if info is None:
                continue
            name = f"Shop {info['shop']}" + (f" #{info['slot']}" if mode == 2 else "")
            if mem.write(base + XC2_ITEMBOX + off + i * 12, bytes(12)):           # take the placeholder out of the pouch again
                writes += 1
                if name not in self.sent_shops:
                    self.sent_shops.add(name)
                    self.pending_checks.append(name)
                    log(f"Shop check: {name}")
        return writes

    # ---- story gates: every locked story step waits for its own key item (rando_bridge xc2_story_gates); the k-th Progressive Story Quest hands over step k's item
    def _gate_table(self) -> Dict[int, int]:
        if self.gates is None:
            self.gates = {}
            try:
                import pkgutil
                data = json.loads(pkgutil.get_data(__package__, "data/gates.json").decode("utf-8"))
                self.gates = {b["need"]: b["item"] for b in data["beats"]}
                self.gates_total = int(data.get("count") or max(self.gates, default=0))
            except Exception:
                pass
        return self.gates

    def _open_gates(self, mem, base: int, counts: Dict[str, int], log: Callable[[str], None]) -> int:
        if not self.slot_data or not self.slot_data.get("story_gating"):
            return 0
        from .xc_inventory import xc2_add_item, xc2_count_item
        have = counts.get("Progressive Story Quest", 0)
        table = self._gate_table()
        # Story Items Required (0..gates_total, default gates_total = vanilla 1-to-1 pacing): scales each beat's
        # threshold down so the SAME beats are reachable with fewer total items - user decision 2026-09-23, to
        # shrink the window where the game's own scenario triggers can outrun a slow/async multiworld's item
        # delivery and hang on a scripted event still waiting for its story item. 0 = every beat unlocked
        # immediately regardless of items received.
        required = self.slot_data.get("story_items_required", self.gates_total)
        try:
            required = int(required)
        except (TypeError, ValueError):
            required = self.gates_total
        writes = 0
        for need, item in table.items():
            if required <= 0:
                threshold = 0
            elif self.gates_total <= 0 or required >= self.gates_total:
                threshold = need                      # vanilla pacing (also the safe fallback if count is unknown)
            else:
                threshold = math.ceil(need * required / self.gates_total)
            if have < threshold:
                continue
            if xc2_count_item(mem, base, "keyitem", item) == 0 and xc2_add_item(mem, base, "keyitem", item, 1):
                writes += 1
                log(f"Story step {need} unlocked ({have}/{threshold} Progressive Story Quest item(s) received"
                    f"{'' if required >= self.gates_total else f', story_items_required={required}'}).")
        return writes

    # ---- blade trust hearts are capped at 1 + copies of the trust item(s)
    def _slots(self, mem, base: int) -> Dict[int, int]:
        if self.blade_slots is None:
            found: Dict[int, int] = {}
            for slot in range(self.BLADE_SLOTS):
                raw = mem.read(base + self.BLADE_BASE + slot * self.BLADE_SIZE + 6, 2)
                bid = struct.unpack("<H", raw)[0] if raw else 0
                if 1001 <= bid <= 1200:
                    found[bid] = slot
            if len(found) < 40:                                # not a blade array (game still loading): try again next pass
                return {}
            self.blade_slots = found
        return self.blade_slots

    def _cap_trust(self, mem, base: int, counts: Dict[str, int], log: Callable[[str], None]) -> int:
        sd = self.slot_data
        if not sd or not sd.get("progressive_blade_trust"):
            return 0
        per_blade = bool(sd.get("trust_per_blade"))
        slots = self._slots(mem, base)
        if not slots:
            return 0
        caps: Dict[int, int] = {}                              # blade id -> hearts allowed
        for name, eff in self.items.items():
            if eff["t"] != "trust_cap" or (eff["blades"] == "all") == per_blade:
                continue
            cap = 1 + min(counts.get(name, 0), eff["max"])
            for bid in (slots if eff["blades"] == "all" else eff["blades"]):
                caps[bid] = max(caps.get(bid, 1), cap)
        writes = 0
        for bid, cap in caps.items():
            slot = slots.get(bid)
            if slot is None or cap >= 5:
                continue
            addr = base + self.BLADE_BASE + slot * self.BLADE_SIZE + self.TRUST_PTS
            raw = mem.read(addr, 8)
            if raw is None:
                continue
            pts, rank = struct.unpack("<II", raw)
            top = self.TRUST_START[cap + 1] - 1                # the last point that is still `cap` hearts
            if 1 <= rank <= 5 and (rank > cap or pts > top):
                new = (min(pts, top), min(rank, cap))
                if mem.write(addr, struct.pack("<II", *new)):
                    writes += 1
                    log(f"Delivery: blade {bid} trust capped at {cap} heart(s) (had {rank} heart(s), {pts} points)")
        return writes

    def _deliver_inventory(self, mem, base: int, counts: Dict[str, int], log: Callable[[str], None]) -> int:
        from .xc_inventory import xc2_add_item
        writes, dirty = 0, False
        for name, eff in self.items.items():
            n = counts.get(name, 0)
            if n <= 0:
                continue
            if eff["t"] == "blade_crystal":
                blade = eff["blade"]
                if blade in self.state.blades:
                    continue
                crystal = self._crystal_map(log).get(blade)
                if crystal is None:
                    continue
                if xc2_add_item(mem, base, "corecrystal", crystal, 1):
                    self.state.blades.append(blade)
                    dirty = True
                    writes += 1
                    log(f"Delivery: {name} - core crystal {crystal} added to the inventory (blade {blade})")
            elif eff["t"] == "give":
                todo = n - self.state.given.get(name, 0)
                for _ in range(max(0, todo)):
                    if not xc2_add_item(mem, base, eff["box"], eff["id"], eff.get("qty", 1)):
                        break
                    self.state.given[name] = self.state.given.get(name, 0) + 1
                    dirty = True
                    writes += 1
                    log(f"Delivery: {name} added to the inventory")
        if dirty:
            self.state.save()
        return writes


_MUTEXES: list = []


def claim_mutex(name: str) -> bool:
    """True when this process is the only one holding the named mutex (two clients multiplying one emulator would feed each other)."""
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == 183           # ERROR_ALREADY_EXISTS
    if handle:
        _MUTEXES.append(handle)                        # keep it for the life of the process
    return bool(handle) and not already


class GainMultiplier:
    """Multiplies experience-type gains: watches counters, and when one rises by d between polls adds d*(m-1) more.
    A counter that falls (the player spends it, a level-up resets it) is only re-baselined.  Jumps above MAX_JUMP are
    treated as loads / resets, not gains."""
    MAX_JUMP = 5_000_000

    def __init__(self):
        self.last: Dict[int, int] = {}
        self.disabled = False
        self.owner_pid = 0
        self._key = None
        self.bonus = 0                                 # total extra points granted this session

    def counters(self, probe) -> List[tuple]:
        """[(address, is_u32)] of every counter to watch; per game."""
        raise NotImplementedError

    def apply(self, probe, mult: int, log: Callable[[str], None]) -> int:
        mem = probe.mem
        if mem is None or self.disabled:
            return 0
        if self.owner_pid != mem.pid:                      # claim this emulator; a second client must not multiply it too
            if not claim_mutex(f"xcap_gain_{mem.pid}"):
                self.disabled = True
                log("Experience multiplier: another Xenoblade client is already multiplying this emulator - disabled in this client.")
                return 0
            self.owner_pid = mem.pid
        key = (mem.pid, tuple(probe.copies))
        if key != self._key:                               # re-attached / the game reloaded: old readings are meaningless
            self._key = key
            self.last.clear()
        writes = 0
        addrs = self.counters(probe)
        if not addrs:
            return 0
        lo, hi = min(addrs), max(addrs) + 4
        block = mem.read(lo, hi - lo) if hi - lo <= 1 << 20 else None      # one read for the whole counter block
        for addr in addrs:
            raw = block[addr - lo:addr - lo + 4] if block is not None else mem.read(addr, 4)
            if raw is None:
                continue
            cur = struct.unpack("<I", raw)[0]
            prev = self.last.get(addr)
            if prev is not None and mult > 1 and 0 < cur - prev <= self.MAX_JUMP:
                extra = (cur - prev) * (mult - 1)
                new = min(cur + extra, 0xFFFFFFF0)
                if mem.write(addr, struct.pack("<I", new)):
                    self.bonus += new - cur
                    writes += 1
                    cur = new
            self.last[addr] = cur
        return writes


class XC2GainMultiplier(GainMultiplier):
    DRIVER_BASE, DRIVER_SIZE, DRIVERS = 0x3C, 0x5A0, 10
    DRIVER_FIELDS = (0xB0, 0xB4, 0xB8, 0xBC)          # Exp, BattleExp, SkillPoints, TotalSkillPoints
    WEAPONS_OFF, WEAPON_SIZE, WEAPONS = 0xC0, 0x14, 27
    WEAPON_FIELDS = (0xC, 0x10)                       # WeaponPoints, TotalWeaponPoints
    BLADE_BASE, BLADE_SIZE, BLADE_SLOTS, BLADE_TRUST = 0x5A3C, 0x8A4, 140, 0x34      # blade trust points

    def counters(self, probe) -> List[tuple]:
        out = []
        for base in probe.live_bases()[:1]:            # the alias shares the same memory
            out += [base + self.BLADE_BASE + i * self.BLADE_SIZE + self.BLADE_TRUST for i in range(self.BLADE_SLOTS)]
            for i in range(self.DRIVERS):
                drv = base + self.DRIVER_BASE + i * self.DRIVER_SIZE
                out += [drv + f for f in self.DRIVER_FIELDS]
                for w in range(self.WEAPONS):
                    out += [drv + self.WEAPONS_OFF + w * self.WEAPON_SIZE + f for f in self.WEAPON_FIELDS]
        return out


class XC3GainMultiplier(GainMultiplier):
    """XC3 keeps live Character objects (level u32, exp u32, bonus_exp u32, ...) in an array with stride 0x3100, allocated right
    after the live save struct (+0x113C0 in every session so far).  Found by that offset, validated, else by a window scan."""
    STRIDE = 0x3100
    COUNT = 12
    DEFAULT_OFF = 0x113C0
    # runtime class entries: obj + 0xF8 + k*0xC0 = {cp u32, unlock_points u16, rank u8, cap u8, ...} (matched against the save file's values)
    CLASS_BASE, CLASS_STRIDE, CLASSES = 0xF8, 0xC0, 64

    def __init__(self):
        super().__init__()
        self.chars = None
        self.chars_for = None

    @staticmethod
    def _ok(blob: bytes, at: int, stride: int) -> bool:
        good = 0
        for i in range(6):
            o = at + i * stride
            if o + 12 > len(blob):
                return False
            lv, ex, bx = struct.unpack_from("<III", blob, o)
            if not (1 <= lv <= 99 and ex < 30_000_000 and bx < 30_000_000):
                return False
            good += 1
        return good == 6

    def _locate(self, probe):
        mem = probe.mem
        for live in probe.live_bases():
            blob = mem.read(live + self.DEFAULT_OFF, self.STRIDE * 6 + 16)
            if blob is not None and self._ok(blob, 0, self.STRIDE):
                return live + self.DEFAULT_OFF
            lo = live - 0x400000
            win = mem.read(lo, 0xC00000)                      # fallback: scan a 12 MB window around the struct
            if win is not None:
                for at in range(0, len(win) - self.STRIDE * 6, 16):
                    if self._ok(win, at, self.STRIDE):
                        return lo + at
        return None

    def counters(self, probe) -> List[tuple]:
        live = probe.live_bases()
        key = tuple(live)
        if self.chars is None or self.chars_for != key:
            self.chars, self.chars_for = self._locate(probe), key
        if self.chars is None:
            return []
        mem = probe.mem
        out = []
        for i in range(self.COUNT):
            o = self.chars + i * self.STRIDE
            head = mem.read(o, 4)
            if head is None or not (1 <= struct.unpack("<I", head)[0] <= 99):
                continue
            out += [o + 4, o + 8]                              # exp, bonus_exp
            out += [o + self.CLASS_BASE + k * self.CLASS_STRIDE for k in range(self.CLASSES)]      # class points (CP) per class
        return out


class _WriteBudget:
    """Caps how many memory writes one apply() call may make. Live-confirmed 2026-09-25: a client attaching to an
    already-progressed multiworld (hundreds of items already received) applied its entire backlog - outfits, gems,
    story/container gate unlocks - in one uninterrupted burst, and since apply() writes every live save copy
    (4 copies seen live), the same backlog was written 3-4x over in well under a second. That flood of memory writes
    is what froze then crashed the emulator; xc3_layout_ok (see apply()) only gates *when* delivery may start, not
    how much it does once started. A shared budget spent across every writer in one apply() call bounds each poll
    tick to a small number of writes regardless of backlog size or copy count, so a large backlog trickles in over
    many 1.5s ticks instead of landing all at once."""
    __slots__ = ("left",)

    def __init__(self, n: int):
        self.left = n

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        return True


class XC3Deliverer:
    """XC3 items applied through the live 2-bit flag array (save struct + 0x2710).  Outfits: 0 = hidden in the Clothing list,
    1 = unlocked (NEW dot), 2 = unlocked and seen (live-verified).  Received -> raised to 1 if 0; not received -> forced to 0.
    Gem / accessory filler goes into the live item arrays once each (DeliveryState, see xc_inventory).
    Also a live 1-bit flag array (save struct + 0x710, same one xc_autotrack's f1 detectors read) for effects like
    Manana's Menu recipes, whose own BDAT row (FLD_MealRecipe.OpenFlag) names the flag directly."""
    FLAG2_BASE = 0x2710
    FLAG1_BASE = 0x710
    MAX_WRITES_PER_POLL = 3        # small and adjustable; see _WriteBudget for why this exists

    def __init__(self, table: dict):
        self.items: Dict[str, dict] = table.get("items", {})
        self.state = DeliveryState()
        self.slot_data: Dict[str, object] = {}
        self.seed_name = ""
        self.layout_warned = False
        self.marker_data = None
        self.pending_checks: List[str] = []
        self.sent_shops: set = set()
        self.gates = None
        self.container_gates = None

    def _marker(self) -> dict:
        if self.marker_data is None:
            try:
                from . import xc_patch
                self.marker_data = xc_patch.read_marker("Xenoblade Chronicles 3")
            except Exception:
                return {}
        return self.marker_data

    # ---- shop checks: every shop slot sells its own placeholder accessory; buying one is the check, then the accessory is taken out again
    def _watch_shops(self, mem, base: int, log: Callable[[str], None]) -> int:
        mode = self.slot_data.get("shop_checks") if self.slot_data else 0
        placeholders = self._marker().get("shop_placeholders") if mode else None
        if not placeholders:
            return 0
        from .xc_inventory import XC3_ARRAYS, XC3_ENTRY, XC3_SHIFT, xc3_remove_placeholders
        off, typ, cap, _st = XC3_ARRAYS["accessory"]
        raw = mem.read(base + XC3_SHIFT + off, 16 * cap)
        if raw is None:
            return 0
        found = set()
        for i in range(cap):
            item, idx, t, serial, qty, fl = XC3_ENTRY.unpack_from(raw, i * 16)
            if item == 0 and t == 0 and serial == 0:
                break
            if t == typ and qty and str(item) in placeholders:
                found.add(item)
        if not found:
            return 0
        for item in found:
            info = placeholders[str(item)]
            name = f"Shop {info['shop']}" + (f" #{info['slot']}" if mode == 2 else "")
            if name not in self.sent_shops:
                self.sent_shops.add(name)
                self.pending_checks.append(name)
                log(f"Shop check: {name}")
        return len(xc3_remove_placeholders(mem, base, "accessory", found))

    def apply(self, probe, counts: Dict[str, int], log: Callable[[str], None]) -> int:
        mem = probe.mem
        if mem is None:
            return 0
        bases = probe.live_bases()
        if not bases:
            return 0
        # Nothing is written or delivered - not the outfit/flag writes below, not inventory, not gating - until at
        # least one live copy's item arrays check out. Previously only the item-array writers (_deliver_inventory,
        # _watch_shops, _open_gates, _open_container_gates) waited on this; the flag2/flag1 loop and
        # _cap_affinity/_cap_story had no such gate and would fire on connect before the game's item lists were
        # found, which is what produced the burst of writes reported live 2026-09-25.
        from .xc_inventory import xc3_layout_ok
        ok_bases = [b for b in bases if xc3_layout_ok(mem, b)]
        if not ok_bases:
            if not self.layout_warned:
                self.layout_warned = True
                log("Delivery: waiting for the game's item lists (load a save; nothing is written or delivered until they are found).")
            return 0
        self.layout_warned = False
        # Every write below (flag2/flag1 loop, and the bases-scanning _cap_affinity/_cap_story) targets ok_bases only,
        # never the raw `bases` list. XC3Probe's "plausible" heuristic can report a candidate that looks enough like
        # a save copy to pass its loose flag-block check without actually being real save data (see the early-game
        # note below); writing flags/caps into such a candidate stomps on whatever memory is actually there.
        # Live-confirmed 2026-09-25: an Eden session crashed with "Cannot execute instruction at unmapped address 0"
        # a few seconds after connect, preceded by repeated Unmapped Read32 errors recurring on the delivery poll
        # interval - consistent with a write landing outside real save data and corrupting a pointer the game later
        # jumped through. xc3_layout_ok's structural check (type/index/qty coherence, serial counter in range) is
        # what makes ok_bases trustworthy; bases is not.
        budget = _WriteBudget(self.MAX_WRITES_PER_POLL)
        writes = 0
        for base in ok_bases:
            if budget.left <= 0:
                break
            blob = mem.read(base + self.FLAG2_BASE, 0x4000)
            if blob is None:
                continue
            for name, eff in self.items.items():
                if budget.left <= 0:
                    break
                if eff["t"] != "flag2":
                    continue
                idx = eff["i"]
                byte, sh = idx >> 2, (idx & 3) * 2
                cur = (blob[byte] >> sh) & 3
                # "also": other item name(s) that grant the same flag (e.g. Class Access and Outfit are the same
                # RSC_PcCostumeOpen bit under two AP item names) - checked on BOTH entries so whichever one the
                # player doesn't have can't see "not wanted" and relock a bit the other one just set this same poll
                want = counts.get(name, 0) > 0 or any(counts.get(a, 0) > 0 for a in eff.get("also", ()))
                if want and cur == 0:
                    new = eff.get("grant", 1)
                elif not want and cur != 0:
                    new = 0
                else:
                    continue
                addr = base + self.FLAG2_BASE + byte
                raw = mem.read(addr, 1)
                if raw is None:
                    continue
                if mem.write(addr, bytes([(raw[0] & ~(3 << sh)) | (new << sh)])):
                    writes += 1
                    budget.left -= 1
                    log(f"Delivery: {name} {'unlocked' if want else 'locked'}")
            if budget.left <= 0:
                break
            blob1 = mem.read(base + self.FLAG1_BASE, 0x2000)
            if blob1 is None:
                continue
            for name, eff in self.items.items():
                if budget.left <= 0:
                    break
                if eff["t"] != "flag1":
                    continue
                idx = eff["i"]
                byte, bit = idx >> 3, idx & 7
                cur = (blob1[byte] >> bit) & 1
                want = counts.get(name, 0) > 0 or any(counts.get(a, 0) > 0 for a in eff.get("also", ()))
                new = 1 if want else 0
                if new == cur:
                    continue
                addr = base + self.FLAG1_BASE + byte
                raw = mem.read(addr, 1)
                if raw is None:
                    continue
                if mem.write(addr, bytes([(raw[0] & ~(1 << bit)) | (new << bit)])):
                    writes += 1
                    budget.left -= 1
                    log(f"Delivery: {name} {'unlocked' if want else 'locked'}")
        # bases[0]/ok_bases[0] is just whichever copy sorts first (by address) - usually fine when there is one real
        # copy, but XC3Probe can also report early-game candidates that pass its flag-block heuristic without having
        # a valid inventory layout yet (see _plausible's 2026-09-22 early-game fix). Inventory-dependent operations
        # need the copy whose item arrays actually check out, or they silently do nothing (live-confirmed: shop
        # checks stopped sending because bases[0] was one of those flag-only candidates while the real copy with
        # working arrays was bases[3]) - ok_bases[0] is guaranteed to be one that passes.
        inv_base = ok_bases[0]
        writes += self._deliver_inventory(mem, inv_base, counts, log, budget)
        writes += self._watch_shops(mem, inv_base, log)
        writes += self._open_gates(mem, inv_base, counts, log, budget)
        writes += self._open_container_gates(mem, inv_base, counts, log, budget)
        if self.slot_data and self.slot_data.get("open_world"):
            # Open World: every colony starts already at max affinity - this directly conflicts with
            # progressive_colony_affinity's job of holding affinity DOWN, so it wins outright rather than
            # stacking with it (see the option's own description).
            writes += self._max_affinity_once(mem, ok_bases, log, budget)
        elif self.slot_data and self.slot_data.get("progressive_colony_affinity"):
            writes += self._cap_affinity(mem, ok_bases, counts, log, budget)
        if self.slot_data and self.slot_data.get("open_world"):
            # Open World: the whole main story is already done except the final battle - same conflict/override
            # reasoning as affinity above, this replaces story_gating's hold-below-complete behavior rather than
            # stacking with it.
            writes += self._story_complete_once(mem, ok_bases, log, budget)
        elif self.slot_data and self.slot_data.get("story_gating"):
            writes += self._cap_story(mem, ok_bases, counts, log, budget)
        return writes

    # ---- story gates: every locked story step waits for its own key item (rando_bridge xc3_story_gates); the k-th Progressive Story Quest hands over step k's item
    def _gate_table(self) -> Dict[int, int]:
        if self.gates is None:
            self.gates = {}
            try:
                import pkgutil
                raw = pkgutil.get_data(__package__, "data/gates.json")
                self.gates = {b["need"]: b["item"] for b in json.loads(raw.decode("utf-8"))["beats"]}
            except Exception:
                pass
        return self.gates

    def _open_gates(self, mem, base: int, counts: Dict[str, int], log: Callable[[str], None], budget: "_WriteBudget") -> int:
        if not self.slot_data or not self.slot_data.get("story_gating"):
            return 0
        from .xc_inventory import xc3_add_item
        have = counts.get("Progressive Story Quest", 0)
        writes = 0
        for need, item in self._gate_table().items():
            if have < need:
                continue
            key = f"__gate:{item}"
            if self.state.given.get(key):
                continue
            if not budget.take():
                break
            if xc3_add_item(mem, base, "precious", item, 1):
                self.state.given[key] = 1
                self.state.save()
                writes += 1
                log(f"Story step {need} unlocked ({have} Progressive Story Quest item(s) received).")
        return writes

    # ---- container gates: every locked container batch waits for its own key item (rando_bridge
    # xc3_container_gates); the k-th Progressive Container Access hands over batch k's item. Unlike story gating
    # this patches the containers' own real spawn/pop condition (GMK_TreasureBox.Condition), so - unlike the story
    # beats - simply granting the key item here is expected to be sufficient; no live memory hold needed.
    def _container_gate_table(self) -> Dict[int, int]:
        if self.container_gates is None:
            self.container_gates = {}
            try:
                import pkgutil
                raw = pkgutil.get_data(__package__, "data/container_gates.json")
                self.container_gates = {b["need"]: b["item"] for b in json.loads(raw.decode("utf-8"))["beats"]}
            except Exception:
                pass
        return self.container_gates

    def _open_container_gates(self, mem, base: int, counts: Dict[str, int], log: Callable[[str], None], budget: "_WriteBudget") -> int:
        if not self.slot_data or not self.slot_data.get("container_gating"):
            return 0
        from .xc_inventory import xc3_add_item
        have = counts.get("Progressive Container Access", 0)
        writes = 0
        for need, item in self._container_gate_table().items():
            if have < need:
                continue
            key = f"__cgate:{item}"
            if self.state.given.get(key):
                continue
            if not budget.take():
                break
            if xc3_add_item(mem, base, "precious", item, 1):
                self.state.given[key] = 1
                self.state.save()
                writes += 1
                log(f"Container batch {need} unlocked ({have} Progressive Container Access item(s) received).")
        return writes

    # ---- colony (region) affinity: the colony's affinity points are a 16-bit flag (save struct + 0x9710 + 2 * RespectFlag); levels start at Level1..Level5 points.
    # Points are held below the next level's threshold until that many "Progressive Affinity" items have arrived (0 items: level 1 max, 4 items: no cap).
    F16_BASE = 0x9710

    def _cap_affinity(self, mem, bases, counts: Dict[str, int], log: Callable[[str], None], budget: "_WriteBudget") -> int:
        writes = 0
        for name, eff in self.items.items():
            if eff["t"] != "affinity_cap":
                continue
            have = min(4, counts.get(name, 0))
            if have >= 4:
                continue
            cap = eff["levels"][have + 1] - 1
            for base in bases:
                addr = base + self.F16_BASE + 2 * eff["flag"]
                raw = mem.read(addr, 2)
                if raw is None or struct.unpack("<H", raw)[0] <= cap:
                    continue
                if not budget.take():
                    return writes
                if mem.write(addr, struct.pack("<H", cap)):
                    writes += 1
                    log(f"Delivery: {name[len('Progressive Affinity: '):]} affinity held at {cap} points ({have} of 4 level-ups received)")
        return writes

    # ---- Open World (user decision 2026-09-26): every colony starts already at max affinity - the mirror image of
    # _cap_affinity above (write UP to the Level5 threshold once, instead of holding DOWN below a cap forever).
    # One-time per validated save (self.state.given), same pattern as _open_gates/_open_container_gates: only marks
    # done once every colony actually got written, so a budget-starved or short-lived poll retries next time instead
    # of silently giving up partway through.
    #
    # LIVE BUG 2026-09-26: originally looped over every base in ok_bases (same shape as _cap_affinity above), and a
    # user's real playthrough (open_world on, "3 save copies" detected) had their ENTIRE remaining location pool
    # read as complete and the goal instantly triggered within minutes of connecting, while standing still in
    # Colony 9 - not a real completion. xc3_layout_ok (xc_inventory.py) only validates the INVENTORY arrays for a
    # candidate base; it says nothing about the flag region at F16_BASE (0x9710) this method writes into, so a
    # non-primary "copy" that merely happens to have a plausible-looking inventory can still be a stale/aliased
    # region for everything else. _cap_affinity/_cap_story share this same multi-base gap, but in practice almost
    # never actually write (a fresh save's real affinity/story state starts well below any cap, so the write is
    # usually skipped) - this method is different: the target is a max value virtually always above the current
    # one, so it writes on every base, every time, every colony, immediately - the first code path to actually
    # exercise the gap at scale. Restricting to bases[0] only, matching the already-proven-safe convention used by
    # _deliver_inventory/_watch_shops/_open_gates/_open_container_gates (see inv_base above) rather than the two
    # "cap" methods, until the multi-base case can be verified live.
    _AFFINITY_MAXED_KEY = "__open_world_affinity_maxed"

    def _max_affinity_once(self, mem, bases, log: Callable[[str], None], budget: "_WriteBudget") -> int:
        if self.state.given.get(self._AFFINITY_MAXED_KEY):
            return 0
        writes = 0
        all_done = True
        base = bases[0]
        for name, eff in self.items.items():
            if eff["t"] != "affinity_cap":
                continue
            target = eff["levels"][4]
            addr = base + self.F16_BASE + 2 * eff["flag"]
            raw = mem.read(addr, 2)
            if raw is None:
                all_done = False
                continue
            if struct.unpack("<H", raw)[0] >= target:
                continue
            if not budget.take():
                return writes
            if mem.write(addr, struct.pack("<H", target)):
                writes += 1
                log(f"Open World: {name[len('Progressive Affinity: '):]} affinity set to max ({target} points)")
            else:
                all_done = False
        if all_done:
            self.state.given[self._AFFINITY_MAXED_KEY] = 1
            self.state.save()
        return writes

    # ---- main story gate (live-verified 2026-09-22, see gen_story_gates2_xc3.py): the old approach patched an item
    # requirement onto GMK_Event map triggers, which turned out to gate ambient side content, not the story - live
    # testing proved chapters advanced with zero blocking. The real driver is QST_Purpose (QuestID 1-7 = the seven
    # chapters' own main quest, auto-advancing task by task); each gated task's progress lives in the same
    # FLD_ConditionFlag-indexed flag arrays xc_autotrack already reads (FlagType 1 = 1-bit array, FlagType 2 = 2-bit
    # array, confirmed live: 0 = not started, 1 = in progress, 2 = complete). Beat i (1-based) is held below
    # "complete" until `have >= i` Progressive Story Quest items have arrived - same cap-below-threshold shape as
    # _cap_affinity, just on quest-task state instead of a 16-bit point counter.
    def _cap_story(self, mem, bases, counts: Dict[str, int], log: Callable[[str], None], budget: "_WriteBudget") -> int:
        writes = 0
        for name, eff in self.items.items():
            if eff["t"] != "story_gate":
                continue
            have = counts.get(name, 0)
            for i, b in enumerate(eff["beats"], start=1):
                if have >= i:
                    continue
                ft, fid = b["flag_type"], b["flag_id"]
                if ft == 1:
                    flag_base, cap, byte, shift, mask = self.FLAG1_BASE, 0, fid >> 3, fid & 7, 1
                elif ft == 2:
                    flag_base, cap, byte, shift, mask = self.FLAG2_BASE, 1, fid >> 2, (fid & 3) * 2, 3
                else:
                    continue
                for base in bases:
                    addr = base + flag_base + byte
                    raw = mem.read(addr, 1)
                    if raw is None:
                        continue
                    cur = (raw[0] >> shift) & mask
                    if cur <= cap:
                        continue
                    if not budget.take():
                        return writes
                    new_byte = (raw[0] & ~(mask << shift)) | (cap << shift)
                    if mem.write(addr, bytes([new_byte])):
                        writes += 1
                        log(f"Delivery: {b['label']} held (need {i} of {len(eff['beats'])} Progressive Story Quest, have {have})")
        return writes

    # ---- Open World (user decision 2026-09-26): the whole main story is already done except the final chapter,
    # mimicking the "everything but the last fight" shape other JRPG Archipelagos use. Same QST_Purpose task flags
    # _cap_story reads/holds above, just forced UP to "complete" instead of held below it.
    #
    # Left un-touched: every beat in the LAST chapter (today: chapter 7, 8 beats) - not just "the last beat in the
    # list", because detect/xc3_story_gates2.json reuses (flag_type, flag_id) pairs across chapters (10 of 141
    # beats collide with another beat elsewhere - confirmed by inspecting the data directly, not assumed): chapter
    # 5 tasks 159/160 happen to share their exact flag with chapter 7 tasks 195/196. Forcing task 160 complete
    # would silently also flip task 196's flag - the literal last-in-list beat - defeating the whole point of
    # leaving something to fight. _final_chapter_beats() below excludes the whole final chapter AND transitively
    # follows shared flags outward, so nothing that aliases into the final chapter's flags gets force-completed
    # either (10 beats end up excluded in total for the current data, all in chapter 5 or 7).
    #
    # RISK, read before trusting this: this is a much bigger blast radius than the affinity write (141 tasks
    # across all 7 chapters, the game's real main-quest tracker, not 15 independent colony counters), and unlike
    # affinity there is no live-tested precedent for forcing this system UP rather than holding it down - I have
    # no way to run the game from this environment. I also do not know FOR CERTAIN that "chapter 7" is entirely
    # and only the final boss content, or that jumping straight to "complete" on every prior task (instead of
    # playing them in order) leaves the game in a clean state rather than a confused one (missing cutscenes/
    # character state it thinks already happened - flag reuse across chapters, just proven above, makes this a
    # real possibility, not a hypothetical one). Single base only, same lesson as the affinity bug above. Test
    # this on a save you are fully willing to lose, watch exactly where the story actually resumes, and tell me
    # if the cutoff needs to move.
    _STORY_COMPLETE_KEY = "__open_world_story_complete"

    @staticmethod
    def _final_chapter_beats(beats: list) -> set:
        """Indices to leave alone: every beat in the last chapter, plus (transitively) any other beat anywhere
        that shares its exact (flag_type, flag_id) with one of those - see the comment above for why."""
        if not beats:
            return set()
        last_chapter = max(b["chapter"] for b in beats)
        keep = {i for i, b in enumerate(beats) if b["chapter"] == last_chapter}
        changed = True
        while changed:
            changed = False
            kept_flags = {(beats[i]["flag_type"], beats[i]["flag_id"]) for i in keep}
            for i, b in enumerate(beats):
                if i not in keep and (b["flag_type"], b["flag_id"]) in kept_flags:
                    keep.add(i)
                    changed = True
        return keep

    def _story_complete_once(self, mem, bases, log: Callable[[str], None], budget: "_WriteBudget") -> int:
        if self.state.given.get(self._STORY_COMPLETE_KEY):
            return 0
        writes = 0
        all_done = True
        base = bases[0]
        for name, eff in self.items.items():
            if eff["t"] != "story_gate":
                continue
            beats = eff["beats"]
            keep = self._final_chapter_beats(beats)
            for i, b in enumerate(beats):
                if i in keep:
                    continue
                ft, fid = b["flag_type"], b["flag_id"]
                if ft == 1:
                    flag_base, target, byte, shift, mask = self.FLAG1_BASE, 1, fid >> 3, fid & 7, 1
                elif ft == 2:
                    flag_base, target, byte, shift, mask = self.FLAG2_BASE, 2, fid >> 2, (fid & 3) * 2, 3
                else:
                    continue
                addr = base + flag_base + byte
                raw = mem.read(addr, 1)
                if raw is None:
                    all_done = False
                    continue
                cur = (raw[0] >> shift) & mask
                if cur >= target:
                    continue
                # LIVE BUG 2026-09-26: a beat's flag can revert on its own right after being set (task 114's
                # flag_id=2 did, every poll, forever) - live evidence that condition-flag slots aren't
                # permanently one beat each, some get reused for other live game state (quest activation, etc.),
                # so writing one can fight whatever else currently owns that slot. Retrying forever both wastes
                # the write budget and keeps re-clobbering that other state. Try each beat exactly once; if it
                # doesn't stick, log it and leave it alone rather than hammering it every poll.
                tries_key = f"__owsc_tries:{ft}:{fid}"
                if self.state.given.get(tries_key):
                    if self.state.given[tries_key] == 1:
                        log(f"Open World: {b['label']} flag reverted after being set once - looks shared with "
                            f"other live game state, leaving it alone instead of retrying forever")
                        self.state.given[tries_key] = 2
                        self.state.save()
                    continue
                if not budget.take():
                    return writes
                new_byte = (raw[0] & ~(mask << shift)) | (target << shift)
                if mem.write(addr, bytes([new_byte])):
                    writes += 1
                    self.state.given[tries_key] = 1
                    self.state.save()
                    log(f"Open World: {b['label']} marked complete")
                else:
                    all_done = False
        if all_done:
            self.state.given[self._STORY_COMPLETE_KEY] = 1
            self.state.save()
        return writes

    def _deliver_inventory(self, mem, base: int, counts: Dict[str, int], log: Callable[[str], None], budget: "_WriteBudget") -> int:
        from .xc_inventory import xc3_add_item
        todo = [(name, eff, counts.get(name, 0) - self.state.given.get(name, 0)) for name, eff in self.items.items()
                if eff["t"] == "give" and counts.get(name, 0) > self.state.given.get(name, 0)]
        if not todo:
            return 0
        writes = 0
        for name, eff, n in todo:
            for _ in range(n):
                if not budget.take():
                    return writes
                if not xc3_add_item(mem, base, eff["kind"], eff["id"], eff.get("qty", 1)):
                    break
                self.state.given[name] = self.state.given.get(name, 0) + 1
                self.state.save()
                writes += 1
                log(f"Delivery: {name} added to the inventory")
        return writes


MULTIPLIERS = {"Xenoblade Chronicles 2": XC2GainMultiplier, "Xenoblade Chronicles 3": XC3GainMultiplier}
DELIVERERS = {"Xenoblade Chronicles 2": XC2Deliverer, "Xenoblade Chronicles 3": XC3Deliverer}
