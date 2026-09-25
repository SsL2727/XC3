"""Build a per-map field-enemy level summary for XC2, used by build_worlds.py to raise a region's Progressive Story
Quest requirement when the map's enemies are meaningfully higher level than its narrative story-chapter would
suggest (user decision 2026-09-23: "prevent the player from being forced to go to areas with enemies way higher
level than them").

Source: <map>_FLD_EnemyPop.json (data/common_gmk, per-map spawn placements: up to 4 enemy slots per row, each
ene{n}ID referencing a CHR_EnArrange.json row for level; ene{n}Lv is a rare per-spawn override) cross-referenced
with CHR_EnArrange's own Lv/LvMin/LvMax. Boss-named spawns ("boss_...") are excluded - those are one-off scripted
fights the story already gates independently, not ambient field danger you route around while doing checks.

We report p75 (75th percentile) of field-enemy level per map, not the median or max: median undersells the real
risk (XC2 zones mix a lot of early trash with pockets of much tougher wildlife you can't avoid while sweeping a
whole map for checks), while max is dominated by rare optional unique monsters a player can choose to avoid.
p75 is a reasonable "you will likely run into something around this level" signal without being that paranoid.

Output: detect/xc2_enemy_levels.json  {map_code: {"n": int, "median": float, "p75": float, "max": float}}
"""
import json
import statistics
from pathlib import Path

J = Path(r"F:\XCAP\work\xc2_json")
OUT = Path(__file__).resolve().parent / "detect" / "xc2_enemy_levels.json"

AREAS = ["ma03a", "ma04a", "ma05a", "ma07a", "ma08a", "ma15a", "ma10a", "ma11a", "ma13a", "ma16a", "ma17a", "ma18a", "ma20a", "ma21a"]


def build():
    arrange = {r["$id"]: r for r in json.load(open(J / "data/common/CHR_EnArrange.json", encoding="utf-8"))["rows"]}

    def enemy_level(row, n):
        eid = row.get(f"ene{n}ID", 0)
        if not eid:
            return None
        ar = arrange.get(eid)
        if ar is None:
            return row.get(f"ene{n}Lv", 0) or None
        lo, hi = ar.get("LvMin", 0), ar.get("LvMax", 0)
        base = (lo + hi) / 2 if (lo and hi) else ar.get("Lv", 0)
        return base if base else (row.get(f"ene{n}Lv", 0) or None)

    out = {}
    for area in AREAS:
        f = J / "data/common_gmk" / f"{area}_FLD_EnemyPop.json"
        if not f.exists():
            continue
        rows = json.load(open(f, encoding="utf-8"))["rows"]
        levels = []
        for row in rows:
            if str(row.get("name", "")).startswith("boss_"):
                continue
            for n in (1, 2, 3, 4):
                lv = enemy_level(row, n)
                if lv:
                    levels.append(lv)
        if not levels:
            continue
        s = sorted(levels)
        out[area] = {"n": len(s), "median": statistics.median(s), "p75": s[int(len(s) * 0.75)], "max": max(s)}
    return out


if __name__ == "__main__":
    data = build()
    OUT.parent.mkdir(exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=1)
    for area, stats in data.items():
        print(area, stats)
    print("maps:", len(data))
