"""Build the XC3 container-location table (detect/xc3_container_locations.json): one location PER CONTAINER.

History: an earlier design was one anonymous pool of "Container Check N" locations (the live detector could only count opened
containers).  That is no longer needed: every field container has its own permanent 1-bit flag,

    flag = 6914 + SequentialID       (SequentialID = the container's row in prg/SYS_GimmickLocation, GimmickType "TreasureBox")

Live-verified on three containers (flags 6958 / 6959 / 7197 = SequentialID 44 / 45 / 283, the first two 5 world units apart) and
cross-checked on recordkeeper's chapter-5 test save: the set bits fall exactly where a chapter-5 player has been (Aetia 32/46,
Fornis 74/81, Pentelas 50/57, Syra 24/34, part of Cadensia, none in Origin / Agnus Castle) and nothing outside 6915..7312.

prg/SYS_GimmickLocation also holds the containers' world position (X, Y, Z) and MapID, and links to map/<map>_GMK_TreasureBox by
GimmickID == ID (355 of 360; RewardID there is the contents).  From that this script derives, per container:
  * name    "<place> Container <k>": <place> is the named area the container is in (its own LocationID when set, else the smallest
            GMK_Location volume that contains it, else the nearest one); k counts within (place, map) in SequentialID order
  * region  the world region of that place's landmark/location check; a container with no usable place of its own takes the region
            that the majority of its 5 nearest placed gimmicks (of any type - enemies, gathering points ...) belong to, through
            their LocationID (leave-one-out on the containers that have one: 98 % correct, vs 83 % for the nearest landmark)
  * batch   the Progressive Container Access batch (gen_container_gates_xc3.py: 20 GMK_TreasureBox rows per batch in (map, row) order)
  * flag, map, x, y, z (world coordinates; the tracker registers them onto the map images)
ma90a (debug map) is skipped; ma21a repeats ma15a's nine containers under the same SequentialIDs (one flag) - kept once, with the lower batch.
"""
import collections
import glob
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_detect_xc3 import REGION_AREA  # noqa: E402  (manual logic region -> map area)

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
WORLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "xenoblade_3", "data", "locations.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_container_locations.json")
FLAG_BASE = 6914
BATCH_SIZE = 20                       # keep in step with gen_container_gates_xc3.py
SKIP_MAPS = {17: "ma90a"}             # debug map
DUP_MAPS = {28: 24}                   # ma21a repeats ma15a's containers (same SequentialIDs)
# last resort when a map has no labelled gimmick at all: the region a player enters that map in (The Cavity is one region anyway)
MAP_ENTRY_REGION = {"ma01a": "Everblight Plain", "ma04a": "Eagus Wilderness", "ma07a": "Urayan Tunnels", "ma09a": "Syra Hovering Reefs",
                    "ma11a": "Agnus Castle Barbican", "ma14a": "Agnus Castle", "ma15a": "City", "ma17a": "Origin", "ma22a": "The Cavity"}
AREA_TITLE = {"ma01a": "Aetia Region", "ma04a": "Fornis Region", "ma07a": "Pentelas Region", "ma09a": "Syra Hovering Reefs",
              "ma11a": "Cadensia Region", "ma14a": "Agnus Castle", "ma15a": "City", "ma17a": "Origin", "ma22a": "The Cavity"}


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\(Lv[^)]*\)\s*$", "", s).lower())


