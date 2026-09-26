"""Convert the three manual apworlds into three native Archipelago worlds and package them as .apworld files.

    python build_worlds.py            # builds all three into out/ and (optionally) installs into custom_worlds
    python build_worlds.py --install  # also copies the .apworld files into G:\\Archipelago\\custom_worlds

Everything game-specific lives in GAMES below; the engine is xc_core.py (copied into every package).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

from docgen import game_doc, setup_doc

HERE = Path(__file__).resolve().parent
SRC = Path(r"C:\Users\JAKECO~1\AppData\Local\Temp\claude\G--Archipelago\1bc81135-ff62-4c92-91e9-0765983e4a24\scratchpad")
MANUAL_APWORLDS = {
    "xenoblade_de": Path(r"F:\XCAP\Xenoblade AP\manual_xenobladechroniclesv2_xanderoni_skipperki1.apworld"),
    "xenoblade_2": Path(r"F:\XCAP\Xenoblade 2 AP\manual_xc2v2_squidy.apworld"),
    "xenoblade_3": Path(r"F:\XCAP\Xenobalde 3 AP\manual_xenobladechronicles3_xanderoni.apworld"),
}
OUT = HERE / "out"
CUSTOM_WORLDS = Path(r"G:\Archipelago\custom_worlds")


def read_manual(pkg: str) -> dict:
    """Read the manual apworld straight from the .apworld zip (so this script does not depend on scratch dirs)."""
    zf = zipfile.ZipFile(MANUAL_APWORLDS[pkg])
    names = zf.namelist()
    root = next(n for n in names if n.endswith("data/game.json")).rsplit("data/game.json", 1)[0]

    def j(name, default=None):
        try:
            return json.loads(zf.read(root + "data/" + name).decode("utf-8-sig"))
        except KeyError:
            return default

    def unwrap(x):
        return x["data"] if isinstance(x, dict) and "data" in x else x

    out = {
        "game": j("game.json"),
        "items": unwrap(j("items.json")),
        "locations": unwrap(j("locations.json")),
        "regions": {k: v for k, v in j("regions.json").items() if not k.startswith("$")},
        "events": unwrap(j("events.json", [])) or [],
        "categories": {k: v for k, v in (j("categories.json", {}) or {}).items() if not k.startswith("$")},
        "options": j("options.json", {}),
        "extra_files": {},
    }
    for n in names:
        if n.startswith(root + "hooks/") and n.endswith("Collectopaedia.py"):
            out["extra_files"]["collectopaedia.py"] = zf.read(n)
    return out


def as_list(x):
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


def strip_dead_terms(text: str, dead_names: set) -> str:
    """Remove top-level AND/OR clauses referencing any name in dead_names from a requires string, splicing the
    remaining terms back together (AND/OR are equal precedence, left-to-right, as xc_logic.lua evaluates them -
    see gen_gates_xc2.py/xc_logic.lua). No-op if nothing in the string is dead. Does not look inside parens: not
    needed for the one known case (a flat two-term AND), and this project's requires strings rarely nest anyway."""
    if not text:
        return text
    parts = re.split(r"(\s+and\s+|\s+or\s+)", text, flags=re.IGNORECASE)   # case-insensitive: XC2's data uses lowercase and/or
    terms, ops = parts[0::2], parts[1::2]

    def is_dead(t):
        m = re.fullmatch(r"\|?([^|:]+?)(?::[^|]*)?\|?", t.strip())
        return bool(m) and m.group(1).strip() in dead_names

    keep = [i for i, t in enumerate(terms) if not is_dead(t)]
    if len(keep) == len(terms):
        return text
    if not keep:
        return ""
    out = terms[keep[0]]
    for k in keep[1:]:
        out += ops[k - 1] + terms[k]
    return out


def set_psq(requires: str, target: int) -> str:
    """Rewrite every 'Progressive Story Quest:N' term in a requires string to a single '|Progressive Story
    Quest:target|' (dropping duplicates - see the XC2 region re-anchoring pass in normalize(), which calls this
    once per region with that region's own arc-entrance beat). Case-insensitive AND/OR split (unlike
    strip_dead_terms's uppercase-only one) because these particular requires strings use lowercase 'and'/'or'."""
    if not requires or "Progressive Story Quest:" not in requires:
        return requires
    parts = re.split(r"(\s+and\s+|\s+or\s+)", requires, flags=re.IGNORECASE)
    terms, ops = parts[0::2], parts[1::2]
    is_psq = [bool(re.fullmatch(r"\|Progressive Story Quest:\d+\|", t.strip())) for t in terms]
    if not any(is_psq):
        return requires
    first_idx = is_psq.index(True)
    keep = [i for i, p in enumerate(is_psq) if not p or i == first_idx]
    terms[first_idx] = f"|Progressive Story Quest:{target}|"
    out = terms[keep[0]]
    for k in keep[1:]:
        out += ops[k - 1] + terms[k]
    return out


# --------------------------------------------------------------------------------------------------------------------
# Per-game configuration. `rule_functions_src` is Python inserted into the package __init__.
# --------------------------------------------------------------------------------------------------------------------


def _story_gate_total(pkg: str) -> int:
    """Total number of story-gate beats (gates.json's own "count") - the upper end of the story_items_required
    option's range, read from data rather than hardcoded so it stays correct if the beat table is ever regenerated."""
    path = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + "_gates.json")
    return json.load(open(path, encoding="utf-8"))["count"] if path.exists() else 116


