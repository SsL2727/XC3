"""Register the game's own world coordinates onto the Gamer Guides map images (and so onto the tracker's FrontierNav tabs).

prg/SYS_GimmickLocation gives every container (and every named place) an exact world position (X, Z) on its map; the Gamer Guides maps
draw the same containers / landmarks in native image pixels.  Per registered Gamer Guides map (or Swordmarch piece) this finds
    u = k * sx * X + tx        v = k * sz * Z + ty         (sx, sz = +-1 axis flips; k px per world unit)
in two steps: a coarse fit from same-named landmarks (trimmed least squares), then a refinement against the containers themselves
(mutual nearest neighbours between the BDAT containers of that game map and the Gamer Guides container markers).  The game map and
flip that leave the most containers within a few pixels win.  Output: F:\\XCAP\\extracted\\xc3_maps\\world_to_gg.json
  {reg key: {"map": "ma04a", "k", "sx", "sz", "tx", "ty", "pairs": mutual container pairs, "tight": pairs within 12 px, "rms": px}}
usage: python xc3_world_register.py [reg key ...]
"""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, r"G:\Archipelago\xc-tools\trackergen")
import xc3_gg_maps as G  # noqa: E402

J = r"F:\XCAP\work\rb\work_xc3\rando\XC3\JsonOutputs"
CONT = r"G:\Archipelago\xc-tools\worldgen\detect\xc3_container_locations.json"
OUT = G.DIR / "world_to_gg.json"
FLIPS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
K = 2.0


def rows(p):
    return json.load(open(os.path.join(J, p), encoding="utf-8"))["rows"]


def fit(P, sx, sz):
    """Least squares (k, tx, ty) for u = k*sx*X + tx, v = k*sz*Z + ty over rows (X, Z, u, v)."""
    a, b = sx * P[:, 0], sz * P[:, 1]
    n = len(P)
    A = np.zeros((2 * n, 3))
    A[:n, 0], A[:n, 1] = a, 1
    A[n:, 0], A[n:, 2] = b, 1
    y = np.r_[P[:, 2], P[:, 3]]
    (k, tx, ty), *_ = np.linalg.lstsq(A, y, rcond=None)
    return float(k), float(tx), float(ty)


def apply(t, XZ):
    k, sx, sz, tx, ty = t
    return np.c_[k * sx * XZ[:, 0] + tx, k * sz * XZ[:, 1] + ty]


def trimmed(P, sx, sz, cut0=250.0):
    idx = np.arange(len(P))
    t = None
    for _ in range(8):
        if len(idx) < 3:
            return None
        k, tx, ty = fit(P[idx], sx, sz)
        t = (k, sx, sz, tx, ty)
        res = np.hypot(*(apply(t, P[:, :2]) - P[:, 2:]).T)
        cut = max(cut0 * 0.2, 2.5 * np.median(res[idx]))
        new = np.nonzero(res <= cut)[0]
        if len(new) == len(idx) and np.all(new == idx):
            break
        idx = new
    return t, len(idx)


def mutual_pairs(XZ, uv, maxd):
    """Mutual nearest neighbours between transformed BDAT points XZ (n, 2) and Gamer Guides points uv (m, 2) closer than maxd."""
    d = np.hypot(XZ[:, None, 0] - uv[None, :, 0], XZ[:, None, 1] - uv[None, :, 1])
    a = d.argmin(axis=1)
    b = d.argmin(axis=0)
    out = [(i, int(a[i])) for i in range(len(XZ)) if b[a[i]] == i and d[i, a[i]] <= maxd]
    return out


