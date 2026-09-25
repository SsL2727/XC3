"""GamerGuides XC3 map markers, registered onto the FrontierNav map images used by the tracker.

`scripts/xc3_gg_download.py` saves each GamerGuides map's markers in that map's native image pixels.  Both sites draw the same game
map textures, so a GamerGuides pixel maps to a FrontierNav image pixel by a uniform scale plus an offset; `scripts/xc3_gg_register.py`
finds that transform per map by matching the two terrain silhouettes and saves it to gg_registration.json.  Here the markers become
tracker pins: quests and other named checks the FrontierNav maps lack.  Every treasure container is a check of its own with an exact
game-world position (prg/SYS_GimmickLocation); `scripts/xc3_world_register.py` registers those world coordinates onto the same images
(native px = 2 * world + offset), so containers are placed from the game's own data, cross-checked against the Gamer Guides markers.
Marker data credit: Gamer Guides (https://www.gamerguides.com).
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageFilter

import xc3_fn_maps as fnm

DIR = Path(r"F:\XCAP\extracted\xc3_maps")
GG_DIR = DIR / "gg"


def norm(s: str) -> str:
    s = re.sub(r"\s*\((?:Lv\.?\s*\d+)\)\s*$", "", s)
    s = re.sub(r"^Shop\s+", "", s)
    s = re.sub(r"\s*#\d+\s*$", "", s)
    s = re.sub(r"\s*\(\d+\)\s*$", "", s)
    return re.sub(r"[^a-z0-9]+", "", s.replace("\u2019", "'").lower())


def load_gg() -> Dict[str, dict]:
    return {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(str(GG_DIR / "*.json")))}


def kind(icon: str) -> str:
    """Category of a GamerGuides marker from its icon name."""
    i = icon.lower()
    for key, label in (("container", "Container"), ("landmark", "Landmark"), ("location", "Location"), ("rest_spot", "Rest Spot"),
                       ("hero_quest", "Quest"), ("standard_quest", "Quest"), ("quest_related", "Quest Event"),
                       ("unique_enemy", "Unique Enemy"), ("elite_enemy", "Elite Enemy"), ("named_grave", "Named Grave"),
                       ("secret_area", "Secret Area"), ("shop", "Shop"), ("commissary", "Shop"), ("husk", "Soldier Husk"),
                       ("ether_channel", "Ether Channel"), ("info", "Info Fragment")):
        if key in i:
            return label
    return "Other"


# FrontierNav feature target type -> GamerGuides marker kinds it can be the same thing as (names repeat across kinds: a unique
# monster and its named grave share a title)
COMPATIBLE = {"Enemy": {"Unique Enemy", "Elite Enemy"}, "Location": {"Landmark", "Location", "Rest Spot", "Secret Area"},
              "Shops": {"Shop"}, "Canteen": {"Rest Spot"}}


def name_pairs(gg_map: dict, fn_map: dict) -> List[Tuple[float, float, float, float]]:
    """(gx, gy, fx, fy) for every FrontierNav feature that has exactly one same-named, same-kind GamerGuides marker."""
    g: Dict[str, List[dict]] = {}
    for m in gg_map["markers"]:
        if m["title"]:
            g.setdefault(norm(m["title"]), []).append(m)
    out = []
    for x in fn_map["features"]:
        allowed = COMPATIBLE.get(x.get("ttype"))
        if not allowed:
            continue
        cands = []
        for nm in {x["name"], x.get("tname") or ""}:
            cands += [m for m in g.get(norm(nm), []) if kind(m["icon"]) in allowed] if nm else []
        cands = list({id(m): m for m in cands}.values())
        if len(cands) == 1:
            out.append((cands[0]["x"], cands[0]["y"], x["x"], x["y"]))
    return out


REG = DIR / "gg_registration.json"
WORLD_REG = DIR / "world_to_gg.json"
MIN_IOU = 0.6                # silhouette overlap below which a registration is not trusted ...
MIN_PAIRS, MAX_PAIR_RMS = 5, 45      # ... unless enough same-named markers in both sources agree with it (px of the FrontierNav image)

# AP location category -> GamerGuides marker kinds that are the same thing
PIN_KINDS = {"quests": {"Quest", "Quest Event"}, "uniquemonsters": {"Unique Enemy"}, "landmarks": {"Landmark", "Secret Area"},
             "locations": {"Location", "Landmark"}, "restspots": {"Rest Spot"}}


def load_registration() -> Dict[str, dict]:
    """{GG map slug (or "slug#piece"): {"fn", "s", "tx", "ty", "iou", ["box"], ...}} for the fits good enough to trust."""
    if not REG.exists():
        return {}
    return {k: v for k, v in json.load(open(REG, encoding="utf-8")).items()
            if v["iou"] >= MIN_IOU or (v.get("pairs", 0) >= MIN_PAIRS and v.get("rms", 1e9) <= MAX_PAIR_RMS)}


def land_masks(images: Dict[str, Image.Image]) -> Dict[str, Image.Image]:
    """{tab key: mask at 1/4 size, white within ~12 px of terrain} from the tracker's tab images (world margin = fnm.BG)."""
    out = {}
    for tab, im in images.items():
        diff = ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, fnm.BG)).convert("L")
        out[tab] = diff.point(lambda v: 255 if v > 6 else 0).reduce(4).point(lambda v: 255 if v else 0).filter(ImageFilter.MaxFilter(7))
    return out


