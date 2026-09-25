"""Build-time data for XC2 shop checks (detect/xc2_shops.json + shop locations for the world).

Every slot of every item shop (MNU_ShopList ShopType 0 -> MNU_ShopNormal row, placed on a map through FLD_NpcPop.ShopID) becomes a check.  The mod gives each
slot its own new pouch item (`ITM_FavoriteList` row 40429+n, price 100 G, named after the multiworld item it holds); buying it is the check.
Two designs, chosen by the `shop_checks` option: one check per slot ("<shop> #k") or one check per shop (any purchase there).
Output: {"placeholder_base": 40429, "shops": [{"table": id, "name", "area", "region", "slots": [{"col": "DefItem1", "orig": item id, "n": placeholder index}]}]}
"""
import glob
import json
import os
import re

J = r"F:\XCAP\work\xc2_json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc2_shops.json")
PLACEHOLDER_BASE = 40429                       # ITM_FavoriteList ends at 40428

# map resource -> (area label, AP region of the manual world); Torna / Land of Challenge maps are not part of the multiworld
MAPS = {"ma02a": ("Argentum", "Free"), "ma03a": ("Maelstrom", "CSEV Maelstrom"), "ma04a": ("Ancient Ship", "Ancient Ship"),
        "ma05a": ("Gormott", "Gormott"), "ma07a": ("Uraya", "Uraya"), "ma08a": ("Mor Ardain", "Mor Ardain"),
        "ma15a": ("Leftheria", "Letheria"), "ma11a": ("Indol", "Indol"), "ma10a": ("Temperantia", "Temperantia"),
        "ma13a": ("Tantal", "Tantal"), "ma16a": ("Spirit Crucible", "Spirit"), "ma17a": ("Cliffs of Morytha", "CliffsOfMorytha"),
        "ma18a": ("Land of Morytha", "LandOfMorytha"), "ma20a": ("World Tree", "WorldTree"), "ma21a": ("Elysium", "FLOS")}


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


# quests that ask the player to BUY something must keep working: slots that sell an item some quest asks the player to hold (FLD_QuestCollect) keep their
# vanilla item (no placeholder, no check), and these shops are left alone completely (quests like "Buy one of each item sold at Llysiau Greens")
KEEP_SHOPS = ("Llysiau Greens", "Belchett Recycling", "Pookapoo")


def required_items():
    return {r["ItemID"] for r in rows(r"data\common\FLD_QuestCollect.json") if r.get("ItemID")}


def build():
    required = required_items()
    shop_list = {r["$id"]: r for r in rows(r"data\common\MNU_ShopList.json")}
    normal = {r["$id"]: r for r in rows(r"data\common\MNU_ShopNormal.json")}
    names = {r["$id"]: r["name"] for r in rows(r"text\common_ms\fld_shopname.json")}
    placed = {}                                                   # shop id -> {map: npc row} (first NPC row seen per map)
    for f in sorted(glob.glob(os.path.join(J, r"data\common_gmk\*_FLD_NpcPop.json"))):
        mp = os.path.basename(f).split("_")[0]
        for r in json.load(open(f, encoding="utf-8"))["rows"]:
            if r.get("ShopID"):
                placed.setdefault(r["ShopID"], {}).setdefault(mp, r)
    tables = {}                                                   # table id -> first placement
    for sid in sorted(placed):
        s = shop_list.get(sid)
        if not s or s["ShopType"] != 0 or not s["TableID"] or s["TableID"] not in normal:
            continue
        maps = sorted(m for m in placed[sid] if m in MAPS)
        if len(placed[sid]) != 1 or not maps:                     # roaming / multi-map vendors (courier, informant boards ...) and DLC maps are skipped
            continue
        npc = placed[sid][maps[0]]
        tables.setdefault(s["TableID"], (sid, names.get(s["Name"]) or f"Shop {sid}", maps[0], npc))
    shops, n, used = [], 0, {}
    for table, (sid, name, mp, npc) in sorted(tables.items()):
        row = normal[table]
        slots = []
        if any(k.lower() in (names.get(shop_list[sid]["Name"]) or "").lower() for k in KEEP_SHOPS):
            continue
        # user decision 2026-09-23: every shop sells exactly 5 AP items (+ whatever quest-required items it already
        # had, untouched above) and nothing else - "forgoes the need to know when shops expand" (Addtem slots
        # unlocking later, vendor conditions, etc.). First 5 non-quest-required slots become the AP placeholders;
        # _xc2_shops (run_randomizer.py) zeroes out every remaining DefItem/Addtem column that isn't one of those
        # 5 and isn't quest-required, using this same `required` set (passed through in the output below).
        for col in [f"DefItem{i}" for i in range(1, 11)] + [f"Addtem{i}" for i in range(1, 6)]:
            if len(slots) >= 5:
                break
            if row[col] and row[col] not in required:
                slots.append({"col": col, "orig": row[col], "n": n})
                n += 1
        if not slots:
            continue
        area, region = MAPS[mp]
        label = f"{area}: {name}"
        used[label] = used.get(label, 0) + 1
        if used[label] > 1:
            label += f" ({used[label]})"
        # the vendor NPC's own spawn condition: this shop's checks cannot be reachable before the NPC exists.
        # ScenarioFlagMin is directly comparable to gates.json's per-beat "scenario" (scenario // 1000 = chapter).
        # QuestFlag/QuestFlagMin/QuestFlagMax gate on a SPECIFIC quest's state (side quests, merc missions, ...) -
        # there is no AP-side detection for arbitrary quest state, so this can only be reported, not enforced.
        shops.append({"table": table, "name": label, "area": area, "region": region, "slots": slots,
                     "scenario_min": npc.get("ScenarioFlagMin", 0), "quest_flag": npc.get("QuestFlag", 0),
                     "quest_min": npc.get("QuestFlagMin", 0), "quest_max": npc.get("QuestFlagMax", 0)})
    return {"placeholder_base": PLACEHOLDER_BASE, "shops": shops, "required": sorted(required)}


def locations(data):
    """World locations: per-shop and per-slot variants (categories decide which one is active)."""
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