GAMES = {
    "xenoblade_de": {
        "game": "Xenoblade Chronicles DE",
        "class": "XenobladeChroniclesDEWorld",
        "title": "Xenoblade Chronicles: Definitive Edition",
        "filler": "Lobster",
        "item_base": 0x5C1000,
        "loc_base": 0x5C100000,
        "death_link": True,
        "default_goal": 0,
        "option_defaults": {"GameVersion": 1},
        "toggle_names": {
            "locations": "Location Discovery Checks", "landmarks": "Landmark Checks", "StoryQuests": "Story Quests",
            "MonsterQuests": "Monster Quests", "CollectionQuests": "Collection Quests", "SearchQuests": "Search Quests",
            "ChallengeQuests": "Challenge Quests", "AffinityQuests": "Affinity Quests", "MaterialQuests": "Material Quests",
            "UniqueMonsters": "Unique Monsters", "SuperBosses": "Super Bosses", "Collectopaedia": "Collectopaedia",
            "HeartToHearts": "Heart-to-Hearts", "AffinityChart": "Affinity Chart", "Achievements": "Achievements",
            "DevelopmentLevels": "Colony 6 Development Levels", "Artsanity": "Artsanity (Art Books as items)",
            "collectopaediasanity": "Collectopaediasanity", "NoponGrandPrix": "Nopon Grand Prix",
        },
    },
    "xenoblade_2": {
        "game": "Xenoblade Chronicles 2",
        "manual_checks_option": True, "client_detected_categories": ["Shops", "Shop Slots"],
        "class": "XenobladeChronicles2World",
        "title": "Xenoblade Chronicles 2",
        "filler": "Nothing",
        "item_base": 0x5C2000,
        "loc_base": 0x5C200000,
        "death_link": True,
        "default_goal": 2,
        "drop_categories": ["Victory", "Traps"],
        "extras_file": "detect/xc2_extras.json",
        "shop_label_width": 23,                                      # the XC2 shop list cuts item names at about 23 characters
        "story_gates_file": "detect/xc2_gates.json",
        "drop_location_regex": r"^(Clear Chapter \d+|Complete chapter \d+)$|Defeat|Defeated",      # chapter clears / boss defeats: no autodetection yet
        "extra_categories": {"Shops": {"choice": {"option": "shop_checks", "values": [1]}},
                             "Shop Slots": {"choice": {"option": "shop_checks", "values": [2]}},
                             "Field Skills": {"yaml_option": ["!field_skill_logic"]},          # the skill items only exist when the skills are not derived from blades
                             "Trust Global": {"yaml_option": ["progressive_blade_trust", "!trust_per_blade"]},
                             "Trust Blade": {"yaml_option": ["progressive_blade_trust", "trust_per_blade"]}},
        "extra_options": {
            "fragments_required": {"type": "Range", "range_start": 5, "range_end": 400, "default": 20,
                                   "display_name": "Fragments Required",
                                   "description": "Amount of Elysium Fragments required for the fragment goal."},
            "total_fragments": {"type": "Range", "range_start": 5, "range_end": 400, "default": 30,
                                "display_name": "Total Number of Fragments",
                                "description": "Amount of Elysium Fragments placed in the multiworld (fragment goal only)."},
            "new_game_plus": {"type": "Toggle", "default": False, "display_name": "New Game Plus",
                              "description": "The client sets GameClearCount to 1 the first time it sees a fresh save (0 clears), as if the game had "
                                             "already been beaten once. Best-effort: the game's own New Game Plus mode is chosen at title-screen save "
                                             "creation, before any client can attach, so this cannot recreate whatever different starting state that "
                                             "path sets up - it only flips the same clear counter the game checks continuously for anything gated on "
                                             "'has cleared before' (e.g. Custom difficulty options). Needs the running client."},
            "shop_checks": {"type": "Choice", "default": 2, "display_name": "Shop Checks",
                            "values": {"Off": 0, "Per Shop": 1, "Per Slot": 2},
                            "description": "Shops are part of the multiworld: every shop item (each costs 100 G and shows the multiworld item it holds) is a check. "
                                           "Per Shop = one check per shop (buying anything there; every slot of the shop then shows the same item), Per Slot (default) = one check per shop slot "
                                           "(about 470), so every slot shows a different item. Shops that quests need (Llysiau Greens ...) and the items quests ask you to buy stay vanilla. Needs the patcher."},
            "story_gating": {"type": "Toggle", "default": True, "display_name": "Story Gating",
                             "description": "Every main story step after the Argentum prologue is locked: the next step only starts once you have received one more "
                                            "Progressive Story Quest item, so the story is played in order as the unlocks are found (the game's story triggers are "
                                            "patched to wait for a flag the client sets). Needs the patcher and the running client."},
            "extra_story_items": {"type": "Range", "range_start": 0, "range_end": _story_gate_total("xenoblade_2"),
                                  "default": 0, "display_name": "Extra Story Items",
                                  "description": "Adds this many additional 'Progressive Story Quest' copies to the pool beyond the "
                                                 f"{_story_gate_total('xenoblade_2')} any gate ever needs - pure slack/redundancy, useful if you want more "
                                                 "items to naturally find without changing story pacing (they never unlock anything past the last "
                                                 "beat, since Story Items Required already governs the largest threshold that matters)."},
            "story_items_required": {"type": "Range", "range_start": 0, "range_end": _story_gate_total("xenoblade_2"),
                                     "default": _story_gate_total("xenoblade_2"), "display_name": "Story Items Required",
                                     "description": "How many Progressive Story Quest items it actually takes to clear every story gate, out of the "
                                                    f"{_story_gate_total('xenoblade_2')} the world places (only matters with Story Gating on). At the default (all of "
                                                    "them) this is vanilla pacing: item N unlocks story beat N, one-to-one. Lower values spread the SAME beats over "
                                                    "fewer items (every item received unlocks proportionally more of the story at once), so a slow or async "
                                                    "multiworld can't fall as far behind live story-trigger progress and hang on a scripted event still waiting for "
                                                    "an item that hasn't arrived yet - 0 unlocks every story beat immediately, no items needed at all. Needs the "
                                                    "patcher and the running client, same as Story Gating."},
            "field_skill_logic": {"type": "Toggle", "default": True, "display_name": "Field Skills From Blades",
                                  "description": "Field skill checks (Fire Mastery, Lockpicking, Cooking ...) are gated by what your rare blades can actually give: the "
                                                 "levels of the blades you have received, at the trust hearts you have unlocked (Progressive Blade Trust), added up over the "
                                                 "blade slots of Rex and two other drivers. Off = the manual world's skill items are shuffled instead."},
            "blade_slots_per_driver": {"type": "Range", "range_start": 1, "range_end": 3, "default": 3, "display_name": "Blade Slots Per Driver",
                                       "description": "How many blades every driver can have equipped at once, as assumed by the field skill logic "
                                                      "(a party has three drivers). Lower it if you do not want the logic to count on all three slots."},
            "progressive_blade_trust": {"type": "Toggle", "default": False, "display_name": "Progressive Blade Trust",
                                        "description": "Blade trust (hearts) is capped at 1 until Trust items arrive; every copy raises the cap by one heart "
                                                       "(4 copies = 5 hearts). Off by default (changed 2026-09-23, per user report) - Trust items and the "
                                                       "field_skill_logic calculations that read them are untouched, so this stays available to turn back "
                                                       "on, but the cap itself isn't enforced by default: blades level trust normally regardless of items "
                                                       "received. Turn on to re-enable the cap."},
            "trust_per_blade": {"type": "Toggle", "default": False, "display_name": "Blade Trust Per Blade",
                                "description": "With Progressive Blade Trust: one set of 4 trust items per blade (about 40 blades) instead of one shared "
                                               "set that raises the cap of every blade."},
        },
        "toggle_names": {
            "enable_locations": "Location Checks", "enable_landmarks": "Landmark Checks",
            "enable_heart_to_hearts": "Heart-to-Hearts", "enable_chest_checks": "Chestsanity",
            "enable_victory": "Elysium Fragment Goal Items", "enable_post_chp5": "Post-Chapter-5 Checks",
            "enable_traps": "Traps", "enable_unrequiredblades": "Non-Story Blades Checks",
        },
    },
    "xenoblade_3": {
        "game": "Xenoblade Chronicles 3",
        "manual_checks_option": True, "client_detected_categories": ["Shops", "Shop Slots"],
        "class": "XenobladeChronicles3World",
        "title": "Xenoblade Chronicles 3",
        "filler": "Motes",
        "extras_file": "detect/xc3_extras.json",
        "extra_categories": {"Colony Affinity": {"yaml_option": ["progressive_colony_affinity"]},
                             "shops": {"choice": {"option": "shop_checks", "values": [0]}},        # the manual world's own 'Buy <item>' checks
                             "Shops": {"choice": {"option": "shop_checks", "values": [1]}},
                             "Shop Slots": {"choice": {"option": "shop_checks", "values": [2]}},
                             "quests": {"yaml_option": ["questsanity"]}},
        "extra_options": {"progressive_colony_affinity": {"type": "Toggle", "default": True, "display_name": "Progressive Colony Affinity",
                                                          "description": "The affinity level of every colony (Colony 9, Colony Gamma, ... City, Nopon Caravans) is capped at level 1 until "
                                                                         "'Progressive Affinity: <colony>' items arrive; each copy raises the cap by one level (4 copies = all 5 levels)."},
                          "story_gating": {"type": "Toggle", "default": True, "display_name": "Story Gating",
                                          "description": "Every main story step is locked: the next one only starts once you have received one more Progressive Story Quest item, so "
                                                         "the story is played in order as the unlocks are found (the game's own cutscene triggers are patched to wait for a flag the "
                                                         "client sets). Needs the patcher AND the Skyline loader (Eden; it crashes Ryujinx) and the running client."},
                          "hero_randomization": {"type": "Toggle", "default": True, "display_name": "Hero Randomization",
                                                 "description": "Every Hero's own story/quest prerequisite is removed: as soon as you receive that Hero's item you can recruit them "
                                                                "the moment you find them, wherever that is in the run, instead of waiting for their personal side-quest chain. Needs "
                                                                "the patcher AND the Skyline loader (Eden; it crashes Ryujinx)."},
                          "container_gating": {"type": "Toggle", "default": True, "display_name": "Container Gating",
                                               "description": "Field containers (chests) are locked in batches of 20 (346 containers, 18 batches): an undiscovered batch's containers do "
                                                              "not appear/pop at all until enough 'Progressive Container Access' items have arrived (each container is its own "
                                                              "check, and the check needs its batch's items in logic). Needs the patcher AND the "
                                                              "Skyline loader (Eden; it crashes Ryujinx)."},
                          "shop_checks": {"type": "Choice", "default": 2, "display_name": "Shop Checks", "values": {"Off": 0, "Per Shop": 1, "Per Slot": 2},
                                          "description": "Shops are part of the multiworld: every commissary / caravan item (each costs 100 G and shows the multiworld item it holds) is a "
                                                         "check. Per Shop = one check per shop (buying anything there), Per Slot = one check per shop slot; shops and items a quest needs "
                                                         "you to buy stay vanilla. Needs the patcher AND the Skyline loader (Eden; it crashes Ryujinx)."},
                          "questsanity": {"type": "Toggle", "default": True, "display_name": "Questsanity",
                                         "description": "Include quest checks in the pool (about 198 of them, the 'Quests' category). Off removes every quest location from the "
                                                        "world entirely (default on, same as today's behavior before this option existed)."},
                          "open_world": {"type": "Toggle", "default": False, "display_name": "Open World",
                                        "description": "Every region is open from the start except behind seven honor-system checkpoints, in this order: Aetia (the starting "
                                                       "continent, no gate needed) -> Fornis -> Pentelas -> Keves Castle -> Cadensia -> Agnus Castle -> Swordmarch/City, each "
                                                       "one opening as 'Progressive Region' items arrive. Origin instead opens on 'Origin Shard' items (see the two options "
                                                       "below) rather than its usual key/story requirements. Neither item has any in-game effect - the client never grants or "
                                                       "enforces them, so nothing physically stops you from wandering past a checkpoint you have not 'unlocked' yet; this is "
                                                       "logic-only, the same honor system Manual worlds already use for anything with no real memory hook. Replaces only the "
                                                       "one region (Millick Meadows/Fornis) that was gated on Progressive Story Quest - the separate Story Gating option "
                                                       "(which locks main-story cutscenes, not region access) is untouched and can still be on at the same time. Every "
                                                       "colony also starts already at max affinity, written once by the client (needs the running client - everything "
                                                       "else here is pure logic and needs nothing extra). Off (default) leaves world traversal exactly as today, unaffected."},
                          "progressive_region_items": {"type": "Range", "range_start": 6, "range_end": 50, "default": 15,
                                                       "display_name": "Progressive Region Items",
                                                       "description": "Open World only. How many 'Progressive Region' items are placed in the pool. The six checkpoints only "
                                                                      "ever need 6 total (one each), so anything above that is pure slack/redundancy for a better chance of "
                                                                      "finding one earlier - it does not change the order regions unlock in."},
                          "origin_shard_items": {"type": "Range", "range_start": 1, "range_end": 20, "default": 20,
                                                 "display_name": "Origin Shard Items",
                                                 "description": "Open World only. How many 'Origin Shard' items are placed in the pool."},
                          "origin_shard_required": {"type": "Range", "range_start": 1, "range_end": 20, "default": 20,
                                                    "display_name": "Origin Shards Required",
                                                    "description": "Open World only. How many 'Origin Shard' items it actually takes to unlock Origin, independent of how "
                                                                   "many are placed in the pool above. If this is higher than Origin Shard Items, it is silently lowered to "
                                                                   "match so Origin always stays reachable."}},
        "item_base": 0x5C3000,
        "loc_base": 0x5C300000,
        "death_link": False,
        "default_goal": 0,
        "toggle_names": {},
    },
}