def main():
    gg = G.load_gg()
    regs = json.load(open(G.DIR / "gg_registration.json", encoding="utf-8"))
    cont = json.load(open(CONT, encoding="utf-8"))["locations"]
    boxes = {}
    for c in cont:
        boxes.setdefault(c["map"], []).append(c)
    map_area = {r["$id"]: r["ID"][4:].lower() for r in rows(r"sys\SYS_MapList.json") if r["ID"].startswith("FLD_MA")}
    names = {r["$id"]: r["name"] for r in rows(r"system\msg_location_name.json")}
    gmk = {}
    for f in glob.glob(os.path.join(J, "map", "*_GMK_Location.json")):
        for r in json.load(open(f, encoding="utf-8"))["rows"]:
            gmk[r["ID"]] = names.get(r["LocationName"], "")
    places = {}                                                       # area -> norm name -> [(X, Z)]
    for r in rows(r"prg\SYS_GimmickLocation.json"):
        n = gmk.get(r["GimmickID"]) if r["GimmickType"] == "Location" else None
        if n and r["MapID"] in map_area:
            places.setdefault(map_area[r["MapID"]], {}).setdefault(G.norm(n), []).append((r["X"], r["Z"]))

    only = set(sys.argv[1:])
    out = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {}
    for key, reg in regs.items():
        slug = key.split("#")[0]
        if slug not in gg or (only and key not in only):
            continue
        box = reg.get("box")
        marks = [m for m in gg[slug]["markers"] if not box or (box[0] <= m["x"] < box[2] and box[1] <= m["y"] < box[3])]
        gc = np.array([(m["x"], m["y"]) for m in marks if G.kind(m["icon"]) == "Container"], dtype=float)
        best = None
        for area, bx in boxes.items():
            XZ = np.array([(c["x"], c["z"]) for c in bx])
            pl = places.get(area, {})
            pairs = []
            for m in marks:
                if G.kind(m["icon"]) in ("Landmark", "Location", "Rest Spot", "Secret Area") and m["title"]:
                    c = pl.get(G.norm(m["title"]))
                    if c and len(c) == 1:
                        pairs.append((c[0][0], c[0][1], m["x"], m["y"]))
            cands = []
            if len(pairs) >= 3:                                        # coarse fit from same-named landmarks
                P = np.array(pairs, dtype=float)
                for sx, sz in FLIPS:
                    r = trimmed(P, sx, sz)
                    if r and r[0][0] > 0:
                        cands.append((r[1], r[0]))
            if not cands and len(gc) >= 2:                                 # translation-only search with k = K: hypothesise every (GG marker, BDAT box) pairing
                best_t = None
                for i in range(len(XZ)):
                    for j in range(len(gc)):
                        t = (K, 1, 1, gc[j, 0] - K * XZ[i, 0], gc[j, 1] - K * XZ[i, 1])
                        mp = mutual_pairs(apply(t, XZ), gc, 25.0)
                        if best_t is None or len(mp) > best_t[0]:
                            best_t = (len(mp), t)
                if best_t and best_t[0] >= len(gc):                        # every GG container of this small map must find its box
                    cands = [(best_t[0], best_t[1])]
            if not cands or len(gc) < 2:
                continue
            for _, t in sorted(cands, key=lambda c: -c[0])[:2]:
                for step in range(6):                                  # refine on the containers themselves
                    uv = apply(t, XZ)
                    maxd = max(12.0, 60.0 - 10 * step)
                    mp = mutual_pairs(uv, gc, maxd)
                    if len(mp) < 3:
                        break
                    P = np.array([(XZ[i, 0], XZ[i, 1], gc[j, 0], gc[j, 1]) for i, j in mp])
                    k, tx, ty = fit(P, t[1], t[2])
                    t = (k, t[1], t[2], tx, ty)
                uv = apply(t, XZ)
                mp = mutual_pairs(uv, gc, 40.0)
                if len(mp) < min(3, len(gc)):
                    continue
                P = np.array([(XZ[i, 0], XZ[i, 1], gc[j, 0], gc[j, 1]) for i, j in mp])          # final fit: k fixed, offsets = median
                t = (K, t[1], t[2], float(np.median(P[:, 2] - K * t[1] * P[:, 0])), float(np.median(P[:, 3] - K * t[2] * P[:, 1])))
                uv = apply(t, XZ)
                mp = mutual_pairs(uv, gc, 40.0)
                res = np.array([np.hypot(*(uv[i] - gc[j])) for i, j in mp])
                tight = int((res <= 12).sum())
                cand = {"map": area, "k": t[0], "sx": t[1], "sz": t[2], "tx": t[3], "ty": t[4], "pairs": len(mp), "tight": tight,
                        "rms": float(np.sqrt((res ** 2).mean())), "gg_containers": len(gc), "bdat_containers": len(bx)}
                if best is None or (cand["tight"], -cand["rms"]) > (best["tight"], -best["rms"]):
                    best = cand
        if best is None:
            print(f"{key:36s} no registration ({len(gc)} GG containers)")
            continue
        out[key] = best
        print(f"{key:36s} -> {best['map']}  k={best['k']:.4f} flip=({best['sx']:+d},{best['sz']:+d})  tight {best['tight']}/{best['gg_containers']} GG"
              f" ({best['bdat_containers']} BDAT)  rms {best['rms']:.1f}px", flush=True)
        json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)


main()
