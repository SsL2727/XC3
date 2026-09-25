"""Build the XC3 item-delivery table (detect/xc3_deliver.json).

outfit       : "<Class> Outfit - <Character>"  ->  2-bit flag from RSC_PcCostumeOpen (row = class, FlagN = character id N).
               Live-verified: 0 = outfit hidden in Clothing list, 1 = unlocked (shown with the NEW dot), 2 = unlocked and seen.
               Character ids (flag columns): Noah 1, Mio 2, Eunie 3, Taion 4, Lanz 5, Sena 6.
class access : "<Class> - <Character>" (category "Class Access - <Character>") -> the SAME RSC_PcCostumeOpen flag as the
               matching outfit item (111 of 117 class-access items match an outfit item's class+character exactly; the
               rest are naming mismatches - e.g. "Souhacker" vs "Soulhacker" - between the manual world's two copies of
               the class list). Both the outfit and class-access entries for a shared flag list each other in "also", so
               receiving either one sets it and receiving only one of the two never relocks what the other set (see
               XC3Deliverer.apply's flag2 handling in xc_deliver.py).
key item     : any "Key Items" item that is also the exact display name of a native ITM_Precious row - given directly via
               the same "give precious item" path as Hero Access (xc3_add_item(..., "precious", id, ...)). Covers most of
               the manual world's "Key Items" (87 of 93 as of this writing); the rest (e.g. "Lucky Seven License") have no
               matching native precious item and are not yet delivered - see the "missing" list this script prints.
plus every effect of detect/xc3_extras.json (gem / accessory filler; run xc3_extras.py first).
"""
import json
import os
import re

J = r"F:\XCAP\work"
RANDO_JSON = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"      # more complete than J\xc3_json\data (e.g. has "Abandoned Resources"); same source xc3_extras.py/gen_gates_xc3.py use
WORLD = r"G:\Archipelago\xc-tools\worldgen\out\xenoblade_3\data"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_deliver.json")
CHAR_ID = {"Noah": 1, "Mio": 2, "Eunie": 3, "Taion": 4, "Lanz": 5, "Sena": 6}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _class_lookup():
    """class-name (normalized) -> BTL_Talent row, restricted to rows with an RSC_PcCostumeOpen entry (Flag1..6)."""
    names = {r["$id"]: [v for v in r.values() if isinstance(v, str)][-1]
             for r in json.load(open(J + r"\xc3_json4\battle_en\EA640EBA.json", encoding="utf-8"))["rows"]}
    tal = json.load(open(J + r"\xc3_json2\btl\BTL_Talent.json", encoding="utf-8"))["rows"]
    cos = json.load(open(J + r"\xc3_json\data\sys\RSC_PcCostumeOpen.json", encoding="utf-8"))["rows"]
    row_of_talent = {c["Talent"]: c for c in cos if c["Talent"]}
    class_id = {}
    for t in tal:                       # several talent rows share a name (e.g. Yumsmith): keep the one that has a costume row
        n = norm(names.get(t["Name"], ""))
        if n and (n not in class_id or t["$id"] in row_of_talent):
            class_id[n] = t["$id"]
    return class_id, row_of_talent


def _costume_flag(cls: str, who: str, class_id: dict, row_of_talent: dict):
    tid = class_id.get(norm(cls))
    row = row_of_talent.get(tid) if tid else None
    cid = CHAR_ID.get(who)
    return row.get(f"Flag{cid}") if (row and cid) else 0


def build_meal_recipes(items):
    """"Manana's Menu" (`<dish> Recipe` items): 1-bit flag straight from FLD_MealRecipe.OpenFlag (0 = no flag needed,
    already unlocked - skipped). Returns (mapping, names with no matching/flagged recipe row)."""
    text = {r["$id"]: r["name"] for r in json.load(open(RANDO_JSON + r"\field\8B7D949B.json", encoding="utf-8"))["rows"]}
    recipes = json.load(open(RANDO_JSON + r"\fld\FLD_MealRecipe.json", encoding="utf-8"))["rows"]
    by_dish = {}
    for r in recipes:
        nm = text.get(r["Name"])
        if nm and r["OpenFlag"]:
            by_dish[nm] = r["OpenFlag"]
    out, missing = {}, []
    for it in items:
        if "Manana's Menu" not in (it.get("category") or []):
            continue
        m = re.match(r"^(.*) Recipe$", it["name"])
        flag = by_dish.get(m.group(1)) if m else None
        if flag:
            out[it["name"]] = {"t": "flag1", "i": flag}
        else:
            missing.append(it["name"])
    return out, missing


