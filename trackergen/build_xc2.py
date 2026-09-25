"""Build the Xenoblade Chronicles 2 PopTracker pack (real in-game area maps + per-area check panels)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

XC3_TEX = r"G:\Archipelago\xc-tools\xc3_lib\xc3_tex.exe"
EXTRACTED = Path(r"F:\XCAP\extracted\xc2")
MAP_CACHE = Path(r"F:\XCAP\work\xc2_maps")
WORLD = Path(r"G:\Archipelago\xc-tools\worldgen\out\xenoblade_2\data")
WORK = Path(r"F:\XCAP\work\tracker_xc2")
ZIP_OUT = Path(os.environ.get("TRACKER_ZIP_OUT", r"G:\Archipelago\poptracker\packs\XC2-AP-Tracker.zip"))     # override while PopTracker has the pack open
MAX_W, MAX_H = 1150, 900

# in-game area (BDAT resource prefix) -> tab title
AREAS = {
    "ma03a": "C.S.E.V. Maelstrom", "ma04a": "Ancient Ship", "ma05a": "Gormott Province", "ma07a": "Kingdom of Uraya",
    "ma08a": "Empire of Mor Ardain", "ma15a": "Leftherian Archipelago", "ma10a": "Temperantia",
    "ma11a": "Indoline Praetorium", "ma13a": "Kingdom of Tantal", "ma16a": "Spirit Crucible Elpys",
    "ma17a": "Cliffs of Morytha", "ma18a": "Land of Morytha", "ma20a": "World Tree", "ma21a": "First Low Orbit Station",
}
# logic region (manual) -> area key ("misc" = no map image of its own)
REGION_AREA = {
    "CSEV Maelstrom": "ma03a", "Ancient Ship": "ma04a", "Gormott": "ma05a", "Gormott2": "ma05a", "Gormott3": "ma05a",
    "Uraya": "ma07a", "Uraya2": "ma07a", "FonsaMayma": "ma07a", "PostRoc": "ma07a",
    "Mor Ardain": "ma08a", "Mor Ardain2": "ma08a", "Factory": "ma08a", "PostMorag": "ma08a",
    "Letheria": "ma15a", "Indol": "ma11a", "PostZeke": "ma11a", "Temperantia": "ma10a",
    "Tantal": "ma13a", "Tantal2": "ma13a", "Tantal3": "ma13a", "Ch7": "ma13a",
    "Spirit": "ma16a", "Spirit2": "ma16a", "Spirit3": "ma16a",
    "CliffsOfMorytha": "ma17a", "CliffsOfMorytha2": "ma17a", "LandOfMorytha": "ma18a", "LandOfMorytha2": "ma18a",
    "WorldTree": "ma20a", "WorldTree2": "ma20a", "FLOS": "ma21a",
    "Titan Battleship1": "misc", "Titan Battleship2": "misc", "Titan Battleship3": "misc", "Free": "misc",
}


def decode(name: str):
    MAP_CACHE.mkdir(parents=True, exist_ok=True)
    png = MAP_CACHE / f"{name}.png"
    if not png.exists():
        tmp = MAP_CACHE / f"_{name}"
        tmp.mkdir(exist_ok=True)
        subprocess.run([XC3_TEX, str(EXTRACTED / "menu/image" / f"{name}.wilay"), str(tmp)], check=True, capture_output=True)
        dds = sorted(tmp.glob("*.dds"))[0]
        subprocess.run([XC3_TEX, str(dds), str(png)], check=True, capture_output=True)
    return Image.open(png)


def best_map(area: str):
    """Pick the area's largest floor image (the overworld / main floor)."""
    cands = sorted(p.stem for p in (EXTRACTED / "menu/image").glob(f"{area}_*_map.wilay"))
    best, best_px = None, 0
    for c in cands:
        if "shipoff" in c or "lodoff" in c:
            continue
        im = decode(c)
        if im.width * im.height > best_px:
            best, best_px = im, im.width * im.height
    return best


