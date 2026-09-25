"""Build the XC3 check-detector table (location name -> how to read it from the live save/flag memory).

XC3 save layout (recordkeeper): flag arrays at +0x710 (same 1/2/4/8/16/32-bit engine as XC2), enemy tombstones at +0x183000.
  landmarks / locations / rest spots / colonies : 1-bit flag  17720 + (GMK_Location row id - 1)   (row ids are global across maps)
  containers                                   : 1-bit flag  6914 + SequentialID (prg/SYS_GimmickLocation TreasureBox row; gen_container_locations_xc3.py)
  quests                                       : 2-bit flag  QST_List.FlagPrt   (2 / 3 = completed)
  unique monsters                              : tombstone[FLD_UMonsterList row id - 1].defeated
  goal                                         : 1-bit flag 6879 (game clear), only counted when it rises after attach
Validated against recordkeeper's chapter-5 test save (landmark counter 113 == landmarks set by this mapping).
"""
import collections
import difflib
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trackergen"))

J = r"F:\XCAP\work\xc3_json"
J2 = r"F:\XCAP\work\xc3_json2"
J3 = r"F:\XCAP\work\xc3_json3\quest_en"
WORLD = r"G:\Archipelago\xc-tools\worldgen\out\xenoblade_3\data"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3.json")

LOCATION_FLAG_BASE = 17720
GAME_CLEAR_FLAG = 6879

# manual logic region -> map areas whose GMK_Location tables hold the region's locations (same grouping as the tracker)
REGION_AREA = {
    "Everblight Plain": "ma01a", "Yzana Plains": "ma01a", "Alfeto Valley": "ma01a", "Melnath's Shoulder": "ma01a",
    "Millick Meadows": "ma01a", "Captocorn Peak": "ma01a", "Colony 9": "ma01a",
    "Eagus Wilderness": "ma04a", "Dannagh Desert": "ma04a", "Elaice Highway": "ma04a", "Ribbi Flats": "ma04a", "Rae-Bel Tableland": "ma04a",
    "Urayan Tunnels": "ma07a", "Urayan Trail": "ma07a", "Great Cotte Falls": "ma07a", "Old Cliffside Way": "ma07a",
    "High Maktha Wildwood": "ma07a", "Low Maktha Wildwood": "ma07a",
    "Syra Hovering Reefs": "ma09a", "Keves Castle": "ma09a",
    "Agnus Castle Barbican": "ma11a", "Great Sword's Base": "ma11a", "Erythia Sea": "ma11a", "Li Garte Prison Camp": "ma11a",
    "Agnus Castle": "ma14a", "City": "ma15a", "Great Sword's Hilt": "ma15a", "Origin": "ma17a", "The Cavity": "ma22a",
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def rows(path):
    return json.load(open(path, encoding="utf-8"))["rows"]


def strip_level(name: str) -> str:
    return re.sub(r"\s*\(Lv[^)]*\)\s*$", "", name).strip()


def build():
    locs = [l for l in json.load(open(WORLD + r"\locations.json", encoding="utf-8")) if not l.get("victory")]

    # ---- location tables: (area, cat, name) -> global row id
    names = {r["$id"]: r["name"] for r in rows(J + r"\en\system~12375808\msg_location_name.json")}
    by_area = collections.defaultdict(lambda: collections.defaultdict(list))     # area -> norm name -> [(cat, id)]
    for f in sorted(glob.glob(J + r"\data\map\ma*_GMK_Location.json")):
        area = os.path.basename(f).split("_")[0]
        if area in ("ma20a", "ma90a"):                 # row ids collide with other maps' flags
            continue
        for r in rows(f):
            nm = names.get(r["LocationName"], "")
            if nm:
                by_area[area][norm(nm)].append((r["CategoryPriority"], r["$id"]))
    all_norm = {a: list(d) for a, d in by_area.items()}

    # ---- quests
    qtext = {r["$id"]: r["<DBAF43F0>"] for r in rows(J3 + r"\AD40857C.json")}
    quests = collections.defaultdict(list)
    for q in rows(J2 + r"\qst\QST_List.json"):
        t = qtext.get(q["QuestTitle"], "") if q["QuestTitle"] else ""
        if t and q["FlagPrt"]:
            quests[norm(t)].append(q["FlagPrt"])

    # ---- unique monsters (tombstones)
    ename = {r["$id"]: r["name"] for r in rows(J + r"\en\system~12375808\msg_enemy_name.json")}
    edata = {r["$id"]: r["MsgName"] for r in rows(J2 + r"\fld\FLD_EnemyData.json")}
    uniques = collections.defaultdict(list)
    for u in rows(J2 + r"\fld\FLD_UMonsterList.json"):
        nm = ename.get(edata.get(u["EnemyID1"], 0), "")
        if nm:
            uniques[norm(nm)].append(u["$id"])

    cpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_container_locations.json")
    containers = {c["name"]: c for c in json.load(open(cpath, encoding="utf-8"))["locations"]} if os.path.exists(cpath) else {}
    want_cat = {"landmarks": (2, 1), "locations": (4, 3, 5), "restspots": (0,)}
    det, stats = {}, collections.Counter()
    for l in locs:
        cats = set(l["category"])
        n = norm(l["name"])
        area = REGION_AREA.get(l["region"])
        base = re.sub(r" - .*$", "", l["region"])
        area = area or REGION_AREA.get(base)
        kinds = [c for c in want_cat if c in cats]
        if kinds and area in by_area:
            cand = by_area[area].get(n)
            how = "exact"
            if not cand:
                close = difflib.get_close_matches(n, all_norm[area], n=1, cutoff=0.88)
                cand, how = (by_area[area][close[0]], "fuzzy") if close else (None, "")
            if cand:
                pick = [c for c in cand if c[0] in want_cat[kinds[0]]] or cand
                det[l["name"]] = {"t": "f1", "i": LOCATION_FLAG_BASE + pick[0][1] - 1, "src": f"location:{area}:{how}"}
                stats["location_" + how] += 1
                continue
        if "quests" in cats:
            cand = quests.get(n)
            if cand:
                det[l["name"]] = {"t": "f2", "i": cand[0], "v": 2, "src": "quest"}
                stats["quest"] += 1
                continue
        if "uniquemonsters" in cats:
            cand = uniques.get(norm(strip_level(l["name"])))
            if cand:
                det[l["name"]] = {"t": "tb", "i": cand[0] - 1, "src": "tombstone"}
                stats["unique"] += 1
                continue
        stats["unmapped:" + (sorted(cats)[0] if cats else "?")] += 1
    for name, c in containers.items():                  # one permanent flag per container; straight from the container table, not the last world build
        det[name] = {"t": "f1", "i": c["flag"], "src": "container"}
        stats["container"] += 1
    return det, stats


if __name__ == "__main__":
    det, stats = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    goals = {"Z\u221e (Lv. 75)": {"t": "f1", "i": GAME_CLEAR_FLAG, "rise": True, "src": "game_clear flag rises after attach"}}
    json.dump({"locations": det, "goals": goals}, open(OUT, "w", encoding="utf-8"), indent=0)
    print("detectors:", len(det), dict(stats))
