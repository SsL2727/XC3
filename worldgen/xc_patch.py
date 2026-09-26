"""Patch step: turn a slot's settings into a game-data mod (via the third-party Series Randomizer) and install it into Ryujinx.

Generation writes a small per-player patch file (`.apxc2` / `.apxc3` / `.apxcde`, a zip holding patch.json) next to the multiworld.  The launcher
opens it with the "<game> Patcher" component, which:
  1. reads the seed's settings,
  2. runs the randomizer headlessly (bridge script `run_randomizer.py`, launched with the system Python that has tkinter),
  3. copies the resulting romfs mod to <Ryujinx data dir>/sdcard/atmosphere/contents/<title id>/,
  4. leaves a `ap_patch.json` marker beside it (seed / slot) that the client uses to check the right mod is installed.
Paths (randomizer folder, extracted BDAT folder per game, Ryujinx data dir, Python) are asked for once and remembered.
"""
from __future__ import annotations

import json
import os
import pkgutil
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Any, Callable, Dict, Optional

from .qol import qol_config

GAMES: Dict[str, Dict[str, Any]] = {
    # 2026-09-23: xc2_fast_travel / xc2_no_crystal_drops were briefly suspected in a crash-on-launch and disabled;
    # the real cause was an unrelated stale non-portable yuzu profile (nothing to do with any BDAT patch content).
    # Both confirmed innocent and re-enabled.
    # "title_id" is the runtime id Ryujinx's Atmosphere-compatible sdcard/atmosphere/contents layer expects (live-
    # tested working there for days). 2026-09-23: confirmed via yuzu's own log ("Loading Xenoblade Chronicles 2
    # (0100E95004038000)", PatchRomFS/PatchExeFS both title_id=0100E95004038000) that yuzu's native load/<id>/<mod>
    # LayeredFS matches the REAL running program id instead - it never sees content placed at 039001, so shops/
    # tutorial-skip/etc silently never applied there. "yuzu_title_id" overrides the id used for the emulator_dirs
    # (yuzu-family) install path only; ryujinx_dir keeps using "title_id" unchanged.
    "Xenoblade Chronicles 2": {"code": "XC2", "suffix": ".apxc2", "title_id": "0100E95004039001",
                               "yuzu_title_id": "0100E95004038000",
                               "ap_patches": ["xc2_blade_crystals", "xc2_fast_travel", "xc2_no_crystal_drops"],
                               "bdat_hint": "folder with common.bdat, common_gmk.bdat and gb/common_ms.bdat (from the game's bdat files)"},
    "Xenoblade Chronicles 3": {"code": "XC3", "suffix": ".apxc3", "title_id": "010074F013262000",
                               "bdat_hint": "folder with des/btl/evt/fld/map/prg/qst/sys/zzz/mnu/dlc.bdat and gb/game/*.bdat"},
    "Xenoblade Chronicles DE": {"code": "XCDE", "suffix": ".apxcde", "title_id": "0100FF500E34A000",
                                "bdat_hint": "folder with the bdat_*.bdat files and the gb text bdats"},
}
PATCH_VERSION = 1
MOD_NAME = "Archipelago"          # folder name of the mod inside a yuzu-family emulator's load/<title id>/ directory


# ------------------------------------------------------------------------------------------------------------------ patch file
def make_patch_data(world) -> Dict[str, Any]:
    mw = world.multiworld
    return {"version": PATCH_VERSION, "game": world.game, "player": world.player, "player_name": mw.player_name[world.player],
            "seed_name": mw.seed_name, "slot_data": world.fill_slot_data()}


def write_patch_file(world, output_directory: str) -> str:
    info = GAMES[world.game]
    base = world.multiworld.get_out_file_name_base(world.player)
    path = os.path.join(output_directory, base + info["suffix"])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("patch.json", json.dumps(make_patch_data(world), indent=1))
    return path


def read_patch_file(path: str) -> Dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("patch.json").decode("utf-8"))