def normalize(pkg: str, manual: dict, cfg: dict) -> dict:
    """Turn manual data into the normalized bundle the engine loads. Returns bundle + a validation report."""
    report = []

    # ---- story gating (XC2): Progressive Area (18) becomes Progressive Story Quest (one per locked story step), region rules follow
    story = json.load(open(HERE / cfg["story_gates_file"], encoding="utf-8")) if cfg.get("story_gates_file") else None
    if story:
        def rewrite(text):
            text = re.sub(r"\|Progressive Area:(\d+)\|", lambda m: f"|Progressive Story Quest:{story['requirements'][m.group(1)]}|", text)
            return re.sub(r"^Progressive Area:(\d+)$", lambda m: f"Progressive Story Quest:{story['requirements'][m.group(1)]}", text)
        manual = dict(manual)
        manual["regions"] = {n: dict(r, requires=rewrite(r.get("requires", "")) if isinstance(r.get("requires", ""), str) else r.get("requires", ""))
                             for n, r in manual["regions"].items()}
        manual["locations"] = [dict(l, requires=(rewrite(l["requires"]) if isinstance(l.get("requires", ""), str)
                                                 else [rewrite(x) for x in l.get("requires", [])])) if l.get("requires") else l
                               for l in manual["locations"]]
        manual["items"] = [dict(i, name="Progressive Story Quest", count=story["count"], category=["Story Quests"])
                           if i["name"] == "Progressive Area" else i for i in manual["items"]]

    # ---- remove driver Arts entirely (XC2): per user decision 2026-09-23 ("Drivers aren't working, remove them
    # entirely"). These were the "<Driver> Arts"-category items (Rex Arts, Nia Arts, Zeke Arts, Tora Arts, Vandham
    # Arts, Morag Arts) whose only effect was xc_deliver.py's art_cap mechanic, clamping a driver's WP-bought art
    # level down to copies received - unreliable in live testing. The delivery code path and generator
    # (gen_deliver_xc2.py) were removed too; nothing else in this world's logic ever referenced these items by name
    # (checked regions.json/locations.json - zero hits), so no dead-requirement cleanup is needed, just drop them
    # from the pool. AP's own filler backfill (create_items) covers the now-smaller pool automatically.
    driver_arts_items = {i["name"] for i in manual.get("items", []) if (i.get("category") or [""])[0].endswith(" Arts")}
    if pkg == "xenoblade_2" and driver_arts_items:
        manual = dict(manual)
        manual["items"] = [i for i in manual["items"] if i["name"] not in driver_arts_items]
        report.append(f"removed {len(driver_arts_items)} driver Arts item(s) from the pool entirely (art_cap "
                      f"delivery mechanic removed - unreliable in live testing, per user decision 2026-09-23)")

    # ---- drop vestigial "Chapter N Clear" gates (XC3): the source manual world assumed vanilla pacing (clearing a
    # chapter automatically opens certain areas); the AP-integrated game instead gates exploration by Area Keys and
    # story completion by Progressive Story Quest, so "Chapter N Clear" as a requirement corresponds to nothing the
    # client ever delivers in sync with real access - a region gated on it (e.g. Millick Meadows, blocking the whole
    # Fornis Region cluster behind it) reads permanently locked in the tracker/generator even once the player can
    # really walk there. Demote the items from progression too, since nothing requires them once stripped.
    # (matched by exact name, not category: "Chapter Clear" is also reused by e.g. "Amphitheater Key", a real,
    # still-required x25 gate on a superboss fight - only the seven singular "Chapter N Clear" items are dead)
    dead_chapter_items = {i["name"] for i in manual["items"]
                          if i.get("category") == ["Chapter Clear"] and re.fullmatch(r"Chapter \d Clear", i["name"])}
    if dead_chapter_items:
        manual = dict(manual)
        manual["regions"] = {n: dict(r, requires=(strip_dead_terms(r["requires"], dead_chapter_items) if isinstance(r.get("requires"), str)
                                                   else [strip_dead_terms(x, dead_chapter_items) for x in r.get("requires", [])]))
                             for n, r in manual["regions"].items()}
        manual["locations"] = [dict(l, requires=(strip_dead_terms(l["requires"], dead_chapter_items) if isinstance(l.get("requires"), str)
                                                 else [strip_dead_terms(x, dead_chapter_items) for x in l.get("requires", [])])) if l.get("requires") else l
                               for l in manual["locations"]]
        manual["items"] = [dict(i, progression=False) if i["name"] in dead_chapter_items else i for i in manual["items"]]
        report.append(f"stripped now-vestigial requirement(s) on {', '.join(sorted(dead_chapter_items))} (vanilla chapter-pacing "
                      f"leftover; real gating is Area Keys + Progressive Story Quest) and demoted them from progression")

    # ---- remove Area Keys entirely (XC3): confirmed there is no real in-game flag or barrier behind these - the
    # game's actual movement-blocking system (GMK_FieldLock, the same Condition machinery Story Gating uses) gates on
    # scenario/story progress, not on these items, so they were unenforceable soft locks that only ever caused the
    # tracker/generator to read a real, physically-reachable region as permanently locked. No known way to retrofit a
    # real lock onto them (no position data to place a new one, and existing FieldLocks don't map to these
    # boundaries). Real progression gating for XC3 exploration is Story Gating (Progressive Story Quest), which is a
    # genuine hard lock. Per-user decision 2026-09-22: remove rather than try to make real.
    area_key_items = {i["name"] for i in manual["items"] if i.get("category") == ["Area Keys"]}
    if area_key_items:
        manual = dict(manual)
        manual["regions"] = {n: dict(r, requires=(strip_dead_terms(r["requires"], area_key_items) if isinstance(r.get("requires"), str)
                                                   else [strip_dead_terms(x, area_key_items) for x in r.get("requires", [])]))
                             for n, r in manual["regions"].items()}
        manual["locations"] = [dict(l, requires=(strip_dead_terms(l["requires"], area_key_items) if isinstance(l.get("requires"), str)
                                                 else [strip_dead_terms(x, area_key_items) for x in l.get("requires", [])])) if l.get("requires") else l
                               for l in manual["locations"]]
        manual["items"] = [i for i in manual["items"] if i["name"] not in area_key_items]
        report.append(f"removed {len(area_key_items)} Area Key item(s) and every now-empty requirement referencing "
                      f"them (unenforceable in-game; real XC3 exploration gating is Story Gating)")

    # ---- restore real story-progress gating on region entrances (XC3): the source manual world's only chapter gate
    # (Millick Meadows required "Chapter 1 Clear" + an Area Key) got stripped above as unenforceable dead weight -
    # correctly, neither clause did anything real - but that left the whole Fornis Region cluster (everything that
    # connects through Millick Meadows) reachable from a fresh save, which was never the intent, just an unfixed
    # side effect of removing the fake gate. Replace it with the real mechanism: the Progressive Story Quest count
    # needed to finish chapter 1 (gen_story_gates2_xc3.py / xc_deliver._cap_story - live-verified 2026-09-22 for the
    # flag_type=2 half, see README). This is the only region the source world ever explicitly chapter-gated; no
    # pacing data exists for the other 27, so none of them are touched here.
    if pkg == "xenoblade_3" and "Millick Meadows" in manual.get("regions", {}):
        gates2_path = HERE / "detect" / "xc3_story_gates2.json"
        if gates2_path.exists():
            gates2 = json.load(open(gates2_path, encoding="utf-8"))
            ch1_beats = sum(1 for b in gates2["beats"] if b["chapter"] == 1)
            if ch1_beats:
                manual = dict(manual)
                manual["regions"] = dict(manual["regions"])
                mm = dict(manual["regions"]["Millick Meadows"])
                gate = f"|Progressive Story Quest:{ch1_beats}|"
                mm["requires"] = gate if not mm.get("requires") else f"{mm['requires']} AND {gate}"
                manual["regions"]["Millick Meadows"] = mm
                report.append(f"restored real gating on Millick Meadows (needs {ch1_beats} Progressive Story Quest "
                              f"= chapter 1 complete) - replaces the unenforceable gate stripped above, which "
                              f"otherwise left the whole Fornis Region cluster open from a fresh save")

    # ---- Open World mode (XC3, user decision 2026-09-26): honor-system region-progression gating, layered on TOP
    # of everything above. This file builds one shared .apworld for every player's YAML, not a per-player artifact,
    # so - same technique as the container-gating {YamlDisabled(container_gating)} clause a bit further down - every
    # added clause has to branch on the player's own open_world choice at generate time via {YamlEnabled(...)}/
    # {YamlDisabled(...)}, not a python if here. 'Progressive Region' and 'Origin Shard' have no in-game delivery at
    # all (client never grants/enforces them - pure AP logic, an honor system): the game unlocks in this order -
    # Aetia (the starting continent - already open, no gate) -> Fornis -> Pentelas -> Keves Castle -> Cadensia ->
    # Agnus Castle -> Swordmarch/City - one Progressive Region entry-region gate per cluster boundary (the same
    # single-choke-point shape as the Millick Meadows fix just above), then Origin on Origin Shard instead of its
    # usual (already-unenforceable, see Area Keys above) requirement. Every non-Millick-Meadows gate ANDs onto
    # whatever real requirement is already there (e.g. Wall Climbing/Rope Sliding are real traversal-skill items,
    # untouched); off (default), every added clause reduces to exactly what was there before this ran.
    if pkg == "xenoblade_3":
        OPEN_WORLD_GATES = {
            "Millick Meadows": 1,              # Fornis
            "Rae-Bel Tableland": 2,             # Pentelas
            "Keves Castle": 3,
            "Great Sword's Base": 4,            # Cadensia
            "Agnus Castle Barbican": 5,
            "City": 6,                          # Swordmarch
        }
        manual = dict(manual)
        manual["regions"] = dict(manual["regions"])
        gated = []
        for region_name, need in OPEN_WORLD_GATES.items():
            if region_name not in manual["regions"]:
                continue
            r = dict(manual["regions"][region_name])
            current = r.get("requires", "") or ""
            gate = f"|Progressive Region:{need}|"
            if region_name == "Millick Meadows" and current:
                # replaces (not ANDs onto) the real Progressive Story Quest gate restored above - the whole point
                # of Open World is to not need real story progress to explore
                r["requires"] = f"({{YamlEnabled(open_world)}} AND {gate}) OR ({{YamlDisabled(open_world)}} AND ({current}))"
            else:
                guarded = f"{{YamlDisabled(open_world)}} OR {gate}"
                r["requires"] = guarded if not current else f"({current}) AND ({guarded})"
            manual["regions"][region_name] = r
            gated.append(region_name)
        if "Origin" in manual["regions"]:
            o = dict(manual["regions"]["Origin"])
            current = o.get("requires", "") or ""
            shard_gate = "{YamlDisabled(open_world)} OR {checkOriginShard()}"
            o["requires"] = shard_gate if not current else f"({current}) AND ({shard_gate})"
            manual["regions"]["Origin"] = o
            gated.append("Origin")
        report.append(f"added Open World mode region gating (XC3) to {', '.join(gated)}: honor-system 'Progressive "
                      f"Region' (no in-game effect) gates Fornis/Pentelas/Keves Castle/Cadensia/Agnus Castle/"
                      f"Swordmarch+City in that order behind their one entry region each; Origin instead needs "
                      f"'Origin Shard'. No effect on any of this unless the open_world option is on.")

    # ---- drop the "Dromarch AND Nia (Driver)" core-party clause from Ancient Ship (XC2): the source manual world
    # glues this same clause onto every region from Ancient Ship onward as a blanket "have your team" requirement,
    # but Ancient Ship is the opening salvage dive - it happens before Nia (and her blade Dromarch) are even
    # introduced in the story, so requiring them here is chronologically backwards and reads as an authoring
    # mistake, not an intentional gate. Live-confirmed 2026-09-22: player was already standing in the Ancient Ship
    # (Progressive Story Quest 7/4, Jin received) with neither item, exactly as vanilla pacing would have it. Only
    # Ancient Ship is touched - per user decision, the same clause on Gormott onward is left alone.
    # (superseded below by the general character-recruitment removal, which covers Dromarch/Nia (Driver)
    # everywhere, not just Ancient Ship - kept only as the changelog entry for that original, narrower fix.)

    # ---- remove character recruitment entirely (XC2): per user decision 2026-09-23. Root cause: none of these
    # items have any delivery mechanism (checked deliver.json - only Roc, an "Extra Blades"-style rare blade, has
    # one; every "Characters"-category item and every non-deliverable "Blades"-category item has none) because
    # recruitment genuinely happens through forced story progression, not something AP can ever hand over - these
    # existed purely as logic/tracking items, decoupled from the real game state they claimed to gate on (the
    # Ancient Ship "Dromarch AND Nia (Driver)" bug earlier this session was one symptom of this same root problem:
    # the game grants these through story regardless of whether the AP item has arrived, so gating on them is
    # requiring something that can desync from reality in either direction and can never be resolved by the
    # player - live-confirmed with a real softlock, the Brighid recruitment scene in Torigoth freezing the game
    # when Progressive Story Quest hadn't caught up). Removed entirely (item pool + every requirement referencing
    # them), same treatment as driver Arts and Area Keys earlier.
    #
    # EXCEPT: 14 of these 18 turned out to be load-bearing for a DIFFERENT system - field_skill_logic's
    # field_level() (xc_logic.lua / xc_core.py RuleCompiler) computes Fire Mastery/Cooking/Superstrength/Focus/...
    # from which blades and drivers the player has, and skills.json's own "drivers" list IS exactly 5 of these
    # (Nia (Driver), Tora, Morag, Zeke, Vandham) with 9 more referenced in its "blades" table (Pyra, Aegis True
    # Form, Dromarch, Poppi a, Poppi QT, Poppi QT Pi, Pandoria, Nia (Blade), Brighid). Removing all 18 outright
    # broke generation entirely - live-confirmed 2026-09-23: "No more spots to place 187 items... 31 unreachable
    # regions, 774 unreachable locations" - because with every tracked driver gone, field_level() can never
    # return anything above 0, permanently failing every region requiring a field skill (nearly all of them past
    # Gormott). These 14 get excluded from removal and stay in the pool; only the 4 that skills.json never
    # references (Dagas, Jin, Malos, Sever) are actually safe to remove.
    # Two separate sets, live-confirmed 2026-09-23 both matter:
    #  - pool_removal: safe to delete outright (4 items - skills.json never references them anywhere).
    #  - gate_removal: ALL 18 - every one of them still needs stripping out of region/location requires strings,
    #    regardless of whether it stays in the pool. Live bug found 2026-09-23: after excluding the 14
    #    field-skill-load-bearing items from pool_removal (to fix the generation failure below), they were still
    #    left as flat requirement terms (e.g. Gormott requiring |Pyra| and |Nia (Driver)|) - since none of them
    #    can ever be delivered, that gate can never be satisfied, so the tracker read Gormott as permanently
    #    locked even standing in it with Nia already recruited. Being IN the pool (for field_skill_logic's cnt()
    #    checks, which only need the AP item to be received/counted, not physically delivered) and being a
    #    logic GATE on a region (which needs the requirement to become true) are different questions - these
    #    items can satisfy the first once placed and found, but can never satisfy the second, so they must never
    #    gate anything directly.
    CHAR_RECRUIT_CATS = {"Characters"}
    if pkg == "xenoblade_2":
        deliver_path = HERE / "detect" / "xc2_deliver.json"
        deliver_items = json.load(open(deliver_path, encoding="utf-8"))["items"] if deliver_path.exists() else {}
        skills_path = HERE / "detect" / "xc2_skills.json"
        skills_data = json.load(open(skills_path, encoding="utf-8")) if skills_path.exists() else {}
        field_skill_load_bearing = set(skills_data.get("drivers", [])) | set(skills_data.get("blades", {}))
        gate_removal = {i["name"] for i in manual.get("items", [])
                       if CHAR_RECRUIT_CATS.intersection(as_list(i.get("category")))
                       or ("Blades" in as_list(i.get("category")) and i["name"] not in deliver_items)}
        pool_removal = gate_removal - field_skill_load_bearing
        if gate_removal:
            manual = dict(manual)
            if pool_removal:
                manual["items"] = [i for i in manual["items"] if i["name"] not in pool_removal]
            # known compound clauses the source world glues onto nearly every region/location - both fully dead
            # once every leaf item is stripped, so the whole parenthesized group goes, not just its leaf terms
            # (strip_dead_terms only strips flat top-level terms, it doesn't look inside parens).
            compound_clauses = [
                r"\(\s*\|Dromarch\|\s+and\s+\|Nia \(Driver\)\|\s*\)",
                r"\(\s*\|Jin\|\s+or\s+\(\s*\|Sever\|\s+and\s+\|Malos\|\s*\)\s*\)",
            ]

            def strip_char_refs(text):
                if not isinstance(text, str) or not text:
                    return text
                for clause in compound_clauses:
                    # trailing connector (clause isn't the last term), else leading (clause IS the last term),
                    # else the clause alone (it's the ENTIRE string) - try each until one actually matches
                    for pat in (clause + r"\s+(?:and|or)\s+", r"\s+(?:and|or)\s+" + clause, clause):
                        new = re.sub(pat, "", text, flags=re.IGNORECASE)
                        if new != text:
                            text = new
                            break
                return strip_dead_terms(text, gate_removal)

            manual["regions"] = {n: dict(r, requires=strip_char_refs(r.get("requires", ""))) for n, r in manual["regions"].items()}
            manual["locations"] = [dict(l, requires=(strip_char_refs(l["requires"]) if isinstance(l.get("requires"), str)
                                                     else [strip_char_refs(x) for x in l.get("requires", [])])) if l.get("requires") else l
                                   for l in manual["locations"]]
            report.append(f"removed {len(pool_removal)} character-recruitment item(s) entirely ({', '.join(sorted(pool_removal)) or 'none'}) "
                          f"and stripped ALL {len(gate_removal)} of them out of every region/location requirement "
                          f"({len(gate_removal) - len(pool_removal)} more items kept in the pool only for field_skill_logic's "
                          f"driver/blade calculations, never as a gate: {', '.join(sorted(field_skill_load_bearing & gate_removal))})")

        # ---- remove the 3 Poppi forms from the pool entirely (user decision 2026-09-23). These ARE in
        # field_skill_load_bearing (skills.json's "blades" table - group "poppi", driver "Tora": Poppi a gives
        # Leaping/Nopon Wisdom/Superstrength, Poppi QT gives Lockpicking/Fortitude, Poppi QT Pi gives Keen Eye/
        # Ancient Wisdom), so this looked exactly like the earlier generation-breaking mistake at first glance -
        # checked properly this time before touching anything: every one of those 7 skills has other blades
        # matching or exceeding the Poppi-tier max level (e.g. Leaping tops out at 3 via Poppi a but 5 via Zenobia/
        # T-elos; Superstrength at 3 vs 5 via Wulfric/Zenobia/Poppibuster; same pattern for all the rest), so
        # field_level()'s achievable max never drops for any of them - confirmed safe, not just assumed.
        poppi_removal = {"Poppi a", "Poppi QT", "Poppi QT Pi"} & {i["name"] for i in manual["items"]}
        if poppi_removal:
            manual = dict(manual)
            manual["items"] = [i for i in manual["items"] if i["name"] not in poppi_removal]
            report.append(f"removed {len(poppi_removal)} Poppi form(s) from the pool entirely ({', '.join(sorted(poppi_removal))}) - "
                          f"verified every field skill they provided has another blade matching or beating its max level")

    # ---- re-anchor every XC2 region's Progressive Story Quest threshold to its arc's ENTRANCE beat, not its EXIT
    # beat (systemic version of the Ancient Ship fix above). gates.json's per-area "requirements" table (used by the
    # Progressive Area -> Progressive Story Quest rewrite at the top of this function) consistently resolved each
    # area to the LAST scenario beat still labeled with that area's name (often literally the first beat of the
    # *next* area) rather than the first - e.g. Gormott required 19, which is Gormott's own last beat (20 is
    # Uraya's first); Ancient Ship required 4, which is one beat past its own block (2-3) into the "Elysium Dream"
    # interstitial. Every later region compounds this by ANDing a stale earlier-arc baseline together with its own
    # (also wrong) threshold. Live-confirmed 2026-09-22 for both Ancient Ship and Gormott: the player physically
    # reached each with the story engine already past it, well before the old threshold. Fix: for every region,
    # replace all Progressive Story Quest terms with a single one set to its own arc's first labeled beat (the
    # minimum 'need' among gates.json beats sharing that area label); duplicate/baseline terms collapse away.
    # Regions with no distinct scenario label of their own (Titan Battleship*, FonsaMayma, PostRoc, Factory,
    # PostMorag, Ch7, PostZeke) inherit whichever arc they were already grouped with by number, matching how the
    # source world differentiated them from their siblings via other items (Level 2 Access Key, Vandham, Tora, ...)
    # rather than a separate story count.
    REGION_ARC = {
        "CSEV Maelstrom": "Maelstrom", "Ancient Ship": "Ancient Ship",
        "Gormott": "Gormott", "Gormott2": "Gormott", "Gormott3": "Gormott",
        "Titan Battleship1": "Gormott", "Titan Battleship2": "Gormott",
        "Uraya": "Uraya", "Uraya2": "Uraya", "FonsaMayma": "Uraya", "PostRoc": "Uraya",
        "Mor Ardain": "Mor Ardain", "Mor Ardain2": "Mor Ardain", "Factory": "Mor Ardain", "PostMorag": "Mor Ardain",
        "Letheria": "Leftheria",
        "Indol": "Indol", "PostZeke": "Indol",
        "Temperantia": "Temperantia", "Titan Battleship3": "Temperantia",
        "Tantal": "Tantal", "Tantal2": "Tantal", "Tantal3": "Tantal", "Ch7": "Tantal",
        "Spirit": "Spirit Crucible", "Spirit2": "Spirit Crucible", "Spirit3": "Spirit Crucible",
        "CliffsOfMorytha": "Cliffs of Morytha", "CliffsOfMorytha2": "Cliffs of Morytha",
        "LandOfMorytha": "Land of Morytha", "LandOfMorytha2": "Land of Morytha",
        "WorldTree": "World Tree", "WorldTree2": "World Tree",
        "FLOS": "Elysium",
    }
    # ---- additionally raise the threshold where a map's field enemies run well above what that chapter's story
    # pacing implies (user decision 2026-09-23: "prevent the player from being forced to go to areas with enemies
    # way higher level than them" - a location should not read "in logic" before the player is at a chapter where
    # the level requirement makes sense). Per-map p75 field-enemy level comes from gen_enemy_levels_xc2.py
    # (detect/xc2_enemy_levels.json, boss spawns excluded - see that script for why p75 not median/max). The
    # player's own target level per chapter is a fixed table from the user, not derived. Only ever RAISES a
    # region's threshold (max of the narrative arc-entrance beat and the enemy-appropriate chapter's first beat) -
    # never lowers below what the arc-entrance fix above already established.
    #
    # ENTRANCE regions (the arc's own un-suffixed name - Gormott, Uraya, Mor Ardain, ...) are EXCLUDED from this
    # raise entirely. Bug found live 2026-09-23: applying it to entrances too made generation fail outright
    # ("No more spots to place 187 items... 31 unreachable regions, 774 unreachable locations") - raising Gormott
    # itself to chapter 4 (need 32) created a circular lock, since most of the Progressive Story Quest copies
    # needed to REACH 32 are only findable by way of locations inside Gormott/Uraya/etc. themselves; an entrance
    # region has to stay reachable on its pure narrative threshold alone or nothing past it can ever be reached
    # either. Only deeper/secondary regions (Gormott2, Gormott3, Titan Battleship1/2, Uraya2, FonsaMayma, PostRoc,
    # ...) - which are only ever reached FROM an already-open entrance, not the way in - still get the enemy raise.
    ENTRANCE_REGIONS = {"CSEV Maelstrom", "Ancient Ship", "Gormott", "Uraya", "Mor Ardain", "Letheria", "Indol",
                       "Temperantia", "Tantal", "Spirit", "CliffsOfMorytha", "LandOfMorytha", "WorldTree", "FLOS"}
    CHAPTER_LEVEL = {1: 5, 2: 18, 3: 25, 4: 35, 5: 40, 6: 45, 7: 55, 8: 60, 9: 99, 10: 99}
    ARC_MAP = {
        "Maelstrom": "ma03a", "Ancient Ship": "ma04a", "Gormott": "ma05a", "Uraya": "ma07a", "Mor Ardain": "ma08a",
        "Leftheria": "ma15a", "Indol": "ma11a", "Temperantia": "ma10a", "Tantal": "ma13a", "Spirit Crucible": "ma16a",
        "Cliffs of Morytha": "ma17a", "Land of Morytha": "ma18a", "World Tree": "ma20a", "Elysium": "ma21a",
    }
    enemy_levels_path = HERE / "detect" / "xc2_enemy_levels.json"
    enemy_levels = json.load(open(enemy_levels_path, encoding="utf-8")) if enemy_levels_path.exists() else {}

    if pkg == "xenoblade_2" and story:
        chapter_first: Dict[int, int] = {}
        arc_first: Dict[str, int] = {}
        for b in story.get("beats", []):
            ch = b["scenario"] // 1000
            chapter_first[ch] = min(chapter_first.get(ch, b["need"]), b["need"])
            m = re.match(r"Story Step \d+ \((.+)\)", b.get("label", ""))
            if m:
                lbl = m.group(1)
                arc_first[lbl] = min(arc_first.get(lbl, b["need"]), b["need"])

        def chapter_for_level(lv: float) -> int:
            for ch in sorted(CHAPTER_LEVEL):
                if CHAPTER_LEVEL[ch] >= lv:
                    return ch
            return max(CHAPTER_LEVEL)

        manual = dict(manual)
        manual["regions"] = dict(manual["regions"])
        changed = []
        enemy_raised = []
        for rname, arc in REGION_ARC.items():
            r = manual["regions"].get(rname)
            narrative_target = arc_first.get(arc)
            if r is None or narrative_target is None:
                continue
            target = narrative_target
            stats = enemy_levels.get(ARC_MAP.get(arc, "")) if rname not in ENTRANCE_REGIONS else None
            if stats:
                enemy_chapter = chapter_for_level(stats["p75"])
                enemy_target = chapter_first.get(enemy_chapter)
                if enemy_target and enemy_target > target:
                    target = enemy_target
                    enemy_raised.append(f"{rname} (p75 enemy lv {stats['p75']:.0f} -> chapter {enemy_chapter})")
            before = r.get("requires", "")
            after = set_psq(before, target)
            if after != before:
                r = dict(r)
                r["requires"] = after
                manual["regions"][rname] = r
                changed.append(f"{rname}->{target}")
        if changed:
            report.append(f"re-anchored {len(changed)} region(s)' Progressive Story Quest threshold to their arc's "
                          f"entrance beat instead of its exit beat: {', '.join(changed)}")
        if enemy_raised:
            report.append(f"further raised {len(enemy_raised)} region(s)' threshold above their narrative entrance "
                          f"beat because field enemies there run well ahead of that chapter's target level: "
                          f"{', '.join(enemy_raised)}")

    # ---- containers (XC3): one location per field container (detect/xc3_container_locations.json, gen_container_locations_xc3.py).
    # Every container has its own permanent 1-bit save flag (6914 + its SequentialID in prg/SYS_GimmickLocation, see gen_detect_xc3.py), so
    # each is an individually detected check with its own game region.  With the container_gating option the container is also
    # locked behind its batch of Progressive Container Access items (the patcher's own GMK_TreasureBox condition), so the same
    # requirement applies in logic.  This replaces both the per-region "<Region> - Containers" placeholders and the interim
    # "Container Check N" ordinal pool.
    old_container_locs = [l for l in manual["locations"]
                          if any(re.fullmatch(rf"{re.escape(l.get('region', ''))} - Containers", c) for c in as_list(l.get("category")))
                          or re.fullmatch(r"Container Check \d+", l["name"])]
    container_pool_path = HERE / "detect" / "xc3_container_locations.json"
    if pkg == "xenoblade_3" and (old_container_locs or container_pool_path.exists()):
        manual = dict(manual)
        manual["locations"] = [l for l in manual["locations"] if l not in old_container_locs]
        added = 0
        if container_pool_path.exists():
            pool = json.load(open(container_pool_path, encoding="utf-8"))
            manual["locations"] = manual["locations"] + [
                {"name": c["name"], "region": c["region"], "category": ["containers"],
                 "requires": f"{{YamlDisabled(container_gating)}} OR |Progressive Container Access:{c['batch']}|"}
                for c in pool["locations"]]
            added = pool["count"]
        report.append(f"replaced {len(old_container_locs)} placeholder XC3 container location(s) with {added} individual container locations "
                      f"(one detector flag each; gated by their Progressive Container Access batch when container_gating is on)")

    # ---- strip to autotracked-only locations (both games): per user decision 2026-09-22, remove every location the
    # client cannot detect on its own from the world entirely, not just hide it behind the manual_checks option -
    # Manual Check and anything else with no live-memory detector. Shops (detected by xc_deliver._watch_shops
    # watching the placeholder item, not in detect.json) and goals are always kept regardless. Items are
    # deliberately left untouched here (same reasoning as the PopTracker automatic-only filter: removing a
    # progression item that still gates a KEPT location's requires would make it unreachable in logic even though
    # it is fine in-game - locations are safe to cut on their own, items are not).
    # Bootstrap note: this only has something to filter against once a detect.json already exists for this package
    # (gen_detect_xc2.py / gen_detect_xc3.py, which themselves read this same build's locations.json) - the very
    # first build of a fresh detect table has nothing built yet, so nothing is stripped that pass; build once, run
    # the matching gen_detect_xc*.py, then build again to actually apply the strip.
    SHOP_CATS = {"Shops", "Shop Slots", "shops"}
    detect_path = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + ".json")
    if detect_path.exists():
        detect = json.load(open(detect_path, encoding="utf-8"))
        detected = set(detect.get("locations", {})) | set(detect.get("goals", {}))
        before = len(manual["locations"])
        manual = dict(manual)
        manual["locations"] = [l for l in manual["locations"]
                               if l["name"] in detected or l.get("victory") or SHOP_CATS.intersection(as_list(l.get("category")))]
        removed = before - len(manual["locations"])
        if removed:
            report.append(f"removed {removed} non-autotracked location(s) ({len(manual['locations'])} remain) - per "
                          f"user decision 2026-09-22, only checks the client can send by itself stay in the pool")

    # ---- items
    items = []
    seen = set()
    for it in manual["items"]:
        name = it["name"]
        if name in seen:
            report.append(f"duplicate item name {name!r} (merged)")
            continue
        seen.add(name)
        entry = {
            "name": name,
            "count": int(it.get("count", 1)),
            "category": as_list(it.get("category")),
        }
        for k in ("progression", "useful", "trap", "progression_skip_balancing"):
            if it.get(k):
                entry[k] = True
        items.append(entry)
    if cfg.get("extras_file"):                       # additions of this project (extra items appended, so the manual world's ids stay put)
        for ex in json.load(open(HERE / cfg["extras_file"], encoding="utf-8"))["items"]:
            if ex["name"] in seen:
                report.append(f"extra item {ex['name']!r} already exists (skipped)")
                continue
            seen.add(ex["name"])
            items.append(dict(ex))
    if cfg["filler"] not in seen:
        items.append({"name": cfg["filler"], "count": 0, "category": ["Filler"]})
    item_names = {i["name"] for i in items}

    # ---- events
    events = []
    for ev in manual["events"]:
        events.append({"name": ev["name"], "region": ev.get("region", "Manual"), "category": as_list(ev.get("category"))})

    # ---- locations (ids assigned in file order; victory locations are address-less)
    locations = []
    seen_loc = {}
    extra_locations = json.load(open(HERE / cfg["extras_file"], encoding="utf-8")).get("locations", []) if cfg.get("extras_file") else []

    # ---- gate shop checks on their vendor NPC's own spawn condition (XC2): xc2_shops.py's locations() always
    # emitted "requires": "" - a shop check was only ever gated by its region, with no regard for whether that
    # specific vendor is even standing there yet. User decision 2026-09-23: "poptracker says certain store items
    # are in logic when in reality they are unobtainable until the player completes certain things ... such as
    # merc missions or quests that only trigger in later chapters." The patcher (_xc2_shops in run_randomizer.py)
    # only swaps a shop's item slots for AP placeholders - it never touches the vendor NPC's FLD_NpcPop row, so
    # the vendor's original spawn condition still applies in the patched game exactly as in vanilla.
    # ScenarioFlagMin is directly comparable to gates.json's beat "scenario" field (scenario // 1000 = chapter),
    # so it gets turned into a Progressive Story Quest requirement, same mechanism as the region re-anchoring
    # above. QuestFlag/QuestFlagMin/QuestFlagMax gate on one specific quest's state (this covers the "merc
    # missions" case - FLD_MercenariesMission quests set the same kind of flag) - there is no AP-side detection
    # for arbitrary quest state (xc_autotrack.py only reads location-shaped save flags), so these cannot be
    # enforced here; they are only reported, so the remaining gap is visible rather than silently unfixed.
    if pkg == "xenoblade_2" and story:
        shops_path = HERE / "detect" / "xc2_shops.json"
        if shops_path.exists():
            shop_data = json.load(open(shops_path, encoding="utf-8"))
            shop_cond = {s["name"]: s for s in shop_data["shops"]}
            gated, quest_only = [], []
            for loc in extra_locations:
                base_name = re.sub(r"^Shop (.+?)(?: #\d+)?$", r"\1", loc["name"])
                cond = shop_cond.get(base_name)
                if not cond:
                    continue
                smin = cond.get("scenario_min", 0)
                if smin:
                    ch = smin // 1000
                    target = chapter_first.get(ch)
                    if target:
                        loc["requires"] = set_psq(loc.get("requires", ""), target) if "Progressive Story Quest:" in loc.get("requires", "") \
                            else (f"|Progressive Story Quest:{target}|" if not loc.get("requires") else f"{loc['requires']} and |Progressive Story Quest:{target}|")
                        gated.append(base_name)
                if cond.get("quest_flag") and not (cond.get("quest_min") == 0 and cond.get("quest_max") == 0 and not smin):
                    quest_only.append(base_name)
            if gated:
                report.append(f"gated {len(set(gated))} shop(s)' checks on their vendor's own chapter-appropriate "
                              f"Progressive Story Quest threshold (vendor NPC spawn condition, not just region): "
                              f"{', '.join(sorted(set(gated)))}")
            if quest_only:
                report.append(f"WARNING: {len(set(quest_only))} shop(s) also gate on a specific quest/merc-mission "
                              f"state with no AP-side detection to enforce it (may still read 'in logic' before "
                              f"actually available - needs a live quest-state detector, not built): "
                              f"{', '.join(sorted(set(quest_only)))}")

    drop = re.compile(cfg["drop_location_regex"], re.I) if cfg.get("drop_location_regex") else None
    dropped = 0
    for loc in list(manual["locations"]) + extra_locations:
        name = loc["name"]
        if drop and drop.search(name) and not loc.get("victory"):          # checks the client cannot send automatically yet (goals are kept)
            dropped += 1
            continue
        if name in seen_loc:
            new_name = f"{name} [{loc.get('region', 'Manual')}]"
            n = 2
            while new_name in seen_loc:
                new_name = f"{name} [{loc.get('region', 'Manual')} {n}]"
                n += 1
            report.append(f"duplicate location name {name!r} renamed {new_name!r}")
            name = new_name
        seen_loc[name] = True
        req = loc.get("requires", "")
        if isinstance(req, list):
            req = " AND ".join(f"|{r}|" for r in req) if req else ""
        entry = {"name": name, "region": loc.get("region", "Manual"), "category": as_list(loc.get("category")), "requires": req}
        for k in ("victory", "exclude"):
            if loc.get(k):
                entry[k] = True
        if loc.get("place_item"):
            entry["place_item"] = as_list(loc["place_item"])
        locations.append(entry)
    if dropped:
        report.append(f"{dropped} location(s) dropped (drop_location_regex)")
    nid = cfg["loc_base"]
    for loc in locations:
        if not loc.get("victory"):
            loc["id"] = nid
            nid += 1

    # ---- checks the client cannot detect on its own (no memory detector, not a shop the patcher handles) only exist with the `manual_checks` option: every other location sends its check by itself
    if cfg.get("manual_checks_option"):
        det_path = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + ".json")
        detectable = set(json.load(open(det_path, encoding="utf-8")).get("locations", {})) if det_path.exists() else set()
        client_cats = set(cfg.get("client_detected_categories", []))
        n_manual = 0
        for loc in locations:
            if loc.get("victory") or loc["name"] in detectable or client_cats & set(loc["category"]):
                continue
            loc["category"] = list(loc["category"]) + ["Manual Check"]
            n_manual += 1
        report.append(f"{n_manual} location(s) the client cannot detect are behind the 'manual_checks' option; {len([l for l in locations if not l.get('victory')]) - n_manual} send by themselves")

    # ---- regions (region graph as authored)
    regions = {}
    for name, r in manual["regions"].items():
        regions[name] = {"requires": r.get("requires", "") if isinstance(r.get("requires", ""), str) else "",
                         "connects_to": r.get("connects_to", []) or [], "starting": bool(r.get("starting"))}
    for loc in locations:
        if loc["region"] not in regions and loc["region"] != "Manual":
            regions[loc["region"]] = {"requires": "", "connects_to": [], "starting": False}
            report.append(f"location region {loc['region']!r} missing in regions.json; created open region")
    # locations without a region live in Manual
    for loc in locations:
        if loc["region"] == "Manual":
            loc["region"] = "Free"
            regions.setdefault("Free", {"requires": "", "connects_to": [], "starting": False})
    for ev in events:
        if ev["region"] == "Manual":
            ev["region"] = "Free"
            regions.setdefault("Free", {"requires": "", "connects_to": [], "starting": False})

    # ---- referenced items: everything named in a requires must exist; required items must be progression
    ref_re = re.compile(r"\|([^|]+)\|")
    by_name = {i["name"]: i for i in items}
    event_names = {e["name"] for e in events}
    fixed = set()
    unknown = set()
    strings = [(l["name"], l["requires"]) for l in locations] + [(n, r["requires"]) for n, r in regions.items()]
    for label, req in strings:
        for m in ref_re.findall(req):
            raw = m.strip()
            if raw.startswith("$"):
                continue
            is_cat = raw.startswith("@")
            nm = raw.lstrip("@").split(":")[0].strip()
            if is_cat:
                members = [i for i in items if nm in i["category"]]
                if not members and not any(nm in e["category"] for e in events):
                    unknown.add("@" + nm)
                for i in members:
                    if not i.get("progression") and not i.get("progression_skip_balancing"):
                        i["progression"] = True
                        fixed.add(i["name"])
                continue
            if nm in by_name:
                i = by_name[nm]
                if not i.get("progression") and not i.get("progression_skip_balancing"):
                    i["progression"] = True
                    fixed.add(nm)
            elif nm not in event_names:
                unknown.add(nm)
    if fixed:
        report.append(f"{len(fixed)} item(s) used by rules but not flagged progression in the manual data; promoted to progression: {sorted(fixed)[:12]}{' ...' if len(fixed) > 12 else ''}")
    if unknown:
        report.append(f"requires reference unknown item/category: {sorted(unknown)}")

    # ---- a requirement for N copies of an item that the pool cannot supply makes the content unreachable
    need = {}
    cat_total = {}
    for i in items:
        for c in i["category"]:
            cat_total[c] = cat_total.get(c, 0) + i["count"]
    for label, req in strings:
        for m in ref_re.findall(req):
            raw = m.strip()
            if raw.startswith("$") or raw.startswith("@"):
                continue
            nm, _, cnt = raw.partition(":")
            nm = nm.strip()
            cnt = cnt.strip()
            if nm in by_name and cnt.isdigit():
                need[nm] = max(need.get(nm, 0), int(cnt))
    for nm, n in sorted(need.items()):
        if by_name[nm]["count"] < n:
            report.append(f"DATA FIX: rules need {nm!r} x{n} but the manual pool only has x{by_name[nm]['count']}; raised to {n}")
            by_name[nm]["count"] = n

    # ---- item ids (after promotion so stable ordering only depends on file order)
    nid = cfg["item_base"]
    for i in items:
        i["id"] = nid
        nid += 1

    # ---- option configuration
    game_cfg = {
        "game": cfg["game"],
        "filler": cfg["filler"],
        "death_link": cfg["death_link"],
        "has_traps": any(i.get("trap") for i in items),
        "default_goal": cfg["default_goal"],
        "categories": {},
        "options": {},
        "toggle_names": cfg.get("toggle_names", {}),
        "world_version": "0.1.0",
        "shop_label_width": cfg.get("shop_label_width", 28),
    }
    for cat, cdata in manual["categories"].items():
        if cat in cfg.get("drop_categories", []):
            continue
        if cdata.get("yaml_option"):
            game_cfg["categories"][cat] = {"yaml_option": cdata["yaml_option"]}
    user_opts = (manual.get("options") or {}).get("user", {})
    for name, spec in user_opts.items():
        if name.startswith("_") or name.startswith("Example") or name == "DLC_enabled":
            continue
        s = {"type": spec["type"].title(), "default": spec.get("default", 0), "description": spec.get("description", [name])}
        if spec["type"].title() == "Choice":
            s["values"] = spec["values"]
        if spec["type"].title() == "Range":
            s["range_start"] = spec["range_start"]
            s["range_end"] = spec["range_end"]
            if spec.get("values"):
                s["values"] = spec["values"]
        if spec["type"].title() == "Toggle":
            s["default"] = bool(spec.get("default", False))
        game_cfg["options"][name] = s

    game_cfg["categories"].update(cfg.get("extra_categories", {}))
    for name, spec in cfg.get("extra_options", {}).items():
        game_cfg["options"][name] = spec
    if cfg.get("manual_checks_option"):
        game_cfg["categories"]["Manual Check"] = {"yaml_option": ["manual_checks"]}
        game_cfg["options"]["manual_checks"] = {"type": "Toggle", "default": False, "display_name": "Manual Checks",
                                                "description": "Also include the checks the client cannot detect automatically (they have to be sent by hand with the client's "
                                                               "/check command). Off (default) = every check in your game is sent by the client when you do it."}
    for name, default in cfg.get("option_defaults", {}).items():
        game_cfg["options"][name]["default"] = default
    return {"items": items, "locations": locations, "regions": regions, "events": events, "game": game_cfg, "report": report}


