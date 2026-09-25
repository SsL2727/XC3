"""Build-time data for XC3 shop checks (detect/xc3_shops.json + shop locations for the world).

Same design as XC2 (see xc2_shops.py): every slot of every commissary / caravan (MNU_ShopList ShopType 0 / 1 -> MNU_ShopTable) is sold as its own new accessory
(`ITM_Accessory` row 777+n, price 100 G, named after the multiworld item behind it); buying it is the check.  One check per shop or one per slot (option `shop_checks`).
The manual world's own "Buy <item>" checks in four of these shops are switched off when shop checks are on (they would be impossible: the slots hold placeholders).
Regions: the colony / area a shop stands in, taken from how the manual world files other checks with the same place name; unknown places get a late region (sound).
"""
import json
import os

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc3_shops.json")
PLACEHOLDER_BASE = 777                        # ITM_Accessory ends at 776

# name fragment -> AP region of the manual XC3 world (first match wins)
REGIONS = [("Colony 9", "Yzana Plains"), ("Battlescar", "Everblight Plain"), ("Gamma", "Alfeto Valley"), ("Hilltop", "Alfeto Valley"),
           ("Colony 4", "Eagus Wilderness"), ("Wilderness", "Eagus Wilderness"), ("Colony 30", "Ribbi Flats"), ("Colony Iota", "Elaice Highway"),
           ("Tableland", "Rae-Bel Tableland"), ("Terrace", "Rae-Bel Tableland"), ("Desert", "Dannagh Desert"), ("Tunnel", "Urayan Tunnels"),
           ("Clifftop", "Urayan Trail"), ("Colony Lambda", "Great Cotte Falls"), ("Cascade", "Great Cotte Falls"), ("Valley", "Great Cotte Falls"),
           ("Lambda", "Great Cotte Falls"), ("Old Way", "Old Cliffside Way"), ("Colony Tau", "High Maktha Wildwood"), ("Colony 11", "Syra Hovering Reefs"),
           ("Reef", "Syra Hovering Reefs"), ("Colony Mu", "Erythia Sea"), ("Atoll", "Erythia Sea"), ("Island", "Erythia Sea"), ("Inlet", "Erythia Sea"),
           ("Sandbar", "Erythia Sea"), ("Peak", "Captocorn Peak"), ("City", "City"), ("Castle", "Keves Castle"), ("Ascension", "Keves Castle")]
DEFAULT_REGION = "Erythia Sea"                # shops whose place is not known for sure (Lakeside, Pass, O'Virbus, Korresia, Handypon, Illicit, Drahaga ...): late, so sound


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


# purchases the story asks for must stay possible: the tutorial quest "Preparing for Battle" is "Buy a Bronze Temple Guard from Camilla" (Colony 9 Commissary).  Slots selling an
# accessory that a quest asks the player to hold (QST_TaskCollect) or that the tutorial names keep their vanilla item (no placeholder, no check); these shops are left alone completely
KEEP_ITEMS = {1, 2, 3}                           # Bronze / Iron / Titanium Temple Guard
KEEP_SHOPS = ("Wellwell",)                       # "go to Wellwell's store to see if you can buy a novel"


def required_items():
    out = set(KEEP_ITEMS)
    for r in rows(r"qst\QST_TaskCollect.json"):
        if 0 < r["TargetID"] < PLACEHOLDER_BASE:
            out.add(r["TargetID"])
    return out


def build():
    required = required_items()
    shop_list = rows(r"mnu\MNU_ShopList.json")
    tables = {r["$id"]: r for r in rows(r"mnu\MNU_ShopTable.json")}
    names = {r["$id"]: r["name"] for r in rows(r"system\msg_shop_name.json")}
    seen, shops, n, used = set(), [], 0, {}
    for s in shop_list:
        if s["ShopType"] not in (0, 1) or s["TableID"] in seen or s["TableID"] not in tables:
            continue
        name = names.get(s["Name"])
        if not name:
            continue
        seen.add(s["TableID"])
        row = tables[s["TableID"]]
        slots = []
        if any(k.lower() in name.lower() for k in KEEP_SHOPS):
            continue
        for i in range(1, 21):
            if row[f"ShopItem{i}"] and row[f"ShopItem{i}"] not in required:
                slots.append({"col": f"ShopItem{i}", "orig": row[f"ShopItem{i}"], "n": n})
                n += 1
        if not slots:
            continue
        region = next((r for frag, r in REGIONS if frag.lower() in name.lower()), DEFAULT_REGION)
        label = name
        used[label] = used.get(label, 0) + 1
        if used[label] > 1:
            label += f" ({used[label]})"
        shops.append({"table": s["TableID"], "name": label, "region": region, "slots": slots})
    return {"placeholder_base": PLACEHOLDER_BASE, "shops": shops}


def locations(data):
    out = []
    for s in data["shops"]:
        out.append({"name": f"Shop {s['name']}", "region": s["region"], "category": ["Shops"], "requires": ""})
        for k, _slot in enumerate(s["slots"], 1):
            out.append({"name": f"Shop {s['name']} #{k}", "region": s["region"], "category": ["Shop Slots"], "requires": ""})
    return out


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    total = sum(len(s["slots"]) for s in data["shops"])
    print(len(data["shops"]), "shops,", total, "slots")
    from collections import Counter
    print(Counter(s["region"] for s in data["shops"]))
    print([s["name"] for s in data["shops"] if s["region"] == DEFAULT_REGION])