def build_key_items(items):
    """"Key Items" (and any other category) items that are natively real ITM_Precious rows in the base game: give
    directly. Returns (mapping, names with no native match)."""
    msg = json.load(open(RANDO_JSON + r"\system\msg_item_precious.json", encoding="utf-8"))["rows"]
    text = {r["$id"]: r["name"] for r in msg}
    precious = json.load(open(RANDO_JSON + r"\sys\ITM_Precious.json", encoding="utf-8"))["rows"]
    by_name = {}
    for r in precious:
        nm = text.get(r["Name"])
        if nm:
            by_name.setdefault(nm, r["$id"])
    out, missing = {}, []
    for it in items:
        if "Key Items" not in (it.get("category") or []):
            continue
        pid = by_name.get(it["name"])
        if pid:
            out[it["name"]] = {"t": "give", "kind": "precious", "id": pid, "qty": 1}
        else:
            missing.append(it["name"])
    return out, missing


def build():
    class_id, row_of_talent = _class_lookup()
    items = json.load(open(WORLD + r"\items.json", encoding="utf-8"))
    out, missing = {}, []
    for it in items:
        cat = it["category"][0]
        m = re.match(r"^(.*) Outfit - (\w+)$", it["name"])
        if not (cat.startswith("Outfits") and m):
            continue
        cls, who = m.group(1), m.group(2)
        flag = _costume_flag(cls, who, class_id, row_of_talent)
        if flag:
            out[it["name"]] = {"t": "flag2", "i": flag, "grant": 1}
        else:
            missing.append(it["name"])
    return out, missing


def build_class_access(items, outfit_entries):
    """"Class Access - <Char>" items: the same RSC_PcCostumeOpen flag as the matching Outfit item (see module
    docstring). Also back-links the outfit entry to the class-access name so either one can set the flag without
    the other relocking it. Returns (class-access mapping, names with no resolvable class+character flag)."""
    class_id, row_of_talent = _class_lookup()
    out, missing = {}, []
    for it in items:
        if not any(c.startswith("Class Access") for c in (it.get("category") or [])):
            continue
        m = re.match(r"^(.*) - (\w+)$", it["name"])
        if not m:
            missing.append(it["name"])
            continue
        cls, who = m.group(1), m.group(2)
        flag = _costume_flag(cls, who, class_id, row_of_talent)
        if not flag:
            missing.append(it["name"])
            continue
        out[it["name"]] = {"t": "flag2", "i": flag, "grant": 1, "also": []}
        outfit_name = f"{cls} Outfit - {who}"
        if outfit_name in outfit_entries:
            out[it["name"]]["also"] = [outfit_name]
            outfit_entries[outfit_name].setdefault("also", []).append(it["name"])
    return out, missing


if __name__ == "__main__":
    items, missing = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print("outfit items mapped:", len(items), "missing:", missing)
    all_items = json.load(open(WORLD + r"\items.json", encoding="utf-8"))
    key_items, key_missing = build_key_items(all_items)
    print("key items mapped:", len(key_items), "missing (no native match):", key_missing)
    class_items, class_missing = build_class_access(all_items, items)
    print("class access items mapped:", len(class_items), "missing (no resolvable flag):", class_missing)
    recipe_items, recipe_missing = build_meal_recipes(all_items)
    print("recipe items mapped:", len(recipe_items), "missing:", recipe_missing)
    items.update(key_items)
    items.update(class_items)
    items.update(recipe_items)
    items.update(json.load(open(os.path.join(os.path.dirname(OUT), "xc3_extras.json"), encoding="utf-8"))["deliver"])
    json.dump({"items": items}, open(OUT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print("delivery entries:", len(items))