# --------------------------------------------------------------------------------------------------------------------
# Per-game world source (rule functions, hooks)
# --------------------------------------------------------------------------------------------------------------------

INIT_TEMPLATE = '''"""{title} - Archipelago world (native, data-driven; logic ported from the manual apworld)."""
from typing import ClassVar

from BaseClasses import Tutorial
from Options import OptionGroup
from worlds.AutoWorld import WebWorld, World

from .xc_core import XCData, XCMixin, to_identifier
{extra_imports}

XC = XCData(__name__)


def launch_client(*args):
    from worlds.LauncherComponents import launch_subprocess
    from .client import main
    launch_subprocess(main, name="{title} Client", args=args)


def launch_patcher(*args):
    from worlds.LauncherComponents import launch_subprocess
    from .patcher import main
    launch_subprocess(main, name="{title} Patcher", args=args)


try:
    from worlds.LauncherComponents import Component, SuffixIdentifier, Type, components
    components.append(Component("{title} Client", func=launch_client, component_type=Type.CLIENT,
                                game_name=XC.game, supports_uri=True))
    components.append(Component("{title} Patcher", func=launch_patcher, component_type=Type.MISC, game_name=XC.game,
                                file_identifier=SuffixIdentifier("{suffix}")))
except Exception:  # never let a launcher API difference stop the world from loading
    pass


class {klass}WebWorld(WebWorld):
    theme = "grass"
    tutorials = [Tutorial("Multiworld Setup Guide", "How to play {title} in an Archipelago multiworld.", "English",
                          "setup_en.md", "setup/en", ["Claude"])]
    option_groups = [OptionGroup(name, opts) for name, opts in XC.option_groups.items() if opts]


{game_source}


class {klass}(XCMixin, World):
    """{title}: every area key, story item, field skill and unlock is shuffled through the multiworld."""
    game = XC.game
    web = {klass}WebWorld()
    options_dataclass = XC.options_dataclass
    options: XC.options_dataclass  # type: ignore
    xc = XC
    item_name_to_id = XC.item_name_to_id
    location_name_to_id = XC.location_name_to_id
    item_name_groups = XC.item_groups
    location_name_groups = XC.location_groups
    required_client_version = (0, 6, 0)
    rule_functions = RULE_FUNCTIONS
{class_body}
'''

