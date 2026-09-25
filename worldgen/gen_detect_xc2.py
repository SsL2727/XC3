"""Build the XC2 check-detector table: manual location name -> how to read it from the game's save/flag memory.

Detector types (evaluated against the live save struct):
  {"t": "f1",  "i": N}       1-bit flag N is set                (landmark / location discovery, quest clear)
  {"t": "f2",  "i": N, "v": 2}  2-bit flag N has reached 2                        (heart-to-hearts: 2 = viewed)
Validation: run against a real save file (default: the user's completed-chapter save) and report how many detectors are true.
"""
import collections
import difflib
import glob
import json
import os
import re
import struct
import sys

J = r"F:\XCAP\work\xc2_json"
WORLD = r"G:\Archipelago\xc-tools\worldgen\out\xenoblade_2\data"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc2.json")
# landmark discovery flags are NOT the FLD_LandmarkPop row's own raw $id (that table has no flag-reference field at
# all, just an unrelated {"noTelop": ...} toggle) - they live at a constant offset from it in the live 1-bit flag
# array. Live-verified 2026-09-22 (two independent samples, same map ma02a): Lemour Inn ($id 203) set flag 14148,
# Central Exchange ($id 202, via the existing fuzzy name match) set flag 14147 - both exactly $id + 13945, so every
# landmark/location detector this script previously emitted was reading the wrong bit entirely.
LANDMARK_FLAG_BASE = 13945

# manual logic region -> map area (same grouping the tracker uses)
REGION_AREA = {
    "CSEV Maelstrom": "ma03a", "Ancient Ship": "ma04a", "Gormott": "ma05a", "Gormott2": "ma05a", "Gormott3": "ma05a",
    "Uraya": "ma07a", "Uraya2": "ma07a", "FonsaMayma": "ma07a", "PostRoc": "ma07a",
    "Mor Ardain": "ma08a", "Mor Ardain2": "ma08a", "Factory": "ma08a", "PostMorag": "ma08a",
    "Letheria": "ma15a", "Indol": "ma11a", "PostZeke": "ma11a", "Temperantia": "ma10a",
    "Tantal": "ma13a", "Tantal2": "ma13a", "Tantal3": "ma13a", "Ch7": "ma13a",
    "Spirit": "ma16a", "Spirit2": "ma16a", "Spirit3": "ma16a",
    "CliffsOfMorytha": "ma17a", "CliffsOfMorytha2": "ma17a", "LandOfMorytha": "ma18a", "LandOfMorytha2": "ma18a",
    "WorldTree": "ma20a", "WorldTree2": "ma20a", "FLOS": "ma21a", "Free": None,
    "Titan Battleship1": None, "Titan Battleship2": None, "Titan Battleship3": None,
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def load(p):
    return json.load(open(p, encoding="utf-8"))["rows"]


def build():
    txt = {r["$id"]: r["name"] for r in load(J + r"\text\common_ms\fld_landmark.json")}
    lm = []
    for f in sorted(glob.glob(J + r"\data\common_gmk\*_FLD_LandmarkPop.json")):
        area = os.path.basename(f).split("_")[0]
        for r in load(f):
            lm.append({"area": area, "id": r["$id"], "name": txt.get(r["MSGID"], ""), "cat": r["category"]})
    by_norm = collections.defaultdict(list)
    for e in lm:
        if e["name"]:
            by_norm[norm(e["name"])].append(e)
    all_norm = list(by_norm)

    kz_txt = {r["$id"]: r["name"] for r in load(J + r"\text\common_ms\fld_kizunatalktitle.json")}
    cond_flag = {r["$id"]: r for r in load(J + r"\data\common\FLD_ConditionFlag.json")}
    cond_list = {r["$id"]: r for r in load(J + r"\data\common\FLD_ConditionList.json")}
    kz = {}
    for r in load(J + r"\data\common_gmk\FLD_KizunaTalk.json"):
        c = cond_list.get(r["ConditionID"])
        if not (r["EventID"] and c):
            continue
        for n in range(1, 9):                      # the availability condition holds the talk's own 2-bit state flag
            if c[f"ConditionType{n}"] == 4 and cond_flag[c[f"Condition{n}"]]["FlagType"] == 2:
                kz.setdefault(norm(kz_txt.get(r["Title"], "")), []).append(cond_flag[c[f"Condition{n}"]]["FlagID"])
                break

    locs = [l for l in json.load(open(WORLD + r"\locations.json", encoding="utf-8")) if not l.get("victory")]
    det = {}
    stats = collections.Counter()
    for l in locs:
        cats = " ".join(l["category"])
        n = norm(l["name"])
        area = REGION_AREA.get(l["region"])
        if re.search(r"Landmarks|Locations|Landmarksanity|Locationsanity", cats):
            cand = by_norm.get(n)
            how = "exact"
            if not cand:
                close = difflib.get_close_matches(n, all_norm, n=1, cutoff=0.85)
                cand = by_norm[close[0]] if close else None
                how = "fuzzy"
            if cand:
                pick = [e for e in cand if e["area"] == area] or cand
                det[l["name"]] = {"t": "f1", "i": pick[0]["id"] + LANDMARK_FLAG_BASE, "src": f"landmark:{pick[0]['area']}:{how}"}
                stats["landmark_" + how] += 1
                continue
        if "Hearttoheart" in cats or "Heart to Hearts" in cats:
            ev = kz.get(n)
            if ev:
                det[l["name"]] = {"t": "f2", "i": ev[0], "v": 2, "src": "kizuna"}   # 0/1 = not seen, 2 = viewed
                stats["h2h"] += 1
                continue
        stats["unmapped"] += 1
    return det, stats


if __name__ == "__main__":
    det, stats = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    goals = {"Clear Chapter 10": {"t": "x", "k": "clear_count", "src": "GameClearCount rises after the ending"}}
    json.dump({"locations": det, "goals": goals}, open(OUT, "w", encoding="utf-8"), indent=0)
    print("detectors:", len(det), dict(stats))
