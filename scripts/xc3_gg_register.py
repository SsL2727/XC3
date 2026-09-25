"""Register every GamerGuides XC3 map onto its FrontierNav image by terrain silhouette.

Both sites draw the same game map textures, so GamerGuides native pixels map onto the FrontierNav stitched image by a uniform scale
and an offset: fn_px = s * gg_px + (tx, ty).  Per map this fetches a low-zoom GamerGuides mosaic (a few dozen tiles, cached under
gg/_tiles, ~0.3 s apart), then searches scale / offset by FFT cross-correlation of the two terrain masks (IoU) and scores the result
against markers that carry the same name in both sources.  Output: F:\\XCAP\\extracted\\xc3_maps\\gg_registration.json
  {gg slug: {"fn": FrontierNav map id, "s", "tx", "ty", "iou", "pairs", "rms"}}
Maps that GamerGuides lays out as a collage of separate FrontierNav maps (PIECES) are registered piece by piece, saved as "<slug>#<piece>"
with the piece's box in GG native px.
usage: python xc3_gg_register.py [slug ...]
"""
import io
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

sys.path.insert(0, r"G:\Archipelago\xc-tools\trackergen")
import xc3_gg_maps as G  # noqa: E402

BASE = "https://www.gamerguides.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
TILES = G.GG_DIR / "_tiles"
THRESH = 14
# GG maps that are collages: slug -> [(piece, box in GG native px (x0, y0, x1, y1), FrontierNav map id)]
PIECES = {"swordmarch-the-city": [("city", (344, 8, 1392, 1264), "great-sword-upper-chapter-5"),
                                  ("upper", (1792, 672, 2512, 1160), "great-sword-upper-chapter-5"),
                                  ("great-sword", (288, 1360, 1384, 2536), "great-sword-upper")]}


def tile_bytes(gm, z, x, y):
    p = TILES / str(gm["map_id"]) / str(z) / f"{x}-{y}.png"
    if p.exists():
        return p.read_bytes() or None
    p.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/assets/maps/{gm['map_id']}/{gm['layer_id']}/{z}/{x}-{y}.png"      # z in max_zoom - zoom_levels + 1 .. max_zoom
    time.sleep(0.3)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            d = r.read()
    except Exception as ex:
        if getattr(ex, "code", None) != 404:
            raise
        d = b""
    p.write_bytes(d)
    return d or None


def mosaic(gm, target=1200):
    """(RGB mosaic, q) with q = mosaic px per native px.  File zoom z runs max_zoom - zoom_levels + 1 .. max_zoom, native at max_zoom."""
    Z, ts, w, h = gm["zoom_levels"], gm["tile_size"], gm["width"], gm["height"]
    zmax = gm.get("max_zoom", 18)
    z = max(zmax - Z + 1, min(zmax, zmax + math.ceil(math.log2(target / max(w, h)))))
    q = 2.0 ** (z - zmax)
    mw, mh = math.ceil(w * q), math.ceil(h * q)
    cols, rows = math.ceil(mw / ts), math.ceil(mh / ts)
    canvas = Image.new("RGB", (cols * ts, rows * ts))
    for x in range(cols):
        for y in range(rows):
            d = tile_bytes(gm, z, x, y)
            if d:
                t = Image.open(io.BytesIO(d)).convert("RGBA")
                bg = Image.new("RGBA", t.size, (0, 0, 0, 255))
                canvas.paste(Image.alpha_composite(bg, t).convert("RGB"), (x * ts, y * ts))
    return canvas.crop((0, 0, mw, mh)), q


