"""Cross-check the tracker's Lua field skill evaluator (trackergen/lua/xc_logic.lua) against the world's Python one (xc_core.XCMixin.field_level).

Random received-item sets are evaluated by both; any mismatch is printed.  usage: python check_skill_logic.py [rounds]
"""
import json
import random
import sys
import types

import lupa

ROOT = r"G:\Archipelago\xc-tools"
sys.path.insert(0, ROOT + r"\worldgen")
DATA = json.load(open(ROOT + r"\worldgen\detect\xc2_skills.json", encoding="utf-8"))

# ---- Python side: the real method bound to a stand-in world --------------------------------------------------------------------
import importlib.util



class _Stub(types.ModuleType):
    """Stand-in for Archipelago's BaseClasses / Options: every name is an empty class (enough to import xc_core)."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        cls = type(name, (), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


for mod in ("BaseClasses", "Options"):
    sys.modules[mod] = _Stub(mod)
spec = importlib.util.spec_from_file_location("xc_core_test", ROOT + r"\worldgen\xc_core.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class FakeState:
    def __init__(self, have):
        self.have = have

    def count(self, name, player):
        return self.have.get(name, 0)


def make_world(mode, slots):
    w = types.SimpleNamespace()
    w.player = 1
    w.xc = types.SimpleNamespace(skills=DATA)
    w._trust_mode, w._slots, w._party_seats = mode, slots, 2
    w._skill_blades = {s: [] for s in DATA["skills"]}
    for name, b in DATA["blades"].items():
        for skill, levels in b["levels"].items():
            w._skill_blades[skill].append((name, b["trust"], b["driver"], b["group"], levels))
    return w


def main(rounds):
    src = open(ROOT + r"\trackergen\lua\xc_logic.lua", encoding="utf-8").read()
    rnd = random.Random(7)
    all_items = list(DATA["blades"]) + DATA["drivers"]
    bad = 0
    for r in range(rounds):
        mode = rnd.choice([0, 1, 2])
        slots = rnd.choice([1, 2, 3])
        have = {}
        for it in all_items:
            if rnd.random() < rnd.choice([0.2, 0.5, 0.9]):
                have[it] = 1
        have["Progressive Blade Trust"] = rnd.randint(0, 4)
        for b in DATA["blades"].values():
            if b["trust"]:
                have[b["trust"]] = rnd.randint(0, 4)
        opts = {"progressive_blade_trust": 0 if mode == 0 else 1, "trust_per_blade": 1 if mode == 2 else 0, "blade_slots_per_driver": slots,
                "field_skill_logic": 1}
        w = make_world(mode, slots)
        expect = {s: core.XCMixin.field_level(w, FakeState(have), s) for s in DATA["skills"]}

        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        lua.execute("XC = {}; XC.funcs = {}; XC.opts = {}; XC.events_have = {}")
        # data as a Lua chunk (same shape as the tracker's logic_data.lua)
        sys.path.insert(0, ROOT + r"\trackergen")
        import common
        codes = {k: "c_" + k for k in list(DATA["blades"]) + DATA["drivers"] + ["Progressive Blade Trust"] +
                 [b["trust"] for b in DATA["blades"].values() if b["trust"]]}
        data = {"codes": codes, "pool": {}, "cats": {}, "regions": {}, "start": [], "events": [], "event_names": {}, "locs": {}, "opts": opts,
                "skills": DATA}
        lua.execute("XC_DATA = " + common.lua_val(data))
        lua.execute("Tracker = {}; ScriptHost = {AddOnFrameHandler = function() end, AddWatchForCode = function() end}")
        code_have = {"c_" + k: v for k, v in have.items()}
        lua.globals().HAVE = lua.table_from(code_have)
        lua.execute("function Tracker:ProviderCountForCode(c) return HAVE[c] or 0 end")
        lua.execute(src)
        got = {s: lua.eval(f"XC.field_level({json.dumps(s)})") for s in DATA["skills"]}
        if got != expect:
            bad += 1
            diff = {s: (expect[s], got[s]) for s in expect if expect[s] != got[s]}
            print("MISMATCH round", r, "mode", mode, "slots", slots, diff)
    print(f"{rounds - bad}/{rounds} rounds agree")


main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
