"""Build the XC3 story-gate table (detect/xc3_gates.json) -- same design as gen_gates_xc2.py, adapted to XC3's data.

The main story is driven by cutscene triggers: rows of `map/<map>_GMK_Event.json` whose `Condition` resolves (through `fld/FLD_ConditionList`,
ConditionType 2) to a `fld/FLD_ConditionScenario` scenario range.  Each distinct scenario value with such a trigger is one *story quest step*
("beat"), exactly like XC2's `evt_CC_...` EventPop rows.  Every beat is locked behind one `Progressive Story Quest` item: beat n needs n items,
so the story is handed out one step at a time, in order.  The bridge patch `xc3_story_gates` inserts a new `FLD_ConditionList` row (ConditionType 6 =
FLD_ConditionItem, chained via `NextPremise` to the trigger's own condition) so the cutscene also needs the client-granted key item.

XC3's FLD_ConditionList is a linked list (one clause per row, `NextPremise` = next clause, AND semantics) rather than XC2's 8-inline-slots row, and its
condition types differ: 2 = FLD_ConditionScenario, 3 = FLD_ConditionQuest, 5 = FLD_ConditionFlag, 6 = FLD_ConditionItem (verified by cross-referencing
`Condition` values against each candidate table's own id range / row count).
"""
import glob
import json
import os

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_gates.json")
ITEM_BASE = 16127                    # new ITM_Precious rows; the game's own table ends at 16126


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


def build():
    cond_list = {r["$id"]: r for r in rows(r"fld\FLD_ConditionList.json")}
    scenario = {r["$id"]: r for r in rows(r"fld\FLD_ConditionScenario.json")}
    chapter_of = {}                                          # scenario value -> chapter number (label only, best-effort)
    for r in rows(r"evt\EVT_listEv.json"):
        chapter_of.setdefault(r["ScenarioFlag"], r["chapter"])

    beats = {}                                                # scenario value -> {map: [GMK_Event ids]}
    for f in sorted(glob.glob(os.path.join(J, r"map\*_GMK_Event.json"))):
        mp = os.path.basename(f).split("_")[0]
        for r in json.load(open(f, encoding="utf-8"))["rows"]:
            c = cond_list.get(r["Condition"])
            if not c or c["ConditionType"] != 2:
                continue
            s = scenario.get(c["Condition"])
            if not s or s["ScenarioMin"] <= 0:
                continue
            beats.setdefault(s["ScenarioMin"], {}).setdefault(mp, []).append(r["$id"])

    values = sorted(beats)
    out_beats = []
    for n, v in enumerate(values, 1):                        # beat n needs n Progressive Story Quest items
        ch = chapter_of.get(v)
        label = f"Story Step {n:03d} (Chapter {ch})" if ch else f"Story Step {n:03d}"
        out_beats.append({"need": n, "scenario": v, "item": ITEM_BASE + n - 1, "label": label, "pops": beats[v]})
    return {"count": len(values), "beats": out_beats}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0)
    print("locked beats:", data["count"], "| triggers:", sum(len(p) for b in data["beats"] for p in b["pops"].values()))
