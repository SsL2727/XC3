"""Download + stitch the FrontierNav XC3 map tiles and export pin positions (in stitched-image pixels).
usage: python xc3_fn_download.py [max zoom (4)] [extra map ids without pins ...]

Politeness: strictly sequential, ~0.15 s pause per request (fn_common.fetch), every tile cached on disk so re-runs
never re-request anything (404s are cached as zero-byte markers).  Only the tile range covering the map's terrain
(from the zoom-0 thumbnail) plus its features is fetched.
"""
import io
import json
import math
import os
import sys

from PIL import Image

import xc3_fn_common as F

OUT = r"F:\XCAP\extracted\xc3_maps"
CACHE = os.path.join(OUT, "_tiles")
MAX_ZOOM = int(sys.argv[1]) if len(sys.argv) > 1 else 4
os.makedirs(CACHE, exist_ok=True)
stats = {"requests": 0, "cached": 0, "bytes": 0}


def tile(path, ext, z, x, y):
    p = os.path.join(CACHE, path, str(z), f"tile_{x}_{y}.{ext}")
    if os.path.exists(p):
        stats["cached"] += 1
        return open(p, "rb").read() or None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    d = F.fetch(f"{F.TILE_ROOT}/{path}/{z}/tile_{x}_{y}.{ext}")
    stats["requests"] += 1
    stats["bytes"] += len(d or b"")
    open(p, "wb").write(d or b"")
    return d


def content_bbox(thumb):
    """Fractional bbox of non-black pixels in the zoom-0 tile (None if it is all black)."""
    im = Image.open(io.BytesIO(thumb)).convert("L")
    bb = im.point(lambda v: 255 if v > 24 else 0).getbbox()
    if not bb:
        return None
    w, h = im.size
    return bb[0] / w, bb[1] / h, bb[2] / w, bb[3] / h


def main():
    g = F.load_graph()
    M = F.maps(g)
    meta_path = os.path.join(OUT, "xc3_maps_meta.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    extra = set(sys.argv[2:])                      # map ids to fetch even though they carry no pins
    for mid, m in M.items():
        t = m.get("tile")
        if not t or not (m["features"] or mid in extra):
            continue
        ts = t["tile_size"]
        z = min(t["zoom"] if t["zoom"] is not None else 0, MAX_ZOOM)
        world = ts * (2 ** z)
        fr = [F.to_frac(f["lng"], f["lat"]) for f in m["features"]]
        u0, v0 = (min(u for u, v in fr), min(v for u, v in fr)) if fr else (1.0, 1.0)
        u1, v1 = (max(u for u, v in fr), max(v for u, v in fr)) if fr else (0.0, 0.0)
        thumb = tile(t["path"], t["ext"], 0, 0, 0)
        if thumb:
            bb = content_bbox(thumb)
            if bb:
                u0, v0, u1, v1 = min(u0, bb[0]), min(v0, bb[1]), max(u1, bb[2]), max(v1, bb[3])
        if u1 <= u0 or v1 <= v0:
            u0, v0, u1, v1 = 0.0, 0.0, 1.0, 1.0
        pad = 0.015
        u0, v0, u1, v1 = max(0, u0 - pad), max(0, v0 - pad), min(1, u1 + pad), min(1, v1 + pad)
        X0, Y0, X1, Y1 = math.floor(u0 * world), math.floor(v0 * world), math.ceil(u1 * world), math.ceil(v1 * world)
        tx0, ty0, tx1, ty1 = X0 // ts, Y0 // ts, (X1 - 1) // ts, (Y1 - 1) // ts
        print(f"{mid}: zoom {z}, tiles {(tx1 - tx0 + 1)}x{(ty1 - ty0 + 1)}, out {X1 - X0}x{Y1 - Y0}", flush=True)
        canvas = Image.new("RGB", ((tx1 - tx0 + 1) * ts, (ty1 - ty0 + 1) * ts))
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                d = tile(t["path"], t["ext"], z, tx, ty)
                if d:
                    canvas.paste(Image.open(io.BytesIO(d)).convert("RGB"), ((tx - tx0) * ts, (ty - ty0) * ts))
        img = canvas.crop((X0 - tx0 * ts, Y0 - ty0 * ts, X1 - tx0 * ts, Y1 - ty0 * ts))
        fname = f"{mid}.png"
        img.save(os.path.join(OUT, fname), optimize=True)
        feats = []
        for f, (u, v) in zip(m["features"], fr):
            feats.append({"id": f["id"], "name": f["name"], "target": f["target"], "ttype": f["ttype"], "tname": f["tname"],
                          "x": round(u * world - X0), "y": round(v * world - Y0)})
        meta[mid] = {"name": m["name"], "file": fname, "size": [X1 - X0, Y1 - Y0], "zoom": z, "features": feats}
        json.dump(meta, open(os.path.join(OUT, "xc3_maps_meta.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"  saved {fname} {img.size}; totals: {stats}", flush=True)
    print("DONE", stats, flush=True)


main()
