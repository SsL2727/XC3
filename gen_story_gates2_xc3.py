"""Build the REAL XC3 story-gate table (detect/xc3_story_gates2.json), superseding gen_gates_xc3.py's approach.

Live-verified 2026-09-22: the old approach (patching an item requirement onto map-placed GMK_Event triggers via
FLD_ConditionList) gates the wrong thing - those triggers are ambient/side events restricted to a scenario range,
not the main story's own advance mechanism, and testing proved they impose no real block on chapter progress.

The real driver is QST_Purpose: QuestID 1-7 are the seven chapters' own main quest ("MQ_01".."MQ_07" in QST_List,
StartPurpose gives each chapter's first task), auto-advancing task by task (AutoStart=1). Each task has a `Flagld`
that is an $id into FLD_ConditionFlag, which resolves to (FlagType, FlagID) - live-confirmed FlagType selects which
width array holds the task's progress (FlagType 1 -> the 1-bit flag array, FlagType 2 -> the 2-bit array, values
0=not started/1=in progress/2=complete). FlagType 4/8 tasks exist too (7 of 148) but their value semantics were
never live-verified, so they are deliberately left out of the gate table rather than risk writing a bad value
(this project already learned the hard way once that a wrong write can freeze the game - see xc_deliver.py).

Only tasks with a CallEventA (i.e. ones that actually play a story cutscene) are gated - the other ~40% of tasks
are silent, structural-only steps.
"""
import json
import os

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_story_gates2.json")


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


def build():
    purpose = rows(r"qst\QST_Purpose.json")
    cf_by_id = {r["$id"]: r for r in rows(r"fld\FLD_ConditionFlag.json")}
    mq = [r for r in purpose if 1 <= r["QuestID"] <= 7 and r["CallEventA"]]
    mq.sort(key=lambda r: (r["QuestID"], r["TaskID"]))

    beats, skipped = [], 0
    for r in mq:
        flag = cf_by_id.get(r["Flagld"])
        if flag is None or flag["FlagType"] not in (1, 2):
            skipped += 1
            continue
        beats.append({"chapter": r["QuestID"], "task": r["TaskID"], "flag_type": flag["FlagType"], "flag_id": flag["FlagID"],
                      "label": f"Chapter {r['QuestID']} Story Beat {r['TaskID']}"})
    return {"count": len(beats), "skipped": skipped, "beats": beats}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0)
    print("beats:", data["count"], "| skipped (unverified flag width):", data["skipped"])