# ------------------------------------------------------------------------------------------------------------------ randomizer config
def rando_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Options for the randomizer bridge (everything the seed asks the game data to change)."""
    game, slot = data["game"], data["slot_data"]
    options: Dict[str, Any] = {}
    options.update(qol_config(game, slot))
    return options


# ------------------------------------------------------------------------------------------------------------------ settings
def settings_path() -> str:
    if os.environ.get("XC_PATCHER_SETTINGS"):                  # test hook: keep experiments away from the real settings
        return os.environ["XC_PATCHER_SETTINGS"]
    try:
        import Utils
        return Utils.user_path("xenoblade_patcher.json")
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".xenoblade_patcher.json")


def load_settings() -> Dict[str, Any]:
    try:
        return json.load(open(settings_path(), encoding="utf-8"))
    except Exception:
        return {}


def save_settings(s: Dict[str, Any]) -> None:
    with open(settings_path(), "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1)


def marker_paths(game: str, settings: Optional[Dict[str, Any]] = None) -> list:
    """Every place the patcher may have left the game's ap_patch.json (Ryujinx sdcard, yuzu-family 'user/load/<title>/Archipelago')."""
    s = settings if settings is not None else load_settings()
    tid = GAMES[game]["title_id"]
    paths = []
    if s.get("ryujinx_dir"):
        paths.append(os.path.join(s["ryujinx_dir"], "sdcard", "atmosphere", "contents", tid, "ap_patch.json"))
    for d in s.get("emulator_dirs", []):
        paths.append(os.path.join(d, "load", tid, MOD_NAME, "ap_patch.json"))
    return paths


def read_marker(game: str) -> Dict[str, Any]:
    """The newest installed ap_patch.json for the game ({} when none)."""
    found = [p for p in marker_paths(game) if os.path.exists(p)]
    if not found:
        return {}
    found.sort(key=os.path.getmtime, reverse=True)
    return json.load(open(found[0], encoding="utf-8"))


def _default_ryujinx() -> str:
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Ryujinx") if appdata else ""


def _find_python() -> str:
    for cand in ("python", "py"):
        exe = shutil.which(cand)
        if exe:
            return exe
    return ""


def ensure_settings(game: str, ask_dir: Callable[[str], str], log: Callable[[str], None]) -> Dict[str, Any]:
    """Fill in whatever is missing (asking the user through `ask_dir(prompt)`), remember it, return the settings."""
    s = load_settings()
    info = GAMES[game]
    s.setdefault("python", _find_python())
    if not s.get("randomizer_dir") or not os.path.isdir(s["randomizer_dir"]):
        d = ask_dir("Folder of the extracted Xenoblade Series Randomizer (contains Randomizer.py)")
        if not d or not os.path.exists(os.path.join(d, "Randomizer.py")):
            raise RuntimeError("The Xenoblade Series Randomizer folder is required (it contains Randomizer.py).")
        s["randomizer_dir"] = d
    bd = s.setdefault("bdat_dirs", {})
    if not bd.get(info["code"]) or not os.path.isdir(bd[info["code"]]):
        d = ask_dir(f"Extracted BDAT folder for {game}: {info['bdat_hint']}")
        if not d or not os.path.isdir(d):
            raise RuntimeError(f"The extracted BDAT folder for {game} is required.")
        bd[info["code"]] = d
    s["emulator_dirs"] = [d for d in s.get("emulator_dirs", []) if os.path.isdir(d)]
    if s.get("ryujinx_dir") and not os.path.isdir(s["ryujinx_dir"]):
        s.pop("ryujinx_dir")
    if not s.get("ryujinx_dir") and not s["emulator_dirs"]:
        d = _default_ryujinx()
        if not d or not os.path.isdir(d):
            d = ask_dir("Ryujinx data folder (contains 'system', 'games', 'sdcard' ...) - or the 'user' folder of an Eden / yuzu / Citron / Sudachi install "
                        "(contains 'load', 'nand', 'keys')")
        if not d or not os.path.isdir(d):
            raise RuntimeError("An emulator data folder is required (Ryujinx data folder, or the 'user' folder of a yuzu-family emulator).")
        if os.path.isdir(os.path.join(d, "load")) or os.path.isdir(os.path.join(d, "nand")):
            s["emulator_dirs"] = [d]
        else:
            s["ryujinx_dir"] = d
    if not s.get("python"):
        raise RuntimeError("A system Python with tkinter is required to run the randomizer (python.exe was not found on PATH).")
    save_settings(s)
    return s


