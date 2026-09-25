"""Build-time data for the XC2 additions to the manual world: extra rare blades (crystals), filler items, and how each is delivered in game.

usage: python xc2_extras.py     ->  detect/xc2_extras.json
  {"items":   [item entries appended to the world's item list],
   "deliver": {item name: effect},                (effects are interpreted by xc_deliver.XC2Deliverer)
   "story_blades": {item name: blade id}}         (blades the story hands out itself; they gate story progress, nothing is delivered)
Effects:  {"t": "blade_crystal", "blade": <CHR_Bl id>}            the blade's own core crystal goes into the inventory
          {"t": "give", "box": "accessory"|"pouch", "id": <ITM_* row id>, "qty": n}
          {"t": "trust_cap", "blades": [<CHR_Bl id>, ...] | "all", "max": 4}   blade trust hearts are capped at 1 + copies received
"""
import json
import os
import re

J = r"F:\XCAP\work\xc2_json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc2_extras.json")

# AP item name -> CHR_Bl id.  Blades of the manual world that come from a core crystal ...
CRYSTAL_BLADES = {"Roc": 1008, "Aegaeon": 1014, "Wulfric": 1016, "Vale": 1018, "Agate": 1019, "Gorg": 1020, "Boreas": 1021,
                  "Perun": 1026, "Kora": 1027, "Ursula": 1029, "Newt": 1030, "Nim": 1031, "Sheba": 1032, "Adenine": 1034,
                  "Zenobia": 1036, "Floren": 1038, "KOS-MOS": 1039, "Herald": 1040}
ALIASES = {"Roc's Core Crystal": "Roc"}                       # story items of the manual world that are the same crystal
# ... and blades the story itself awakens (no crystal exists for them)
STORY_BLADES = {"Pyra": 1001, "Aegis True Form": 1002, "Dromarch": 1004, "Poppi a": 1005, "Poppi QT": 1006, "Poppi QT Pi": 1007,
                "Pandoria": 1010, "Sever": 1042, "Dagas": 1022}
# rare blades that are not in the manual world's pool: added as extra (non-progression) items
EXTRA_BLADES = [1015, 1017, 1023, 1024, 1025, 1028, 1033, 1035, 1037, 1041, 1104, 1105, 1106, 1107, 1108, 1109, 1111]

# blades whose trust has its own item in "per blade" mode (Pyra also covers Mythra's record; the other story blades are separate)
TRUST_BLADES = {name: [bid] for name, bid in {**CRYSTAL_BLADES, **STORY_BLADES}.items() if name != "Aegis True Form"}
TRUST_BLADES["Pyra"] = [1001, 1002]
TRUST_STEPS = 4                                               # hearts 2..5

ACCESSORY_ZONES_SKIPPED = {0, 58}                             # 0 = Torna-only rows, 58 = DLC costume accessories


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


