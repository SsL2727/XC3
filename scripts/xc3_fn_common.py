"""Shared helpers for reading the FrontierNav XC3 wiki graph (xc3_graph.json) and fetching map tiles (used by xc3_fn_download.py)."""
import json
import math
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GRAPH = r"F:\XCAP\extracted\xc3_maps\xc3_graph.json"   # the wiki graph: https://frontiernav.net/files/user-content/xenoblade-chronicles-3/<hash>.json (see /api/namespaces/xenoblade-chronicles-3/index.json)
TILE_ROOT = "https://frontiernav.net/files/games/xenoblade-chronicles-3/maps/tiles"
UA = {"User-Agent": "Mozilla/5.0 (personal PopTracker pack build)"}


def load_graph():
    return json.load(open(GRAPH, encoding="utf-8"))


def rel_ends(data, key):
    """Ids at the far end of a relationship dict like {'a__Type-KEY__b': True}."""
    return [k.split("__")[-1] for k in data.get(key, {})]


def maps(graph):
    """{map id: {name, tile:{path,ext,zoom,tile_size}, features:[{id,name,target,ttype,tname,lng,lat}]}}"""
    ents = graph["entities"]
    out = {}
    for mid, m in ents.items():
        if m["type"] != "Map":
            continue
        tiles = rel_ends(m["data"], "MapTile-MAP-Map")
        tile = None
        if tiles:
            td = ents[tiles[0].split("__")[0]]["data"] if tiles[0] not in ents else ents[tiles[0]]["data"]
        feats = []
        for fk in m["data"].get("MapFeature-MAP-Map", {}):
            fid = fk.split("__")[0]
            f = ents.get(fid)
            if not f or "geometry" not in f["data"]:
                continue
            tg = rel_ends(f["data"], "MapFeature-MAP_TARGET")
            te = ents.get(tg[0]) if tg else None
            lng, lat = f["data"]["geometry"]["coordinates"][:2]
            feats.append({"id": fid, "name": f["data"].get("name", fid).replace(" (Map Feature)", ""),
                          "target": tg[0] if tg else None, "ttype": te["type"] if te else None,
                          "tname": te["data"].get("name") if te else None, "lng": lng, "lat": lat})
        out[mid] = {"name": m["data"]["name"], "features": feats}
    # tiles hang off MapTile entities pointing back at their map
    for e in ents.values():
        if e["type"] != "MapTile":
            continue
        for k in e["data"].get("MapTile-MAP", {}):
            mid = k.split("__")[-1]
            if mid in out:
                out[mid]["tile"] = {"path": e["data"]["path"], "ext": e["data"].get("extension", "jpg"),
                                    "zoom": e["data"].get("max_native_zoom"), "tile_size": e["data"].get("tile_size", 256)}
    return out


def to_frac(lng, lat):
    """Web-Mercator (Leaflet default CRS) -> fraction (u, v) of the whole tile square, origin top-left."""
    u = (lng + 180.0) / 360.0
    v = 0.5 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi)
    return u, v


def fetch(url, retries=3, pause=0.15):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                d = r.read()
            time.sleep(pause)
            return d
        except Exception as ex:
            code = getattr(ex, "code", None)
            if code == 404:
                return None
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    return None