# XC2 does not read its BDATs as loose RomFS files at all: the real game packs everything (including common.bdat /
# common_gmk.bdat / gb/common_ms.bdat) inside a proprietary archive, /bf2.ard (indexed by /bf2.arh), sitting at
# RomFS root. Confirmed 2026-09-23 by extracting the actual .nsp+update RomFS directly: its only top-level entries
# are bf2.ard, bf2.arh and stream/ - there is no bdat/ folder to loose-file-override via LayeredFS at all. Every
# prior "romfs/bdat/*.bdat" drop (the whole AP_PATCHES pipeline: blade crystals, story gates, shops, fast travel,
# crystal-drop removal, tutorial skip) sat at a path the game's own code never reads, so none of it ever actually
# applied in-game, on any emulator. The real fix: inject the freshly-packed bdat files into a COPY of the real
# archive with XbTool's ReplaceArchive task, then ship that modified bf2.ard/bf2.arh as the RomFS override instead.
def _xc2_archive_paths(s: Dict[str, Any]) -> tuple:
    """(xbtool_exe, pristine_arh, pristine_ard) for the XC2 archive-repack step; settings keys let this be moved."""
    xbtool = s.get("xbtool_path") or r"G:\Archipelago\xc-tools\xbtool\XbTool.exe"
    archive_dir = s.get("xc2_archive_dir") or r"F:\XCAP\work\xc2_archive"
    return xbtool, os.path.join(archive_dir, "bf2.arh"), os.path.join(archive_dir, "bf2.ard")


def _repack_xc2_archive(src: str, s: Dict[str, Any], log: Callable[[str], None]) -> Optional[str]:
    """Inject every loose romfs/bdat/*.bdat the randomizer just packed into a copy of the real bf2.ard/arh archive.
    Returns the folder holding the patched archive pair, or None if there was nothing to do. The archive is ~11 GB;
    the install step junctions each destination's romfs folder to this directory instead of copying it there (C: on
    this machine is chronically near-full - "no space left on device" trying to copy it live-confirmed 2026-09-23),
    so this folder must stay put (not a tempdir) for as long as the mod stays installed."""
    xbtool, pristine_arh, pristine_ard = _xc2_archive_paths(s)
    bdat_root = os.path.join(src, "romfs", "bdat")
    if not os.path.isdir(bdat_root) or not os.path.isfile(pristine_arh) or not os.path.isfile(pristine_ard):
        return None
    log("Injecting patched BDATs into a copy of the real game archive (this takes a few minutes - it's an 11 GB file)...")
    patched_dir = os.path.join(os.path.dirname(pristine_ard), "patched")
    os.makedirs(patched_dir, exist_ok=True)
    patched_arh = os.path.join(patched_dir, "bf2.arh")
    patched_ard = os.path.join(patched_dir, "bf2.ard")
    shutil.copyfile(pristine_arh, patched_arh)
    shutil.copyfile(pristine_ard, patched_ard)
    for dirpath, _dirs, files in os.walk(bdat_root):
        for fn in files:
            local = os.path.join(dirpath, fn)
            internal = "/bdat/" + os.path.relpath(local, bdat_root).replace(os.sep, "/")
            proc = subprocess.run([xbtool, "-g", "xb2", "-t", "ReplaceArchive", "-a", patched_arh, patched_ard,
                                    "-i", local, "-o", internal], capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"XbTool failed to inject {internal} into the game archive:\n{proc.stderr[-2000:]}")
    shutil.rmtree(os.path.join(src, "romfs"))          # nothing else XC2-specific ever lived under romfs - just bdat/
    log("Archive repack done.")
    return patched_dir