DE_SOURCE = '''
from .collectopaedia import COLLECTOPAEDIA_REQUIREMENTS, COLLECTOPAEDIA_LOCATIONS, PAGE_REQUIREMENTS

REGION_LEVELS = [
    ("Colony 9", 7, "|Colony 9 Access|"), ("Tephra Cave", 12, "|Tephra Cave Access|"),
    ("Bionis' Leg", 25, "|Bionis' Leg Access|"), ("Colony 6", 26, "|Colony 6 Access|"),
    ("Ether Mine", 27, "|Ether Mine Access|"), ("Satorl Marsh", 28, "|Satorl Marsh Access|"),
    ("Bionis' Interior (1st Visit)", 32, "|Bionis' Interior (1st Visit) Access|"),
    ("Makna Forest", 34, "|Makna Forest Access|"), ("Frontier Village", 36, "|Frontier Village Access|"),
    ("Eryth Sea", 37, "|Eryth Sea Access|"), ("Alcamoth", 37, "|Alcamoth Access|"),
    ("High Entia Tomb", 38, "|High Entia Tomb Access|"),
    ("Prison Island (1st Visit)", 42, "|Prison Island (1st Visit) Access|"),
    ("Valak Mountain", 48, "|Valak Mountain Access|"), ("Sword Valley (MISSABLE)", 52, "|Sword Valley Access|"),
    ("Galahad Fortress (MISSABLE)", 55, "|Galahad Fortress Access|"), ("Fallen Arm", 58, "|Fallen Arm Access|"),
    ("Mechonis Field (MISSABLE)", 60, "|Mechonis Field Access|"),
    ("Central Factory (MISSABLE)", 65, "|Central Factory Access|"), ("Agniratha (MISSABLE)", 70, "|Agniratha Access|"),
    ("Mechonis Core", 72, "|Mechonis Core Access|"), ("Bionis' Interior (2nd Visit)", 75, "|Bionis' Interior (2nd Visit) Access|"),
    ("Prison Island (2nd Visit)", 80, "|Prison Island (2nd Visit) Access|"),
]


def _has_danger_tolerance(world, arg):
    """Requires access to the region whose enemy level exceeds (monster level - Danger Tolerance)."""
    effective = int(arg) - world.opt("Danger_Tolerance")
    requirement = ""
    for _region, level, requires in REGION_LEVELS:
        requirement = requires
        if effective < level:
            break
    return requirement or True


def _quest_paola_and_narine(world, arg):
    return ("|Shulk Progressive Affinity Rank:4| AND |Reyn Progressive Affinity Rank:4|"
            " AND ((|Sharla Progressive Affinity Rank:4| AND |Melia Progressive Affinity Rank:4|)"
            " OR (|Sharla Progressive Affinity Rank:4| AND |Fiora Progressive Affinity Rank:4|)"
            " OR (|Sharla Progressive Affinity Rank:4| AND |Seven Progressive Affinity Rank:4|)"
            " OR (|Melia Progressive Affinity Rank:4| AND |Fiora Progressive Affinity Rank:4|)"
            " OR (|Melia Progressive Affinity Rank:4| AND |Seven Progressive Affinity Rank:4|))")


def _yaml_enabled(world, arg):
    return world.opt_on(arg)


def _yaml_disabled(world, arg):
    return not world.opt_on(arg)


def _yaml_compare(world, arg):
    m = re.match(r"\\s*(!?)([A-Za-z0-9_]+)\\s*(==|!=|>=|<=|=|<|>)\\s*(.+?)\\s*$", arg)
    if not m:
        raise ValueError(f"bad YamlCompare({arg})")
    neg, name, op, val = m.groups()
    option = getattr(world.options, to_identifier(name))
    if val.lstrip("-").isdigit():
        target = int(val)
    elif val.lower() in ("true", "false"):
        target = int(val.lower() == "true")
    else:
        target = option.from_text(val).value
    cur = option.value
    result = {"==": cur == target, "=": cur == target, "!=": cur != target, ">=": cur >= target,
              "<=": cur <= target, "<": cur < target, ">": cur > target}[op]
    return (not result) if neg else result


RULE_FUNCTIONS = {
    "hasDangerTolerance": _has_danger_tolerance,
    "questPaolaAndNarineReq": _quest_paola_and_narine,
    "YamlEnabled": _yaml_enabled,
    "YamlDisabled": _yaml_disabled,
    "YamlCompare": _yaml_compare,
}
'''

