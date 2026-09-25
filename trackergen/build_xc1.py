"""Build the Xenoblade Chronicles DE PopTracker pack (real in-game maps, BDAT-derived pin positions)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

XC3_TEX = r"G:\Archipelago\xc-tools\xc3_lib\xc3_tex.exe"
EXTRACTED = Path(r"F:\XCAP\extracted\xc1")
JSON_DIR = Path(r"F:\XCAP\work\xc1_json")
MAP_CACHE = Path(r"F:\XCAP\work\xc1_maps")
WORLD = Path(r"G:\Archipelago\xc-tools\worldgen\out\xenoblade_de\data")
WORK = Path(r"F:\XCAP\work\tracker_xc1")
ZIP_OUT = Path(r"G:\Archipelago\poptracker\packs\XC1-DE-AP-Tracker.zip")
MAX_W = 1150   # canvas (map + 330px panel) must fit the PopTracker viewport at natural size
MAX_H = 900
NO_BOUNDS = set()

# manual region -> (BDAT FLD_maplist ids used for name matching, map key)
REGIONS = {
    "Colony 9": ([2], "ma0101"), "Tephra Cave": ([3], "ma0201"), "Bionis' Leg": ([4], "ma0301"),
    "Colony 6": ([5], "ma0401"), "Ether Mine": ([6], "ma0402"), "Satorl Marsh": ([7], "ma0501"),
    "Bionis' Interior (1st Visit)": ([25], "ma2101"), "Makna Forest": ([8], "ma0601"),
    "Frontier Village": ([9], "ma0701"), "Eryth Sea": ([12], "ma1001"), "Alcamoth": ([13, 30, 34], "ma1101"),
    "High Entia Tomb": ([11], "ma0901"), "Prison Island (1st Visit)": ([14, 15], "ma1201"),
    "Valak Mountain": ([16], "ma1301"), "Sword Valley (MISSABLE)": ([17], "ma1401"),
    "Galahad Fortress (MISSABLE)": ([18], "ma1501"), "Fallen Arm": ([19], "ma1601"),
    "Mechonis Field (MISSABLE)": ([21], "ma1701"), "Central Factory (MISSABLE)": ([24], "ma2001"),
    "Agniratha (MISSABLE)": ([23], "ma1901"), "Mechonis Core": ([27], "ma2301"),
    "Bionis' Interior (2nd Visit)": ([25], "ma2101"), "Prison Island (2nd Visit)": ([14, 15], "ma1201"),
    "Memory Space": ([26], "ma2201"), "Prologue": ([1], None),
}
# BDAT map id -> (map key, wilay used)
MAP_FILES = {
    2: ("ma0101", "mf03_map01_ma0101_f01_map"), 3: ("ma0201", "mf03_map01_ma0201_f01_map"),
    4: ("ma0301", "mf03_map01_ma0301_f01_map"), 5: ("ma0401", "mf03_map01_ma0401_f01_map"),
    6: ("ma0402", "mf03_map01_ma0402_f01_map"), 7: ("ma0501", "mf03_map01_ma0501_f01_map"),
    8: ("ma0601", "mf03_map01_ma0601_f01_map"), 9: ("ma0701", "mf03_map01_ma0701_f01_map"),
    11: ("ma0901", "mf03_map01_ma0901_f01_map"), 12: ("ma1001", "mf03_map01_ma1001_f01_map"),
    13: ("ma1101", "mf03_map01_ma1101_f01_map"), 14: ("ma1201", "mf03_map01_ma1201_f01_map"),
    16: ("ma1301", "mf03_map01_ma1301_f01_map"), 17: ("ma1401", "mf03_map01_ma1401_f01_map"),
    18: ("ma1501", "mf03_map01_ma1501_f01_map"), 19: ("ma1601", "mf03_map01_ma1601_f01_map"),
    21: ("ma1701", "mf03_map01_ma1701_f01_map"), 23: ("ma1901", "mf03_map01_ma1901_f01_map"),
    24: ("ma2001", "mf03_map01_ma2001_f01_map"), 25: ("ma2101", "mf03_map01_ma2101_f01_map"),
    26: ("ma2201", "mf03_map01_ma2201_f01_map"), 27: ("ma2301", "mf03_map01_ma2301_f01_map"),
}
KEY_TO_MAPID = {v[0]: k for k, v in MAP_FILES.items()}
MAP_TITLES = {
    "ma0101": "Colony 9", "ma0201": "Tephra Cave", "ma0301": "Bionis' Leg", "ma0401": "Colony 6", "ma0402": "Ether Mine",
    "ma0501": "Satorl Marsh", "ma0601": "Makna Forest", "ma0701": "Frontier Village", "ma0901": "High Entia Tomb",
    "ma1001": "Eryth Sea", "ma1101": "Alcamoth", "ma1201": "Prison Island", "ma1301": "Valak Mountain",
    "ma1401": "Sword Valley", "ma1501": "Galahad Fortress", "ma1601": "Fallen Arm", "ma1701": "Mechonis Field",
    "ma1901": "Agniratha", "ma2001": "Central Factory", "ma2101": "Bionis' Interior", "ma2201": "Memory Space",
    "ma2301": "Mechonis Core",
}


def decode(name: str) -> Image.Image:
    MAP_CACHE.mkdir(parents=True, exist_ok=True)
    png = MAP_CACHE / f"{name}.png"
    if png.exists():
        return Image.open(png)
    src = EXTRACTED / "menu" / "image" / f"{name}.wilay"
    tmp = MAP_CACHE / f"_{name}"
    tmp.mkdir(exist_ok=True)
    subprocess.run([XC3_TEX, str(src), str(tmp)], check=True, capture_output=True)
    dds = sorted(tmp.glob("*.dds"))[0]
    subprocess.run([XC3_TEX, str(dds), str(png)], check=True, capture_output=True)
    return Image.open(png)


def style(ims, target: tuple) -> Image.Image:
    """The in-game map art is the alpha channel (height-shaded relief). Floors share the area's coordinate bounds, so
    all floors are unioned into one top-down map; tint it like the in-game UI."""
    from PIL import ImageChops
    if not isinstance(ims, (list, tuple)):
        ims = [ims]
    a = None
    for im in ims:
        ch = im.getchannel(3).resize(target, Image.LANCZOS)
        a = ch if a is None else ImageChops.lighter(a, ch)
    lut_r = [int(14 + (v / 255) ** 0.9 * 200) for v in range(256)]
    lut_g = [int(22 + (v / 255) ** 0.9 * 205) for v in range(256)]
    lut_b = [int(42 + (v / 255) ** 0.9 * 170) for v in range(256)]
    return Image.merge("RGB", (a.point(lut_r), a.point(lut_g), a.point(lut_b)))


def floors_of(key: str):
    """All main floor images (fNN_map) of an area; Prison Island's two visits use ma1201 and ma1202."""
    prefixes = [key] + (["ma1202"] if key == "ma1201" else [])
    names = []
    for pre in prefixes:
        names += sorted(p.stem for p in (EXTRACTED / "menu" / "image").glob(f"mf03_map01_{pre}_f[0-9][0-9]_map.wilay"))
    return names


