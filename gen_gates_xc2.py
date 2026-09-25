"""Build the XC2 story-gate table (detect/xc2_gates.json).

The main story is driven by cutscene triggers: rows of `common_gmk/maNNa_FLD_EventPop.json` (story ones are named `evt_CC_...`, narrow scenario range,
`Condition` = FLD_ConditionList id).  Each distinct scenario value with such a trigger is one *story quest step* ("beat").  Every beat after the prologue in
Argentum is locked behind one `Progressive Story Quest` item: beat n needs n items, so the story is handed out one step at a time, in order.
The bridge patch `xc2_story_gates` adds `1-bit flag == 1` to the Condition of every trigger of a locked beat; the client sets that flag when enough items arrived.

Logic: the manual world gated regions by `Progressive Area:k`.  Region tier k now needs `Progressive Story Quest:R_k` where R_k = the number of locked beats before the
story enters the next known tier (sound: it is the count needed to finish everything in the region).  build_worlds rewrites the rules from `requirements`.
"""
import glob
import json
import os
import re

J = r"F:\XCAP\work\xc2_json\data\common_gmk"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc2_gates.json")
FLAG_BASE = 65000                    # 1-bit flag ids (array of 65536); nothing in the game data references these

# tier of the manual world -> (map, first scenario step of that region's story); tiers 5, 7 and 11 have no known entry step and merge with the previous one
ARRIVALS = {1: 1017, 2: 1020, 3: 2002, 4: 3008, 6: 4014, 8: 5009, 9: 5023, 10: 5044, 12: 6034, 13: 7006, 14: 7019, 15: 7044, 16: 8004, 17: 8032, 18: 10002}
ITEM_BASE = 25500                    # new key items (ITM_PreciousList rows) that unlock the steps; ITM_PreciousList ends at 25499
AREAS = {"ma02a": "Argentum", "ma03a": "Maelstrom", "ma04a": "Ancient Ship", "ma05a": "Gormott", "ma07a": "Uraya", "ma08a": "Mor Ardain",
         "ma10a": "Temperantia", "ma11a": "Indol", "ma13a": "Tantal", "ma15a": "Leftheria", "ma16a": "Spirit Crucible", "ma17a": "Cliffs of Morytha",
         "ma18a": "Land of Morytha", "ma20a": "World Tree", "ma21a": "Elysium", "ma30a": "Elysium Dream"}
FIRST_LOCKED = int(os.environ.get("XC2_GATE_FIRST", 1017))                  # the Argentum prologue (scenario steps before the Maelstrom) stays open: the manual world's 'Free' region needs no items
ALL_TIERS = list(range(1, 19))


def build():
    beats = {}
    for f in sorted(glob.glob(os.path.join(J, "*_FLD_EventPop.json"))):
        mp = os.path.basename(f).split("_")[0]
        for r in json.load(open(f, encoding="utf-8"))["rows"]:
            if (r["EventID"] and r["ScenarioFlagMax"] - r["ScenarioFlagMin"] <= 3 and 1001 <= r["ScenarioFlagMin"] < 10050
                    and r["name"].startswith("evt_") and not r["name"].startswith("evt_qst")):
                beats.setdefault(r["ScenarioFlagMin"], {}).setdefault(mp, []).append(r["$id"])
    values = sorted(beats)
    locked = [v for v in values if v >= FIRST_LOCKED]
    out_beats = []
    for n, v in enumerate(locked, 1):                       # beat n needs n Progressive Story Quest items
        area = AREAS.get(sorted(beats[v])[0], sorted(beats[v])[0])
        out_beats.append({"need": n, "scenario": v, "flag": FLAG_BASE + n, "item": ITEM_BASE + n - 1, "label": f"Story Step {n:03d} ({area})",
                          "pops": beats[v]})
    # per user decision 2026-09-23: don't gate the ONE beat right after the Brighid fight in Torigoth. The fight
    # itself (CHR_EnArrange 187/1434, FLD_EnemyPop boss_ma05a04_01) isn't part of this beat system at all - it's
    # an enemy spawn (ScenarioFlagMin/Max=2019 exactly), gated purely by raw scenario progress, not by an
    # AP-patched trigger condition. It sits between beat 9 (scenario 2014) and beat 10 (scenario 2022), so beat 10
    # is the next cutscene trigger the story hits right after winning that fight - live-confirmed 2026-09-23 as
    # the softlock point (game froze entering that cutscene with Progressive Story Quest short of what it
    # needed). The key item still exists and is still tracked/deliverable for count purposes; only the CONDITION
    # PATCH onto its own trigger(s) is skipped (see xc2_story_gates in run_randomizer.py), so the story can
    # advance past it immediately without waiting on an item at all.
    NO_GATE_AFTER_BRIGHID = 10
    for b in out_beats:
        if b["need"] == NO_GATE_AFTER_BRIGHID:
            b["skip_gate"] = True

    index = {v: n for n, v in enumerate(locked, 1)}           # scenario value -> beat number
    known = sorted(ARRIVALS)
    req = {}
    for tier in ALL_TIERS:
        later = [t for t in known if t > tier]
        req[str(tier)] = (index[ARRIVALS[later[0]]] - 1) if later else len(locked)
    return {"flag_type": 1, "count": len(locked), "beats": out_beats, "requirements": req}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0)
    print("locked beats:", data["count"], "| triggers:", sum(len(p) for b in data["beats"] for p in b["pops"].values()))
    print("requirements:", data["requirements"])
