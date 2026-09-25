# Xenoblade Chronicles 2 — Archipelago Setup Guide

Complete step-by-step guide for setting up and playing an Archipelago multiworld with Xenoblade Chronicles 2,
on this machine's existing install. XC2 runs on **Ryujinx**, always with an isolated root — never point it at a
real/shared profile.

For XC3, see [SETUP_XC3.md](SETUP_XC3.md) instead (it runs on a different emulator, Eden). For the technical/developer
reference (how the world is built, data formats, etc.), see [README.md](README.md).

---

## Key facts you need before starting

| What | Value |
|---|---|
| Emulator | Ryujinx, at `D:\Emulators\ryujinx-1.3.3-win_x64\publish\Ryujinx.exe` |
| Isolated root | `F:\XCAP\work\ryu_root` — **always launch with `-r` pointed here**, never bare |
| Base game file | `F:\XCAP\Xenoblade 2 AP\Xenoblade Chronicles 2[0100E95004038000][US][v0].nsp` |
| Mod install location | `F:\XCAP\work\ryu_root\sdcard\atmosphere\contents\0100E95004039001\` (this is the *runtime* title id the mod system targets — not the base package id `...038000` you see in Ryujinx's own game list) |
| Controls | Your physical gamepad only — the in-game controls are **not** bound to keyboard |

**A `.apworld` file is not a patch file.** `custom_worlds\xenoblade_2.apworld` is the *world definition*
(what the generator and the tracker use) — you never open it directly. The actual per-seed patch is the
`.apxc2` file bundled inside your generated multiworld zip.

---

## 1. One-time setup (already done on this machine, listed for reference)

- Archipelago portable install at `G:\Archipelago\` (`ArchipelagoGenerate.exe`, `ArchipelagoServer.exe`,
  `ArchipelagoLauncher.exe`, `custom_worlds\xenoblade_2.apworld`).
- Xenoblade Series Randomizer extracted at `F:\XCAP\work\randomizer\Xenoblade-Series-Randomizer-1.4.2`.
- XC2's unpacked BDAT at `F:\XCAP\work\rb\xc2_bdat`.
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
python build_worlds.py --only xenoblade_2 --install
```

---

## 2. Write your player YAML

One YAML per player, e.g. `Players\XC2.yaml`. Options worth knowing (all in the apworld's own generated docs too):

- **`story_gating`** (default on): the main story is locked behind `Progressive Story Quest` items, received in
  order — a real, hard-enforced lock (the game's own cutscene triggers refuse to fire without the item).
- **`field_skill_logic`** (default on): field skill checks (Fire Mastery, Lockpicking, Cooking...) are gated by
  what your received rare blades can actually give, at their unlocked trust hearts.
- **`progressive_blade_trust`** (default on) / **`trust_per_blade`** (default off): trust hearts capped until
  Trust items arrive, either shared across all blades or per-blade.
- **`shop_checks`** (default "Per Slot"): shop items become checks.
- **`manual_checks`** (default off): include checks the client can't auto-detect (send with `/check` by hand).

## 3. Generate

Keep your YAMLs in an isolated folder — a big shared `Players\` folder with unrelated broken worlds in it can
fail generation on something that has nothing to do with you.

```bash
mkdir -p "F:\XCAP\work\session\players" "F:\XCAP\work\session\out"
cp "G:\Archipelago\Players\XC2.yaml" "F:\XCAP\work\session\players"
"G:\Archipelago\ArchipelagoGenerate.exe" --player_files_path "F:\XCAP\work\session\players" --outputpath "F:\XCAP\work\session\out"
```

This produces `AP_<seed>.zip` in the output folder, containing the multidata, your `.apxc2` patch file, and a
spoiler log.

## 4. Host

```bash
"G:\Archipelago\ArchipelagoServer.exe" "F:\XCAP\work\session\out\AP_<seed>.zip" --port 38281
```

Leave this running for the whole session. Use a different `--port` if you already have another server running
(e.g. testing XC3 at the same time).

## 5. Patch

**Extract the `.apxc2` file** from the zip first, then pass it *directly* to the launcher — do **not** open the
"Xenoblade Chronicles 2 Patcher" component on its own from the component list, it will just error with
"Open a patch file (.apxc*) with this component.":

```bash
"G:\Archipelago\ArchipelagoLauncher.exe" "F:\XCAP\work\session\out\AP_<seed>_P1_XC2.apxc2"
```

This takes a minute or two (it loads every installed apworld first, then runs the base randomizer headlessly,
then applies this project's own bridge patches, then installs into the Ryujinx isolated root). No console output
means it's still working — check for the result marker instead of waiting on log text:

```bash
find "F:\XCAP\work\ryu_root\sdcard\atmosphere\contents\0100E95004039001" -iname "ap_patch.json"
```

A fresh timestamp there means it succeeded. If it fails with "old mod files in use," **close Ryujinx first** (it
holds the mod folder open while running) and retry.

## 6. Launch and start a new game

```bash
"D:\Emulators\ryujinx-1.3.3-win_x64\publish\Ryujinx.exe" -r "F:\XCAP\work\ryu_root" "F:\XCAP\Xenoblade 2 AP\Xenoblade Chronicles 2[0100E95004038000][US][v0].nsp"
```

Boot takes a little while (shader compilation on first launch especially). At the title screen you should see
`Randomizer vX.X.X` printed in the corner — that confirms the patch is active. **Start a New Game, not
Continue** — autotracking baselines against whatever save exists, so continuing an old save makes it look like a
burst of checks are already done.

## 7. Connect the client

From the Launcher, open the client **with no arguments** (passing a URL directly to it breaks the
multiprocessing spawn on this build — connect manually instead):

```bash
"G:\Archipelago\ArchipelagoLauncher.exe" "Xenoblade Chronicles 2 Client"
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
Open `G:\Archipelago\poptracker\packs\XC2-AP-Tracker.zip` in PopTracker, then connect it to the same
server/slot via its own Archipelago connector (separate from the game client — both connect independently). The
connector toggle is the small "AP" label in the toolbar: click it once to open/close the connection prompt.

---

## Troubleshooting

- **Ryujinx crashes or freezes**: close it (only the instance you launched — never touch a real/shared
  Ryujinx profile) and relaunch with the same command from step 6. Known causes seen this project: the
  randomizer's "Tutorial Skips" QoL option conflicting with the native cutscene-skip button, and possible
  GPU/resource contention if another emulator is also running.
- **Controls don't respond**: your keyboard won't control the game — Ryujinx reads from your physical gamepad.
- **A quest/chest/shop check didn't send**: check `/autotrack status` first — it may simply be `HELD` (see
  above). If autotracking shows attached and it's still not registering, that specific location may not have
  an automatic detector yet (use `/check` manually) — see the detection coverage note in README.md.
- **Shop items bought but no check sent**: confirm `shop_checks` isn't set to "Off" in your YAML, and that
  `/deliver status` shows delivery is `on`.