def norm_name(s: str) -> str:
    return re.sub(r"\s*\((?:[^()]*Colony 9|Tephra Cave|Bionis' Leg|Colony 6|Ether Mine|Satorl Marsh|Makna Forest|Frontier Village|Eryth Sea|Alcamoth|High Entia Tomb|Valak Mountain|Sword Valley|Galahad Fortress|Fallen Arm|Mechonis Field|Central Factory|Agniratha|Prison Island|Bionis' Interior|Mechonis Core|Memory Space|1st Visit|2nd Visit|MISSABLE|Location)[^)]*\)", "", s).strip()


def build():
    world_locs = json.loads((WORLD / "locations.json").read_text(encoding="utf-8"))
    lm = json.loads((JSON_DIR / "data/bdat_common/landmarklist.json").read_text(encoding="utf-8"))["rows"]
    lmn = {r["$id"]: r["name"] for r in json.loads((JSON_DIR / "text/bdat_common_ms/landmarklist_ms.json").read_text(encoding="utf-8"))["rows"]}
    ml = {r["$id"]: r for r in json.loads((JSON_DIR / "data/bdat_common/FLD_maplist.json").read_text(encoding="utf-8"))["rows"]}

    # ---- maps
    maps = {}
    scale_of = {}
    for mid, (key, wil) in MAP_FILES.items():
        raws = [decode(n) for n in (floors_of(key) or [wil])]
        raw = raws[0]
        row = ml[mid]
        nominal = (row["mapimage_size_x"], row["mapimage_size_y"])
        if not nominal[0] or not nominal[1]:
            nominal = (raw.width // 2, raw.height // 2)   # no bounds in the table: image only, no coordinate pins
            row = dict(row, minimap_lt_x=0, minimap_rb_x=0, minimap_lt_z=0, minimap_rb_z=0)
            ml[mid] = row
            NO_BOUNDS.add(mid)
        f = min(1.0, MAX_W / nominal[0], MAX_H / nominal[1])
        size = (max(1, int(nominal[0] * f)), max(1, int(nominal[1] * f)))
        maps[key] = {"title": MAP_TITLES[key], "img": style(raws, size), "pin": 24 if max(size) > 1000 else 18}
        scale_of[mid] = size

    # ---- pins from landmarklist
    by_name = {}
    for r in lm:
        by_name.setdefault(lmn[r["name"]], []).append(r)
    pins = {}
    unmatched = []
    for l in world_locs:
        if not any(c in ("landmarks", "locations") for c in l["category"]):
            continue
        region = l["region"]
        want_maps = REGIONS.get(region, ([], None))[0]
        cands = by_name.get(l["name"]) or by_name.get(norm_name(l["name"])) or []
        pick = [r for r in cands if r["mapID"] in want_maps]
        if not pick and len(cands) == 1 and cands[0]["mapID"] in MAP_FILES:
            pick = cands
        if not pick:
            unmatched.append(l["name"])
            continue
        r = pick[0]
        mid = r["mapID"]
        if mid not in MAP_FILES or mid in NO_BOUNDS:
            unmatched.append(l["name"])
            continue
        mrow = ml[mid]
        W, H = scale_of[mid]
        x = (r["posX"] - mrow["minimap_lt_x"]) / (mrow["minimap_rb_x"] - mrow["minimap_lt_x"]) * W
        y = (r["posZ"] - mrow["minimap_lt_z"]) / (mrow["minimap_rb_z"] - mrow["minimap_lt_z"]) * H
        pins[l["name"]] = (MAP_FILES[mid][0], max(4, min(W - 4, x)), max(4, min(H - 4, y)))
    print(f"pins resolved: {len(pins)}; landmark/location checks without coordinates: {len(unmatched)}")

    region_map = {reg: v[1] for reg, v in REGIONS.items() if v[1]}
    region_map["Free"] = "ma0101"

    def group_of(l):
        cats = set(l["category"])
        for cat, label in (("StoryQuests", "Story Quests"), ("AffinityQuests", "Affinity Quests"), ("MonsterQuests", "Monster Quests"),
                           ("CollectionQuests", "Other Quests"), ("SearchQuests", "Other Quests"), ("ChallengeQuests", "Other Quests"),
                           ("MaterialQuests", "Other Quests"), ("UniqueMonsters", "Unique Monsters"), ("SuperBosses", "Super Bosses"),
                           ("AffinityChart", "Affinity Chart"), ("HeartToHearts", "Heart-to-Hearts"), ("Achievements", "Achievements"),
                           ("Collectopaedia", "Collectopaedia"), ("DevelopmentLevels", "Development"), ("NoponGrandPrix", "Nopon Grand Prix"),
                           ("landmarks", "Landmarks (unplaced)"), ("locations", "Locations (unplaced)")):
            if cat in cats:
                return label
        return "Bosses / Other"

    def item_group_of(i):
        c = (i.get("category") or ["Other"])[0]
        if c.endswith("Collectopaedia") or "Collection (" in c or c == "Collectopaedia Pages":
            return "Collectopaedia"
        if c.endswith("Skill Trees"):
            return "Skill Trees"
        if c.endswith("Affinity"):
            return "Affinity Ranks"
        if c in ("Spoilers", "NoSpoilers"):
            return "Story Items"
        return c

    game_lua = build_game_lua()
    cfg = {
        "uid": "xenoblade_de_ap", "title": "Xenoblade Chronicles DE AP Tracker", "game_name": "Xenoblade Chronicles DE",
        "world_dir": str(WORLD), "work_dir": str(WORK), "zip_out": str(ZIP_OUT), "maps": maps,
        "pin_positions": pins, "region_map": region_map, "group_of": group_of, "item_group_of": item_group_of,
        "left_groups": ["Area Keys", "Hunting Licenses", "Memory Fragments", "Colony 6 Reconstruction"],
        "min_map": (950, 620),
        "game_lua": game_lua, "item_size": 36, "wide_groups": {"Collectopaedia": (26, 30)},
        "category_default_override": {"Spoilers": False, "NoSpoilers": True, "DefinitiveEdition": True, "Switch2Version": False},
        "readme": README,
    }
    pack = common.Pack(cfg)
    z = pack.build()
    print("built", z, pack.stats)
    return pack


def build_game_lua() -> str:
    coll_py = Path(r"G:\Archipelago\xc-tools\worldgen\out\xenoblade_de\collectopaedia.py").read_text(encoding="utf-8")
    ns = {}
    exec(coll_py, ns)
    req = ns["COLLECTOPAEDIA_REQUIREMENTS"]
    locs = {l["name"]: {"area": l["area"], "cat": l["cat"]} for l in ns["COLLECTOPAEDIA_LOCATIONS"]}
    pages = ns["PAGE_REQUIREMENTS"]
    header = "-- Xenoblade Chronicles DE specific rule functions (ported from the manual hooks)" + chr(10)
    return header + XC1_LUA.replace("__REQ__", common.lua_val(req)).replace("__LOCS__", common.lua_val(locs)).replace("__PAGES__", common.lua_val(pages))


XC1_LUA = r'''
local REGION_LEVELS = {
    { "Colony 9", 7, "|Colony 9 Access|" }, { "Tephra Cave", 12, "|Tephra Cave Access|" },
    { "Bionis' Leg", 25, "|Bionis' Leg Access|" }, { "Colony 6", 26, "|Colony 6 Access|" },
    { "Ether Mine", 27, "|Ether Mine Access|" }, { "Satorl Marsh", 28, "|Satorl Marsh Access|" },
    { "Bionis' Interior (1st Visit)", 32, "|Bionis' Interior (1st Visit) Access|" },
    { "Makna Forest", 34, "|Makna Forest Access|" }, { "Frontier Village", 36, "|Frontier Village Access|" },
    { "Eryth Sea", 37, "|Eryth Sea Access|" }, { "Alcamoth", 37, "|Alcamoth Access|" },
    { "High Entia Tomb", 38, "|High Entia Tomb Access|" },
    { "Prison Island (1st Visit)", 42, "|Prison Island (1st Visit) Access|" },
    { "Valak Mountain", 48, "|Valak Mountain Access|" }, { "Sword Valley (MISSABLE)", 52, "|Sword Valley Access|" },
    { "Galahad Fortress (MISSABLE)", 55, "|Galahad Fortress Access|" }, { "Fallen Arm", 58, "|Fallen Arm Access|" },
    { "Mechonis Field (MISSABLE)", 60, "|Mechonis Field Access|" },
    { "Central Factory (MISSABLE)", 65, "|Central Factory Access|" }, { "Agniratha (MISSABLE)", 70, "|Agniratha Access|" },
    { "Mechonis Core", 72, "|Mechonis Core Access|" }, { "Bionis' Interior (2nd Visit)", 75, "|Bionis' Interior (2nd Visit) Access|" },
    { "Prison Island (2nd Visit)", 80, "|Prison Island (2nd Visit) Access|" },
}

XC.funcs.hasDangerTolerance = function(arg)
    local effective = tonumber(arg) - XC.opt("Danger_Tolerance")
    local req = ""
    for _, r in ipairs(REGION_LEVELS) do
        req = r[3]
        if effective < r[2] then break end
    end
    if req == "" then return true end
    return req
end

XC.funcs.questPaolaAndNarineReq = function()
    return "|Shulk Progressive Affinity Rank:4| AND |Reyn Progressive Affinity Rank:4|"
        .. " AND ((|Sharla Progressive Affinity Rank:4| AND |Melia Progressive Affinity Rank:4|)"
        .. " OR (|Sharla Progressive Affinity Rank:4| AND |Fiora Progressive Affinity Rank:4|)"
        .. " OR (|Sharla Progressive Affinity Rank:4| AND |Seven Progressive Affinity Rank:4|)"
        .. " OR (|Melia Progressive Affinity Rank:4| AND |Fiora Progressive Affinity Rank:4|)"
        .. " OR (|Melia Progressive Affinity Rank:4| AND |Seven Progressive Affinity Rank:4|))"
end

-- Collectopaedia completion checks are driven by the "Progressive <type> Category" items instead of plain region rules
local COLLECT_REQ = __REQ__
local COLLECT_LOCS = __LOCS__
local PAGE_REQ = __PAGES__
local CATS = { "Vegetable", "Flower", "Fruit", "Animal", "Bug", "Nature", "Part", "Strange" }

local function cat_ok(area, cat)
    if cat == "ALL" then
        for _, c in ipairs(CATS) do
            if XC.count("Progressive " .. c .. " Category") < COLLECT_REQ[area][c] then return false end
        end
        return true
    end
    return XC.count("Progressive " .. cat .. " Category") >= COLLECT_REQ[area][cat]
end

XC.game_override = function(L, idx)
    if XC.opt("Collectopaedia") == 0 then return nil end
    local info = COLLECT_LOCS[L.name]
    if not info then return nil end
    local sanity = XC.opt("collectopaediasanity") > 0
    if sanity and info.cat == "ALL" then
        local members = XC_DATA.cats[info.area .. " Collectopaedia"] or {}
        for _, n in ipairs(members) do
            if XC.count(n) < 1 then return false end
        end
        return true
    elseif sanity then
        if not cat_ok(info.area, info.cat) then return false end
        for _, n in ipairs(PAGE_REQ[info.area .. "|" .. info.cat] or {}) do
            if XC.count(n) < 1 then return false end
        end
        return true
    end
    return cat_ok(info.area, info.cat)
end
'''

README = """# Xenoblade Chronicles DE - Archipelago PopTracker

Pack for the `Xenoblade Chronicles DE` Archipelago world.

* Maps are the game's own area maps, extracted from the Definitive Edition RomFS and tinted like the in-game UI.
* Landmark and location-discovery checks are pinned at their real in-game coordinates (from the game's `landmarklist`
  table and the map's own world-to-image bounds). Every other check type (quests, unique monsters, affinity chart, ...)
  is grouped in the panel on the left of each area map because the game has no single map position for it.
* Logic is evaluated live from the world's own rule data (`scripts/xc_logic.lua`), including Danger Tolerance,
  Key Leniency independent region gating and the Collectopaedia rules. Options are taken from slot data on connect.
"""

if __name__ == "__main__":
    build()
