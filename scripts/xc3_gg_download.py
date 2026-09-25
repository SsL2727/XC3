"""Fetch the GamerGuides XC3 interactive-map marker data (https://www.gamerguides.com/xenoblade-chronicles-3/maps).

Each map page carries `GG.mapData` (map id, native image size, source image name); the markers come from /map/<id>/geojson.  Saves one
compact JSON per map to F:\\XCAP\\extracted\\xc3_maps\\gg\\<slug>.json:
  {"slug", "title", "map_id", "width", "height", "filename", "markers": [{"title", "icon", "x", "y"}], plus layer_id / zoom_levels / max_zoom / tile_size / fn_pattern (tile URL: /assets/maps/<map_id>/<layer_id>/<z>/<x>-<y>.png with
z in [max_zoom - zoom_levels + 1, max_zoom], native resolution at max_zoom, x / y counted from the image's top-left tile)}
x / y are pixels of the map's native image (top-left origin).  Sequential, ~1 s between requests; already saved maps are skipped.
usage: python xc3_gg_download.py [--force]
"""
import json
import os
import re
import sys
import time
import urllib.request

OUT = r"F:\XCAP\extracted\xc3_maps\gg"
BASE = "https://www.gamerguides.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
SKIP = {"future-redeemed-dlc-map"}          # DLC map, not part of the tracker


def get(url):
    time.sleep(1.0)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def main():
    os.makedirs(OUT, exist_ok=True)
    force = "--force" in sys.argv
    index = get(f"{BASE}/xenoblade-chronicles-3/maps")
    slugs = sorted(set(re.findall(r'href="/xenoblade-chronicles-3/maps/([^"#?/]+)"', index)) - SKIP)
    for slug in slugs:
        path = os.path.join(OUT, f"{slug}.json")
        if os.path.exists(path) and not force:
            print("have", slug)
            continue
        page = get(f"{BASE}/xenoblade-chronicles-3/maps/{slug}")
        m = re.search(r"GG\.mapData\s*=\s*(\{.*?\});\s*\n", page, re.S)
        if not m:
            print("NO mapData for", slug)
            continue
        md = json.JSONDecoder().raw_decode(m.group(1))[0]
        gj = json.loads(get(f"{BASE}/map/{md['map_id']}/geojson"))
        markers = []
        for f in gj["markers"]["features"]:
            p = f["properties"]
            pts = p.get("origPoints") or []
            if not pts:
                continue
            icon = re.sub(r".*/([^/:]+?)\.png.*", r"\1", p.get("iconImage") or "")
            markers.append({"title": (p.get("title") or "").strip(), "icon": icon, "x": pts[0][0], "y": pts[0][1]})
        json.dump({"slug": slug, "title": md["title"], "map_id": md["map_id"], "width": md["width"], "height": md["height"],
                   "filename": md.get("filename"), "layer_id": md["layers"][0]["layer_id"], "zoom_levels": md["zoom_levels"], "max_zoom": md.get("max_zoom", 18),
                   "tile_size": md.get("tile_size", 256), "fn_pattern": md.get("fn_pattern"), "markers": markers}, open(path, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
        print(f"{slug}: id {md['map_id']} {md['width']}x{md['height']} {md.get('filename')} -> {len(markers)} markers", flush=True)


main()
