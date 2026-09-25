"""Shared PopTracker pack builder for the Xenoblade AP worlds.

A game adapter (build_xc1.py, ...) supplies maps + pin positions; everything else (items, icons, locations,
logic data, autotracking mapping, layout, manifest, zip) is generated here from the apworld's data files.
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
FONT_REG = "C:/Windows/Fonts/arial.ttf"


def font(size: int, bold: bool = True):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")


def clean(text: str) -> str:
    """PopTracker uses '/' as a path separator and '@' as a path prefix; keep display names free of both."""
    return text.replace("/", " - ").replace("@", "at ").strip()


def lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def lua_val(v, indent=0) -> str:
    pad = "  " * indent
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return lua_str(v)
    if v is None:
        return "nil"
    if isinstance(v, (list, tuple)):
        if not v:
            return "{}"
        inner = ",\n".join(pad + "  " + lua_val(x, indent + 1) for x in v)
        return "{\n" + inner + "\n" + pad + "}"
    if isinstance(v, dict):
        if not v:
            return "{}"
        parts = []
        for k, x in v.items():
            key = f"[{lua_str(k)}]" if isinstance(k, str) else f"[{k}]"
            parts.append(pad + "  " + key + " = " + lua_val(x, indent + 1))
        return "{\n" + ",\n".join(parts) + "\n" + pad + "}"
    raise TypeError(type(v))


# ---------------------------------------------------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------------------------------------------------

CATEGORY_HUES = {}


def category_color(cat: str) -> Tuple[int, int, int]:
    h = int(hashlib.md5(cat.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.55)
    return int(r * 255), int(g * 255), int(b * 255)


def wrap_label(name: str, width: int = 8, max_lines: int = 3) -> List[str]:
    words = re.sub(r"[()]", "", name).replace("-", " ").split()
    lines: List[str] = []
    cur = ""
    for w in words:
        if len(w) > width:
            w = w[: width - 1] + "."
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1:])[:width]]
    return lines


def fit_text(d: "ImageDraw.ImageDraw", text: str, f, max_w: int) -> str:
    """text, or the longest prefix (+ ellipsis) that fits max_w pixels in font f - unlike a fixed character
    cutoff, this never chops a short label short and never overflows a long one."""
    if d.textlength(text, font=f) <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if d.textlength(text[:mid] + "…", font=f) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + "…") if lo > 0 else "…"


def make_icon(name: str, cat: str, size: int = 48) -> Image.Image:
    im = Image.new("RGB", (size, size), (16, 16, 24))
    d = ImageDraw.Draw(im, "RGBA")
    base = category_color(cat)
    d.rounded_rectangle([1, 1, size - 2, size - 2], radius=8, fill=base + (255,), outline=(240, 240, 250, 255), width=2)
    d.rectangle([3, 3, size - 4, 9], fill=(255, 255, 255, 40))
    lines = wrap_label(name)
    fs = 12 if max(len(l) for l in lines) <= 6 else 10
    f = font(fs)
    lh = fs + 1
    y = (size - lh * len(lines)) // 2
    for line in lines:
        w = d.textlength(line, font=f)
        d.text(((size - w) / 2 + 1, y + 1), line, font=f, fill=(0, 0, 0, 200))
        d.text(((size - w) / 2, y), line, font=f, fill=(255, 255, 255, 255))
        y += lh
    return im


# ---------------------------------------------------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------------------------------------------------

SHOP_CATEGORIES = {"Shops", "Shop Slots", "shops"}    # detected by watching the shop placeholder appear/disappear (xc_deliver._watch_shops) or the
                                                       # base randomizer's own native check flow (lowercase "shops", shop_checks="Off") - not in detect.json


def automatic_location_names(world: Path) -> Optional[set]:
    """Names of every location this world's client can actually send by itself: present in detect.json's memory-flag
    detectors, or a shop check (its own, separate detection path - see SHOP_CATEGORIES), or a goal (kept regardless,
    same as drop_location_regex - /goal is how it is reported either way, that is not what 'manual' means here).
    None if the world has no detect.json (nothing to filter against)."""
    detect_path = world / "detect.json"
    if not detect_path.exists():
        return None
    detect = json.loads(detect_path.read_text(encoding="utf-8"))
    detected = set(detect.get("locations", {})) | set(detect.get("goals", {}))
    locs = json.loads((world / "locations.json").read_text(encoding="utf-8"))
    out = set()
    for l in locs:
        if l["name"] in detected or l.get("victory") or SHOP_CATEGORIES.intersection(l.get("category", [])):
            out.add(l["name"])
    return out


class Pack:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.world = Path(cfg["world_dir"])
        self.items: List[dict] = json.loads((self.world / "items.json").read_text(encoding="utf-8"))
        skip = set(cfg.get("skip_categories", []))                      # location groups that are off in the default YAML (e.g. per-slot shop checks)
        self.locations: List[dict] = [l for l in json.loads((self.world / "locations.json").read_text(encoding="utf-8"))
                                      if not skip.intersection(l.get("category", []))]
        if cfg.get("automatic_only"):
            auto = automatic_location_names(self.world)
            if auto is not None:
                self.locations = [l for l in self.locations if l["name"] in auto]
        self.regions: Dict[str, dict] = json.loads((self.world / "regions.json").read_text(encoding="utf-8"))
        self.events: List[dict] = json.loads((self.world / "events.json").read_text(encoding="utf-8"))
        self.gcfg: dict = json.loads((self.world / "game.json").read_text(encoding="utf-8"))
        self.out_dir = Path(cfg["work_dir"])
        self.item_by_name = {i["name"]: i for i in self.items}
        self.report: List[str] = []

    # -- defaults ----------------------------------------------------------------------------------------------------
    def default_options(self) -> Dict[str, int]:
        opts: Dict[str, int] = {}
        for name, spec in self.gcfg.get("options", {}).items():
            opts[name] = int(spec.get("default", 0)) if not isinstance(spec.get("default"), bool) else int(spec["default"])
        for cat, cdata in self.gcfg.get("categories", {}).items():
            for raw in cdata.get("yaml_option", []):
                name = raw[1:] if raw.startswith("!") else raw
                opts.setdefault(name, 1)
        return opts

    def category_default_enabled(self, cat: str, opts: Dict[str, int]) -> bool:
        ov = self.cfg.get("category_default_override", {})
        if cat in ov:
            return ov[cat]
        data = self.gcfg.get("categories", {}).get(cat)
        if not data:
            return True
        for raw in data.get("yaml_option", []):
            want = True
            name = raw
            if raw.startswith("!"):
                name, want = raw[1:], False
            if (opts.get(name, 0) > 0) != want:
                return False
        return True

    def entry_default_enabled(self, entry: dict, opts: Dict[str, int]) -> bool:
        return all(self.category_default_enabled(c, opts) for c in entry.get("category", []))

    # -- items -------------------------------------------------------------------------------------------------------
    def tracked_items(self, opts) -> List[dict]:
        out = []
        for i in self.items:
            if not (i.get("progression") or i.get("progression_skip_balancing")):
                continue
            out.append(i)
        return out

    def build(self) -> Path:
        cfg = self.cfg
        root = self.out_dir / "pack"
        if root.exists():
            shutil.rmtree(root)
        for sub in ("images/items", "images/maps", "items", "maps", "locations", "layouts", "scripts/autotracking"):
            (root / sub).mkdir(parents=True, exist_ok=True)

        opts = self.default_options()
        tracked = self.tracked_items(opts)
        codes: Dict[str, str] = {}
        for i in tracked:
            codes[i["name"]] = f"i{i['id']}"

        # ---- item icons + items.json
        items_json = []
        for i in tracked:
            code = codes[i["name"]]
            cat = (i.get("category") or ["Other"])[0]
            make_icon(i["name"], cat).save(root / "images/items" / f"{code}.png")
            entry = {"name": i["name"], "codes": code, "img": f"images/items/{code}.png",
                     "disabled_img_mods": "@disabled"}
            if i["count"] > 1:
                entry.update({"type": "consumable", "min_quantity": 0, "max_quantity": int(i["count"]),
                              "increment": 1, "decrement": 1, "initial_quantity": 0, "overlay_background": "#000000cc",
                              "overlay_font_size": 14})
            else:
                entry["type"] = "toggle"
            items_json.append(entry)
        (root / "items/items.json").write_text(json.dumps(items_json, indent=1), encoding="utf-8")

        # ---- maps, pins and locations
        loc_index: Dict[str, int] = {}
        loc_rows: List[dict] = []
        real_locs = [l for l in self.locations if not l.get("victory")]
        for l in real_locs:
            loc_rows.append(l)
            loc_index[l["name"]] = len(loc_rows)

        maps_json, locations_json, mapping, missing_pos = self.build_maps_and_locations(root, real_locs, loc_index, opts)
        (root / "maps/maps.json").write_text(json.dumps(maps_json, indent=1), encoding="utf-8")
        (root / "locations/locations.json").write_text(json.dumps(locations_json, indent=1), encoding="utf-8")

        # ---- lua data
        pool = {}
        for i in tracked:
            if self.entry_default_enabled(i, opts):
                pool[i["name"]] = int(i["count"])
        cats: Dict[str, List[str]] = {}
        for i in self.items:
            for c in i.get("category", []):
                cats.setdefault(c, []).append(i["name"])
        for e in self.events:
            for c in e.get("category", []):
                cats.setdefault(c, []).append(e["name"])
        regions_lua = {}
        for name, r in self.regions.items():
            regions_lua[name] = {"req": r.get("requires", ""), "to": r.get("connects_to", []) or []}
        starts = [n for n, r in self.regions.items() if r.get("starting")] or list(self.regions)
        locs_lua = {}
        for name, idx in loc_index.items():
            l = self.loc_by_name(name)
            locs_lua[idx] = {"name": name, "region": l["region"], "req": l.get("requires", "")}
        data = {
            "codes": codes, "pool": pool, "cats": cats, "regions": regions_lua, "start": starts,
            "events": [{"name": e["name"], "region": e.get("region", "Free")} for e in self.events],
            "event_names": {e["name"]: True for e in self.events},
            "locs": locs_lua, "opts": opts,
        }
        skills_file = self.world / "skills.json"
        if skills_file.exists():                                        # XC2: field skill levels of the blades (see worldgen/xc2_skills.py)
            data["skills"] = json.loads(skills_file.read_text(encoding="utf-8"))
        (root / "scripts/logic_data.lua").write_text("XC_DATA = " + lua_val(data) + "\n", encoding="utf-8")
        shutil.copy(HERE / "lua/xc_logic.lua", root / "scripts/xc_logic.lua")
        game_lua = cfg.get("game_lua", "")
        (root / "scripts/game_logic.lua").write_text(game_lua, encoding="utf-8")

        # ---- AP mapping
        item_map = {}
        for i in tracked:
            item_map[i["id"]] = [codes[i["name"]], "consumable" if i["count"] > 1 else "toggle"]
        loc_id_map = {}
        for l in real_locs:
            if l["name"] in mapping:
                loc_id_map[l["id"]] = mapping[l["name"]]
        mapping_lua = ["ITEM_MAPPING = " + lua_val(item_map), "LOCATION_MAPPING = " + lua_val({k: [v] for k, v in loc_id_map.items()})]
        (root / "scripts/autotracking/mapping.lua").write_text("\n".join(mapping_lua) + "\n", encoding="utf-8")
        (root / "scripts/autotracking/archipelago.lua").write_text(AP_LUA, encoding="utf-8")
        (root / "scripts/init.lua").write_text(INIT_LUA, encoding="utf-8")

        # ---- layout
        layouts = self.build_layouts(tracked, codes, maps_json, opts)
        (root / "layouts/layouts.json").write_text(json.dumps(layouts, indent=1), encoding="utf-8")

        manifest = {
            "name": cfg["title"], "game_name": cfg["game_name"], "package_uid": cfg["uid"],
            "package_version": cfg.get("version", "1.0.0"), "platform": "pc", "author": "Built with Claude Code",
            "min_poptracker_version": "0.25.2",
            "variants": {"archipelago": {"display_name": "Archipelago", "flags": ["ap"]}},
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (root / "settings.json").write_text(json.dumps({"smooth_scaling": True}, indent=2), encoding="utf-8")
        (root / "README.md").write_text(cfg.get("readme", ""), encoding="utf-8")

        zpath = Path(cfg["zip_out"])
        if zpath.exists():
            zpath.unlink()
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(root).as_posix())
        self.stats = {"items": len(tracked), "locations": len(real_locs), "mapped": len(mapping), "unpositioned": missing_pos}
        return zpath

    def loc_by_name(self, name: str) -> dict:
        if not hasattr(self, "_lbn"):
            self._lbn = {l["name"]: l for l in self.locations}
        return self._lbn[name]

    # -- maps & locations ---------------------------------------------------------------------------------------------
    def build_maps_and_locations(self, root: Path, real_locs: List[dict], loc_index: Dict[str, int], opts):
        cfg = self.cfg
        maps = cfg["maps"]                # map_id -> {"title", "img": PIL.Image, "pin": int}
        pins: Dict[str, Tuple[str, int, int]] = cfg["pin_positions"]
        region_map: Dict[str, str] = cfg["region_map"]
        group_of: Callable[[dict], str] = cfg["group_of"]
        parent_of: Callable[[dict], str] = cfg.get("parent_of", lambda l: l["region"])
        # sub-header inside the panel, one level finer than parent_of's map-tab grouping (e.g. XC3's real zone name under
        # its region's area tab); defaults to parent_of itself, which collapses to the old single-level panel (XC2's own
        # sub-region names are internal logic ids, not player-facing, so it keeps the coarse grouping unless overridden)
        sub_region_of: Callable[[dict], str] = cfg.get("sub_region_of", parent_of)
        PANEL_W = 300
        ROW_H = cfg.get("row_h", 36)

        # group unpositioned checks: map -> sub-region -> category -> locations
        priority = set(cfg.get("priority_groups", ()))
        tree: Dict[str, Dict[str, Dict[str, List[dict]]]] = {}
        positioned: List[dict] = []
        for l in real_locs:
            if l["name"] in pins:
                positioned.append(l)
            else:
                area = parent_of(l)
                mid = region_map.get(area) or next(iter(maps))
                tree.setdefault(mid, {}).setdefault(sub_region_of(l), {}).setdefault(group_of(l), []).append(l)

        # flatten into panel entries per map: ('hdr', sub_region, None) then ('row', sub_region, category) rows,
        # sub-regions alphabetical, categories within a sub-region: priority ones (Chests ...) first, then alphabetical
        PanelEntry = Tuple[str, str, Optional[str]]
        panel_entries: Dict[str, List[PanelEntry]] = {}
        panel_index: Dict[str, Dict[Tuple[str, str], int]] = {}
        for mid, subs in tree.items():
            entries: List[PanelEntry] = []
            index: Dict[Tuple[str, str], int] = {}
            for sub in sorted(subs):
                entries.append(("hdr", sub, None))
                for cat in sorted(subs[sub], key=lambda c: (c not in priority, c)):
                    index[(sub, cat)] = len(entries)
                    entries.append(("row", sub, cat))
            panel_entries[mid] = entries
            panel_index[mid] = index

        maps_json = []
        canvases: Dict[str, Tuple[Image.Image, int, Tuple[int, int], int, int]] = {}   # canvas, x-off, map-off, ncols, rows_per_col
        for mid, m in maps.items():
            base: Image.Image = m["img"].convert("RGB")
            min_w, min_h = self.cfg.get("min_map", (0, 0))
            pw, ph = max(base.width, min_w), max(base.height, min_h)
            if (pw, ph) != base.size:      # pad small maps so the default window size stays comfortable
                padded = Image.new("RGB", (pw, ph), (9, 11, 20))
                padded.paste(base, ((pw - base.width) // 2, (ph - base.height) // 2))
                map_off = ((pw - base.width) // 2, (ph - base.height) // 2)
                base = padded
            else:
                map_off = (0, 0)
            entries = panel_entries.get(mid, [])
            # spread the panel over columns instead of stretching the canvas into one tall mostly-empty strip:
            # target each column at roughly the map's own height, capped so very long lists still get more columns
            target_h = max(base.height, 480)
            rows_avail = max(1, (target_h - 60 - 20) // ROW_H)
            ncols = min(5, max(1, -(-len(entries) // rows_avail))) if entries else 0
            rows_per_col = max(1, -(-len(entries) // ncols)) if ncols else 0
            H = max(base.height, 60 + rows_per_col * ROW_H + 20)
            W = base.width + PANEL_W * ncols
            canvas = Image.new("RGB", (W, H), (9, 11, 20))
            off = PANEL_W * ncols
            canvas.paste(base, (off, 0))
            d = ImageDraw.Draw(canvas, "RGBA")
            fh = font(15)
            fl = font(14, bold=False)
            for i, (kind, sub, cat) in enumerate(entries):
                col, row = divmod(i, rows_per_col)
                cx, y = col * PANEL_W, 56 + row * ROW_H
                if row == 0:
                    d.rectangle([cx, 0, cx + PANEL_W - 1, H - 1], fill=(18, 22, 40, 255))
                    d.text((cx + 12, 10), "Checks without a map position", font=font(14), fill=(230, 220, 160, 255))
                if kind == "hdr":
                    label = fit_text(d, sub, fh, PANEL_W - 20)
                    d.text((cx + 10, y - 8), label, font=fh, fill=(150, 190, 230, 255))
                    d.line([(cx + 10, y + 12), (cx + PANEL_W - 12, y + 12)], fill=(150, 190, 230, 90), width=1)
                else:
                    label = fit_text(d, cat, fl, PANEL_W - 32)
                    d.text((cx + 22, y - 6), label, font=fl, fill=(210, 214, 232, 255))
            canvases[mid] = (canvas, off, map_off, ncols, rows_per_col)
            path = f"images/maps/{mid}.png"
            canvas.save(root / path, optimize=True)
            maps_json.append({"name": mid, "img": path, "location_size": m.get("pin", 22),
                              "location_border_thickness": 2})

        loc_json: Dict[str, dict] = {}      # region -> location group
        mapping: Dict[str, str] = {}

        def region_node(region: str) -> dict:
            if region not in loc_json:
                loc_json[region] = {"name": clean(region), "children": []}
            return loc_json[region]

        # pin_positions[name] is (map id, x, y) or (map id, x, y, label), or a list of those to pin one check on several maps.
        # Checks whose entries carry the same label share ONE pin (a location with one section per check, e.g. all slots of a
        # shop), instead of each stacking its own pin on the exact same spot.
        shared: Dict[Tuple[str, str], dict] = {}
        for l in positioned:
            entries = pins[l["name"]]
            if entries and isinstance(entries[0], str):
                entries = [entries]
            label = entries[0][3] if len(entries[0]) > 3 else None
            node = region_node(parent_of(l))
            sname = clean(l["name"]) if label else "Check"
            sec = {"name": sname, "access_rules": [f"$xc|{loc_index[l['name']]}"]}
            child = shared.get((node["name"], label)) if label else None
            if child is not None:
                used = {s["name"] for s in child["sections"]}
                base_name, n = sname, 2
                while sec["name"] in used:
                    sec["name"] = f"{base_name} ({n})"
                    n += 1
                child["sections"].append(sec)
            else:
                mlocs = []
                for e in entries:
                    emid, ex, ey = e[0], e[1], e[2]
                    eoff, (emox, emoy) = canvases[emid][1], canvases[emid][2]
                    mlocs.append({"map": emid, "x": int(round(ex + eoff + emox)), "y": int(round(ey + emoy))})
                child = {"name": clean(label or l["name"]), "sections": [sec], "map_locations": mlocs}
                node["children"].append(child)
                if label:
                    shared[(node["name"], label)] = child
            mapping[l["name"]] = f"@{node['name']}/{child['name']}/{sec['name']}"

        for mid, subs in tree.items():
            _, _, _, ncols, rows_per_col = canvases[mid]
            for sub, cats in subs.items():
                for cat, members in cats.items():
                    idx = panel_index[mid][(sub, cat)]
                    col, row = divmod(idx, rows_per_col)
                    px, py = col * PANEL_W + PANEL_W - 14, 56 + row * ROW_H
                    node = region_node(sub)
                    pin_name = clean(f"{sub} - {cat}")
                    secs = []
                    used = set()
                    for l in members:
                        sname = clean(l["name"])
                        base_name = sname
                        n = 2
                        while sname in used:
                            sname = f"{base_name} ({n})"
                            n += 1
                        used.add(sname)
                        secs.append({"name": sname, "access_rules": [f"$xc|{loc_index[l['name']]}"]})
                        mapping[l["name"]] = f"@{node['name']}/{pin_name}/{sname}"
                    node["children"].append({"name": pin_name, "sections": secs,
                                             "map_locations": [{"map": mid, "x": int(px), "y": int(py)}]})
        return maps_json, list(loc_json.values()), mapping, len(real_locs) - len(positioned)

    # -- layouts -----------------------------------------------------------------------------------------------------
    def build_layouts(self, tracked, codes, maps_json, opts):
        group_of_item = self.cfg["item_group_of"]
        priority = self.cfg.get("left_groups", [])
        groups: Dict[str, List[str]] = {}
        for i in tracked:
            if not self.entry_default_enabled(i, opts):
                continue
            groups.setdefault(group_of_item(i), []).append(codes[i["name"]])
        layouts = {}

        def grid(codes_list, cols):
            rows = [codes_list[k:k + cols] for k in range(0, len(codes_list), cols)]
            return {"type": "itemgrid", "item_size": self.cfg.get("item_size", 40), "item_margin": "2,2",
                    "h_alignment": "left", "rows": rows}

        def group_widget(name, cs, cols):
            return {"type": "group", "header": name, "content": grid(cs, cols)}

        left = [group_widget(g, groups[g], 8) for g in priority if g in groups]
        rest = [(g, cs) for g, cs in groups.items() if g not in priority]
        tabs = []
        for m in maps_json:
            tabs.append({"title": self.cfg["maps"][m["name"]]["title"], "content": {"type": "map", "maps": [m["name"]]}})
        if rest:
            # big groups (e.g. collectopaedia pages) get a wide, compact grid; the rest stack in a second column
            wide = self.cfg.get("wide_groups", {})
            big, small = [], []
            for g, cs in rest:
                if g in wide:
                    cols_n, size = wide[g]
                    rows = [cs[k:k + cols_n] for k in range(0, len(cs), cols_n)]
                    big.append({"type": "group", "header": g, "content": {"type": "itemgrid", "item_size": size, "item_margin": "1,1",
                                                                           "h_alignment": "left", "rows": rows}})
                else:
                    small.append(group_widget(g, cs, 8))
            columns = []
            if big:
                columns.append({"type": "array", "orientation": "vertical", "content": big})
            # spread the small groups over up to three columns
            ncol = 3 if len(small) > 6 else (2 if len(small) > 3 else 1)
            cols = [[] for _ in range(ncol)]
            for k, w in enumerate(small):
                cols[k % ncol].append(w)
            for c in cols:
                if c:
                    columns.append({"type": "array", "orientation": "vertical", "content": c})
            tabs.append({"title": "All Items", "content": {"type": "array", "orientation": "horizontal", "content": columns}})
        root_content = {"type": "dock", "dropshadow": True, "content": []}
        if left:
            root_content["content"].append({"type": "array", "orientation": "vertical", "dock": "left", "content": left})
        root_content["content"].append({"type": "tabbed", "tabs": tabs})
        layouts["tracker_default"] = {"type": "container", "background": "#0b0d18", "content": root_content}
        return layouts


INIT_LUA = '''-- Xenoblade AP tracker -- entry point
ScriptHost:LoadScript("scripts/logic_data.lua")

Tracker:AddItems("items/items.json")
Tracker:AddMaps("maps/maps.json")
Tracker:AddLocations("locations/locations.json")
Tracker:AddLayouts("layouts/layouts.json")

ScriptHost:LoadScript("scripts/xc_logic.lua")
ScriptHost:LoadScript("scripts/game_logic.lua")

if Archipelago then
    ScriptHost:LoadScript("scripts/autotracking/archipelago.lua")
end
'''

AP_LUA = '''-- Archipelago auto-tracking (item / location ids come from mapping.lua, generated from the apworld)
ScriptHost:LoadScript("scripts/autotracking/mapping.lua")

CUR_INDEX = -1
SLOT_DATA = nil

local function find(code)
    return Tracker:FindObjectForCode(code)
end

local function all_location_ids()
    local set = {}
    for _, list in ipairs({ Archipelago.MissingLocations or {}, Archipelago.CheckedLocations or {} }) do
        for _, id in ipairs(list) do set[id] = true end
    end
    return set
end

function onClear(slot_data)
    SLOT_DATA = slot_data
    CUR_INDEX = -1
    for _, entry in pairs(ITEM_MAPPING) do
        local obj = find(entry[1])
        if obj then
            if entry[2] == "consumable" then obj.AcquiredCount = 0 else obj.Active = false end
        end
    end
    local existing = all_location_ids()
    local have_list = next(existing) ~= nil
    for id, sections in pairs(LOCATION_MAPPING) do
        local obj = find(sections[1])
        if obj then
            -- checks that are not part of this slot (disabled categories) are shown as done
            if have_list and not existing[id] then
                obj.AvailableChestCount = 0
            else
                obj.AvailableChestCount = obj.ChestCount
            end
        end
    end
    if slot_data then
        XC.reset_options(slot_data)
    else
        XC.reset_options(nil)
    end
end

function onItem(index, item_id, item_name, player_number)
    if index <= CUR_INDEX then return end
    CUR_INDEX = index
    local entry = ITEM_MAPPING[item_id]
    if not entry then return end
    local obj = find(entry[1])
    if not obj then return end
    if entry[2] == "consumable" then
        obj.AcquiredCount = obj.AcquiredCount + 1
    else
        obj.Active = true
    end
end

function onLocation(location_id, location_name)
    local sections = LOCATION_MAPPING[location_id]
    if not sections then return end
    local obj = find(sections[1])
    if obj then obj.AvailableChestCount = 0 end
end

Archipelago:AddClearHandler("xc clear handler", onClear)
Archipelago:AddItemHandler("xc item handler", onItem)
Archipelago:AddLocationHandler("xc location handler", onLocation)
'''