def mask_of(im):
    return (np.asarray(im.convert("L")) > THRESH).astype(np.float32)


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def best_shift(A, B):
    """Max-IoU placement of mask B on mask A (B may hang over the edges): returns (iou, dx, dy) with B's top-left at (dx, dy) in A."""
    H, W = A.shape
    h, w = B.shape
    n0, n1 = H + h, W + w
    fa = np.fft.rfft2(A, (n0, n1))
    fb = np.fft.rfft2(B, (n0, n1))
    corr = np.fft.irfft2(fa * np.conj(fb), (n0, n1))            # corr[dy, dx] = sum A(y+dy, x+dx) * B(y, x), wraps for negative shifts
    inter = np.rint(corr)
    union = A.sum() + B.sum() - inter
    iou = np.where(union > 0, inter / np.maximum(union, 1), 0)
    iy, ix = np.unravel_index(np.argmax(iou), iou.shape)
    dy = iy if iy < n0 // 2 else iy - n0
    dx = ix if ix < n1 // 2 else ix - n1
    return float(iou[iy, ix]), int(dx), int(dy)


def resized(mask, sx, sy):
    h, w = mask.shape
    im = Image.fromarray((mask * 255).astype(np.uint8)).resize((max(1, round(w * sx)), max(1, round(h * sy))), Image.BILINEAR)
    return np.asarray(im).astype(np.float32) / 255.0


