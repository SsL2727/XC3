# Xenoblade Chronicles 3 — Archipelago Setup Guide

Complete step-by-step guide for setting up and playing an Archipelago multiworld with Xenoblade Chronicles 3,
on this machine's existing install. XC3 runs on **Eden** (a yuzu-family emulator), not Ryujinx — the Skyline
loader that Story Gating and Hero Randomization need crashes Ryujinx.

For XC2, see [SETUP_XC2.md](SETUP_XC2.md) instead (it runs on a different emulator, Ryujinx). For the
technical/developer reference (how the world is built, data formats, etc.), see [README.md](README.md).

---

## Key facts you need before starting

| What | Value |
|---|---|
| Emulator | Eden, at `F:\XCAP\work\emus\eden\eden.exe` (portable — never point it at a shared profile) |
| Base game file | `F:\XCAP\Xenobalde 3 AP\Xenoblade Chronicles 3 [010074F013262000][v0].nsp` |
| Title id | `010074F013262000` |
| Mod install location | `F:\XCAP\work\emus\yuzu\user\load\010074F013262000\Archipelago\` (this is hard-linked to the equivalent path under `emus\eden\user\...` — same files, either path works) |
| Controls | Your physical gamepad only — the in-game controls are **not** bound to keyboard |

**A `.apworld` file is not a patch file.** `custom_worlds\xenoblade_3.apworld` is the *world definition*
(what the generator and the tracker use) — you never open it directly. The actual per-seed patch is the
`.apxc3` file bundled inside your generated multiworld zip.

---

## 1. One-time setup (already done on this machine, listed for reference)

- Archipelago portable install at `G:\Archipelago\` (`ArchipelagoGenerate.exe`, `ArchipelagoServer.exe`,
  `ArchipelagoLauncher.exe`, `custom_worlds\xenoblade_3.apworld`).
- Xenoblade Series Randomizer extracted at `F:\XCAP\work\randomizer\Xenoblade-Series-Randomizer-1.4.2`.
- XC3's unpacked BDAT at `F:\XCAP\extracted\xc3_rando_bdat`.
- Patcher settings remembered in `G:\Archipelago\xenoblade_patcher.json` (delete it to be asked again):
  ```json
  {
   "python": "C:\\Python314\\python.exe",
   "randomizer_dir": "F:\\XCAP\\work\\randomizer\\Xenoblade-Series-Randomizer-1.4.2",
   "bdat_dirs": {"XC2": "F:\\XCAP\\work\\rb\\xc2_bdat", "XC3": "F:\\XCAP\\extracted\\xc3_rando_bdat"},
   "ryujinx_dir": "F:\\XCAP\\work\\ryu_root",
   "emulator_dirs": ["F:\\XCAP\\work\\emus\\yuzu\\user"]
  }
  ```

If the apworld ever needs rebuilding after a code change:
```bash
cd G:\Archipelago\xc-tools\worldgen
python build_worlds.py --only xenoblade_3 --install
```

---

## 2. Write your player YAML

One YAML per player, e.g. `Players\XC3.yaml`. Options worth knowing (all in the apworld's own generated docs too):

- **`story_gating`** (default on): every main story chapter is locked behind `Progressive Story Quest` items,
  received in order — a real, hard-enforced lock (the game's own cutscene triggers refuse to fire without the
  item). Needs the patcher and Eden specifically.
- **`hero_randomization`** (default on): each Hero is recruitable immediately once you receive their item,
  instead of waiting for their personal quest chain. Needs Eden.
- **`progressive_colony_affinity`** (default on): every colony's affinity level is capped until
  `Progressive Affinity: <colony>` items arrive.
- **`shop_checks`** (default "Per Slot"): shop items become checks.
- **`manual_checks`** (default off): include checks the client can't auto-detect (send with `/check` by hand).

**Note on exploration**: unlike XC2, XC3's regions are *not* gated by any AP item — nothing stops you from
physically walking into an area early. Real progression gating for XC3 comes entirely from `story_gating`.

## 3. Generate

Keep your YAMLs in an isolated folder — a big shared `Players\` folder with unrelated broken worlds in it can
fail generation on something that has nothing to do with you.

```bash
mkdir -p "F:\XCAP\work\session\players" "F:\XCAP\work\session\out"
cp "G:\Archipelago\Players\XC3.yaml" "F:\XCAP\work\session\players"
"G:\Archipelago\ArchipelagoGenerate.exe" --player_files_path "F:\XCAP\work\session\players" --outputpath "F:\XCAP\work\session\out"
```

This produces `AP_<seed>.zip` in the output folder, containing the multidata, your `.apxc3` patch file, and a
spoiler log.

## 4. Host

```bash
"G:\Archipelago\ArchipelagoServer.exe" "F:\XCAP\work\session\out\AP_<seed>.zip" --port 38281
```

Leave this running for the whole session. Use a different `--port` if you already have another server running
(e.g. testing XC2 at the same time).

## 5. Patch

**Close Eden first if it's running** — it holds the mod folder open, and patching will fail with "old mod files
in use" otherwise. Then **extract the `.apxc3` file** from the zip and pass it *directly* to the launcher — do
**not** open the "Xenoblade Chronicles 3 Patcher" component on its own from the component list, it will just
error with "Open a patch file (.apxc*) with this component.":

```bash
"G:\Archipelago\ArchipelagoLauncher.exe" "F:\XCAP\work\session\out\AP_<seed>_P2_XC3.apxc3"
```

This takes a minute or two (it loads every installed apworld first, then runs the base randomizer headlessly,
then applies this project's own bridge patches, then installs into Eden's mod folder). No console output means
it's still working — check for the result marker instead of waiting on log text:

```bash
find "F:\XCAP\work\emus\yuzu\user\load\010074F013262000" -iname "ap_patch.json"
```

A fresh timestamp there means it succeeded.

## 6. Launch and start a new game

```bash
"F:\XCAP\work\emus\eden\eden.exe" "F:\XCAP\Xenobalde 3 AP\Xenoblade Chronicles 3 [010074F013262000][v0].nsp"
```

Boot takes a little while (shader compilation, especially on the first launch after a fresh patch). At the
title screen you should see `Randomizer vX.X.X` printed in the corner — that confirms the patch is active.
**Start a New Game, not Continue** — autotracking baselines against whatever save exists, so continuing an old
save makes it look like a burst of checks are already done.

## 7. Connect the client

From the Launcher, open the client **with no arguments** (passing a URL directly to it breaks the
multiprocessing spawn on this build — connect manually instead):

```bash
"G:\Archipelago\ArchipelagoLauncher.exe" "Xenoblade Chronicles 3 Client"
```

In the client window: type `127.0.0.1:38281` (or your port) into the Server field, click **Connect**, then enter
your slot name when prompted. Once connected you'll see confirmation lines for item delivery and autotracking
coverage.

## 8. Play

Useful in-client commands:
- `/autotrack [status|on|off|baseline|send]` — automatic check detection from the emulator.
  - If a lot of checks suddenly appear "held" (more than ~30 at once, e.g. right after connecting to an
    already-progressed save, or after a client restart), that's a safety net, not a bug — `/autotrack send` sends
    them if they're real progress, `/autotrack baseline` discards them and only tracks from that point forward.
- `/deliver [status|on|off|reset]` — applies received items into the game automatically; `reset` if starting a
  new save under the same seed/slot.
- `/check <location>`, `/checkmatch <text>`, `/find <text>`, `/missing`, `/goal` — manual check-sending and
  lookups.

### PopTracker (optional)
Open `G:\Archipelago\poptracker\packs\XC3-AP-Tracker.zip` in PopTracker, then connect it to the same
server/slot via its own Archipelago connector (separate from the game client — both connect independently). The
connector toggle is the small "AP" label in the toolbar: click it once to open/close the connection prompt.

---

## Troubleshooting

- **Eden freezes** (screen stops updating mid-frame, log stops mid-write with no error): close it and relaunch
  with the same command from step 6 — this is a known Eden v0.0.3 stability issue, not specific to the patched
  game. No progress is lost; your save is on disk, not in the emulator's memory.
- **Controls don't respond**: your keyboard won't control the game — Eden reads from your physical gamepad.
- **A quest/chest/shop check didn't send**: check `/autotrack status` first — it may simply be `HELD` (see
  above). If autotracking shows attached and it's still not registering, that specific location may not have
  an automatic detector yet (use `/check` manually). Containers are detected individually (each container is
  its own check, "<place> Container N", with its own save flag).
- **Shop items bought but no check sent**: confirm `shop_checks` isn't set to "Off" in your YAML, and that
  `/deliver status` shows delivery is `on`.
- **Item delivery coverage**: most filler (gems, accessories), Colony Affinity, Hero Access, Outfits, Class
  Access, most Key Items, and Manana's Menu recipes deliver into the game automatically. Collectopaedia Decks,
  Gem Crafting, Progressive Hunting License, Traversal Skills, and Flutes are received/tracked correctly but
  don't yet have a way to apply themselves in-game — check with the project owner for current status.