# ------------------------------------------------------------------------------------------------------------------ the patch run
def run_patch(patch_path: str, ask_dir: Optional[Callable[[str], str]] = None, log: Callable[[str], None] = print) -> str:
    """Build and install the mod for a patch file; returns the installed mod directory."""
    data = read_patch_file(patch_path)
    game = data["game"]
    info = GAMES[game]
    s = ensure_settings(game, ask_dir or (lambda prompt: input(prompt + ": ").strip()), log)

    work = tempfile.mkdtemp(prefix="xc_patch_")
    out_dir = os.path.join(work, "out")
    cfg = {"game": info["code"], "randomizer_root": s["randomizer_dir"], "bdat_dir": s["bdat_dirs"][info["code"]], "out_dir": out_dir,
           "work_dir": os.path.join(s.get("work_dir") or os.path.join(os.path.dirname(settings_path()), "xc_rando_work"), info["code"]),
           "seed": f"{data['seed_name']}-{data['player']}", "options": rando_config(data), "ap_patches": list(info.get("ap_patches", []))}
    if info["code"] == "XC2" and data["slot_data"].get("story_gating"):      # region entrances wait for Progressive Area items
        cfg["ap_patches"].append("xc2_story_gates")
        cfg["gates"] = json.loads(pkgutil.get_data(__package__, "data/gates.json").decode("utf-8"))
    open_world = info["code"] == "XC3" and bool(data["slot_data"].get("open_world"))
    if info["code"] == "XC3" and data["slot_data"].get("story_gating") and not open_world:   # cutscene triggers wait for Progressive Story Quest items (Open World's save is past them)
        cfg["ap_patches"].append("xc3_story_gates")
        cfg["gates"] = json.loads(pkgutil.get_data(__package__, "data/gates.json").decode("utf-8"))
    if info["code"] == "XC3" and data["slot_data"].get("hero_randomization"):
        cfg["ap_patches"].append("xc3_hero_access")
        cfg["heroes"] = json.loads(pkgutil.get_data(__package__, "data/heroes.json").decode("utf-8"))
    if info["code"] == "XC3" and data["slot_data"].get("container_gating"):    # field containers stay un-poppable until enough Progressive Container Access items arrive
        cfg["ap_patches"].append("xc3_container_gates")
        cfg["container_gates"] = json.loads(pkgutil.get_data(__package__, "data/container_gates.json").decode("utf-8"))
    if info["code"] in ("XC2", "XC3") and data["slot_data"].get("shop_checks"):
        cfg["ap_patches"].append(f"{info['code'].lower()}_shops")
        cfg["shops"] = json.loads(pkgutil.get_data(__package__, "data/shops.json").decode("utf-8"))
        cfg["shop_labels"] = data["slot_data"].get("shop_labels", {})
        cfg["shop_mode"] = data["slot_data"]["shop_checks"]
    cfg_path = os.path.join(work, "config.json")
    bridge = os.path.join(work, "run_randomizer.py")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)
    with open(bridge, "wb") as fh:
        fh.write(pkgutil.get_data(__package__, "run_randomizer.py"))
    if cfg["options"] or cfg["ap_patches"]:
        log(f"Randomizer options: {json.dumps(cfg['options'])}")
    else:
        log("No game-data changes requested (baseline mod only).")
    log("Running the randomizer (this takes a few seconds)...")
    proc = subprocess.run([s["python"], bridge, cfg_path], capture_output=True, text=True)
    for line in proc.stdout.splitlines()[-12:]:
        log(line)
    if proc.returncode != 0:
        log(proc.stderr[-2000:])
        raise RuntimeError("The randomizer reported errors (see the log above); nothing was installed.")

    src = os.path.join(out_dir, "contents", info["title_id"])
    if not os.path.isdir(src):
        raise RuntimeError(f"The randomizer produced no output for title {info['title_id']}.")
    xc2_romfs_link = _repack_xc2_archive(src, s, log) if info["code"] == "XC2" else None
    marker = {"game": game, "seed_name": data["seed_name"], "player": data["player"], "player_name": data["player_name"]}
    if os.path.exists(os.path.join(out_dir, "ap_map.json")):             # what the patches decided (read by the client)
        marker.update(json.load(open(os.path.join(out_dir, "ap_map.json"), encoding="utf-8")))

    installed = []

    def put(dst: str, with_loader: bool) -> None:
        try:
            # A previous install may have left dst/romfs as a junction into the permanent patched-archive folder
            # (see below). os.rmdir on a junction removes only the link, never the target's contents - verified
            # empirically 2026-09-23 - so this must run before the rmtree below, which must never be allowed to
            # recurse into that junction (it would delete the one persistent copy of the patched ~11 GB archive).
            os.rmdir(os.path.join(dst, "romfs"))
        except OSError:
            pass
        shutil.rmtree(dst, ignore_errors=True)
        if os.path.exists(dst):
            raise RuntimeError("The old mod files are in use - close the emulator completely and patch again.")
        shutil.copytree(src, dst)
        if info["code"] == "XC2" and xc2_romfs_link:
            # The patched archive lives permanently at xc2_romfs_link (see _repack_xc2_archive) - junctioned in
            # rather than copied, since it's ~11 GB and C: here doesn't reliably have that much room. Junctions
            # (unlike symlinks) don't need admin/Developer Mode on Windows.
            romfs_dst = os.path.join(dst, "romfs")
            os.makedirs(dst, exist_ok=True)
            proc = subprocess.run(["cmd", "/c", "mklink", "/J", romfs_dst, xc2_romfs_link], capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"Could not junction {romfs_dst} -> {xc2_romfs_link}:\n{proc.stdout}{proc.stderr}")
        if info["code"] == "XC3" and not with_loader:
            # Xenoblade 3 only reads loose BDATs through the randomizer's Skyline plugin + exefs patch.  Ryujinx crashes with it (null access in the game at
            # boot), so there it is only installed when settings say so ("xc3_loader": true); yuzu-family emulators (Eden) run it.
            shutil.rmtree(os.path.join(dst, "exefs"), ignore_errors=True)
            shutil.rmtree(os.path.join(dst, "romfs", "skyline"), ignore_errors=True)
            log("NOTE: Xenoblade 3 needs the Skyline loader to read this mod; it was NOT installed on Ryujinx (it crashes there). Use Eden (or another "
                "yuzu-family emulator) via the 'emulator_dirs' patcher setting, or set \"xc3_loader\": true in the settings.")
        with open(os.path.join(dst, "ap_patch.json"), "w", encoding="utf-8") as fh:
            json.dump(marker, fh)
        installed.append(dst)

    if s.get("ryujinx_dir"):
        dst_root = os.path.join(s["ryujinx_dir"], "sdcard", "atmosphere", "contents")
        os.makedirs(dst_root, exist_ok=True)
        put(os.path.join(dst_root, info["title_id"]), bool(s.get("xc3_loader")))
    load_title_id = info.get("yuzu_title_id", info["title_id"])
    for d in s.get("emulator_dirs", []):                                  # Eden / yuzu / Citron / Sudachi: <user dir>/load/<title id>/<mod>/{exefs,romfs}
        os.makedirs(os.path.join(d, "load", load_title_id), exist_ok=True)
        put(os.path.join(d, "load", load_title_id, MOD_NAME), True)
    shutil.rmtree(work, ignore_errors=True)
    if open_world:
        _install_open_world_save(_xc3_save_targets(s, info["title_id"]), data, log)
        if s.get("ryujinx_dir"):
            log("NOTE: the Open World save is only installed for Eden / yuzu-family emulators, not Ryujinx.")
        log("Installed to " + ", ".join(installed) + f". Load save slot 1 in {game} (Open World).")
    else:
        log("Installed to " + ", ".join(installed) + f". Start {game} with a NEW game.")
    return installed[0]


