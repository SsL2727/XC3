"""Build the XC3 container-gate table (detect/xc3_container_gates.json): batches of GMK_TreasureBox rows locked
behind "Progressive Container Access" items, so undiscovered containers stop being interactable (their own
Condition field, same FLD_ConditionList mechanism story_gating uses) until enough copies have arrived.

Unlike the main story beats (see gen_story_gates2_xc3.py's postmortem on GMK_Event), GMK_TreasureBox.Condition is
the container's own real spawn/pop gate - not an ambient side-trigger - so the existing BDAT chain-splice patch
(rando_bridge._xc3_story_gates, reused here as _xc3_container_gates) is the right mechanism this time, no live
memory hold needed.

357 boxes total across 10 maps; batched (not gated one at a time - 357 individual items would be impractical
pacing) into fixed-size groups in stable (map, $id) order.
"""
import glob
import json
import os

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_container_gates.json")
ITEM_BASE = 16163                    # right after gen_heroes_xc3.py's 14 hero-access items (16150..16162)
BATCH_SIZE = 20


def build():
    boxes = []                                                 # [(map, $id)], stable order
    for f in sorted(glob.glob(os.path.join(J, r"map\*_GMK_TreasureBox.json"))):
        mp = os.path.basename(f).split("_")[0]
        for r in json.load(open(f, encoding="utf-8"))["rows"]:
            boxes.append((mp, r["$id"]))

    beats = []
    for n, i in enumerate(range(0, len(boxes), BATCH_SIZE), 1):
        batch = boxes[i:i + BATCH_SIZE]
        pops = {}
        for mp, box_id in batch:
            pops.setdefault(mp, []).append(box_id)
        beats.append({"need": n, "item": ITEM_BASE + n - 1, "label": f"Container Access {n:03d}", "pops": pops})
    return {"count": len(beats), "total_boxes": len(boxes), "batch_size": BATCH_SIZE, "beats": beats}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0)
    print("batches:", data["count"], "| total boxes:", data["total_boxes"], "| batch size:", data["batch_size"])