DE_BODY = '''
    def category_override(self, category):
        version = self.opt("GameVersion")
        if category == "DefinitiveEdition":
            return version >= 1
        if category == "Switch2Version":
            return version == 2
        return None

    def early_hook(self):
        if not self.opt_on("Collectopaedia") and self.opt_on("collectopaediasanity"):
            from Options import OptionError
            raise OptionError(f"{self.player_name}: Collectopaediasanity requires Collectopaedia to be enabled.")
        early = ["Tephra Cave Key", "Bionis' Leg Key", "Colony 6 Key", "Ether Mine Key", "Satorl Marsh Key"]
        for idx in range(min(self.opt("Key_Leniency"), 5)):
            self.multiworld.local_early_items[self.player][early[idx]] = 1

    def rules_hook(self, compiler):
        # Collectopaedia completion checks use the category-progression items rather than the plain region rules.
        if not self.opt_on("Collectopaedia"):
            return
        from worlds.generic.Rules import set_rule
        p = self.player
        sanity = self.opt_on("collectopaediasanity")
        cats = ["Vegetable", "Flower", "Fruit", "Animal", "Bug", "Nature", "Part", "Strange"]

        def cat_ok(state, area, cat):
            if cat == "ALL":
                return all(state.count(f"Progressive {c} Category", p) >= COLLECTOPAEDIA_REQUIREMENTS[area][c] for c in cats)
            return state.count(f"Progressive {cat} Category", p) >= COLLECTOPAEDIA_REQUIREMENTS[area][cat]

        for loc in COLLECTOPAEDIA_LOCATIONS:
            try:
                location = self.multiworld.get_location(loc["name"], p)
            except KeyError:
                continue
            area, cat = loc["area"], loc["cat"]
            if sanity and cat == "ALL":
                members = self.xc.item_groups.get(f"{area} Collectopaedia", set())
                set_rule(location, lambda state, m=tuple(members): all(state.has(n, p) for n in m))
            elif sanity:
                need = PAGE_REQUIREMENTS.get(f"{area}|{cat}", [])
                set_rule(location, lambda state, a=area, c=cat, n=tuple(need): cat_ok(state, a, c) and all(state.has(x, p) for x in n))
            else:
                set_rule(location, lambda state, a=area, c=cat: cat_ok(state, a, c))
'''

