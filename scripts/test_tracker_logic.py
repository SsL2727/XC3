"""Compare the tracker's Lua logic engine (xc_logic.lua + generated data) with an independent Python reference on random inventories.

usage: python test_tracker_logic.py <pack.zip> <world data dir> [n_states]
"""
import json
import math
import random
import re
import sys
import zipfile

import lupa

PACK, WORLD = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 60
zf = zipfile.ZipFile(PACK)
items = json.load(open(WORLD + "/items.json", encoding="utf-8"))
locations = json.load(open(WORLD + "/locations.json", encoding="utf-8"))
regions = json.load(open(WORLD + "/regions.json", encoding="utf-8"))
events = json.load(open(WORLD + "/events.json", encoding="utf-8"))

# ---------------------------------------------------------------------------------------------------- Lua side
lua = lupa.LuaRuntime(unpack_returned_tuples=True)
counts = {}
lua.execute("""
function make_tracker(getcount)
  Tracker = { ProviderCountForCode = function(self, code) return getcount(code) end }
  ScriptHost = { AddOnFrameHandler = function() end, AddWatchForCode = function() end }
end
""")
lua.globals().make_tracker(lambda code: counts.get(code, 0))
for name in ("scripts/logic_data.lua", "scripts/xc_logic.lua", "scripts/game_logic.lua"):
    lua.execute(zf.read(name).decode("utf-8"))

data = lua.globals().XC_DATA
codes = {k: v for k, v in data.codes.items()}
pool = {k: v for k, v in data.pool.items()}
idx_of = {}
for i, l in data.locs.items():
    idx_of[l.name] = i

# ---------------------------------------------------------------------------------------------- Python reference
ITEM = {i["name"]: i for i in items}
CATS = {}
for i in items:
    for c in i["category"]:
        CATS.setdefault(c, []).append(i["name"])
for e in events:
    for c in e.get("category", []):
        CATS.setdefault(c, []).append(e["name"])

opts = {k: v for k, v in data.opts.items()}
REGION_LEVELS = None
if "hasDangerTolerance" in zf.read("scripts/game_logic.lua").decode():
    REGION_LEVELS = [(7, "Colony 9"), (12, "Tephra Cave"), (25, "Bionis' Leg"), (26, "Colony 6"), (27, "Ether Mine"), (28, "Satorl Marsh"),
                     (32, "Bionis' Interior (1st Visit)"), (34, "Makna Forest"), (36, "Frontier Village"), (37, "Eryth Sea"), (37, "Alcamoth"),
                     (38, "High Entia Tomb"), (42, "Prison Island (1st Visit)"), (48, "Valak Mountain"), (52, "Sword Valley"),
                     (55, "Galahad Fortress"), (58, "Fallen Arm"), (60, "Mechonis Field"), (65, "Central Factory"), (70, "Agniratha"),
                     (72, "Mechonis Core"), (75, "Bionis' Interior (2nd Visit)"), (80, "Prison Island (2nd Visit)")]


def ref_expand(text):
    def fn(m):
        name, args = m.group(1), m.group(2).strip()
        if name == "YamlEnabled":
            return "1" if opts.get(args, 0) else "0"
        if name == "YamlDisabled":
            return "0" if opts.get(args, 0) else "1"
        if name == "YamlCompare":
            mm = re.match(r"\s*(!?)([A-Za-z0-9_]+)\s*(==|!=|>=|<=|=|<|>)\s*(.+?)\s*$", args)
            neg, nm, op, val = mm.groups()
            cur = opts.get(nm, 0)
            t = int(val)
            r = {"==": cur == t, "=": cur == t, "!=": cur != t, ">=": cur >= t, "<=": cur <= t, "<": cur < t, ">": cur > t}[op]
            return "1" if (not r if neg else r) else "0"
        if name == "hasDangerTolerance":
            eff = int(args) - opts.get("Danger_Tolerance", 0)
            req = ""
            for lvl, reg in REGION_LEVELS:
                req = f"|{reg} Access|"
                if reg in ("Sword Valley", "Galahad Fortress", "Mechonis Field", "Central Factory", "Agniratha"):
                    pass
                if eff < lvl:
                    break
            return "(" + req + ")"
        if name == "questPaolaAndNarineReq":
            return ("(|Shulk Progressive Affinity Rank:4| AND |Reyn Progressive Affinity Rank:4| AND ((|Sharla Progressive Affinity Rank:4| AND "
                    "|Melia Progressive Affinity Rank:4|) OR (|Sharla Progressive Affinity Rank:4| AND |Fiora Progressive Affinity Rank:4|) OR "
                    "(|Sharla Progressive Affinity Rank:4| AND |Seven Progressive Affinity Rank:4|) OR (|Melia Progressive Affinity Rank:4| AND "
                    "|Fiora Progressive Affinity Rank:4|) OR (|Melia Progressive Affinity Rank:4| AND |Seven Progressive Affinity Rank:4|)))")
        raise KeyError(name)
    for _ in range(4):
        text = re.sub(r"\{(\w+)\((.*?)\)\}", fn, text)
    return text