DEFAULT_XC3_SAVE_DIR = r"F:\XCAP\work\emus\eden\user\nand\user\save\0000000000000000\F2DF0042DCA2C1FAFDC05D1CE5065C54\010074F013262000"
OPEN_WORLD_SLOT = "bf3game01"
OPEN_WORLD_MARKER = "ap_open_world.json"


def _xc3_save_dirs(user_dir: str, title_id: str) -> list:
    """<user>/nand/user/save/<zeros>/<profile>/<title id> folders that already exist for the game."""
    root = os.path.join(user_dir, "nand", "user", "save")
    found = []
    for zeros in (os.listdir(root) if os.path.isdir(root) else []):
        for profile in (os.listdir(os.path.join(root, zeros)) if os.path.isdir(os.path.join(root, zeros)) else []):
            for tid in (os.listdir(os.path.join(root, zeros, profile)) if os.path.isdir(os.path.join(root, zeros, profile)) else []):
                if tid.upper() == title_id.upper():
                    found.append(os.path.join(root, zeros, profile, tid))
    return found


def _xc3_save_targets(s: Dict[str, Any], title_id: str) -> list:
    """The XC3 save folder(s) to install into: the "xc3_save_dir" setting if that folder exists, else every existing
    XC3 save folder under the yuzu-family emulator dirs."""
    explicit = s.get("xc3_save_dir") or DEFAULT_XC3_SAVE_DIR
    if os.path.isdir(explicit):
        return [explicit]
    targets = [t for d in s.get("emulator_dirs", []) for t in _xc3_save_dirs(d, title_id)]
    if not targets:
        raise RuntimeError(f"No Xenoblade Chronicles 3 save folder found (tried {explicit} and the emulator folders). Start the "
                           "game once in the emulator (reach the title screen so it makes its system save), or set "
                           "\"xc3_save_dir\" in the patcher settings, then patch again.")
    return targets


