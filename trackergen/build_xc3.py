"""Build the Xenoblade Chronicles 3 PopTracker pack.

Map art and pin positions come from the FrontierNav wiki's XC3 interactive maps (xc3_fn_maps.py; fetched by
scripts/xc3_fn_download.py): unique monsters, shops (one pin per shop, one section per slot), landmarks, locations and rest spots
that the wiki maps get real pins.  Gamer Guides' interactive maps (xc3_gg_maps.py; scripts/xc3_gg_download.py, registered onto the
FrontierNav images by scripts/xc3_gg_register.py) add quest pins and whatever else the wiki lacks.  Every treasure container is a
check of its own, positioned from prg/SYS_GimmickLocation (the game's world coordinates, registered onto the same images by
scripts/xc3_world_register.py).  Every other check without a position is grouped per region in the panel next to the area map.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import xc3_fn_maps as fnm  # noqa: E402
import xc3_gg_maps as ggm  # noqa: E402

WORLD = Path(r"G:\Archipelago\xc-tools\worldgen\out\xenoblade_3\data")
CONTAINERS = Path(r"G:\Archipelago\xc-tools\worldgen\detect\xc3_container_locations.json")
WORK = Path(r"F:\XCAP\work\tracker_xc3")
ZIP_OUT = Path(os.environ.get("TRACKER_ZIP_OUT", r"G:\Archipelago\poptracker\packs\XC3-AP-Tracker.zip"))     # override while PopTracker has the pack open
MAX_W, MAX_H = 1400, 1400
PIN = 18
MIN_EXTRA_PINS = 2          # wiki sub-maps (upper Aetia, castle floors, ...) only become tabs when at least this many pins land on them

# game map area -> tab title (names from the game's own minimap area-name table)
AREAS = {
    "ma01a": "Aetia Region", "ma04a": "Fornis Region", "ma07a": "Pentelas Region", "ma09a": "Syra Hovering Reefs",
    "ma11a": "Cadensia Region", "ma14a": "Agnus Castle", "ma15a": "City", "ma17a": "Origin", "ma22a": "The Cavity",
}
# game map area -> FrontierNav map id (floor 01 of that area)
FN_BASE = {
    "ma01a": "aetia-region-full", "ma04a": "fornis-region-full", "ma07a": "pentelas-region-full", "ma09a": "syra-hovering-reefs-map",
    "ma11a": "cadensia-region-full-map", "ma14a": "ascension-grounds", "ma15a": "great-sword-upper-chapter-5",
    "ma17a": "origin-interior-map", "ma22a": "great-sword-upper",
}
# manual logic region -> map area (verified by matching location names against each area's location table)
REGION_AREA = {
    "Everblight Plain": "ma01a", "Yzana Plains": "ma01a", "Alfeto Valley": "ma01a", "Melnath's Shoulder": "ma01a",
    "Millick Meadows": "ma01a", "Captocorn Peak": "ma01a",
    "Eagus Wilderness": "ma04a", "Dannagh Desert": "ma04a", "Elaice Highway": "ma04a", "Ribbi Flats": "ma04a", "Rae-Bel Tableland": "ma04a",
    "Urayan Tunnels": "ma07a", "Urayan Trail": "ma07a", "Great Cotte Falls": "ma07a", "Old Cliffside Way": "ma07a",
    "High Maktha Wildwood": "ma07a", "Low Maktha Wildwood": "ma07a",
    "Syra Hovering Reefs": "ma09a", "Keves Castle": "ma09a",
    "Agnus Castle Barbican": "ma11a", "Great Sword's Base": "ma11a", "Erythia Sea": "ma11a", "Li Garte Prison Camp": "ma11a",
    "Agnus Castle": "ma14a", "City": "ma15a", "Great Sword's Hilt": "ma15a", "Origin": "ma17a", "The Cavity": "ma22a",
}


def group_label(l: dict) -> str:
    cats = set(l["category"])
    for cat, label in (("bosses", "Bosses"), ("uniquemonsters", "Unique Monsters"), ("enemies", "Enemies"), ("quests", "Quests"),
                       ("affinitychart", "Affinity Chart"), ("landmarks", "Landmarks"), ("locations", "Locations"),
                       ("restspots", "Rest Spots"), ("shops", "Shops"), ("Shops", "Shops"), ("Shop Slots", "Shops"),
                       ("containers", "Chests")):
        if cat in cats:
            return label
    return "Other"


def item_group_of(i):
    return (i.get("category") or ["Other"])[0]


def build(automatic_only: bool = False):
    meta = fnm.load_meta()
    locations = json.load(open(WORLD / "locations.json", encoding="utf-8"))
    maps, key_of, scale = {}, {}, {}
    for area, title in AREAS.items():
        fn_id = FN_BASE[area]
        img, f = fnm.load_map(meta, fn_id, MAX_W, MAX_H)
        maps[area] = {"title": title, "img": img, "pin": PIN}
        key_of[fn_id], scale[fn_id] = area, f
    area_title = {k: v["title"] for k, v in maps.items()}
    # sub-maps of the wiki (upper Aetia, castle floors, Maktha Wildwood ...) get their own tab if enough checks are pinned on them
    extras = [i for i in meta if i not in key_of]
    for fn_id in extras:
        img, f = fnm.load_map(meta, fn_id, MAX_W, MAX_H)
        key_of[fn_id], scale[fn_id] = fn_id, f
        maps[fn_id] = {"title": meta[fn_id]["name"], "img": img, "pin": PIN}
    pins = fnm.pins_for(locations, meta, key_of, scale)
    gg, regs = ggm.load_gg(), ggm.load_registration()
    land = ggm.land_masks({k: v["img"] for k, v in maps.items()})
    for name, entries in ggm.pins_for(locations, gg, regs, key_of, scale, land).items():          # what the wiki maps lack (quests, ...)
        have = {e[0] for e in pins.get(name, [])}
        pins.setdefault(name, []).extend(e for e in entries if e[0] not in have)
    # every container is a check of its own (one save flag each); its game-world coordinates are carried onto the map images
    containers = json.load(open(CONTAINERS, encoding="utf-8"))["locations"]
    pins.update(ggm.container_pins(containers, gg, regs, ggm.load_world_registration(), key_of, scale, land))
    per_tab = {}
    for entries in pins.values():
        for e in entries:
            per_tab[e[0]] = per_tab.get(e[0], 0) + 1
    for fn_id in extras:
        if per_tab.get(fn_id, 0) < MIN_EXTRA_PINS:
            del maps[fn_id]
    pins = {n: [e for e in es if e[0] in maps] for n, es in pins.items()}
    pins = {n: es for n, es in pins.items() if es}
    print(f"containers pinned: {sum(1 for c in containers if c['name'] in pins)} of {len(containers)} (the rest are listed beside the map)")
    print(f"pins: {len(pins)} checks pinned on {len({e[0] for es in pins.values() for e in es})} maps ({sorted(maps)})")

    def parent_of(l):
        return area_title[REGION_AREA[l["region"]]]

    region_map = {title: area for area, title in area_title.items()}
    zip_out = ZIP_OUT.with_name("XC3-AP-Tracker-AutoOnly.zip") if automatic_only else ZIP_OUT
    cfg = {
        "skip_categories": [],
        "automatic_only": automatic_only,
        "uid": "xenoblade_3_ap_auto" if automatic_only else "xenoblade_3_ap",
        "title": "Xenoblade Chronicles 3 AP Tracker (Automatic Checks Only)" if automatic_only else "Xenoblade Chronicles 3 AP Tracker",
        "game_name": "Xenoblade Chronicles 3",
        "world_dir": str(WORLD), "work_dir": str(WORK), "zip_out": str(zip_out), "maps": maps, "pin_positions": pins,
        "region_map": region_map, "group_of": group_label, "parent_of": parent_of, "sub_region_of": lambda l: l["region"],
        "item_group_of": item_group_of, "row_h": 26,
        "left_groups": ["Area Keys", "Traversal Skills", "Hunting Licenses", "Flutes", "Chapter Clear"],
        "priority_groups": ["Chests"],
        "wide_groups": {"Key Items": (16, 34), "Gem Crafting": (16, 34), "Collectopaedia Decks": (16, 34), "Hero Access": (16, 34),
                        "Manana's Menu": (16, 34)},
        "min_map": (950, 700), "game_lua": "", "item_size": 38, "readme": README,
    }
    pack = common.Pack(cfg)
    z = pack.build()
    print(f"built {z} {pack.stats}")


README = """# Xenoblade Chronicles 3 - Archipelago PopTracker

Pack for the `Xenoblade Chronicles 3` Archipelago world (items, live logic, autotracking, check lists per region).

* Each tab is an area map from the FrontierNav wiki (https://frontiernav.net - map data credit: FrontierNav contributors), stitched from
  the wiki's map tiles.  Marker positions also come from Gamer Guides' interactive maps (https://www.gamerguides.com - credit: Gamer
  Guides), laid onto those images, and are cross-checked against the game's own object positions.
* Checks with a map position get a real pin: unique monsters, quests, landmarks / locations / rest spots, shops (one pin per shop,
  one section per slot) and treasure containers.  Everything else (bosses, affinity chart, ...) stays in the panel beside the map,
  listed per region and coloured by what is in logic.
* Every treasure container is a check of its own ("<place> Container N"), detected by its own save flag and pinned at its real position
  (the game's own world coordinates, laid onto the maps).  With Container Gating on, a container also needs its batch of
  Progressive Container Access items.
* Logic is evaluated live from the world's rule data (`scripts/xc_logic.lua`); options come from slot data.
"""

if __name__ == "__main__":
    build()
    build(automatic_only=True)
