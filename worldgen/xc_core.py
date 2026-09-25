"""Shared, data-driven engine for the Xenoblade Chronicles Archipelago worlds.

The item/location/region tables and every ``requires`` expression are ported verbatim from the community
manual apworlds. The rule compiler below reproduces the Manual framework's evaluation semantics
(``|item:N|``, ``|@category:N|``, ``{function(args)}``, AND/OR evaluated left-to-right, region ``requires``
applied to every inbound entrance *and* to the locations inside the region).
"""
from __future__ import annotations

import json
import logging
import math
import pkgutil
import re
from collections import Counter
from dataclasses import make_dataclass
from typing import Any, Callable, ClassVar, Dict, List, Optional, Set, Tuple, Type

from BaseClasses import CollectionState, Entrance, Item, ItemClassification, Location, LocationProgressType, Region
from Options import (Choice, DeathLink, DefaultOnToggle, NamedRange, Option, OptionGroup, PerGameCommonOptions, Range,
                     StartInventoryPool, Toggle)

logger = logging.getLogger("xenoblade")

VICTORY_ITEM = "__Victory__"


def load_json(package: str, name: str):
    return json.loads(pkgutil.get_data(package, f"data/{name}").decode("utf-8"))


def slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")


def to_identifier(text: str) -> str:
    """YAML-safe option key (mirrors Manual's format_to_valid_identifier closely enough for our option names)."""
    out = re.sub(r"[^0-9a-zA-Z_]", "_", text.strip())
    if out and out[0].isdigit():
        out = "_" + out
    return out


# --------------------------------------------------------------------------------------------------------------------
# Option construction
# --------------------------------------------------------------------------------------------------------------------

class FillerTrapPercent(Range):
    """How many filler items are replaced with traps. 0 = no traps, 100 = every filler is a trap."""
    display_name = "Filler Trap Percentage"
    range_start = 0
    range_end = 100
    default = 0


class ExperienceMultiplier(Range):
    """Multiplies experience-type gains (EXP, skill points, weapon/AP-style points) while you play, so runs move faster.
    1 = normal. The client applies it live to whatever the game awards; it never changes what you spend."""
    display_name = "Experience Multiplier"
    range_start = 1
    range_end = 50
    default = 1


def build_options(game_cfg: dict, victory_names: List[str]) -> Tuple[Type[PerGameCommonOptions], Dict[str, list]]:
    opts: Dict[str, Type[Option]] = {}
    groups: Dict[str, list] = {}

    opts["start_inventory_from_pool"] = StartInventoryPool

    if len(victory_names) > 1:
        goal_dict = {"option_" + slug(v): i for i, v in enumerate(victory_names)}
        goal_dict["display_name"] = "Goal"
        goal_dict["__module__"] = __name__
        goal_dict["__doc__"] = "Choose the victory condition for this world."
        goal_dict["default"] = game_cfg.get("default_goal", 0)
        opts["goal"] = type("goal", (Choice,), goal_dict)

    if game_cfg.get("has_traps"):
        opts["filler_traps"] = FillerTrapPercent

    if game_cfg.get("game") in ("Xenoblade Chronicles 2", "Xenoblade Chronicles 3"):
        opts["experience_multiplier"] = ExperienceMultiplier

    from .qol import QOL                                   # randomizer-backed quality-of-life options (see qol.py)
    for key, kind, title, doc, default, rng, _builder in QOL.get(game_cfg.get("game"), []):
        if kind == "toggle":
            opts[key] = type(key, (DefaultOnToggle if default else Toggle,), {"display_name": title, "__doc__": doc, "__module__": __name__})
        else:
            opts[key] = type(key, (Range,), {"display_name": title, "__doc__": doc, "range_start": rng[0], "range_end": rng[1],
                                             "default": default, "__module__": __name__})
        groups.setdefault("Quality of Life", []).append(opts[key])

    if game_cfg.get("death_link"):
        opts["death_link"] = DeathLink

    for name, spec in game_cfg.get("options", {}).items():
        kind = spec["type"]
        key = to_identifier(name)
        args: Dict[str, Any] = {"display_name": spec.get("display_name", name), "__module__": __name__}
        if kind == "Toggle":
            base: Type[Option] = DefaultOnToggle if spec.get("default") else Toggle
        elif kind == "Choice":
            base = Choice
            for label, val in spec["values"].items():
                args["option_" + to_identifier(label).lower()] = val
            args["default"] = spec.get("default", 0)
        elif kind == "Range":
            args["range_start"] = spec["range_start"]
            args["range_end"] = spec["range_end"]
            args["default"] = spec.get("default", spec["range_start"])
            if spec.get("values"):
                base = NamedRange
                args["special_range_names"] = {to_identifier(k).lower(): v for k, v in spec["values"].items()}
            else:
                base = Range
        else:
            raise ValueError(f"unsupported option type {kind}")
        opts[key] = type(key, (base,), {**args, "__doc__": "\n".join(spec.get("description", [name])) if isinstance(spec.get("description"), list) else spec.get("description", name)})
        if spec.get("group"):
            groups.setdefault(spec["group"], []).append(opts[key])

    # category toggles: every yaml_option referenced by a category becomes a DefaultOnToggle
    for cat, cdata in game_cfg.get("categories", {}).items():
        for raw in cdata.get("yaml_option", []):
            name = raw[1:] if raw.startswith("!") else raw
            key = to_identifier(name)
            if key not in opts:
                opts[key] = type(key, (DefaultOnToggle,), {
                    "display_name": game_cfg.get("toggle_names", {}).get(name, name),
                    "__doc__": game_cfg.get("toggle_docs", {}).get(name, "Include the locations and items linked to this option."),
                    "__module__": __name__})
                groups.setdefault("Location Categories", []).append(opts[key])

    dc = make_dataclass("XenobladeOptions", list(opts.items()), bases=(PerGameCommonOptions,))
    return dc, groups