def ref_atom(tok, inv):
    is_cat = tok.startswith("|@")
    inner = tok.strip("|").lstrip("@$")
    name, _, cnt = inner.partition(":")
    name, cnt = name.strip(), (cnt.strip() or "1")

    def resolve(total):
        c = cnt.lower()
        if c == "all":
            return total
        if c == "half":
            return int(total / 2)
        if c.endswith("%"):
            return math.ceil(total * min(1, max(0, float(c[:-1]) / 100)))
        return int(c)
    if is_cat:
        members = CATS.get(name, [])
        n = resolve(sum(pool.get(m, 0) for m in members))
        if not members:
            return False
        return n <= 0 or sum(inv.get(m, 0) for m in members) >= n
    n = resolve(pool.get(name, 0))
    if n <= 0:
        return True
    if name not in ITEM and name not in {e["name"] for e in events}:
        return False
    return inv.get(name, 0) >= n


def ref_eval(text, inv):
    if not text.strip():
        return True
    text = ref_expand(text)
    toks = re.findall(r"\|[^|]*\||\(|\)|\bAND\b|\bOR\b|\b[01]\b", text, flags=re.I)
    pos = 0

    def operand():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == "(":
            v = expr()
            nonlocal_close()
            return v
        if t in ("0", "1"):
            return t == "1"
        return ref_atom(t, inv)

    def nonlocal_close():
        nonlocal pos
        if pos < len(toks) and toks[pos] == ")":
            pos += 1

    def expr():
        nonlocal pos
        v = operand()
        while pos < len(toks) and toks[pos].upper() in ("AND", "OR"):
            op = toks[pos].upper()
            pos += 1
            r = operand()
            v = (v and r) if op == "AND" else (v or r)
        return v
    return expr()


import os
COLL = None
_cp = os.path.join(WORLD, "..", "collectopaedia.py")
if os.path.exists(_cp):
    ns = {}
    exec(open(_cp, encoding="utf-8").read(), ns)
    COLL = ({l["name"]: l for l in ns["COLLECTOPAEDIA_LOCATIONS"]}, ns["COLLECTOPAEDIA_REQUIREMENTS"], ns["PAGE_REQUIREMENTS"])


def ref_override(name, inv):
    if COLL is None or not opts.get("Collectopaedia"):
        return None
    locs_, req, pages = COLL
    info = locs_.get(name)
    if not info:
        return None
    area, cat = info["area"], info["cat"]
    kinds = ["Vegetable", "Flower", "Fruit", "Animal", "Bug", "Nature", "Part", "Strange"]

    def cat_ok():
        if cat == "ALL":
            return all(inv.get(f"Progressive {c} Category", 0) >= req[area][c] for c in kinds)
        return inv.get(f"Progressive {cat} Category", 0) >= req[area][cat]
    sanity = opts.get("collectopaediasanity")
    if sanity and cat == "ALL":
        return all(inv.get(n, 0) >= 1 for n in CATS.get(f"{area} Collectopaedia", []))
    if sanity:
        return cat_ok() and all(inv.get(n, 0) >= 1 for n in pages.get(f"{area}|{cat}", []))
    return cat_ok()


def ref_accessible(inv):
    inv = dict(inv)
    have_events = set()
    for _ in range(60):
        cur = dict(inv)
        for e in have_events:
            cur[e] = cur.get(e, 0) + 1
        starts = [n for n, r in regions.items() if r.get("starting")] or list(regions)
        reach = set()
        queue = []
        for r in starts:
            if ref_eval(regions[r].get("requires", ""), cur):
                reach.add(r)
                queue.append(r)
        while queue:
            c = queue.pop(0)
            for n in regions[c].get("connects_to", []) or []:
                if n not in reach and ref_eval(regions[n].get("requires", ""), cur):
                    reach.add(n)
                    queue.append(n)
        new = {e["name"] for e in events if e.get("region", "Free") in reach} - have_events
        if not new:
            break
        have_events |= new
    cur = dict(inv)
    for e in have_events:
        cur[e] = cur.get(e, 0) + 1
    result = {}
    for l in locations:
        if l.get("victory"):
            continue
        o = ref_override(l["name"], cur)
        result[l["name"]] = l["region"] in reach and (o if o is not None else ref_eval(l.get("requires", ""), cur))
    return result


def lua_accessible(inv):
    counts.clear()
    for name, n in inv.items():
        if name in codes:
            counts[codes[name]] = n
    lua.execute("XC.dirty = true")
    xc = lua.globals().xc
    return {name: bool(xc(str(i))) for name, i in idx_of.items()}


# ------------------------------------------------------------------------------------------------------ compare
prog = [i for i in items if i.get("progression") or i.get("progression_skip_balancing")]
rnd = random.Random(1234)
mismatch = 0
checked = 0
for state in range(N):
    frac = rnd.choice([0.0, 0.1, 0.3, 0.5, 0.8, 1.0]) if state else 1.0
    inv = {}
    for i in prog:
        if state == 0:
            inv[i["name"]] = i["count"]      # everything: must reach every location
        elif rnd.random() < frac:
            inv[i["name"]] = rnd.randint(1, i["count"]) if rnd.random() < 0.5 else i["count"]
    a, b = ref_accessible(inv), lua_accessible(inv)
    reachable = sum(a.values())
    for name in a:
        checked += 1
        if a[name] != b.get(name):
            mismatch += 1
            if mismatch <= 8:
                loc = next(l for l in locations if l["name"] == name)
                print("MISMATCH", name, "ref", a[name], "lua", b.get(name), "|", loc.get("requires", "")[:160])
    if state < 6 or state == N - 1:
        print(f"state {state}: frac {frac}: reference {reachable}/{len(a)} accessible")
print(f"{checked} location checks compared over {N} inventories, {mismatch} mismatches")
sys.exit(1 if mismatch else 0)
