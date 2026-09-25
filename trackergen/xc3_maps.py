"""Stitch XC3's tiled map pyramids (menu wilay tiles) into one PNG per area.

Tiles are named <area>_<floor>[_s2|_s3]_map_<RR><CC>.wilay: RR = tile row, CC = tile column; the _s2/_s3 suffix is a coarser
level (half / quarter resolution). We pick the finest level whose stitched size stays below MAX_PIXELS.
usage: python xc3_maps.py <area> [floor]
"""
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

UI = Path(r"F:\XCAP\extracted\xc3_ui")
CACHE = Path(r"F:\XCAP\work\xc3_maps_cache")
TEX = r"G:\Archipelago\xc-tools\xc3_lib\xc3_tex.exe"
MAX_PIXELS = 4200


def decode_tile(name: str) -> Image.Image:
    CACHE.mkdir(parents=True, exist_ok=True)
    png = CACHE / f"{name}.png"
    if not png.exists():
        tmp = CACHE / f"_{name}"
        tmp.mkdir(exist_ok=True)
        subprocess.run([TEX, str(UI / f"{name}.wilay"), str(tmp)], check=True, capture_output=True)
        dds = sorted(tmp.glob("*.dds"))[0]
        subprocess.run([TEX, str(dds), str(png)], check=True, capture_output=True)
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()
    return Image.open(png)


def tiles_of(area: str, floor: str, level: str):
    pat = re.compile(rf"^{area}_{floor}{level}_map_(\d\d)(\d\d)\.wilay$")
    out = {}
    for p in UI.iterdir():
        m = pat.match(p.name)
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = p.stem
    return out


def stitch(area: str, floor: str = "01", max_pixels: int = MAX_PIXELS) -> Image.Image:
    for level in ("", "_s2", "_s3"):
        t = tiles_of(area, floor, level)
        if not t:
            continue
        sample = decode_tile(next(iter(t.values())))
        tw, th = sample.size
        rows = max(r for r, _ in t) + 1
        cols = max(c for _, c in t) + 1
        if max(rows * th, cols * tw) <= max_pixels or level == "_s3":
            break
    canvas = Image.new("RGBA", (cols * tw, rows * th), (0, 0, 0, 0))
    for (r, c), name in t.items():
        canvas.paste(decode_tile(name), (c * tw, r * th))
    return canvas


if __name__ == "__main__":
    area = sys.argv[1]
    floor = sys.argv[2] if len(sys.argv) > 2 else "01"
    im = stitch(area, floor)
    out = Path(rf"F:\XCAP\work\xc3_maps_cache\_stitched_{area}_{floor}.png")
    im.save(out)
    print(area, floor, im.size, out)