# --------------------------------------------------------------------------------------------------------------------
# Item / Location classes
# --------------------------------------------------------------------------------------------------------------------

class XCItem(Item):
    game = ""  # filled per world


class XCLocation(Location):
    game = ""


def classification_of(entry: dict) -> ItemClassification:
    cls = ItemClassification.filler
    if entry.get("trap"):
        cls |= ItemClassification.trap
    if entry.get("useful"):
        cls |= ItemClassification.useful
    if entry.get("progression_skip_balancing"):
        cls |= ItemClassification.progression_skip_balancing
    elif entry.get("progression"):
        cls |= ItemClassification.progression
    return cls


# --------------------------------------------------------------------------------------------------------------------
# Rule compiler
# --------------------------------------------------------------------------------------------------------------------

_TOKEN = re.compile(r"\|[^|]*\||§\d+§|\(|\)|\bAND\b|\bOR\b|\b[01]\b", re.IGNORECASE)
_FUNC = re.compile(r"\{(\w+)\((.*?)\)\}")
Rule = Callable[[CollectionState], bool]


class RuleCompiler:
    """Compiles Manual 'requires' strings into fast closures for one world instance."""

    MAX_DEPTH = 5

    def __init__(self, world, functions: Dict[str, Callable]):
        self.world = world
        self.player = world.player
        self.functions = functions
        self._cache: Dict[str, Optional[Rule]] = {}
        self.unknown_refs: Set[str] = set()

    # -- public ------------------------------------------------------------------------------------------------------
    def compile(self, text: str, label: str = "") -> Optional[Rule]:
        """Return a rule closure, or None when the expression is always true."""
        if text is None:
            return None
        text = text.strip()
        if text == "":
            return None
        if text in self._cache:
            return self._cache[text]
        node = self._compile_text(text, label, 0)
        rule: Optional[Rule]
        if node is True:
            rule = None
        elif node is False:
            rule = lambda state: False
        else:
            rule = node
        self._cache[text] = rule
        return rule

    # -- expansion of {functions} -------------------------------------------------------------------------------------
    def _expand(self, text: str, label: str, depth: int, dynamic: List[Rule]) -> str:
        if depth > self.MAX_DEPTH:
            raise RecursionError(f"requires of '{label}' expands functions too deeply: {text}")
        found = _FUNC.findall(text)
        if not found:
            return text
        for fname, fargs in found:
            fn = self.functions.get(fname)
            if fn is None:
                raise ValueError(f"unknown rule function '{fname}' in '{label}'")
            result = fn(self.world, fargs.strip())
            token = "{" + fname + "(" + fargs + ")}"
            if isinstance(result, bool):
                rep = "1" if result else "0"
            elif isinstance(result, str):
                rep = "(" + result + ")" if result.strip() else "1"
            elif callable(result):
                dynamic.append(result)
                rep = f"§{len(dynamic) - 1}§"
            else:
                raise TypeError(f"function {fname} returned {type(result)}")
            text = text.replace(token, rep)
        return self._expand(text, label, depth + 1, dynamic)

    def _compile_text(self, text: str, label: str, depth: int):
        dynamic: List[Rule] = []
        text = self._expand(text, label, depth, dynamic)
        tokens = _TOKEN.findall(text)
        leftover = _TOKEN.sub("", text)
        if leftover.strip():
            raise ValueError(f"unparsable text {leftover.strip()!r} in requires of '{label}': {text}")
        pos = 0

        def parse_operand():
            nonlocal pos
            if pos >= len(tokens):
                raise ValueError(f"unexpected end of expression in '{label}'")
            tok = tokens[pos]
            pos += 1
            if tok == "(":
                node = parse_expr()
                if pos < len(tokens) and tokens[pos] == ")":
                    pos += 1
                elif pos < len(tokens):
                    raise ValueError(f"unbalanced parentheses in '{label}'")
                # else: missing ')' at the very end - the manual engine implicitly closes it, so do we
                return node
            if tok in ("0", "1"):
                return tok == "1"
            if tok.startswith("§"):
                return dynamic[int(tok[1:-1])]
            if tok.startswith("|"):
                return self._atom(tok, label)
            raise ValueError(f"unexpected token {tok!r} in '{label}'")

        def parse_expr():
            nonlocal pos
            left = parse_operand()
            while pos < len(tokens) and tokens[pos].upper() in ("AND", "OR"):
                op = tokens[pos].upper()
                pos += 1
                right = parse_operand()
                left = self._combine(op, left, right)
            return left

        node = parse_expr()
        if pos != len(tokens):
            raise ValueError(f"trailing tokens in requires of '{label}': {tokens[pos:]}")
        return node

    @staticmethod
    def _combine(op: str, a, b):
        if op == "AND":
            if a is False or b is False:
                return False
            if a is True:
                return b
            if b is True:
                return a
            parts = (a.parts if getattr(a, "kind", None) == "AND" else [a]) + (b.parts if getattr(b, "kind", None) == "AND" else [b])

            def and_rule(state, parts=tuple(parts)):
                for p in parts:
                    if not p(state):
                        return False
                return True
            and_rule.kind = "AND"
            and_rule.parts = list(parts)
            return and_rule
        else:
            if a is True or b is True:
                return True
            if a is False:
                return b
            if b is False:
                return a
            parts = (a.parts if getattr(a, "kind", None) == "OR" else [a]) + (b.parts if getattr(b, "kind", None) == "OR" else [b])

            def or_rule(state, parts=tuple(parts)):
                for p in parts:
                    if p(state):
                        return True
                return False
            or_rule.kind = "OR"
            or_rule.parts = list(parts)
            return or_rule

    # -- atoms ---------------------------------------------------------------------------------------------------------
    def _atom(self, token: str, label: str):
        inner = token.strip("|")
        is_cat = inner.startswith("@")
        inner = inner.lstrip("@$")
        name, _, count = inner.partition(":")
        name = name.strip()
        count = count.strip() or "1"
        w = self.world
        player = self.player
        if is_cat:
            members = w.category_members(name)
            if not members:
                self.unknown_refs.add("@" + name)
            total = sum(w.progression_counts.get(m, 0) for m in members)
            n = self._resolve_count(count, total, label)
            if not members:
                return False
            if n <= 0:
                return True
            if len(members) == 1:
                only = members[0]
                return lambda state, only=only, n=n: state.count(only, player) >= n
            names = tuple(members)
            return lambda state, names=names, n=n: state.has_from_list(names, player, n)
        if w.skill_logic and name in w.xc.skills["skills"]:
            n = int(count) if count.isdigit() else 1
            return True if n <= 0 else w.skill_rule(name, n)
        total = w.progression_counts.get(name, 0)
        n = self._resolve_count(count, total, label)
        if n <= 0:
            return True
        if name not in w.item_name_to_id and name not in w.event_names:
            self.unknown_refs.add(name)
            return False
        return lambda state, name=name, n=n: state.count(name, player) >= n

    @staticmethod
    def _resolve_count(count: str, total: int, label: str) -> int:
        c = count.lower()
        if c == "all":
            return total
        if c == "half":
            return int(total / 2)
        if c.endswith("%") and len(c) > 1:
            pct = max(0.0, min(1.0, float(c[:-1]) / 100))
            return math.ceil(total * pct)
        try:
            return int(c)
        except ValueError as ex:
            raise ValueError(f"bad count {count!r} in requires of '{label}'") from ex