def tint(im: Image.Image) -> Image.Image:
    """Composite the RGBA in-game map over the tracker's navy background."""
    bg = Image.new("RGB", im.size, (14, 20, 40))
    bg.paste(im.convert("RGB"), mask=im.getchannel(3))
    f = min(1.0, MAX_W / bg.width, MAX_H / bg.height)
    return bg.resize((max(1, int(bg.width * f)), max(1, int(bg.height * f))), Image.LANCZOS)


def group_label(l: dict) -> str:
    cats = l["category"]
    for c in cats:
        for suffix, label in ((" Story", "Story"), (" Landmarks", "Landmarks"), (" Locations", "Locations"), (" Chests", "Chests"),
                              (" Heart to Hearts", "Heart-to-Hearts")):
            if c.endswith(suffix):
                return label
    for c, label in (("Hearttoheart", "Heart-to-Hearts"), ("Blade summoning", "Blade Summoning"), ("Pouch Favorites", "Pouch Favorites"),
                     ("Chestsanity", "Chests"), ("Landmarksanity", "Landmarks"), ("Locationsanity", "Locations"), ("URQBlades", "Non-story Blades"),
                     ("Shops", "Shops"), ("Shop Slots", "Shops")):
        if c in cats:
            return label
    return "Other"


def build(automatic_only: bool = False):
    maps = {}
    for area, title in AREAS.items():
        im = best_map(area)
        if im is None:
            print("no map for", area)
            continue
        maps[area] = {"title": title, "img": tint(im), "pin": 20}
    # plain canvas for checks that belong to no single area map
    maps["misc"] = {"title": "Other / Story", "img": Image.new("RGB", (900, 420), (14, 20, 40)), "pin": 20}
    region_map = {}
    area_title = {k: v["title"] for k, v in maps.items()}

    def parent_of(l):
        return area_title.get(REGION_AREA.get(l["region"], "misc"), "Other / Story")

    for r, a in REGION_AREA.items():
        region_map[area_title.get(a, "Other / Story")] = a if a in maps else "misc"

    def item_group_of(i):
        c = (i.get("category") or ["Other"])[0]
        return {"Areas": "Progress", "Story Items": "Story Items", "Victory": "Goal"}.get(c, c)

    zip_out = ZIP_OUT.with_name("XC2-AP-Tracker-AutoOnly.zip") if automatic_only else ZIP_OUT
    cfg = {
        "skip_categories": [],
        "automatic_only": automatic_only,
        "uid": "xenoblade_2_ap_auto" if automatic_only else "xenoblade_2_ap",
        "title": "Xenoblade Chronicles 2 AP Tracker (Automatic Checks Only)" if automatic_only else "Xenoblade Chronicles 2 AP Tracker",
        "game_name": "Xenoblade Chronicles 2",
        "world_dir": str(WORLD), "work_dir": str(WORK), "zip_out": str(zip_out), "maps": maps, "pin_positions": {},
        "region_map": region_map, "group_of": group_label, "parent_of": parent_of, "item_group_of": item_group_of,
        "left_groups": ["Progress", "Characters", "Blades", "Extra Blades", "Trust Global", "Story Items"],
        "priority_groups": ["Chests"],
        "min_map": (1000, 640),
        "game_lua": XC2_LUA, "item_size": 40, "readme": README,
    }
    pack = common.Pack(cfg)
    z = pack.build()
    print("built", z, pack.stats)


XC2_LUA = r'''
-- Xenoblade Chronicles 2: Elysium Fragment goal
XC.funcs.checkFragments = function()
    local required = XC.opt("fragments_required")
    local total = XC.opt("total_fragments")
    if required > total then required = total end
    return function() return XC.count("Elysium Fragment") >= required end
end
'''

README = """# Xenoblade Chronicles 2 - Archipelago PopTracker

Pack for the `Xenoblade Chronicles 2` Archipelago world.

* Each tab is the game's own area map (extracted from the RomFS) for that part of the story; the checks that belong to the
  area are listed in the panel on the left of the map (Story / Landmarks / Locations / Chests / ...).
  XC2 stores landmark and chest positions inside its map object files rather than in the BDAT tables, so individual
  checks are not pinned on the map.
* Logic is evaluated live from the world's own rule data (`scripts/xc_logic.lua`); options come from slot data.
"""

if __name__ == "__main__":
    build()
    build(automatic_only=True)
