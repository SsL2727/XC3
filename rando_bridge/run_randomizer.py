"""Headless driver for the Xenoblade Series Randomizer (third-party, GUI-only) so the Archipelago clients can build a game mod from slot data.

usage: python run_randomizer.py <config.json>
config = {
  "game": "XC2" | "XC3" | "XCDE",
  "randomizer_root": "<extracted Xenoblade-Series-Randomizer dir>",      (a working copy is made under work_dir)
  "bdat_dir": "<dir with the game's extracted BDATs (XC2: common.bdat, common_gmk.bdat, gb/common_ms.bdat)>",
  "out_dir": "<atmosphere/contents-style output dir; the mod lands in <out_dir>/<titleid>/romfs/bdat>",
  "work_dir": "<scratch dir>",
  "seed": "text",
  "options": {"<Option name>": true | false | {"on": true, "spin": 5, "sub": {"<Sub name>": true | false | {"on": true, "spin": 20}}}}
}
The randomizer's own option objects (scripts/Interactables.py) are driven exactly like its GUI does: state variables are set, the enabled
options' commands run in priority order, then the JSON is packed back into BDATs with bdat-toolset.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import traceback


def _xc2_blade_crystals(game, root_copy, json_out, ap_map, cfg):
    """Every rare blade gets its own core crystal (the randomizer's custom crystals), so a blade can be sent as a single item.
    Writes ap_map["blade_crystals"] = {blade id: crystal item id}."""
    import XC2.XC2_Scripts.CoreCrystals as CoreCry               # noqa: E402
    from XC2.XC2_Scripts import IDs                              # noqa: E402
    # RareBladeProbabilityEqualizer rewrites the gacha table's probability columns (BLD_RareList) and makes the game hang while loading;
    # the gacha is not part of this project, so it is always skipped.  "debug_skip" (config) neutralises further steps when bisecting.
    for name in ["RareBladeProbabilityEqualizer"] + list(cfg.get("debug_skip", [])):
        setattr(CoreCry, name, lambda *a, **k: None)
    CoreCry.CustomCoreCrystalRando()                             # no-op when a crystal option of the randomizer already ran it
    rows = json.load(open(os.path.join(json_out, "common", "ITM_CrystalList.json"), encoding="utf-8"))["rows"]
    mapping = {str(r["BladeID"]): r["$id"] for r in rows if r["$id"] in IDs.CustomCrystalIDs}
    if len(mapping) != len(IDs.CustomCrystalIDs):
        raise RuntimeError(f"blade crystals are not unique ({len(mapping)} blades for {len(IDs.CustomCrystalIDs)} crystals)")
    ap_map["blade_crystals"] = mapping


def _dump(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _xc2_story_gates(game, root_copy, json_out, ap_map, cfg):
    """Lock story steps until the player holds the step's unlock item.  cfg["gates"] = {"beats": [{"need", "item", "label", "pops": {map: [FLD_EventPop ids]}}]}
    (see worldgen/gen_gates_xc2.py).  Every beat gets a new key item (ITM_PreciousList row `item`, named after the step); the beat's cutscene triggers get
    `player has that item` (FLD_ConditionItem row, ConditionType 5) added to their Condition, so that step of the main story cannot start before the client hands
    the item over.  gates["always"] = test mode: the condition is FLD_ConditionScenario row 1 (always true)."""
    gates = cfg["gates"]
    d = lambda n: os.path.join(json_out, "common", f"{n}.json")
    txt_path = os.path.join(json_out, "common_ms", "itm_precious.json")
    cond_item = json.load(open(d("FLD_ConditionItem"), encoding="utf-8"))
    conds = json.load(open(d("FLD_ConditionList"), encoding="utf-8"))
    keys = json.load(open(d("ITM_PreciousList"), encoding="utf-8"))
    txt = json.load(open(txt_path, encoding="utf-8"))
    by_id = {r["$id"]: r for r in conds["rows"]}
    template = next(r for r in keys["rows"] if r["$id"] == 25499)
    next_ci = max(r["$id"] for r in cond_item["rows"]) + 1
    next_cond = max(r["$id"] for r in conds["rows"]) + 1
    next_text = max(r["$id"] for r in txt["rows"]) + 1
    pop_files = {}
    skipped, gated = [], 0
    for beat in gates["beats"]:
        new_key = dict(template)
        new_key.update({"$id": beat["item"], "Name": next_text, "Caption": next_text + 1, "ValueMax": 1, "ClearNewGame": 0, "NoMultiple": 0})
        for col in [c for c in new_key if c.startswith("sort")]:
            new_key[col] = beat["item"]
        keys["rows"].append(new_key)
        txt["rows"].append({"$id": next_text, "style": 36, "name": beat["label"]})
        txt["rows"].append({"$id": next_text + 1, "style": 61, "name": "Unlocks the next step of the main story. Received from the multiworld."})
        next_text += 2
        cond_item["rows"].append({"$id": next_ci, "ItemCategory": 0, "ItemID": beat["item"], "Number": 1})
        ctype, cid = (1, 1) if gates.get("always") else (5, next_ci)      # 1 = FLD_ConditionScenario, 5 = FLD_ConditionItem
        next_ci += 1
        if beat.get("skip_gate"):          # per-beat opt-out (gen_gates_xc2.py) - item still exists/still delivered, its
            continue                       # own trigger(s) just never get the "player has item" condition added
        for mp, ids in beat["pops"].items():
            if mp not in pop_files:
                path = os.path.join(json_out, "common_gmk", f"{mp}_FLD_EventPop.json")
                pop_files[mp] = (path, json.load(open(path, encoding="utf-8")))
            for row in pop_files[mp][1]["rows"]:
                if row["$id"] not in ids:
                    continue
                old = by_id.get(row["Condition"]) if row["Condition"] else None
                if old is None:
                    new = {"$id": next_cond, "Premise": 0}
                    for k in range(1, 9):
                        new[f"ConditionType{k}"] = ctype if k == 1 else 0
                        new[f"Condition{k}"] = cid if k == 1 else 0
                else:                                            # keep the trigger's own condition and add ours (AND)
                    free = [k for k in range(1, 9) if old[f"ConditionType{k}"] == 0]
                    if old["Premise"] != 0 or not free:
                        skipped.append((mp, row["$id"]))
                        continue
                    new = dict(old)
                    new["$id"] = next_cond
                    new[f"ConditionType{free[0]}"] = ctype
                    new[f"Condition{free[0]}"] = cid
                conds["rows"].append(new)
                by_id[next_cond] = new
                row["Condition"] = next_cond
                next_cond += 1
                gated += 1
    for path, data in pop_files.values():
        _dump(path, data)
    _dump(d("FLD_ConditionItem"), cond_item)
    _dump(d("FLD_ConditionList"), conds)
    _dump(d("ITM_PreciousList"), keys)
    _dump(txt_path, txt)
    ap_map["story_gates"] = {str(b["need"]): b["item"] for b in gates["beats"]}
    print(f"story gates: {gated} story triggers locked over {len(gates['beats'])} steps" + (f"; SKIPPED {skipped}" if skipped else ""))


def _xc2_fast_travel(game, root_copy, json_out, ap_map, cfg):
    """Always-on (user decision 2026-09-23): every landmark's own warp condition (FLD_LandmarkPop.stoff_cndID,
    the game's own gate on whether you can currently fast-travel TO that landmark - separate from cndID, which
    gates whether it's even visible/discovered) gets zeroed out, so any already-discovered landmark can always be
    warped to regardless of story/quest state. This is the softlock escape hatch: if a scripted event ever hangs
    the game with story items still short of what a trigger needed, the player can open the map and warp away
    (menu access permitting) instead of being stuck. Purely a game-data patch - no live memory tracking needed,
    unlike the position/cutscene-state investigation earlier this session which hit real technical walls."""
    import glob
    cleared, seen_maps = 0, 0
    for path in sorted(glob.glob(os.path.join(json_out, "common_gmk", "*_FLD_LandmarkPop.json"))):
        data = json.load(open(path, encoding="utf-8"))
        changed = False
        for row in data["rows"]:
            if row.get("stoff_cndID", 0):
                row["stoff_cndID"] = 0
                cleared += 1
                changed = True
        if changed:
            _dump(path, data)
        seen_maps += 1
    ap_map["fast_travel_unlocked"] = True
    print(f"fast travel: cleared {cleared} landmark warp-condition(s) across {seen_maps} map(s) - every "
          f"discovered landmark can always be fast-traveled to")


def _xc2_no_crystal_drops(game, root_copy, json_out, ap_map, cfg):
    """Always-on (user decision 2026-09-23): "the only obtainable blades are from the multiworld" - strip every
    core crystal (ITM_CrystalList rows 45001-45057) out of enemy drop tables (BTL_EnDropItem, BTL_EnDropQuest) and
    every map's treasure box table (FLD_TboxPop), so a crystal can never be found any other way. Safe in
    isolation from the AP blade_crystal delivery mechanism (_xc2_blade_crystals, xc_deliver.py's blade_crystal
    effect): that writes a crystal directly into the corecrystal inventory box via xc2_add_item, it never goes
    through these drop/chest tables at all, so zeroing every reference here cannot affect which crystal a
    multiworld blade item delivers. The in-game core crystal gacha/shop itself is untouched (out of scope -
    "enemies and chests" specifically) - see _xc2_blade_crystals's own note that the gacha isn't part of this
    project at all."""
    import glob
    CRYSTAL_LO, CRYSTAL_HI = 45001, 45057

    def clean_slots(row, id_fmt, extra_fmts):
        cleared = 0
        i = 1
        while id_fmt.format(i) in row:
            key = id_fmt.format(i)
            if CRYSTAL_LO <= row.get(key, 0) <= CRYSTAL_HI:
                row[key] = 0
                for fmt in extra_fmts:
                    k = fmt.format(i)
                    if k in row:
                        row[k] = 0
                cleared += 1
            i += 1
        return cleared

    total = 0
    for name, id_fmt, extra in (("BTL_EnDropItem", "ItemID{}", ("DropProb{}", "NoGetByEnh{}", "FirstNamed{}")),
                                ("BTL_EnDropQuest", "ItemID{}", ("DropProb{}", "GetConditon{}"))):
        path = os.path.join(json_out, "common", f"{name}.json")
        if not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        changed = False
        for row in data["rows"]:
            n = clean_slots(row, id_fmt, extra)
            total += n
            changed = changed or n > 0
        if changed:
            _dump(path, data)

    for path in sorted(glob.glob(os.path.join(json_out, "common_gmk", "*_FLD_TboxPop.json"))):
        data = json.load(open(path, encoding="utf-8"))
        changed = False
        for row in data["rows"]:
            n = clean_slots(row, "itm{}ID", ("itm{}Num", "itm{}Per"))
            total += n
            changed = changed or n > 0
        if changed:
            _dump(path, data)

    ap_map["no_crystal_drops"] = True
    print(f"no crystal drops: cleared {total} core-crystal reference(s) from enemy drop tables and treasure boxes")


def _xc2_shops(game, root_copy, json_out, ap_map, cfg):
    """Every shop slot sells its own new pouch item (100 G) named after the multiworld item behind it.
    cfg["shops"] = build-time table (worldgen/xc2_shops.py), cfg["shop_labels"] = {table id: [label per slot]}, cfg["shop_mode"] = 1 per shop / 2 per slot."""
    shops = cfg["shops"]
    labels = cfg["shop_labels"]
    base = shops["placeholder_base"]
    fav_path = os.path.join(json_out, "common", "ITM_FavoriteList.json")
    txt_path = os.path.join(json_out, "common_ms", "itm_favorite.json")
    shop_path = os.path.join(json_out, "common", "MNU_ShopNormal.json")
    fav = json.load(open(fav_path, encoding="utf-8"))
    txt = json.load(open(txt_path, encoding="utf-8"))
    normal = json.load(open(shop_path, encoding="utf-8"))
    template = next(r for r in fav["rows"] if r["$id"] == 40001)
    tables = {r["$id"]: r for r in normal["rows"]}
    next_text = max(r["$id"] for r in txt["rows"]) + 1
    # user decision 2026-09-23: every shop sells exactly 5 AP items plus whatever quest-required items it already
    # had. xc2_shops.py caps `shop["slots"]` at 5 (choosing them from the non-quest-required columns) - only those
    # chosen columns get overwritten with placeholders here; every other column is left exactly as vanilla.
    # 2026-09-23 diagnostic revert: this function used to also zero out every OTHER DefItem/Addtem column not
    # chosen and not quest-required (to fully hide vanilla overflow). That's suspected of writing shop data yuzu
    # can't handle (crash-on-launch reported right after this shipped) - reverted to the simpler write-only-5 form
    # until confirmed innocent or guilty.
    placeholders = {}
    for shop in shops["shops"]:
        row = tables[shop["table"]]
        shop_labels = labels.get(str(shop["table"]), [])
        for k, slot in enumerate(shop["slots"]):
            item_id = base + slot["n"]
            new = dict(template)
            new.update({"$id": item_id, "Name": next_text, "Caption": 0, "Price": 100, "ValueMax": 1, "Rarity": 0, "TrustPoint": 0})
            for col in [c for c in new if c.startswith("sort")]:
                new[col] = item_id
            fav["rows"].append(new)
            txt["rows"].append({"$id": next_text, "style": 36, "name": shop_labels[k] if k < len(shop_labels) else "Nothing"})
            next_text += 1
            row[slot["col"]] = item_id
            placeholders[str(item_id)] = {"shop": shop["name"], "slot": k + 1}
    _dump(fav_path, fav)
    _dump(txt_path, txt)
    _dump(shop_path, normal)
    ap_map["shop_placeholders"] = placeholders
    print(f"shops: {len(placeholders)} shop slots now sell AP placeholders ({len(shops['shops'])} shops)")


def _xc3_shops(game, root_copy, json_out, ap_map, cfg):
    """Every commissary / caravan slot sells its own new accessory (100 G) named after the multiworld item behind it (see worldgen/xc3_shops.py).
    cfg["shops"] = build-time table, cfg["shop_labels"] = {table id: [label per slot]}."""
    shops = cfg["shops"]
    labels = cfg["shop_labels"]
    base = shops["placeholder_base"]
    acc_path = os.path.join(json_out, "sys", "ITM_Accessory.json")
    txt_path = os.path.join(json_out, "system", "msg_item_accessory.json")
    shop_path = os.path.join(json_out, "mnu", "MNU_ShopTable.json")
    acc = json.load(open(acc_path, encoding="utf-8"))
    txt = json.load(open(txt_path, encoding="utf-8"))
    table = json.load(open(shop_path, encoding="utf-8"))
    template = next(r for r in acc["rows"] if r["$id"] == 1)
    tables = {r["$id"]: r for r in table["rows"]}
    text_template = txt["rows"][0]
    next_text = max(r["$id"] for r in txt["rows"]) + 1
    placeholders = {}
    for shop in shops["shops"]:
        row = tables[shop["table"]]
        shop_labels = labels.get(str(shop["table"]), [])
        for k, slot in enumerate(shop["slots"]):
            item_id = base + slot["n"]
            new = dict(template)
            new.update({"$id": item_id, "ID": f"ACCESSORY_AP_{slot['n']:04d}", "Name": next_text, "Price": 100, "Rarity": 0, "Sell": 0, "NcType": 0, "NcNum": 0,
                        "ForgePoint": 0, "SortParam": item_id})
            acc["rows"].append(new)
            trow = dict(text_template)
            trow.update({"$id": next_text, "label": "<00000000>", "name": shop_labels[k] if k < len(shop_labels) else "Nothing"})
            txt["rows"].append(trow)
            next_text += 1
            row[slot["col"]] = item_id
            placeholders[str(item_id)] = {"shop": shop["name"], "slot": k + 1}
    _dump(acc_path, acc)
    _dump(txt_path, txt)
    _dump(shop_path, table)
    ap_map["shop_placeholders"] = placeholders
    print(f"shops: {len(placeholders)} shop slots now sell AP placeholders ({len(shops['shops'])} shops)")


def _xc3_story_gates(game, root_copy, json_out, ap_map, cfg):
    """Lock XC3 story steps until the player holds the step's unlock item -- same idea as _xc2_story_gates, adapted to XC3's FLD_ConditionList.
    FLD_ConditionList is NOT a table of arbitrary-id links: NextPremise only ever holds 0 (end of chain), 1 (AND with the row at $id+1) or 2 (OR with
    the row at $id+1) -- a clause chain is a run of *consecutive* ids.  So a trigger's own chain (which may itself be several rows long) cannot be
    pointed to from the middle of a new chain; instead the whole original chain is copied to fresh consecutive ids right after a new item-clause,
    and only the trigger's `Condition` field is repointed, to the new chain's first id.  cfg["gates"] = {"beats": [{"need", "item", "label",
    "pops": {map: [GMK_Event ids]}}]}.  Every beat gets a new key item (ITM_Precious row `item`)."""
    gates = cfg["gates"]
    d = lambda sub, n: os.path.join(json_out, sub, f"{n}.json")
    cond_item = json.load(open(d("fld", "FLD_ConditionItem"), encoding="utf-8"))
    conds = json.load(open(d("fld", "FLD_ConditionList"), encoding="utf-8"))
    by_id = {r["$id"]: r for r in conds["rows"]}
    keys = json.load(open(d("sys", "ITM_Precious"), encoding="utf-8"))
    txt = json.load(open(d("system", "msg_item_precious"), encoding="utf-8"))
    template = next(r for r in keys["rows"] if r["$id"] == 16001)
    next_ci = max(r["$id"] for r in cond_item["rows"]) + 1
    next_cond = max(r["$id"] for r in conds["rows"]) + 1
    next_text = max(r["$id"] for r in txt["rows"]) + 1
    event_files = {}
    gated = 0
    for beat in gates["beats"]:
        new_key = dict(template)
        new_key.update({"$id": beat["item"], "ID": f"ITM_PRC_AP{beat['need']:04d}", "Name": next_text, "Caption": next_text + 1, "ForgePoint": 0})
        keys["rows"].append(new_key)
        txt["rows"].append({"$id": next_text, "label": "<00000000>", "style": 15, "name": beat["label"]})
        txt["rows"].append({"$id": next_text + 1, "label": "<00000000>", "style": 49, "name": "Unlocks the next step of the main story. Received from the multiworld."})
        next_text += 2
        cond_item["rows"].append({"$id": next_ci, "ID": "<00000000>", "ItemID": beat["item"], "NumberMin": 1, "NumberMax": 99})
        for mp, ids in beat["pops"].items():
            if mp not in event_files:
                path = os.path.join(json_out, "map", f"{mp}_GMK_Event.json")
                event_files[mp] = (path, json.load(open(path, encoding="utf-8")))
            for row in event_files[mp][1]["rows"]:
                if row["$id"] not in ids:
                    continue
                # walk the trigger's own (possibly multi-row) chain, so it can be copied whole after the new item clause
                orig_chain = []
                cur = by_id.get(row["Condition"]) if row["Condition"] else None
                while cur is not None:
                    orig_chain.append(cur)
                    cur = by_id.get(cur["$id"] + 1) if cur["NextPremise"] in (1, 2) else None
                start = next_cond
                new_row = {"$id": next_cond, "ID": "<00000000>", "ConditionType": 6, "Condition": next_ci,
                          "NextPremise": 1 if orig_chain else 0, "DebugID": "", "Comment": ""}
                conds["rows"].append(new_row)
                by_id[next_cond] = new_row
                next_cond += 1
                for c in orig_chain:
                    # orig_chain was walked to its own natural end (NextPremise not in (1, 2)), so each row's NextPremise is already correct as-is
                    copy_row = {"$id": next_cond, "ID": "<00000000>", "ConditionType": c["ConditionType"], "Condition": c["Condition"],
                               "NextPremise": c["NextPremise"], "DebugID": "", "Comment": ""}
                    conds["rows"].append(copy_row)
                    by_id[next_cond] = copy_row
                    next_cond += 1
                row["Condition"] = start
                gated += 1
        next_ci += 1
    _dump(d("sys", "ITM_Precious"), keys)
    _dump(d("system", "msg_item_precious"), txt)
    _dump(d("fld", "FLD_ConditionItem"), cond_item)
    _dump(d("fld", "FLD_ConditionList"), conds)
    for path, data in event_files.values():
        _dump(path, data)
    print(f"story gates: {len(gates['beats'])} steps, {gated} cutscene trigger(s) gated")


def _xc3_container_gates(game, root_copy, json_out, ap_map, cfg):
    """Lock XC3 field containers (map/<map>_GMK_TreasureBox.json rows) until the player holds the batch's unlock item -
    same chain-splice mechanic as _xc3_story_gates, but GMK_TreasureBox.Condition is the container's own real spawn/pop
    gate (not an ambient side-trigger the way the story beats' GMK_Event triggers turned out to be), so this is expected
    to actually block appearance rather than just fail silently. cfg["container_gates"] = {"beats": [{"need", "item",
    "label", "pops": {map: [GMK_TreasureBox ids]}}]}. Every batch gets a new key item (ITM_Precious row `item`)."""
    gates = cfg["container_gates"]
    d = lambda sub, n: os.path.join(json_out, sub, f"{n}.json")
    cond_item = json.load(open(d("fld", "FLD_ConditionItem"), encoding="utf-8"))
    conds = json.load(open(d("fld", "FLD_ConditionList"), encoding="utf-8"))
    by_id = {r["$id"]: r for r in conds["rows"]}
    keys = json.load(open(d("sys", "ITM_Precious"), encoding="utf-8"))
    txt = json.load(open(d("system", "msg_item_precious"), encoding="utf-8"))
    template = next(r for r in keys["rows"] if r["$id"] == 16001)
    next_ci = max(r["$id"] for r in cond_item["rows"]) + 1
    next_cond = max(r["$id"] for r in conds["rows"]) + 1
    next_text = max(r["$id"] for r in txt["rows"]) + 1
    box_files = {}
    gated = 0
    for beat in gates["beats"]:
        new_key = dict(template)
        new_key.update({"$id": beat["item"], "ID": f"ITM_PRC_APC{beat['need']:04d}", "Name": next_text, "Caption": next_text + 1, "ForgePoint": 0})
        keys["rows"].append(new_key)
        txt["rows"].append({"$id": next_text, "label": "<00000000>", "style": 15, "name": beat["label"]})
        txt["rows"].append({"$id": next_text + 1, "label": "<00000000>", "style": 49, "name": "Unlocks the next batch of field containers. Received from the multiworld."})
        next_text += 2
        cond_item["rows"].append({"$id": next_ci, "ID": "<00000000>", "ItemID": beat["item"], "NumberMin": 1, "NumberMax": 99})
        for mp, ids in beat["pops"].items():
            if mp not in box_files:
                path = os.path.join(json_out, "map", f"{mp}_GMK_TreasureBox.json")
                box_files[mp] = (path, json.load(open(path, encoding="utf-8")))
            for row in box_files[mp][1]["rows"]:
                if row["$id"] not in ids:
                    continue
                orig_chain = []
                cur = by_id.get(row["Condition"]) if row["Condition"] else None
                while cur is not None:
                    orig_chain.append(cur)
                    cur = by_id.get(cur["$id"] + 1) if cur["NextPremise"] in (1, 2) else None
                start = next_cond
                new_row = {"$id": next_cond, "ID": "<00000000>", "ConditionType": 6, "Condition": next_ci,
                          "NextPremise": 1 if orig_chain else 0, "DebugID": "", "Comment": ""}
                conds["rows"].append(new_row)
                by_id[next_cond] = new_row
                next_cond += 1
                for c in orig_chain:
                    copy_row = {"$id": next_cond, "ID": "<00000000>", "ConditionType": c["ConditionType"], "Condition": c["Condition"],
                               "NextPremise": c["NextPremise"], "DebugID": "", "Comment": ""}
                    conds["rows"].append(copy_row)
                    by_id[next_cond] = copy_row
                    next_cond += 1
                row["Condition"] = start
                gated += 1
        next_ci += 1
    _dump(d("sys", "ITM_Precious"), keys)
    _dump(d("system", "msg_item_precious"), txt)
    _dump(d("fld", "FLD_ConditionItem"), cond_item)
    _dump(d("fld", "FLD_ConditionList"), conds)
    for path, data in box_files.values():
        _dump(path, data)
    print(f"container gates: {len(gates['beats'])} batches, {gated} container(s) gated")


def _xc3_hero_access(game, root_copy, json_out, ap_map, cfg):
    """Every Hero's MNU_HeroDictionary.WakeupCondition is replaced with 'player has this key item' (a new FLD_ConditionItem / ITM_Precious row), so a Hero
    can be recruited as soon as the multiworld item is received -- no story/quest prerequisite, the recruit NPC just has to be found (which can now happen
    at any point in the run, not only after that Hero's own personal sidequest chain).  cfg["heroes"] = {"heroes": [{"pc", "name", "item"}]} (see
    worldgen/gen_heroes_xc3.py)."""
    heroes = cfg["heroes"]
    d = lambda sub, n: os.path.join(json_out, sub, f"{n}.json")
    cond_item = json.load(open(d("fld", "FLD_ConditionItem"), encoding="utf-8"))
    conds = json.load(open(d("fld", "FLD_ConditionList"), encoding="utf-8"))
    keys = json.load(open(d("sys", "ITM_Precious"), encoding="utf-8"))
    txt = json.load(open(d("system", "msg_item_precious"), encoding="utf-8"))
    hd = json.load(open(d("mnu", "MNU_HeroDictionary"), encoding="utf-8"))
    template = next(r for r in keys["rows"] if r["$id"] == 16001)
    next_ci = max(r["$id"] for r in cond_item["rows"]) + 1
    next_text = max(r["$id"] for r in txt["rows"]) + 1
    by_pc = {r["PcID"]: r for r in hd["rows"]}
    by_hash = {r["ID"]: r for r in conds["rows"]}              # WakeupCondition is a hash-string that names a FLD_ConditionList row's own "ID", not its $id
    done = 0
    for h in heroes["heroes"]:
        row = by_pc.get(h["pc"])
        cond_row = by_hash.get(row["WakeupCondition"]) if row else None
        if cond_row is None:
            continue
        new_key = dict(template)
        new_key.update({"$id": h["item"], "ID": f"ITM_PRC_APH{h['item']}", "Name": next_text, "Caption": next_text + 1, "ForgePoint": 0})
        keys["rows"].append(new_key)
        txt["rows"].append({"$id": next_text, "label": "<00000000>", "style": 15, "name": f"{h['name']} Access"})
        txt["rows"].append({"$id": next_text + 1, "label": "<00000000>", "style": 49, "name": "Lets you recruit this Hero. Received from the multiworld."})
        next_text += 2
        cond_item["rows"].append({"$id": next_ci, "ID": "<00000000>", "ItemID": h["item"], "NumberMin": 1, "NumberMax": 99})
        # overwrite the row in place (same $id, same ID hash) so every other table that names this condition by hash still resolves correctly
        cond_row["ConditionType"] = 6
        cond_row["Condition"] = next_ci
        cond_row["NextPremise"] = 0
        next_ci += 1
        done += 1
    _dump(d("sys", "ITM_Precious"), keys)
    _dump(d("system", "msg_item_precious"), txt)
    _dump(d("fld", "FLD_ConditionItem"), cond_item)
    _dump(d("fld", "FLD_ConditionList"), conds)
    print(f"hero access: {done} of {len(heroes['heroes'])} heroes rewired to item-based recruiting")


AP_PATCHES = {"xc2_blade_crystals": _xc2_blade_crystals, "xc2_story_gates": _xc2_story_gates, "xc2_shops": _xc2_shops, "xc3_shops": _xc3_shops,
             "xc3_story_gates": _xc3_story_gates, "xc3_hero_access": _xc3_hero_access, "xc3_container_gates": _xc3_container_gates,
             "xc2_fast_travel": _xc2_fast_travel, "xc2_no_crystal_drops": _xc2_no_crystal_drops}


def main(cfg_path: str) -> int:
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    game = cfg["game"]
    src = cfg["randomizer_root"]
    work = cfg["work_dir"]
    root_copy = os.path.join(work, "rando")
    if not os.path.isdir(root_copy):
        os.makedirs(work, exist_ok=True)
        shutil.copytree(src, root_copy, ignore=shutil.ignore_patterns("JsonOutputs", "__pycache__", "*.pyc"))
    os.chdir(root_copy)
    sys.path.insert(0, root_copy)
    sys.setrecursionlimit(10000)

    import tkinter
    root = tkinter.Tk()
    root.withdraw()
    from scripts import Interactables, XCRandomizer          # noqa: E402

    if game == "XC2":
        import XC2.XC2_Scripts.XC2_Settings as S            # noqa: E402
    elif game == "XC3":
        import XC3.XC3_Scripts.XC3_Settings as S            # noqa: E402
    elif game == "XCDE":
        import XCDE.XCDE_Scripts.XCDE_Settings as S         # noqa: E402
    else:
        raise SystemExit(f"unknown game {game}")
    W = S.WindowData
    options = Interactables.XenoOptionDict[game]

    # ---- input: BDATs into the layout the randomizer expects (<Game>/bdat)
    bdat_in = os.path.join(root_copy, game, "bdat")
    shutil.rmtree(bdat_in, ignore_errors=True)                # always start from the user's untouched BDATs
    shutil.copytree(cfg["bdat_dir"], bdat_in)

    # ---- option states (what the GUI's checkboxes / spinboxes would hold)
    wanted = cfg.get("options", {})
    for opt in options:
        spec = wanted.get(opt.name)
        on = bool(spec if not isinstance(spec, dict) else spec.get("on", True)) if spec is not None else False
        opt.checkBoxVal = tkinter.BooleanVar(value=on)
        if opt.hasSpinBox:
            spin = spec.get("spin", opt.spinDefault) if isinstance(spec, dict) else opt.spinDefault
            opt.spinBoxVal = tkinter.IntVar(value=int(spin))
        subspec = spec.get("sub", {}) if isinstance(spec, dict) else {}
        for sub in opt.subOptions:
            s = subspec.get(sub.name)
            if s is None:
                state = bool(sub.defState) if on else False
                spin = sub.spinDefault
            else:
                state = bool(s if not isinstance(s, dict) else s.get("on", True))
                spin = s.get("spin", sub.spinDefault) if isinstance(s, dict) else sub.spinDefault
            sub.checkBoxVal = tkinter.BooleanVar(value=state)
            if sub.hasSpinBox:
                sub.spinBoxVal = tkinter.IntVar(value=int(spin))
    unknown = [k for k in wanted if k not in {o.name for o in options}]
    if unknown:
        print("WARNING: unknown randomizer options:", unknown)

    # ---- unpack
    json_out = os.path.join(root_copy, game, "JsonOutputs")
    shutil.rmtree(json_out, ignore_errors=True)
    os.makedirs(json_out, exist_ok=True)
    tool = os.path.join(root_copy, "Toolset", "bdat-toolset-win64.exe")
    for name in W.mainFolderNames:
        path = f"{bdat_in}/{name}.bdat"
        if not os.path.exists(path):
            print(f"WARNING: {path} is missing - options that need it will fail")
            continue
        subprocess.run([tool, "extract", path, "-o", json_out, "-f", "json", "--pretty"] + W.extraArgs, check=True)
    for name in W.subFolderNames:
        path = f"{bdat_in}/{W.textFolderName}/{name}.bdat"
        if not os.path.exists(path):
            print(f"WARNING: {path} is missing - options that need it will fail")
            continue
        subprocess.run([tool, "extract", path, "-o", json_out, "-f", "json", "--pretty"] + W.extraArgs, check=True)

    # remember every table's real columns: some third-party options write columns this game version does not have, which makes the packer panic
    columns = {}
    for dirpath, _dirs, files in os.walk(json_out):
        for fn in files:
            if fn.endswith(".json"):
                fp = os.path.join(dirpath, fn)
                try:
                    rows = json.load(open(fp, encoding="utf-8")).get("rows", [])
                    columns[fp] = (set(rows[0].keys()), os.path.getmtime(fp)) if rows and isinstance(rows[0], dict) else None
                except Exception:
                    columns[fp] = None

    seed = str(cfg.get("seed", "archipelago"))
    random.seed(seed)
    for cmd in W.preCommands:
        cmd()

    # ---- run enabled options in the randomizer's own order
    options.sort(key=lambda x: x.prio)
    for opt in options:
        if opt.checkBoxVal.get():
            for command in opt.preRandoCommands:
                try:
                    command()
                except Exception:
                    print(f"ERROR pre {opt.name}\n{traceback.format_exc()}")
    failed = []
    for opt in options:
        if not opt.checkBoxVal.get():
            continue
        opt.subOptions.sort(key=lambda x: x.prio)
        for sub in opt.subOptions:
            if not sub.checkBoxVal.get():
                continue
            try:
                for command in sub.commands:
                    command()
            except Exception:
                failed.append(f"{opt.name}: {sub.name}")
                print(f"ERROR sub {opt.name}: {sub.name}\n{traceback.format_exc()}")
        for command in opt.commands:
            try:
                command()
            except Exception:
                failed.append(opt.name)
                print(f"ERROR {opt.name}\n{traceback.format_exc()}")
    ap_map = {}
    for patch in cfg.get("ap_patches", []):
        try:
            AP_PATCHES[patch](game, root_copy, json_out, ap_map, cfg)
        except Exception:
            failed.append(f"ap patch {patch}")
            print(f"ERROR ap patch {patch}\n{traceback.format_exc()}")
    for cmd in W.postCommands:
        try:
            cmd()
        except Exception:
            print(f"ERROR post\n{traceback.format_exc()}")

    # ---- drop columns the tables do not have (see above)
    for fp, info in columns.items():
        if info is None or not os.path.exists(fp) or os.path.getmtime(fp) == info[1]:
            continue
        try:
            data = json.load(open(fp, encoding="utf-8"))
            extra = set()
            for row in data.get("rows", []):
                if isinstance(row, dict):
                    bad = [k for k in row if k not in info[0]]
                    extra.update(bad)
                    for k in bad:
                        del row[k]
            if extra:
                print(f"WARNING: {os.path.basename(fp)}: dropped columns {sorted(extra)} that this game version does not have")
                json.dump(data, open(fp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        except Exception:
            print(f"WARNING: could not sanitize {fp}: {traceback.format_exc()}")

    # ---- pack
    out_spot = os.path.join(cfg["out_dir"], W.outputPath if hasattr(W, "outputPath") else "")
    out_spot = os.path.join(cfg["out_dir"], *S.outputPath.split("/")) if hasattr(S, "outputPath") else out_spot
    os.makedirs(out_spot, exist_ok=True)
    subprocess.run([tool, "pack", json_out, "-o", out_spot, "-f", "json"], check=True)
    txt = os.path.join(out_spot, W.textFolderName)
    os.makedirs(txt, exist_ok=True)
    for name in W.subFolderNames:
        if os.path.exists(os.path.join(out_spot, f"{name}.bdat")):
            shutil.move(os.path.join(out_spot, f"{name}.bdat"), os.path.join(txt, f"{name}.bdat"))
    if ap_map:
        with open(os.path.join(cfg["out_dir"], "ap_map.json"), "w", encoding="utf-8") as fh:
            json.dump(ap_map, fh, indent=1)
    if game == "XC3":
        # Xenoblade 3 only reads loose BDATs through the randomizer's Skyline plugin (libxcnx_file_loader.nro) + exefs patch: without them the mod is ignored
        title_dir = os.path.join(cfg["out_dir"], "contents", "010074F013262000")
        shutil.copytree(os.path.join(root_copy, "XC3", "Loader", "exefs"), os.path.join(title_dir, "exefs"), dirs_exist_ok=True)
        shutil.copytree(os.path.join(root_copy, "XC3", "Loader", "skyline"), os.path.join(title_dir, "romfs", "skyline"), dirs_exist_ok=True)
    print("packed to", out_spot, "| failed options:", failed or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