def best_shift_window(A, B):
    """Like best_shift, but the union only counts A inside B's window: B may be one piece of a larger map A."""
    H, W = A.shape
    h, w = B.shape
    n0, n1 = H + h, W + w
    fa = np.fft.rfft2(A, (n0, n1))
    inter = np.rint(np.fft.irfft2(fa * np.conj(np.fft.rfft2(B, (n0, n1))), (n0, n1)))
    win = np.rint(np.fft.irfft2(fa * np.conj(np.fft.rfft2(np.ones_like(B), (n0, n1))), (n0, n1)))       # A's terrain under B's box
    union = win + B.sum() - inter
    iou = np.where(union > 0, inter / np.maximum(union, 1), 0)
    iy, ix = np.unravel_index(np.argmax(iou), iou.shape)
    return float(iou[iy, ix]), int(ix if ix < n1 // 2 else ix - n1), int(iy if iy < n0 // 2 else iy - n0)


def scan(fn_mask, gmask, q, s_center, d, half_steps, step, shift=best_shift):
    """Best (iou, s, tx, ty) over scales s_center * (1 + step*i), i in [-half_steps, half_steps], at 1/d working resolution."""
    A = resized(fn_mask, 1 / d, 1 / d)
    best = None
    for i in range(-half_steps, half_steps + 1):
        s = s_center * (1 + step * i)
        k = (s / d) / q
        iou, dx, dy = shift(A, resized(gmask, k, k))
        if best is None or iou > best[0]:
            best = (iou, s, dx * d, dy * d)
    return best


def prepare(gm):
    """(terrain mask of the GG mosaic, q) - built once per GG map."""
    gimg, q = mosaic(gm)
    return mask_of(gimg), q


def coarse(gmask, q, fn_mask_full, fid):
    """First-pass fit of one FrontierNav map (None if its aspect ratio cannot match): {"fn", "s", "tx", "ty", "iou"}."""
    gx0, gy0, gx1, gy1 = bbox(gmask)
    fx0, fy0, fx1, fy1 = bbox(fn_mask_full)
    # native-px scale guess from the terrain extents (fn px per gg native px); reject maps whose aspect differs
    sw = (fx1 - fx0) / ((gx1 - gx0) / q)
    sh = (fy1 - fy0) / ((gy1 - gy0) / q)
    if not (0.85 < sw / sh < 1.18):
        return None
    iou, s, tx, ty = scan(fn_mask_full, gmask, q, (sw + sh) / 2, 8, 8, 0.01)              # +-8 %
    return {"fn": fid, "s": s, "tx": tx, "ty": ty, "iou": round(iou, 3)}


def refine(gmask, q, fn_mask_full, r):
    iou, s, tx, ty = scan(fn_mask_full, gmask, q, r["s"], 3, 8, 0.002)              # +-1.6 %
    iou, s, tx, ty = scan(fn_mask_full, gmask, q, s, 1, 2, 0.002)                    # full resolution
    return {**r, "s": s, "tx": tx, "ty": ty, "iou": round(iou, 3)}


def register_piece(gmask, q, box, fn_mask, fid):
    """Fit one piece of a collage GG map (mosaic mask + q, box in native px) onto a whole FrontierNav map; no scale guess is available
    from the extents, so the scale is searched over the whole range seen so far (0.19 - 1.8)."""
    cx0, cy0 = int(box[0] * q), int(box[1] * q)
    crop = gmask[cy0:int(box[3] * q), cx0:int(box[2] * q)]
    best = max((scan(fn_mask, crop, q, c, 8, 8, 0.04, best_shift_window) for c in (0.3, 0.42, 0.55, 0.7, 0.9, 1.15, 1.45, 1.85)),
               key=lambda r: r[0])
    for d, half, step in ((4, 6, 0.01), (2, 4, 0.004), (1, 2, 0.002)):
        best = scan(fn_mask, crop, q, best[1], d, half, step, best_shift_window)
    iou, sc, tx, ty = best
    # crop origin -> GG native origin: fn = sc * (native - cx0 / q) + t
    return {"fn": fid, "s": sc, "tx": tx - sc * cx0 / q, "ty": ty - sc * cy0 / q, "iou": round(iou, 3), "box": list(box)}


def main():
    meta = json.load(open(G.DIR / "xc3_maps_meta.json", encoding="utf-8"))
    gg = G.load_gg()
    only = set(sys.argv[1:])
    out_path = G.DIR / "gg_registration.json"
    out = json.load(open(out_path, encoding="utf-8")) if out_path.exists() else {}
    fn_masks = {fid: mask_of(Image.open(G.DIR / m["file"])) for fid, m in meta.items()}
    for slug, gm in gg.items():
        if only and slug not in only:
            continue
        gmask, q = prepare(gm)
        if slug in PIECES:
            for name, box, fid in PIECES[slug]:
                r = register_piece(gmask, q, box, fn_masks[fid], fid)
                out[f"{slug}#{name}"] = r
                print(f"{slug}#{name:11s} -> {fid:28s} iou={r['iou']} s={r['s']:.4f} t=({r['tx']:.0f},{r['ty']:.0f})", flush=True)
                json.dump(out, open(out_path, "w", encoding="utf-8"), indent=1)
            continue
        # maps sharing same-named markers first (their coarse fit decides), then every other map
        ranked = sorted(meta, key=lambda fid: -len(G.name_pairs(gm, meta[fid])))
        results = [r for r in (coarse(gmask, q, fn_masks[fid], fid) for fid in ranked) if r]
        if not results:
            print(f"{slug}: no compatible FrontierNav map")
            continue
        results.sort(key=lambda r: -r["iou"])
        refined = sorted((refine(gmask, q, fn_masks[r["fn"]], r) for r in results[:2]), key=lambda r: -r["iou"])
        best = refined[0]
        pairs = G.name_pairs(gm, meta[best["fn"]])
        if pairs:
            errs = [math.hypot(best["s"] * a + best["tx"] - c, best["s"] * b + best["ty"] - d) for a, b, c, d in pairs]
            best["pairs"], best["rms"] = len(pairs), round(math.sqrt(sum(e * e for e in errs) / len(errs)), 1)
        best["runner_up"] = [(r["fn"], r["iou"]) for r in refined[1:] + results[2:3]]
        out[slug] = best
        print(f"{slug:26s} -> {best['fn']:28s} iou={best['iou']} s={best['s']:.4f} t=({best['tx']},{best['ty']}) "
              f"pairs={best.get('pairs', 0)} rms={best.get('rms')}px  runner-up {best['runner_up']}", flush=True)
        json.dump(out, open(out_path, "w", encoding="utf-8"), indent=1)


main()