def _install_open_world_save(targets: list, data: Dict[str, Any], log: Callable[[str], None]) -> None:
    """Put the prepared Open World save into slot 1, once per seed. Existing saves are backed up first; re-patching the
    same seed leaves the slot alone so a run in progress is never overwritten."""
    this_run = {"seed_name": data["seed_name"], "player": data["player"]}
    save = pkgutil.get_data(__package__, "data/open_world.sav")
    thumb = pkgutil.get_data(__package__, "data/open_world.tmb")
    for target in targets:
        marker_path = os.path.join(target, OPEN_WORLD_MARKER)
        try:
            previous = json.load(open(marker_path, encoding="utf-8"))
        except Exception:
            previous = None
        if previous == this_run:
            log(f"Open World save already installed for this seed in {target} - left untouched.")
            continue
        if os.listdir(target):
            backup = f"{target}_backup_{time.strftime('%Y%m%d_%H%M%S')}"
            shutil.copytree(target, backup)
            log(f"Backed up existing saves to {backup}")
        with open(os.path.join(target, OPEN_WORLD_SLOT + ".sav"), "wb") as fh:
            fh.write(save)
        with open(os.path.join(target, OPEN_WORLD_SLOT + ".tmb"), "wb") as fh:
            fh.write(thumb)
        with open(marker_path, "w", encoding="utf-8") as fh:
            json.dump(this_run, fh)
        log(f"Installed the Open World save into slot 1: {target}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: xc_patch <patch file>")
        return 2
    try:
        run_patch(argv[0])
    except Exception as ex:
        print(f"Patching failed: {ex}")
        return 1
    return 0


def launch_gui(patch_path: str) -> None:
    """Entry used by the launcher component: same as run_patch but with folder dialogs and a result message box."""
    import Utils
    logs = []

    def ask(prompt: str) -> str:
        return Utils.open_directory(prompt) or ""

    try:
        dst = run_patch(patch_path, ask, logs.append)
        Utils.messagebox("Xenoblade patcher", "\n".join(logs[-6:]) or f"Installed to {dst}")
    except Exception as ex:
        Utils.messagebox("Xenoblade patcher", f"Patching failed:\n{ex}", error=True)