# --------------------------------------------------------------------------------------------------------------------
# Generic world behaviour (mixin; concrete worlds combine it with worlds.AutoWorld.World)
# --------------------------------------------------------------------------------------------------------------------

class XCData:
    """Parsed, immutable data bundle shared by a world class and its instances."""

    def __init__(self, package: str):
        self.package = package
        self.cfg = load_json(package, "game.json")
        self.items: List[dict] = load_json(package, "items.json")
        self.locations: List[dict] = load_json(package, "locations.json")
        self.regions: Dict[str, dict] = load_json(package, "regions.json")
        self.events: List[dict] = load_json(package, "events.json")
        self.game: str = self.cfg["game"]
        self.filler_name: str = self.cfg["filler"]

        try:                                                 # optional: blades -> field skill levels (XC2, see xc2_skills.py)
            self.skills: Optional[dict] = load_json(package, "skills.json")
        except Exception:
            self.skills = None

        self.item_by_name = {i["name"]: i for i in self.items}
        self.loc_by_name = {l["name"]: l for l in self.locations}
        self.victory_names = [l["name"] for l in self.locations if l.get("victory")]
        self.item_name_to_id: Dict[str, int] = {i["name"]: i["id"] for i in self.items}
        self.location_name_to_id: Dict[str, int] = {l["name"]: l["id"] for l in self.locations if not l.get("victory")}
        self.event_names = {e["name"] for e in self.events}

        self.item_groups: Dict[str, Set[str]] = {}
        for i in self.items:
            for c in i.get("category", []):
                self.item_groups.setdefault(c, set()).add(i["name"])
        self.location_groups: Dict[str, Set[str]] = {}
        for l in self.locations:
            if l.get("victory"):
                continue
            for c in l.get("category", []):
                self.location_groups.setdefault(c, set()).add(l["name"])
        # group names may not collide with item / location names
        for g in list(self.item_groups):
            if g in self.item_name_to_id:
                self.item_groups[g + " (group)"] = self.item_groups.pop(g)
        for g in list(self.location_groups):
            if g in self.location_name_to_id:
                self.location_groups[g + " (group)"] = self.location_groups.pop(g)

        self.options_dataclass, self.option_groups = build_options(self.cfg, self.victory_names)


