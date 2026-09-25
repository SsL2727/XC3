"""Build-time data for the XC2 field skill logic: what every blade contributes to each field skill at each trust level.

usage: python xc2_skills.py     ->  detect/xc2_skills.json

Field skills are not items in this world.  The party's level of a field skill is the sum of the levels of the blades it has equipped,
so it follows from the blades received, their trust hearts (Progressive Blade Trust) and the blade slots of the drivers in the party.

Game data used (BDAT): CHR_Bl.FSkill1..3 (the blade's three field skills) and CHR_Bl.FskillAchivement1..3 -> FLD_AchievementSet.AchievementID1..5.  Every
non-empty AchievementID is one node of the blade's affinity chart that raises that skill by one level; the position 1..5 of the node is the trust
heart (affinity level) the ring is available at.  So the level of skill i at h hearts = number of non-empty ids among the first h positions
(capped by FLD_FieldSkillList.MaxLevel).  Common blades and Torna blades are not counted (their levels are random / not in the pool).

Output:
  {"skills": {skill name: FLD_FieldSkillList id},
   "blades": {item name: {"trust": trust item name | null, "driver": item of the only driver who can equip it | null, "group": slot group | null,
                          "levels": {skill name: [level at 1 heart, ..., level at 5 hearts]}}},
   "drivers": [items of the drivers who can join the party besides Rex]}
"""
import json
import os

import xc2_extras as X

J = X.J
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect", "xc2_skills.json")

SKILLS = {"Fire Mastery": 10, "Water Mastery": 11, "Earth Mastery": 12, "Wind Mastery": 13, "Electric Mastery": 14, "Ice Mastery": 15,
          "Dark Mastery": 16, "Lockpicking": 18, "Keen Eye": 19, "Leaping": 20, "Superstrength": 21, "Focus": 22, "Ancient Wisdom": 23,
          "Nopon Wisdom": 24, "Fortitude": 25, "Cooking": 26}
DRIVERS = ["Nia (Driver)", "Tora", "Morag", "Zeke", "Vandham"]

# item name -> CHR_Bl id for blades outside xc2_extras.CRYSTAL_BLADES / EXTRA_BLADES
OTHER_BLADES = {"Nia (Blade)": 1011, "Brighid": 1009}
# blades that only one driver can equip: item -> (driver item or None for Rex, slot group).  Blades of one group share a single slot
# (Pyra/Mythra switch in place, Poppi evolves), so at most one of them counts.
EXCLUSIVE = {"Pyra": (None, "pyra"), "Aegis True Form": (None, "pyra"), "Nia (Blade)": (None, "nia"),
             "Dromarch": ("Nia (Driver)", "dromarch"), "Poppi a": ("Tora", "poppi"), "Poppi QT": ("Tora", "poppi"),
             "Poppi QT Pi": ("Tora", "poppi"), "Pandoria": ("Zeke", "pandoria"), "Brighid": ("Morag", "brighid")}
# story blades whose field skills are not counted: Sever belongs to Malos (never in the party), Dagas only has non-standard skills
SKIPPED = {"Sever", "Dagas"}


def rows(path):
    return json.load(open(os.path.join(J, path), encoding="utf-8"))["rows"]


def build():
    chr_bl = {r["$id"]: r for r in rows(r"data\common\CHR_Bl.json")}
    sets = {r["$id"]: r for r in rows(r"data\common\FLD_AchievementSet.json")}
    fskill = {r["$id"]: r for r in rows(r"data\common\FLD_FieldSkillList.json")}
    blade_names = {r["$id"]: r["name"] for r in rows(r"text\common_ms\chr_bl_ms.json")}
    by_id = {v: k for k, v in SKILLS.items()}

    blades = {}
    ids = {**X.CRYSTAL_BLADES, **{k: v for k, v in X.STORY_BLADES.items() if k not in SKIPPED}, **OTHER_BLADES}
    for bid in X.EXTRA_BLADES:
        ids[blade_names[chr_bl[bid]["Name"]]] = bid
    for name, bid in ids.items():
        rec = chr_bl[bid]
        levels = {}
        for i in (1, 2, 3):
            sid = rec[f"FSkill{i}"]
            if sid not in by_id:
                continue
            aset = sets.get(rec[f"FskillAchivement{i}"])
            if not aset:
                continue
            nodes = [1 if aset[f"AchievementID{k}"] else 0 for k in range(1, 6)]
            cap = fskill[sid]["MaxLevel"]
            lv, run = [], 0
            for n in nodes:
                run += n
                lv.append(min(run, cap))
            levels[by_id[sid]] = lv
        if not levels:
            continue
        driver, group = EXCLUSIVE.get(name, (None, None))
        trust = f"{name} Trust" if name not in OTHER_BLADES else None       # Nia (Blade) / Brighid have no trust item of their own
        if name == "Aegis True Form":
            trust = "Pyra Trust"                             # Pyra's trust item covers her Mythra record
        blades[name] = {"trust": trust or None, "driver": driver, "group": group, "levels": levels}
    return {"skills": SKILLS, "blades": blades, "drivers": DRIVERS}


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print("blades:", len(data["blades"]))
    for s in SKILLS:
        tops = sorted((b["levels"][s][4] for b in data["blades"].values() if s in b["levels"]), reverse=True)
        print(f"  {s:16s} {len(tops):2d} blades, best 3: {sum(tops[:3]):2d}, best 9: {sum(tops[:9]):2d}")