def on_land(land: Optional[Dict[str, Image.Image]], tab: str, x: int, y: int) -> bool:
    """Is (x, y) within ~12 px of terrain on the tab image (always true without a mask for that tab)?"""
    if land is None or tab not in land:
        return True
    lm = land[tab]
    return 0 <= x // 4 < lm.width and 0 <= y // 4 < lm.height and bool(lm.getpixel((x // 4, y // 4)))


def placed(gg: Dict[str, dict], regs: Dict[str, dict], key_of: Dict[str, str], scale: Dict[str, float],
           land: Optional[Dict[str, Image.Image]] = None):
    """Yield (slug, tab key, marker, tracker x, tracker y) for every GamerGuides marker on a map that is a tracker tab.

    Some GamerGuides maps cover more ground than their FrontierNav counterpart (Keves Castle's interior): with `land` given, markers
    that fall in the tab image's empty margin are skipped rather than pinned on nothing."""
    for key, r in regs.items():                      # "<slug>" or "<slug>#<piece>" (a piece of a collage map, limited to its box)
        slug = key.split("#")[0]
        if slug not in gg or r["fn"] not in key_of:
            continue
        f = scale[r["fn"]]
        tab = key_of[r["fn"]]
        box = r.get("box")
        for m in gg[slug]["markers"]:
            if box and not (box[0] <= m["x"] < box[2] and box[1] <= m["y"] < box[3]):
                continue
            x, y = round((r["s"] * m["x"] + r["tx"]) * f), round((r["s"] * m["y"] + r["ty"]) * f)
            if on_land(land, tab, x, y):
                yield slug, tab, m, x, y


def pins_for(locations: List[dict], gg: Dict[str, dict], regs: Dict[str, dict], key_of: Dict[str, str],
             scale: Dict[str, float], land: Optional[Dict[str, Image.Image]] = None) -> Dict[str, list]:
    """{AP location name: [(tab key, x, y), ...]} for checks whose name matches a named GamerGuides marker of the same kind."""
    idx: Dict[str, List[Tuple[str, int, int, str]]] = {}
    for _, tab, m, x, y in placed(gg, regs, key_of, scale, land):
        if m["title"]:
            idx.setdefault(norm(m["title"]), []).append((tab, x, y, kind(m["icon"])))
    out: Dict[str, list] = {}
    for l in locations:
        cat = next((c for c in PIN_KINDS if c in (l.get("category") or [])), None)
        if not cat:
            continue
        seen, entries = set(), []
        for tab, x, y, k in idx.get(norm(l["name"]), []):
            if k in PIN_KINDS[cat] and tab not in seen:             # first marker per tab (a quest can list its giver and its goal)
                seen.add(tab)
                entries.append((tab, x, y))
        if entries:
            out[l["name"]] = entries
    return out


def load_world_registration() -> Dict[str, dict]:
    """{registration key: {"map", "k", "sx", "sz", "tx", "ty", ...}}: game world (X, Z) -> Gamer Guides native px (xc3_world_register.py)."""
    return json.load(open(WORLD_REG, encoding="utf-8")) if WORLD_REG.exists() else {}


def container_pins(containers: List[dict], gg: Dict[str, dict], regs: Dict[str, dict], w2g: Dict[str, dict], key_of: Dict[str, str],
                   scale: Dict[str, float], land: Optional[Dict[str, Image.Image]] = None, near: float = 30.0) -> Dict[str, list]:
    """{container check name: [(tab key, x, y)]}: each container's world position carried onto a map image.

    A game map can have several images (Aetia: the full map, its upper level, Elgares Depths; Pentelas: + Low Maktha; ...).  A container
    goes on the image whose Gamer Guides container marker lies within `near` native px of where the container lands; failing that on the
    game map's main image (the one with most markers), provided it lands on terrain there."""
    cands: Dict[str, list] = {}
    gcont: Dict[str, List[Tuple[float, float]]] = {}
    for key, w in w2g.items():
        r = regs.get(key)
        slug = key.split("#")[0]
        if not r or slug not in gg or r["fn"] not in key_of:
            continue
        box = r.get("box")
        gcont[key] = [(m["x"], m["y"]) for m in gg[slug]["markers"] if kind(m["icon"]) == "Container"
                      and (not box or (box[0] <= m["x"] < box[2] and box[1] <= m["y"] < box[3]))]
        cands.setdefault(w["map"], []).append((key, r, w))
    main = {area: max(c, key=lambda t: len(gcont[t[0]]))[0] for area, c in cands.items()}
    out: Dict[str, list] = {}
    for c in containers:
        best = None                                                  # (rank, distance, entry)
        for key, r, w in cands.get(c["map"], []):
            u = w["k"] * w["sx"] * c["x"] + w["tx"]
            v = w["k"] * w["sz"] * c["z"] + w["ty"]
            box = r.get("box")
            if box and not (box[0] <= u < box[2] and box[1] <= v < box[3]):
                continue
            tab, f = key_of[r["fn"]], scale[r["fn"]]
            x, y = round((r["s"] * u + r["tx"]) * f), round((r["s"] * v + r["ty"]) * f)
            if not on_land(land, tab, x, y):
                continue
            d = min((((u - gx) ** 2 + (v - gy) ** 2) ** 0.5 for gx, gy in gcont[key]), default=1e9)
            rank = 0 if d <= near else (1 if key == main[c["map"]] else 2)
            if rank < 2 and (best is None or (rank, d) < best[:2]):
                best = (rank, d, (tab, x, y))
        if best:
            out[c["name"]] = [best[2]]
    return out