XC2_SOURCE = '''
def _check_fragments(world, arg):
    required = world.opt("fragments_required")
    total = world.opt("total_fragments")
    if required > total:
        total, required = required, total
    p = world.player
    return lambda state: state.count("Elysium Fragment", p) >= required


RULE_FUNCTIONS = {"checkFragments": _check_fragments}
'''

XC2_BODY = '''
    def category_override(self, category):
        if category == "Victory":
            return self.active_goal_name == "Collect Elysium fragments"
        return None

    def pool_hook(self, pool):
        if self.active_goal_name == "Collect Elysium fragments":
            required = self.opt("fragments_required")
            total = max(self.opt("total_fragments"), required)
            have = sum(1 for i in pool if i.name == "Elysium Fragment")
            for _ in range(max(0, total - have)):
                pool.append(self.create_item("Elysium Fragment"))
        extra_story = self.opt("extra_story_items")               # user decision 2026-09-23: more copies than any
        for _ in range(max(0, extra_story)):                      # gate ever needs, purely as slack/redundancy
            pool.append(self.create_item("Progressive Story Quest"))
        return pool
'''

XC3_SOURCE = '''
def _yaml_enabled(world, arg):
    return world.opt_on(arg)


def _yaml_disabled(world, arg):
    return not world.opt_on(arg)


def _check_origin_shard(world, arg):
    # Origin Shard Items (pool count) and Origin Shards Required (threshold) are independently player-configured;
    # clamp so a required-higher-than-placed YAML can never make Origin unreachable.
    p = world.player
    need = min(world.opt("origin_shard_required", 20), world.opt("origin_shard_items", 20))
    return lambda state: state.count("Origin Shard", p) >= need


RULE_FUNCTIONS = {"YamlEnabled": _yaml_enabled, "YamlDisabled": _yaml_disabled, "checkOriginShard": _check_origin_shard}
'''
XC3_BODY = '''
    def pool_hook(self, pool):
        # Open World (user decision 2026-09-26): 'Progressive Region' / 'Origin Shard' are honor-system logic
        # items with count 0 in the base data (detect/xc3_extras.json) - pool_hook alone decides how many exist,
        # straight from the player's own Range options, same shape as XC2's extra_story_items/fragments pattern.
        if self.opt_on("open_world"):
            region_total = self.opt("progressive_region_items", 15)
            have_region = sum(1 for i in pool if i.name == "Progressive Region")
            for _ in range(max(0, region_total - have_region)):
                pool.append(self.create_item("Progressive Region"))
            shard_total = self.opt("origin_shard_items", 20)
            have_shard = sum(1 for i in pool if i.name == "Origin Shard")
            for _ in range(max(0, shard_total - have_shard)):
                pool.append(self.create_item("Origin Shard"))
        return pool
'''