def build(verbose=False):
    gl = rows(r"prg\SYS_GimmickLocation.json")
    map_area = {r["$id"]: r["ID"][4:].lower() for r in rows(r"sys\SYS_MapList.json") if r["ID"].startswith("FLD_MA")}   # 18 -> ma01a
    names = {r["$id"]: r["name"] for r in rows(r"system\msg_location_name.json")}

    # --- named places (GMK_Location gimmicks): map id -> [{name, pos, size}], and LocationID hash -> name
    gmk_loc = {}
    for f in glob.glob(os.path.join(J, "map", "*_GMK_Location.json")):
        for r in json.load(open(f, encoding="utf-8"))["rows"]:
            gmk_loc[r["ID"]] = names.get(r["LocationName"], "")
    places = collections.defaultdict(list)
    for r in gl:
        if r["GimmickType"] == "Location" and gmk_loc.get(r["GimmickID"]):
            places[r["MapID"]].append({"name": gmk_loc[r["GimmickID"]], "p": (r["X"], r["Y"], r["Z"]), "s": (r["SX"], r["SY"], r["SZ"])})

    # --- the world's landmark / location / rest-spot checks: normalised name -> [(region, area)]
    ap = collections.defaultdict(list)
    for l in json.load(open(WORLD, encoding="utf-8")):
        if set(l["category"]) & {"landmarks", "locations", "restspots"}:
            area = REGION_AREA.get(l["region"]) or REGION_AREA.get(re.sub(r" - .*$", "", l["region"]))
            ap[norm(l["name"])].append((l["region"], area))

    def region_of(place_name, area):
        c = ap.get(norm(place_name), [])
        for reg, a in c:
            if a == area:
                return reg
        return None

    # every placed gimmick whose LocationID names a place that has a check of its own labels its spot with that check's region
    labelled = collections.defaultdict(lambda: ([], []))          # map id -> (xz points, regions)
    for r in gl:
        n = gmk_loc.get(r["LocationID"])
        a = map_area.get(r["MapID"])
        reg = region_of(n, a) if n and a else None
        if reg:
            labelled[r["MapID"]][0].append((r["X"], r["Z"]))
            labelled[r["MapID"]][1].append(reg)

    def vote(mid, pos, k=5):
        pts, regs = labelled[mid]
        if not pts:
            return None
        d = sorted((math.hypot(pos[0] - x, pos[2] - z), rg) for (x, z), rg in zip(pts, regs))[:k]
        w = collections.Counter()
        for dist, rg in d:
            w[rg] += 1 / (1 + dist)
        return w.most_common(1)[0][0]

    # --- batches, exactly as gen_container_gates_xc3.py orders them
    order = []
    for f in sorted(glob.glob(os.path.join(J, "map", "*_GMK_TreasureBox.json"))):
        mp = os.path.basename(f).split("_")[0]
        for r in json.load(open(f, encoding="utf-8"))["rows"]:
            order.append((mp, r["$id"], r["ID"]))
    batch_of = {(mp, rid): i // BATCH_SIZE + 1 for i, (mp, rid, _) in enumerate(order)}
    row_of = {(mp, gid): rid for mp, rid, gid in order}

    # --- containers
    tb = [r for r in gl if r["GimmickType"] == "TreasureBox"]
    by_seq = {}
    for r in tb:
        if r["MapID"] in SKIP_MAPS:
            continue
        mid = DUP_MAPS.get(r["MapID"], r["MapID"])
        area = map_area[r["MapID"]]
        rid = row_of.get((area, r["GimmickID"]))
        batch = batch_of.get((area, rid), 0)
        e = by_seq.setdefault(r["SequentialID"], {"row": r, "map": mid, "batch": batch})
        if r["MapID"] == mid:
            e["row"], e["map"] = r, mid
        e["batch"] = min(e["batch"] or batch, batch or e["batch"])
    stats = collections.Counter()
    out = []
    for seq, e in by_seq.items():
        r, mid = e["row"], e["map"]
        area = map_area[mid]
        pos = (r["X"], r["Y"], r["Z"])
        pl = places.get(mid, [])
        how, place = None, None
        if r["LocationID"] in gmk_loc and gmk_loc[r["LocationID"]]:
            place, how = gmk_loc[r["LocationID"]], "id"
        else:
            inside = [g for g in pl if all(abs(pos[i] - g["p"][i]) <= g["s"][i] / 2 for i in range(3))]
            if inside:
                place, how = min(inside, key=lambda g: g["s"][0] * g["s"][1] * g["s"][2])["name"], "inside"
            elif pl:
                place, how = min(pl, key=lambda g: math.hypot(pos[0] - g["p"][0], pos[2] - g["p"][2]))["name"], "nearest"
        region = region_of(place, area) if place and how == "id" else None
        rhow = "place"
        if region is None:
            region, rhow = vote(mid, pos), "vote"
        if region is None and place:                        # no labelled gimmicks on this map: the place's own check, if it has one
            region, rhow = region_of(place, area), "place-name"
        if region is None:
            region, rhow = MAP_ENTRY_REGION[area], "map-entry"
        stats[f"place:{how}"] += 1
        stats[f"region:{rhow if region else 'NONE'}"] += 1
        out.append({"seq": seq, "flag": FLAG_BASE + seq, "map": area, "place": place or AREA_TITLE.get(area, area), "region": region,
                    "batch": e["batch"], "x": round(pos[0], 2), "y": round(pos[1], 2), "z": round(pos[2], 2), "_how": how})

    # --- names: "<place> Container <k>" (k per place and map, in flag order); place names used on several maps get the map's title
    users = collections.defaultdict(set)
    for c in out:
        users[c["place"]].add(c["map"])
    counter = collections.Counter()
    for c in sorted(out, key=lambda c: (c["map"], c["place"], c["seq"])):
        key = (c["map"], c["place"])
        counter[key] += 1
        base = c["place"] if len(users[c["place"]]) == 1 else f"{c['place']} ({AREA_TITLE.get(c['map'], c['map'])})"
        c["name"] = f"{base} Container {counter[key]}"
    for c in out:
        del c["_how"]
    out.sort(key=lambda c: (list(AREA_TITLE).index(c["map"]), c["seq"]))
    if verbose:
        print(dict(stats))
    return {"count": len(out), "flag_base": FLAG_BASE, "batch_size": BATCH_SIZE, "locations": out}, stats


if __name__ == "__main__":
    data, stats = build(verbose=True)
    missing = [c["name"] for c in data["locations"] if not c["region"]]
    if missing:
        print("WITHOUT REGION:", len(missing), missing[:10])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print("container locations:", data["count"], "| per region:", dict(collections.Counter(c["region"] for c in data["locations"])))