class XCMixin:
    """Behaviour shared by all Xenoblade worlds. The concrete class supplies ``xc`` (XCData) and rule functions."""

    xc: ClassVar[XCData]
    rule_functions: ClassVar[Dict[str, Callable]] = {}
    topology_present = False

    # ---- helpers ---------------------------------------------------------------------------------------------------
    def opt(self, name: str, default: int = 0) -> int:
        option = getattr(self.options, to_identifier(name), None)
        return default if option is None else option.value

    def opt_on(self, name: str) -> bool:
        return self.opt(name) > 0

    def category_enabled(self, category: str) -> bool:
        hook = getattr(self, "category_override", None)
        if hook is not None:
            res = hook(category)
            if res is not None:
                return res
        data = self.xc.cfg.get("categories", {}).get(category)
        if not data:
            return True
        choice = data.get("choice")                          # {"option": name, "values": [allowed values]} for Choice options
        if choice and self.opt(choice["option"]) not in choice["values"]:
            return False
        for raw in data.get("yaml_option", []):
            want = True
            name = raw
            if raw.startswith("!"):
                name, want = raw[1:], False
            if self.opt_on(name) != want:
                return False
        return True

    def entry_enabled(self, entry: dict) -> bool:
        return all(self.category_enabled(c) for c in entry.get("category", []))

    def category_members(self, category: str) -> List[str]:
        if not hasattr(self, "_cat_cache"):
            self._cat_cache: Dict[str, List[str]] = {}
        if category not in self._cat_cache:
            names = [i["name"] for i in self.xc.items if category in i.get("category", [])]
            names += [e["name"] for e in self.xc.events if category in e.get("category", [])]
            self._cat_cache[category] = names
        return self._cat_cache[category]

    @property
    def event_names(self) -> Set[str]:
        return self.xc.event_names

    # ---- field skills derived from blades (XC2) ----------------------------------------------------------------------
    @property
    def skill_logic(self) -> bool:
        return self.xc.skills is not None and self.opt_on("field_skill_logic")

    def _prepare_skills(self) -> None:
        """Per-skill tables for field_level(): [(blade item, trust item | None, driver | None, slot group | None, [level per heart])]."""
        m = self.xc.skills
        self._skill_blades: Dict[str, list] = {s: [] for s in m["skills"]}
        for name, b in m["blades"].items():
            for skill, levels in b["levels"].items():
                self._skill_blades[skill].append((name, b["trust"], b["driver"], b["group"], levels))
        self._slots = max(1, self.opt("blade_slots_per_driver", 3))
        self._party_seats = 2                                # Rex + two more drivers
        if not self.opt_on("progressive_blade_trust"):
            self._trust_mode = 0                             # hearts are levelled freely: assume all 5
        elif self.opt_on("trust_per_blade"):
            self._trust_mode = 2
        else:
            self._trust_mode = 1

    def field_level(self, state: CollectionState, skill: str) -> int:
        """Best level of a field skill the party can field: the blades received, at the trust hearts the trust items allow, in the
        slots (blade_slots_per_driver each) of Rex and the two best drivers received.  Blades that only one driver can equip need that driver."""
        p = self.player
        count = state.count
        mode = self._trust_mode
        if mode == 1:
            g_hearts = 1 + min(4, count("Progressive Blade Trust", p))
        flex: List[int] = []
        groups: Dict[tuple, int] = {}
        for name, trust, driver, group, levels in self._skill_blades[skill]:
            if not count(name, p):
                continue
            if mode == 0:
                hearts = 5
            elif mode == 1:
                hearts = g_hearts
            else:
                hearts = 5 if trust is None else 1 + min(4, count(trust, p))
            v = levels[hearts - 1]
            if v <= 0:
                continue
            if group is None:
                flex.append(v)
            else:
                key = (driver, group)
                if v > groups.get(key, 0):
                    groups[key] = v
        if not flex and not groups:
            return 0
        flex.sort(reverse=True)
        avail = [d for d in self.xc.skills["drivers"] if count(d, p)]
        excl_drivers = sorted({d for (d, _g) in groups if d is not None and d in avail})
        generic = len(avail) - len(excl_drivers)
        seats, slots = self._party_seats, self._slots
        best = 0
        # every choice of which exclusive-blade drivers join the party (the rest of the seats go to drivers without such blades)
        from itertools import combinations
        for r in range(0, min(seats, len(excl_drivers)) + 1):
            for chosen in combinations(excl_drivers, r):
                n_party = 1 + r + min(seats - r, generic)
                vals = flex + [v for (d, _g), v in groups.items() if d is None or d in chosen]
                vals.sort(reverse=True)
                total = sum(vals[:n_party * slots])
                if total > best:
                    best = total
        return best

    def skill_rule(self, skill: str, n: int) -> Rule:
        return lambda state, skill=skill, n=n: self.field_level(state, skill) >= n

    # ---- generation ------------------------------------------------------------------------------------------------
    # Universal Tracker: the world can be regenerated from slot data alone
    ut_can_gen_without_yaml = True

    @staticmethod
    def interpret_slot_data(slot_data: Dict[str, Any]) -> Dict[str, Any]:
        return slot_data

    def _restore_options_from_slot_data(self) -> None:
        passthrough = getattr(self.multiworld, "re_gen_passthrough", None)
        if not passthrough or self.game not in passthrough:
            return
        slot = passthrough[self.game]
        for key in self.options_dataclass.type_hints:
            if key in slot and hasattr(getattr(self.options, key, None), "value"):
                try:
                    getattr(self.options, key).value = slot[key]
                except Exception:  # pragma: no cover
                    pass

    def generate_early(self) -> None:
        self._restore_options_from_slot_data()
        self.progression_counts: Counter = Counter()
        self.enabled_locations: List[dict] = []
        self.active_goal_name: Optional[str] = None
        if self.xc.victory_names:
            idx = self.opt("goal") if len(self.xc.victory_names) > 1 else 0
            self.active_goal_name = self.xc.victory_names[idx]
        if self.skill_logic:
            self._prepare_skills()
        hook = getattr(self, "early_hook", None)
        if hook:
            hook()

    def create_regions(self) -> None:
        xc = self.xc
        regions: Dict[str, Region] = {}
        menu = Region("Menu", self.player, self.multiworld)
        regions["Menu"] = menu
        manual = Region("Manual", self.player, self.multiworld)
        regions["Manual"] = manual
        for name in xc.regions:
            regions[name] = Region(name, self.player, self.multiworld)

        for loc in xc.locations:
            if loc.get("victory"):
                continue
            if not self.entry_enabled(loc):
                continue
            region = regions[loc["region"]]
            location = XCLocation(self.player, loc["name"], loc["id"], region)
            location.game = xc.game
            if loc.get("exclude"):
                location.progress_type = LocationProgressType.EXCLUDED
            region.locations.append(location)
            self.enabled_locations.append(loc)

        # events (locked, progression, address-less)
        for ev in xc.events:
            if not self.entry_enabled(ev):
                continue
            region = regions[ev.get("region", "Manual")]
            location = XCLocation(self.player, ev.get("location_name", f"{ev['name']} (event)"), None, region)
            item = XCItem(ev["name"], ItemClassification.progression, None, self.player)
            item.game = xc.game
            location.game = xc.game
            location.place_locked_item(item)
            region.locations.append(location)

        # goal
        goal = xc.loc_by_name[self.active_goal_name]
        goal_region = regions[goal.get("region", "Manual")]
        goal_loc = XCLocation(self.player, goal["name"], None, goal_region)
        goal_loc.game = xc.game
        victory = XCItem(VICTORY_ITEM, ItemClassification.progression, None, self.player)
        victory.game = xc.game
        goal_loc.place_locked_item(victory)
        goal_region.locations.append(goal_loc)

        # connections: Menu -> Manual -> starting regions; region graph as authored
        starting = [n for n, r in xc.regions.items() if r.get("starting")] or list(xc.regions)
        menu.connect(manual, "MenuToManual")
        for n in starting:
            manual.connect(regions[n], f"ManualTo{n}")
        for name, r in xc.regions.items():
            for target in r.get("connects_to", []) or []:
                regions[name].connect(regions[target], f"{name}To{target}")

        self.multiworld.regions.extend(regions.values())
        self.region_map = regions

    def create_item(self, name: str, class_override: Optional[ItemClassification] = None) -> Item:
        entry = self.xc.item_by_name[name]
        cls = class_override if class_override is not None else classification_of(entry)
        item = XCItem(name, cls, self.xc.item_name_to_id[name], self.player)
        item.game = self.xc.game
        return item

    def get_filler_item_name(self) -> str:
        """Games with real filler pools ("Filler <kind>" item categories) draw a kind, then an item of that kind; else the plain filler."""
        kinds = sorted(g for g in self.xc.item_groups if g.startswith("Filler "))
        if not kinds:
            return self.xc.filler_name
        return self.random.choice(sorted(self.xc.item_groups[self.random.choice(kinds)]))

    def create_items(self) -> None:
        xc = self.xc
        pool: List[Item] = []
        traps: List[str] = []
        for entry in xc.items:
            name = entry["name"]
            if name == xc.filler_name:
                continue
            if entry.get("trap"):
                traps.append(name)
            if not self.entry_enabled(entry):
                continue
            for _ in range(int(entry.get("count", 1))):
                pool.append(self.create_item(name))

        hook = getattr(self, "pool_hook", None)
        if hook:
            pool = hook(pool)

        n_locations = len([l for l in self.multiworld.get_unfilled_locations(self.player)])
        extras = n_locations - len(pool)
        if extras > 0:
            trap_pct = self.opt("filler_traps") if traps else 0
            trap_count = extras * trap_pct // 100
            for _ in range(trap_count):
                pool.append(self.create_item(self.random.choice(traps)))
            for _ in range(extras - trap_count):
                pool.append(self.create_item(self.get_filler_item_name()))
        elif extras < 0:
            logger.warning("%s has more items than locations; removing %d non-progression items", xc.game, -extras)
            removable = [i for i in pool if not i.advancement]
            order = {ItemClassification.filler: 0, ItemClassification.trap: 1, ItemClassification.useful: 2}
            self.random.shuffle(removable)
            removable.sort(key=lambda i: order.get(i.classification, 3))
            for it in removable[:-extras]:
                pool.remove(it)
            if len(pool) > n_locations:
                raise Exception(f"{xc.game}: too many progression items ({len(pool)}) for {n_locations} locations")

        # "excluded" locations may only hold filler; if the pool has too little filler (small worlds, many fragments, ...)
        # the surplus excluded locations are returned to normal priority so the fill can always complete
        excluded = [l for l in self.multiworld.get_locations(self.player)
                    if l.progress_type == LocationProgressType.EXCLUDED and l.address is not None]
        junk = sum(1 for i in pool if not i.advancement and not (i.classification & ItemClassification.useful))
        if len(excluded) > junk:
            logger.warning("%s: only %d filler items for %d excluded locations; %d location(s) lose their 'excluded' status",
                           xc.game, junk, len(excluded), len(excluded) - junk)
            for l in excluded[junk:]:
                l.progress_type = LocationProgressType.DEFAULT

        # progression counts drive ALL / half / % requirements and are needed by the rule compiler
        self.progression_counts = Counter(i.name for i in pool if i.advancement)
        for it in self.multiworld.precollected_items[self.player]:
            if it.advancement:
                self.progression_counts[it.name] += 1
        self.multiworld.itempool += pool

    def set_rules(self) -> None:
        xc = self.xc
        compiler = RuleCompiler(self, self.rule_functions)
        self.rule_compiler = compiler
        p = self.player
        region_rules: Dict[str, Optional[Rule]] = {}
        for name, r in xc.regions.items():
            region_rules[name] = compiler.compile(r.get("requires", ""), name)

        from worlds.generic.Rules import add_rule, set_rule
        for name, r in xc.regions.items():
            rule = region_rules[name]
            if rule is None:
                continue
            for ent in self.region_map[name].entrances:
                add_rule(ent, rule)

        for region_name, region in self.region_map.items():
            rrule = region_rules.get(region_name)
            for location in region.locations:
                entry = xc.loc_by_name.get(location.name)
                lrule = compiler.compile(entry.get("requires", ""), entry["name"]) if entry else None
                if lrule is not None and rrule is not None:
                    set_rule(location, (lambda state, a=lrule, b=rrule: a(state) and b(state)))
                elif lrule is not None:
                    set_rule(location, lrule)
                elif rrule is not None:
                    set_rule(location, rrule)

        hook = getattr(self, "rules_hook", None)
        if hook:
            hook(compiler)

        if compiler.unknown_refs:
            logger.warning("%s: rules reference items that do not exist: %s", xc.game, sorted(compiler.unknown_refs))

        self.multiworld.completion_condition[p] = lambda state: state.has(VICTORY_ITEM, p)


    def pre_fill(self) -> None:
        """Self-check: with every progression item in hand, report anything that is still unreachable."""
        try:
            state = self.multiworld.get_all_state(False)
        except Exception:  # pragma: no cover
            return
        bad_regions = [r.name for r in self.region_map.values() if not r.can_reach(state)]
        unreachable = [l.name for r in self.region_map.values() for l in r.locations
                       if l.address is not None and not l.can_reach(state)]
        if bad_regions or unreachable:
            logger.warning("%s logic self-check: %d unreachable regions %s, %d unreachable locations (first: %s)",
                           self.xc.game, len(bad_regions), bad_regions[:8], len(unreachable), unreachable[:6])
            if getattr(self, "_debug", False):
                for name in unreachable[:12]:
                    entry = self.xc.loc_by_name[name]
                    logger.warning("   %s | region=%s | requires=%s", name, entry["region"], entry.get("requires", "")[:200])

    def generate_basic(self) -> None:
        xc = self.xc
        for loc in self.enabled_locations:
            names = loc.get("place_item")
            if not names:
                continue
            location = self.multiworld.get_location(loc["name"], self.player)
            candidates = [i for i in self.multiworld.itempool if i.player == self.player and i.name in names]
            if not candidates:
                raise Exception(f"{xc.game}: no item from {names} available to place at '{loc['name']}'")
            chosen = self.random.choice(candidates)
            location.place_locked_item(chosen)
            self.multiworld.itempool.remove(chosen)

    def shop_labels(self) -> Dict[str, List[str]]:
        """{shop table id: [text shown for each slot]}: the multiworld item behind every shop check (shown in the game's shop list)."""
        try:
            import pkgutil
            shops = json.loads(pkgutil.get_data(self.xc.package, "data/shops.json").decode("utf-8"))["shops"]
        except Exception:
            return {}
        mode = self.opt("shop_checks")
        if mode not in (1, 2):
            return {}

        width = int(self.xc.cfg.get("shop_label_width", 28))

        def fit(text: str, w: int) -> str:
            return text if len(text) <= w else text[:w - 1] + "~"

        def label(location_name: str) -> str:
            loc = self.multiworld.get_location(location_name, self.player)
            item = loc.item
            if item is None:
                return "Nothing"
            name = item.name
            for prefix in ("Pouch: ", "Accessory: ", "Gem: "):        # the shop list is narrow: drop the filler prefixes
                if name.startswith(prefix):
                    name = name[len(prefix):]
            if item.player != self.player:
                name = f"{name} ({self.multiworld.get_player_name(item.player)})"
            return name

        def distinct(texts: List[str]) -> List[str]:
            """Every slot of a shop must read differently (the game cuts long names): repeats get a counter in front, before the cut."""
            seen: Dict[str, int] = {}
            out_l = []
            for t in texts:
                shown = fit(t, width)
                seen[shown] = seen.get(shown, 0) + 1
                if seen[shown] > 1:
                    shown = f"{seen[shown]}) " + fit(t, width - len(f"{seen[shown]}) "))
                out_l.append(shown)
            return out_l

        out: Dict[str, List[str]] = {}
        for shop in shops:
            if mode == 1:
                out[str(shop["table"])] = [fit(label(f"Shop {shop['name']}"), width)] * len(shop["slots"])
            else:
                out[str(shop["table"])] = distinct([label(f"Shop {shop['name']} #{k}") for k in range(1, len(shop["slots"]) + 1)])
        return out

    def fill_slot_data(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"goal": self.active_goal_name}
        if hasattr(self.options, "shop_checks"):
            data["shop_labels"] = self.shop_labels()
        common = set(PerGameCommonOptions.type_hints)
        for key in self.options_dataclass.type_hints:
            if key in common:
                continue
            data[key] = getattr(self.options, key).value
        data["death_link"] = bool(getattr(getattr(self.options, "death_link", None), "value", 0))
        data["world_version"] = self.xc.cfg.get("world_version", "0.1.0")
        hook = getattr(self, "slot_data_hook", None)
        if hook:
            data = hook(data)
        return data

    def generate_output(self, output_directory: str) -> None:
        """Per-player patch file (settings for the game-data mod); opened with the '<game> Patcher' launcher component."""
        from .xc_patch import write_patch_file
        write_patch_file(self, output_directory)
