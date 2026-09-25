"""Map art + pin positions for the XC3 tracker, taken from the FrontierNav wiki (https://frontiernav.net, XC3 interactive maps).

`scripts/xc3_fn_download.py` fetches the wiki's map tile pyramids, stitches one PNG per map and exports every map feature's position
(in stitched-image pixels) to F:\\XCAP\\extracted\\xc3_maps\\xc3_maps_meta.json.  Here those images become the tracker's tabs and the
features become real map pins for the checks whose names match (unique monsters, shops + shop slots, landmarks, locations, rest spots).
Map data credit: FrontierNav contributors.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

DIR = Path(r"F:\XCAP\extracted\xc3_maps")
META = DIR / "xc3_maps_meta.json"
BG = (14, 20, 40)

# AP location category -> whether its name is a plain feature name or a shop check (shops share one pin per shop)
PIN_CATEGORIES = ("uniquemonsters", "landmarks", "locations", "restspots", "Shops", "Shop Slots")


def load_meta() -> dict:
    return json.load(open(META, encoding="utf-8"))


def norm(s: str) -> str:
    s = re.sub(r"\s*\(Lv\.?\s*\d+\)\s*$", "", s)         # unique monsters carry their level: "Petrivore Judomar (Lv. 31)"
    s = re.sub(r"^Shop\s+", "", s)                         # shop checks: "Shop Colony 9 Commissary #3"
    s = re.sub(r"\s*#\d+\s*$", "", s)
    s = re.sub(r"\s*\(\d+\)\s*$", "", s)                   # duplicate-name counter: "... Commissary (2)"
    return re.sub(r"[^a-z0-9]+", "", s.replace("\u2019", "'").lower())


def shop_label(name: str) -> str:
    s = re.sub(r"^Shop\s+", "", name)
    s = re.sub(r"\s*#\d+\s*$", "", s)
    s = re.sub(r"\s*\(\d+\)\s*$", "", s)
    return f"{s} (Shop)"


def feature_index(meta: dict) -> Dict[str, List[Tuple[str, dict]]]:
    idx: Dict[str, List[Tuple[str, dict]]] = {}
    for mid, m in meta.items():
        for f in m["features"]:
            for nm in {f["name"], f.get("tname") or ""}:
                if nm:
                    idx.setdefault(norm(nm), []).append((mid, f))
    return idx


def load_map(meta: dict, fn_id: str, max_w: int, max_h: int) -> Tuple[Image.Image, float]:
    """The stitched map on the tracker's own background colour, scaled to fit (max_w, max_h); returns (image, scale)."""
    im = Image.open(DIR / meta[fn_id]["file"]).convert("RGB")
    mask = im.convert("L").point(lambda v: 255 if v > 12 else 0)      # near-black world margin -> tracker background
    im = Image.composite(im, Image.new("RGB", im.size, BG), mask)
    f = min(1.0, max_w / im.width, max_h / im.height)
    if f < 1.0:
        im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
    return im, f


def pins_for(locations: List[dict], meta: dict, key_of: Dict[str, str], scale: Dict[str, float]) -> Dict[str, list]:
    """{AP location name: [(tab key, x, y[, label]), ...]} for every check whose name matches a wiki map feature.

    key_of: FrontierNav map id -> the tracker's tab key (maps that are not tabs are ignored); scale: FN map id -> resize factor."""
    idx = feature_index(meta)
    out: Dict[str, list] = {}
    for l in locations:
        cats = l.get("category") or []
        cat = next((c for c in PIN_CATEGORIES if c in cats), None)
        if not cat:
            continue
        hits = idx.get(norm(l["name"]), [])
        entries, seen = [], set()
        for mid, f in hits:
            if mid not in key_of or key_of[mid] in seen:
                continue
            seen.add(key_of[mid])
            e = [key_of[mid], round(f["x"] * scale[mid]), round(f["y"] * scale[mid])]
            if cat in ("Shops", "Shop Slots"):
                e.append(shop_label(l["name"]))
            entries.append(tuple(e))
        if entries:
            out[l["name"]] = entries
    return out
