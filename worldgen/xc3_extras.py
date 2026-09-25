"""Build-time data for the XC3 additions to the manual world: filler items (gems of every level, accessories) and how each is delivered.

usage: python xc3_extras.py     ->  detect/xc3_extras.json     {"items": [...], "deliver": {item name: {"t": "give", "kind": "gem"|"accessory", "id": <ITM_* row id>, "qty": n}}}
Reads the game's data from the randomizer's unpacked BDAT JSON (see scripts/build_xc3_bdat_input.py + rando_bridge).
"""
import json
import os

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_extras.json")


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


def build():
    items, deliver = [], {}
    gem_names = {r["$id"]: r["name"] for r in rows(r"system\msg_item_gem.json")}
    seen = set()
    for r in rows(r"sys\ITM_Gem.json"):
        nm = gem_names.get(r["Name"])
        if not nm or nm in seen:
            continue
        seen.add(nm)
        item = f"Gem: {nm}"
        items.append({"name": item, "count": 0, "category": ["Filler Gem"]})
        deliver[item] = {"t": "give", "kind": "gem", "id": r["$id"], "qty": 1}

    acc_names = {r["$id"]: r["name"] for r in rows(r"system\msg_item_accessory.json")}
    chosen = {}
    for r in rows(r"sys\ITM_Accessory.json"):                         # the quality variants share a name: keep the lowest
        nm = acc_names.get(r["Name"])
        if not nm or r["Price"] <= 0 or "_DEL_" in r["ID"]:
            continue
        if nm not in chosen or r["Rarity"] < chosen[nm]["Rarity"]:
            chosen[nm] = r
    for nm, r in sorted(chosen.items(), key=lambda kv: kv[1]["$id"]):
        item = f"Accessory: {nm}"
        items.append({"name": item, "count": 0, "category": ["Filler Accessory"]})
        deliver[item] = {"t": "give", "kind": "accessory", "id": r["$id"], "qty": 1}
    # colony (region) affinity: every colony's affinity level is capped until "Progressive Affinity: <colony>" items arrive (4 copies = all 5 levels); the points are a 16-bit flag
    colony_names = {r["$id"]: r["name"] for r in rows(r"system\msg_colony_name.json")}
    for c in rows(r"fld\FLD_ColonyList.json"):
        if not c["RespectFlag"]:
            continue
        name = colony_names.get(c["Name"])
        if not name:
            continue
        item = f"Progressive Affinity: {name}"
        items.append({"name": item, "count": 4, "category": ["Colony Affinity"], "useful": True})
        deliver[item] = {"t": "affinity_cap", "flag": c["RespectFlag"], "levels": [c[f"Level{i}"] for i in range(1, 6)]}
    # main story gating: live memory hold, not a BDAT patch (see gen_story_gates2_xc3.py for why the old
    # FLD_ConditionList/GMK_Event approach - still run at patch time, harmless but ineffective - doesn't actually
    # block anything). Each beat is a main-quest task's own progress flag, held below "complete" until enough
    # Progressive Story Quest items have arrived (XC3Deliverer._cap_story).
    gates2 = json.load(open(os.path.join(os.path.dirname(OUT), "xc3_story_gates2.json"), encoding="utf-8"))
    items.append({"name": "Progressive Story Quest", "count": gates2["count"], "category": ["Story Quests"], "progression": True})
    deliver["Progressive Story Quest"] = {"t": "story_gate", "beats": gates2["beats"]}

    # container gating (rando_bridge xc3_container_gates, see gen_container_gates_xc3.py): a single repeating item
    # hands out each batch's own key item in order (XC3Deliverer._open_container_gates) - the container's own
    # GMK_TreasureBox.Condition is what the bridge patch gates, so no live memory hold is needed here (unlike story
    # gating, whose old BDAT trigger turned out not to be load-bearing for progression).
    cgates = json.load(open(os.path.join(os.path.dirname(OUT), "xc3_container_gates.json"), encoding="utf-8"))
    items.append({"name": "Progressive Container Access", "count": cgates["count"], "category": ["Container Access"], "progression": True})

    # hero access (rando_bridge xc3_hero_access, see gen_heroes_xc3.py): receiving the item lets the Hero be recruited immediately, no story/quest wait
    heroes = json.load(open(os.path.join(os.path.dirname(OUT), "xc3_heroes.json"), encoding="utf-8"))
    for h in heroes["heroes"]:
        deliver[h["name"]] = {"t": "give", "kind": "precious", "id": h["item"], "qty": 1}

    import xc3_shops
    shops = xc3_shops.build()
    json.dump(shops, open(os.path.join(os.path.dirname(OUT), "xc3_shops.json"), "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    return {"items": items, "deliver": deliver, "locations": xc3_shops.locations(shops)}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    kinds = {}
    for e in data["deliver"].values():
        key = e.get("kind", e["t"])
        kinds[key] = kinds.get(key, 0) + 1
    print("items:", len(data["items"]), "deliver:", kinds)
