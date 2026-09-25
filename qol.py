"""Quality-of-life YAML options, mapped onto the Series Randomizer's own options (third party; used only to build the game-data mod).

Each entry: (yaml key, kind, title, doc, default, (range_start, range_end) or None, builder)
builder(value) -> a fragment of the randomizer config  {"<Option name>": True | {"on":..,"spin":..,"sub":{"<Sub name>": bool | {"on":..,"spin":..}}}}
or None when the value means "off".  Fragments are deep-merged (an explicit True beats False).
EXP / SP / WP / CP style boosts are NOT here: the client's live `experience_multiplier` already covers them without touching game data.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

XC2 = "Xenoblade Chronicles 2"
XC3 = "Xenoblade Chronicles 3"
XCDE = "Xenoblade Chronicles DE"


def _on(name: str, **extra):
    return {name: {"on": True, **extra}}


QOL: Dict[str, List[tuple]] = {
    XC2: [
        ("qol_tutorial_skips", "toggle", "Tutorial Skips", "Skips as many tutorials and early Argentum quests as possible.", False, None,
         lambda v: {"Tutorial Skips": True} if v else None),
        ("qol_quest_skips", "toggle", "Quest Skips", "Speeds up several tedious main-story quests (puzzle tree wood, Nia rumours, indol quiz, ...).", False, None,
         lambda v: _on("Quest Skips") if v else None),
        ("qol_easy_affinity_trees", "toggle", "Easy Affinity Trees",
         "Trust is the only condition for levelling up a blade's affinity tree, so blade skills fill in by themselves when a new trust level is reached.",
         True, None, lambda v: {"Easy Affinity Trees": True} if v else None),
        ("qol_field_skill_reduction", "range", "Field Skill Level Reduction", "Lowers every field skill requirement in the world by this many levels (0 = off).", 0, (0, 12),
         lambda v: _on("Field Skills", sub={"Reduce All Field Skills": {"on": True, "spin": v}, "Remove Story Field Skills": False, "Remove All Field Skills": False}) if v else None),
        ("qol_freely_engage_blades", "toggle", "Freely Engage Blades", "Every driver can engage every blade.", False, None,
         lambda v: {"Freely Engage Blades": True} if v else None),
        ("qol_movespeed_boost", "range", "Movement Speed Boost", "Adds a permanent movement speed bonus (in steps of 10%, x10; 0 = off).", 0, (0, 50),
         lambda v: _on("Resource Boosts", sub={"EXP Boost": False, "SP Boost": False, "WP Boost": False, "Movespeed Boost": {"on": True, "spin": v}}) if v else None),
        ("qol_chest_visibility", "toggle", "Increase Chest Visibility", "Treasure chests are easier to spot.", False, None,
         lambda v: _on("Treasure Chests", sub={"Chest Type Matches Contents": False, "Increase Chest Visibility": True, "Condense Gold Loot": False}) if v else None),
        ("qol_condense_gold", "toggle", "Condense Gold Loot", "Gold from chests drops as a single pile.", False, None,
         lambda v: _on("Treasure Chests", sub={"Chest Type Matches Contents": False, "Increase Chest Visibility": False, "Condense Gold Loot": True}) if v else None),
        ("qol_everlasting_pouch_items", "toggle", "Everlasting Pouch Items", "Pouch items last as long as possible.", False, None,
         lambda v: {"Everlasting Pouch Items": True} if v else None),
        ("qol_mute_popups", "toggle", "Mute Popups", "Stops blade skill / pouch item refill / landmark popups.", False, None,
         lambda v: {"Mute Popups": True} if v else None),
    ],
    XC3: [
        ("qol_tutorial_skips", "toggle", "Tutorial Skips", "Removes tutorials; as a side effect all systems are available from the start.", False, None,
         lambda v: {"Tutorial Skips": True} if v else None),
        ("qol_speed_boost", "range", "Movement Speed Boost", "Colony 4's affinity reward becomes an instant movement speed deed (percent speed, 0 = off).", 0, (0, 255),
         lambda v: _on("Speed Boost", spin=v) if v else None),
        ("qol_early_arts_cancel", "toggle", "Early Arts Cancel", "The Art of Flow is given during the introduction.", False, None,
         lambda v: {"Early Arts Cancel": True} if v else None),
        ("qol_easy_gem_crafting", "toggle", "Easy Gem Crafting", "Reduces the material requirements for gem crafting.", False, None,
         lambda v: {"Easy Gem Crafting": True} if v else None),
    ],
    XCDE: [
        ("qol_quickstep", "range", "Quickstep", "The gem man gifts two free quickstep gems (percent speed, 0 = off).", 0, (0, 100),
         lambda v: _on("Quickstep", spin=v) if v else None),
        ("qol_easy_affinity", "toggle", "Easy Affinity", "Area affinity is maxed out after any quest.", False, None,
         lambda v: {"Easy Affinity": True} if v else None),
    ],
}


def _merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge two randomizer option dicts; an explicit True beats False, spins and subs are combined."""
    out = dict(a)
    for k, vb in b.items():
        if k not in out:
            out[k] = vb
            continue
        va = out[k]
        da = va if isinstance(va, dict) else {"on": bool(va)}
        db = vb if isinstance(vb, dict) else {"on": bool(vb)}
        merged = {**da, **db}
        merged["on"] = bool(da.get("on")) or bool(db.get("on"))
        subs = dict(da.get("sub", {}))
        for sk, sv in db.get("sub", {}).items():
            if sk in subs:
                sa = subs[sk] if isinstance(subs[sk], dict) else {"on": bool(subs[sk])}
                sb = sv if isinstance(sv, dict) else {"on": bool(sv)}
                m = {**sa, **sb}
                m["on"] = bool(sa.get("on")) or bool(sb.get("on"))
                subs[sk] = m
            else:
                subs[sk] = sv
        if subs:
            merged["sub"] = subs
        out[k] = merged
    return out


def qol_config(game: str, slot_data: Dict[str, Any]) -> Dict[str, Any]:
    """Randomizer option dict for the QoL choices stored in a slot's data."""
    cfg: Dict[str, Any] = {}
    for key, kind, _title, _doc, default, _rng, builder in QOL.get(game, []):
        value = slot_data.get(key, default)
        frag = builder(bool(value) if kind == "toggle" else int(value))
        if frag:
            cfg = _merge(cfg, frag)
    return cfg