def build():
    blade_names = {r["$id"]: r["name"] for r in rows(r"text\common_ms\chr_bl_ms.json")}
    chr_bl = {r["$id"]: r for r in rows(r"data\common\CHR_Bl.json")}
    items, deliver = [], {}

    for name, bid in CRYSTAL_BLADES.items():
        deliver[name] = {"t": "blade_crystal", "blade": bid}
    for alias, name in ALIASES.items():
        deliver[alias] = {"t": "blade_crystal", "blade": CRYSTAL_BLADES[name]}
    for bid in EXTRA_BLADES:
        name = blade_names[chr_bl[bid]["Name"]]
        items.append({"name": name, "count": 1, "category": ["Extra Blades"], "progression": True})     # progression: the field skill logic counts them
        deliver[name] = {"t": "blade_crystal", "blade": bid}

    # blade trust: one shared "Progressive Blade Trust" (x4) or one "<blade> Trust" (x4) per blade, chosen by the trust_per_blade option
    items.append({"name": "Progressive Blade Trust", "count": TRUST_STEPS, "category": ["Trust Global"], "progression": True})
    deliver["Progressive Blade Trust"] = {"t": "trust_cap", "blades": "all", "max": TRUST_STEPS}
    for bid in EXTRA_BLADES:
        TRUST_BLADES.setdefault(blade_names[chr_bl[bid]["Name"]], [bid])
    for name, ids in TRUST_BLADES.items():
        items.append({"name": f"{name} Trust", "count": TRUST_STEPS, "category": ["Trust Blade"], "progression": True})
        deliver[f"{name} Trust"] = {"t": "trust_cap", "blades": ids, "max": TRUST_STEPS}

    equip = rows(r"data\common\ITM_PcEquip.json")
    equip_names = {r["$id"]: r["name"] for r in rows(r"text\common_ms\itm_pcequip.json")}
    chosen = {}
    for r in equip:                                                # the three quality variants share a name: keep the lowest
        nm = equip_names.get(r["Name"])
        if not nm or r["Zone"] in ACCESSORY_ZONES_SKIPPED or r["Price"] <= 0:
            continue
        if nm not in chosen or r["Rarity"] < chosen[nm]["Rarity"]:
            chosen[nm] = r
    for nm, r in sorted(chosen.items(), key=lambda kv: kv[1]["$id"]):
        item = f"Accessory: {nm}"
        items.append({"name": item, "count": 0, "category": ["Filler Accessory"]})
        deliver[item] = {"t": "give", "box": "accessory", "id": r["$id"], "qty": 1}

    fav = rows(r"data\common\ITM_FavoriteList.json")
    fav_names = {r["$id"]: r["name"] for r in rows(r"text\common_ms\itm_favorite.json")}
    seen = set()
    for r in fav:
        nm = fav_names.get(r["Name"])
        if not nm or nm in seen:
            continue
        seen.add(nm)
        item = f"Pouch: {nm} x5"
        items.append({"name": item, "count": 0, "category": ["Filler Pouch"]})
        deliver[item] = {"t": "give", "box": "pouch", "id": r["$id"], "qty": 5}

    # Core Chips (Poppi's Role chips - ITM_HanaRole, box "corechip") and Aux Cores (Poppi's Assist mods -
    # ITM_HanaAssist, box "auxcore") as filler, per user decision 2026-09-23. Condition (most rows have one,
    # referencing an FLD_ConditionList row) is the VANILLA crafting-unlock gate, irrelevant here since these are
    # placed directly into the inventory by xc2_add_item, bypassing crafting entirely - not filtered on.
    role_names = {r["$id"]: r["name"] for r in rows(r"text\common_ms\itm_hana_role_ms.json")}
    for r in rows(r"data\common\ITM_HanaRole.json"):
        nm = role_names.get(r["Name"])
        if not nm:
            continue
        item = f"Core Chip: {nm}"
        items.append({"name": item, "count": 0, "category": ["Filler Core Chip"]})
        deliver[item] = {"t": "give", "box": "corechip", "id": r["$id"], "qty": 1}

    # ITM_HanaAssist's "Name" field points into text\common_ms\itm_orb.json ("orb" = the internal name for what
    # the English localization calls Aux Cores, e.g. "Critical Up I", "Aquatic Hunter IV" - matches the Xenoblade
    # wiki's Aux Core listing, confirmed 2026-09-23).
    orb_names = {r["$id"]: r["name"] for r in rows(r"text\common_ms\itm_orb.json")}
    for r in rows(r"data\common\ITM_HanaAssist.json"):
        nm = orb_names.get(r["Name"])
        if not nm:
            continue
        item = f"Aux Core: {nm}"
        items.append({"name": item, "count": 0, "category": ["Filler Aux Core"]})
        deliver[item] = {"t": "give", "box": "auxcore", "id": r["$id"], "qty": 1}

    import xc2_shops
    shops = xc2_shops.build()
    json.dump(shops, open(os.path.join(os.path.dirname(OUT), "xc2_shops.json"), "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    return {"items": items, "deliver": deliver, "story_blades": STORY_BLADES, "locations": xc2_shops.locations(shops)}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    kinds = {}
    for e in data["deliver"].values():
        kinds[e["t"] + ("/" + e["box"] if "box" in e else "")] = kinds.get(e["t"] + ("/" + e["box"] if "box" in e else ""), 0) + 1
    print("items:", len(data["items"]), "deliver:", kinds)
