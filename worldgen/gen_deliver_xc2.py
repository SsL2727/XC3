"""Build the XC2 item-delivery table: AP item name -> how to apply it to the running game.

Output: detect/xc2_deliver.json  {"items": {name: {...}}, "vanilla_crystals": {blade id: crystal id},
                                  "story_blades": {item name: blade id}}
built entirely from detect/xc2_extras.json (blade crystals, accessory / pouch filler; run xc2_extras.py first).

art_cap (driver art level caps) removed entirely 2026-09-23 per user decision - unreliable in live testing
("Drivers aren't working"). This script used to also map "<Driver> Arts"-category items to BTL_Arts_Dr rows and
clamp their level; that mapping and the corresponding item-pool entries are both gone now.
"""
import json
import os

J = r"F:\XCAP\work\xc2_json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc2_deliver.json")


if __name__ == "__main__":
    extras = json.load(open(os.path.join(os.path.dirname(OUT), "xc2_extras.json"), encoding="utf-8"))
    items = dict(extras["deliver"])
    crystals = json.load(open(J + r"\data\common\ITM_CrystalList.json", encoding="utf-8"))["rows"]
    vanilla = {str(r["BladeID"]): r["$id"] for r in crystals if r["BladeID"] and r["$id"] >= 45002}
    json.dump({"items": items, "vanilla_crystals": vanilla, "story_blades": extras["story_blades"]},
              open(OUT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print("delivery entries:", len(items))
