"""Build the XC3 hero-access table (detect/xc3_heroes.json): which MNU_HeroDictionary PcID each 'Hero Access' item of the manual world unlocks.

The manual world's 21 "Hero Access" items (Ethel, Valdi, Zeon, ...) are not wired to anything in the game; `xc3_hero_access` (rando_bridge) needs to know
which PcID each one is.  Built by cross-referencing every Hero's recruit quest title (MNU_HeroDictionary.WakeupQuest -> QST_List.QuestTitle -> quest text)
against the location names the manual world's own 'requires' already gate behind that item (e.g. item "Zeon" gates location "Reasons to Evolve", which is
also PC_ZEON's recruit quest title) -- only pairs confirmed this way are used; the rest (crossover guests with no in-game gate, and a few Heroes whose
recruit quest is untitled/hidden so no cross-reference exists) are left out, so the client only ever touches a Hero it is sure about.

usage: python gen_heroes_xc3.py     ->  detect/xc3_heroes.json     {"heroes": [{"pc": "PC_ZEON", "name": "Zeon", "item": <ITM_Precious id>}, ...]}
"""
import json
import os

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_heroes.json")
ITEM_BASE = 16150                    # right after gen_gates_xc3.py's 23 story-gate items (16127..16149)

# item name (as it appears in the manual world's item pool) -> the PcID(s) it recruits (see the module docstring for how these were confirmed)
PC_OF = {"Zeon": ["PC_ZEON"], "Gray": ["PC_GREY"], "Riku & Manana": ["PC_RIKU", "PC_MANANA"], "Teach": ["PC_SHIDOU"], "Isurd": ["PC_ISURUGI"],
         "Ashera": ["PC_ASHERAH"], "Monica": ["PC_MONICA"], "Miyabi": ["PC_MIYABI"], "Valdi": ["PC_RUDY"], "Alexandria": ["PC_NIINA"],
         "Fiona": ["PC_MASHIRO"], "Ghondor": ["PC_GONDOU"], "Triton": ["PC_TRYDEN"]}


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


def build():
    hd = {r["PcID"] for r in rows(r"mnu\MNU_HeroDictionary.json")}
    heroes, item_id = [], ITEM_BASE
    for name, pcs in PC_OF.items():
        for pc in pcs:
            if pc not in hd:
                continue
            heroes.append({"pc": pc, "name": name, "item": item_id})
        item_id += 1
    return {"heroes": heroes}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0)
    print("heroes wired:", len(data["heroes"]), "|", ", ".join(sorted({h["name"] for h in data["heroes"]})))