PATCHER_TEMPLATE = """import sys


def main(*args):
    from .xc_patch import launch_gui, main as cli_main
    if args:
        launch_gui(str(args[0]))
    else:
        sys.exit("Open a patch file (.apxc*) with this component.")
"""

CLIENT_TEMPLATE = """from .xc_client import run_client

GAME = "__GAME__"


def main(*args):
    run_client(GAME, list(args))
"""




def write_package(pkg: str, bundle: dict, cfg: dict, manual: dict) -> Path:
    pdir = OUT / pkg
    if pdir.exists():
        shutil.rmtree(pdir)
    (pdir / "data").mkdir(parents=True)
    (pdir / "docs").mkdir()
    game = bundle["game"]
    (pdir / "data" / "game.json").write_text(json.dumps(game, indent=1), encoding="utf-8")
    (pdir / "data" / "items.json").write_text(json.dumps(bundle["items"], indent=0), encoding="utf-8")
    (pdir / "data" / "locations.json").write_text(json.dumps(bundle["locations"], indent=0), encoding="utf-8")
    (pdir / "data" / "regions.json").write_text(json.dumps(bundle["regions"], indent=1), encoding="utf-8")
    (pdir / "data" / "events.json").write_text(json.dumps(bundle["events"], indent=0), encoding="utf-8")
    shutil.copy(HERE / "xc_core.py", pdir / "xc_core.py")
    shutil.copy(HERE / "xc_client.py", pdir / "xc_client.py")
    shutil.copy(HERE / "xc_autotrack.py", pdir / "xc_autotrack.py")
    for extra in ("qol.py", "xc_patch.py", "xc_inventory.py", "xc_failsafe.py"):
        shutil.copy(HERE / extra, pdir / extra)
    shutil.copy(HERE.parent / "rando_bridge" / "run_randomizer.py", pdir / "run_randomizer.py")
    (pdir / "patcher.py").write_text(PATCHER_TEMPLATE.replace("__GAME__", cfg["game"]), encoding="utf-8")
    detect = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + ".json")            # xenoblade_2 -> xc2.json, _de -> xcde.json
    if detect.exists():
        shutil.copy(detect, pdir / "data" / "detect.json")
    shutil.copy(HERE / "xc_deliver.py", pdir / "xc_deliver.py")
    shops = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + "_shops.json")
    if shops.exists():
        shutil.copy(shops, pdir / "data" / "shops.json")
    gates = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + "_gates.json")
    if gates.exists():
        shutil.copy(gates, pdir / "data" / "gates.json")
    heroes = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + "_heroes.json")
    if heroes.exists():
        shutil.copy(heroes, pdir / "data" / "heroes.json")
    container_gates = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + "_container_gates.json")
    if container_gates.exists():
        shutil.copy(container_gates, pdir / "data" / "container_gates.json")
    skills = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + "_skills.json")
    if skills.exists():
        shutil.copy(skills, pdir / "data" / "skills.json")
    deliver = HERE / "detect" / (pkg.replace("xenoblade_", "xc") + "_deliver.json")
    if deliver.exists():
        # 2026-09-23 bug fix: this used to be a blind copy. xc2_extras.py's own "deliver" dict (Pouch/Core Chip/Aux
        # Core give-entries) was never merged in, so it never reached the apworld's data/deliver.json - the ONLY
        # file XC2Deliverer actually loads at runtime (xc_client.py: pkgutil.get_data(__package__,
        # "data/deliver.json")). Pouch items happened to still work because gen_deliver_xc2.py independently
        # generates its own separate "Pouch: X x5" entries into xc2_deliver.json; Core Chips and Aux Cores only
        # ever existed in xc2_extras.json's deliver dict, so they were silently never deliverable in-game - the
        # AP item id -> name mapping (items.json) was correct all along, delivery just never had the data for
        # them. Confirmed live 2026-09-23 (items registered as received but never appeared in the inventory).
        deliver_data = json.load(open(deliver, encoding="utf-8"))
        if cfg.get("extras_file"):
            extras_deliver = json.load(open(HERE / cfg["extras_file"], encoding="utf-8")).get("deliver", {})
            deliver_data["items"] = {**deliver_data.get("items", {}), **extras_deliver}
        json.dump(deliver_data, open(pdir / "data" / "deliver.json", "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    (pdir / "client.py").write_text(CLIENT_TEMPLATE.replace("__GAME__", cfg["game"]), encoding="utf-8")
    for fname, content in manual["extra_files"].items():
        (pdir / fname).write_bytes(content)

    extra_imports = "import re" if pkg == "xenoblade_de" else ""
    game_source = {"xenoblade_de": DE_SOURCE, "xenoblade_2": XC2_SOURCE, "xenoblade_3": XC3_SOURCE}[pkg]
    class_body = {"xenoblade_de": DE_BODY, "xenoblade_2": XC2_BODY, "xenoblade_3": XC3_BODY}[pkg]
    init = INIT_TEMPLATE.format(title=cfg["title"], klass=cfg["class"], game_source=game_source,
                                class_body=class_body, extra_imports=extra_imports,
                                suffix={"xenoblade_de": ".apxcde", "xenoblade_2": ".apxc2", "xenoblade_3": ".apxc3"}[pkg])
    (pdir / "__init__.py").write_text(init, encoding="utf-8")
    (pdir / "archipelago.json").write_text(json.dumps({
        "game": cfg["game"], "world_version": "0.1.0", "minimum_ap_version": "0.6.0", "authors": ["Claude"],
        "compatible_version": 7, "version": 7}, indent=2), encoding="utf-8")
    (pdir / "docs" / "setup_en.md").write_text(setup_doc(pkg, cfg), encoding="utf-8")
    (pdir / "docs" / f"en_{cfg['game']}.md").write_text(game_doc(pkg, cfg, bundle), encoding="utf-8")
    return pdir


def zip_package(pdir: Path, pkg: str) -> Path:
    OUT.mkdir(exist_ok=True)
    target = OUT / f"{pkg}.apworld"
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pdir.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                zf.write(f, f"{pkg}/" + f.relative_to(pdir).as_posix())
    return target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    for pkg, cfg in GAMES.items():
        if args.only and pkg not in args.only:
            continue
        manual = read_manual(pkg)
        bundle = normalize(pkg, manual, cfg)
        print(f"== {pkg}: {len(bundle['items'])} items, {len(bundle['locations'])} locations, "
              f"{len(bundle['regions'])} regions, {len(bundle['events'])} events")
        for line in bundle["report"]:
            print("   -", line)
        pdir = write_package(pkg, bundle, cfg, manual)
        target = zip_package(pdir, pkg)
        print("   built", target)
        if args.install:
            shutil.copy(target, CUSTOM_WORLDS / target.name)
            print("   installed ->", CUSTOM_WORLDS / target.name)


if __name__ == "__main__":
    main()
