# Handoff: XC3 Open World + client fixes (cloud session, 2026-09-25 → 26)

This is for a local (desktop) Claude continuing this work. It covers what changed, where things stand, what's
untested, and the traps we hit. The code is the source of truth. This explains why it looks the way it does.

Repo: `SsL2727/XC3`. The worlds are built by `worldgen/build_worlds.py`, which turns the third-party "Manual" apworlds
into native AP worlds and packages them as `.apworld` files.

## Current state

| PR | What | State |
|----|------|-------|
| #1–#5 | XC3 client: burst-delivery crash, write throttling, writes restricted to validated save copies, `/autotrack send` fix, per-check autotrack confirmation | merged, user-confirmed working |
| #6 / #7 | `XCData(__name__)` "fix" (it broke all three worlds) and its revert | merged. **Do not reintroduce** — `__name__` is correct |
| #8–#11 | Open World v1: region gating, Origin Shard, Questsanity, live story-flag forcing | merged. The live forcing is **replaced by #12** |
| **#12** | **Open World v2: start from a prepared late-game save** (branch `feature/xc3-open-world-save`) | **open, NOT tested in-game** |

- Commit `ad85a07` (per-session bookkeeping fix, branch `fix/story-beat-shared-flags`) was never merged. It doesn't
  matter: #12 deletes the code it fixed.
- The user merges PRs within seconds of creation. Anything pushed to a branch after that is orphaned and needs a new
  PR. Check PR state before pushing more commits to an existing branch.

**The immediate next step:** the user tests #12's build in Eden:
1. Patch with `open_world: true`.
2. Load save slot 1.
3. Confirm the game loads at the end of chapter 7.
4. Confirm landmarks, chests and unique monsters send as checks.
5. Confirm beating the final boss fires the goal.

## Open World v2: how it works (PR #12)

The user's design:
- The game is fully unlocked. Only the final boss remains, and every colony is at its final state.
- Honor-system "Progressive Region" and "Origin Shard" items are logic-only. They gate, in order: Aetia → Fornis →
  Pentelas → Keves Castle → Cadensia → Agnus Castle → Swordmarch/City, then Origin via shards.

Implementation:
- `worldgen/detect/xc3_open_world_base.sav.gz`: a 100% save (game v1.3.0, save format v9, DLC Wave 3). Scenario is
  1537 (`FEV07_330_010`), with only the final battle left. Colony affinity is already 8000 everywhere, which is max.
- `worldgen/xc3_open_world_save.py` → `build()` resets every check the client detects (`detect/xc3.json`):
  - landmark/location 1-bit flags (489)
  - containers (346)
  - unique-monster tombstones (100), via byte `0x183000 + i*20 + 3`
  - `game_clear` (1-bit 6879), because the goal detector waits for it to **rise**
  - The landmark and secret counters (16-bit 1945 / 1944) are recomputed from what's still unlocked, using
    `detect/xc3_location_categories.json`.
  - It keeps `HOME_LOCATION` = "Colony 9 Assembly Square" unlocked (a real fast-travel point with a `MapJumpID`),
    so the save isn't left with nowhere to fast travel.
  - Quests are left as done.
  - Verified offline: 227 bytes change, all inside the flag and tombstone regions.
- `build_worlds.py`, for xenoblade_3:
  - writes `data/open_world.sav` and `data/open_world.tmb` into the package
  - category `quests` gets `yaml_option ["questsanity", "!open_world"]`
  - new category `Open World Start` (`["!open_world"]`) tags the home landmark, removing its check when Open World
    is on
- `xc_patch.py`, when `open_world` is on:
  - skips the `xc3_story_gates` patch
  - `_install_open_world_save()` writes `bf3game01.sav` and `.tmb` into
    `<eden user>/nand/user/save/<zeros>/<profile>/010074F013262000/`
  - backs up the existing folder to `…_backup_<timestamp>` first
  - writes a marker `ap_open_world.json` (seed_name + player) so re-patching the same seed never overwrites the slot
  - installs into the `xc3_save_dir` setting (default `DEFAULT_XC3_SAVE_DIR`, the user's Eden folder
    `F:\XCAP\work\emus\eden\user\nand\user\save\0000000000000000\F2DF0042DCA2C1FAFDC05D1CE5065C54\010074F013262000`)
    if that folder exists, else searches the yuzu-family emulator dirs; on Ryujinx it just logs a note
- `xc_deliver.py`: when Open World is on, skips `_open_gates`, `_cap_story` and `_cap_affinity`, which would drag the
  finished story and maxed colonies back down. The v1 live writes (`_story_complete_once`, `_max_affinity_once`) are
  **deleted**.

The region/Origin gating from v1 is unchanged: requires strings in `normalize()`, `pool_hook`, `checkOriginShard`.

### Known caveats (tell the user, test for)

- **DLC:** the save came from a DLC Wave 3 playthrough and may not load without the DLC.
- **Level/gear:** the save is end-game level and gear. Only checks were reset.
- **Spawn map:** it loads in map `ma64a`. That's unverified to be the final area. You leave by fast travelling to
  Colony 9.
- **Save version:** the save is format v9. Recordkeeper targets v10. Only the flag and tombstone regions are edited,
  and they read correctly, but nothing else in the struct should be assumed to be at v10 offsets.
- **Extra files:** the marker file and backup folder sit next to the game's saves. Eden probably ignores them.
  Untested.

## Verified facts (reuse these; don't re-derive)

**Save layout**, per [roccodev/recordkeeper](https://github.com/roccodev/recordkeeper) `lib/src/save/`:
- raw struct, magic `6A FA 68 B3`, no checksum or compression
- the save file offsets are the same as the live struct the client reads (`base` in `xc_autotrack` / `xc_deliver`)
- flags start at `0x710`:
  - 1-bit: `0x710`
  - 2-bit: `0x2710`
  - 4-bit: `0x6710`
  - 8-bit: `0x7710`
  - 16-bit: `0x9710`
  - 32-bit: `0xAF10`
  - indices are 0-based
- tombstones: `0x183000`, stride 20

**Key flags** (recordkeeper `app-builder/res/flags.json`):
- scenario = 16-bit #1 (offset `0x9712`)
- `game_clear` = 1-bit 6879
- `new_game_plus` = 1-bit 23894
- location base = 1-bit 17720. Flag = 17720 + (`GMK_Location` row `$id` − 1). Row ids are global across maps
  (ma01a 1–74, ma04a 201–…).
- `landmark_count` = 16-bit 1945, `secret_count` = 16-bit 1944
- colony affinity = 16-bit 1913–1927. `SYS_NewGamePlusFlag`'s `F16_RESPECT` range confirms it.

**Other game data:**
- **Story progress:** everything keys off the scenario counter. `SYS_ScenarioFlag` lists the 573 steps, ids 1001–1573.
  `GMK_FieldLock` (87 rows, in the `map` bdat) are temporary walls active only during narrow scenario windows, not
  long-term region gates.
- **Why v1 failed:** 29 of the 141 "story beat" flags in `detect/xc3_story_gates2.json` are shared/reused slots. Their
  `FLD_ConditionFlag` columns `A8D0C912` / `DA6D358F` are `(0,0)`; dedicated flags are `(1,1)` or `(2,2)`. That
  plus flag-id reuse across chapters is why forcing flags live corrupted quests. The `"dedicated"` field is still in
  three data files (`xc3_story_gates2.json`, `xc3_deliver.json`, and `xc3_extras.json`'s `deliver`). Nothing reads
  it since #12.
- **BDAT tooling:** tables are named by MurmurHash3_x86_32, seed 0 (test vector `"FLD_EnemyData"` → `0x2521C473`).
  Python reader: `Sir-Teatei-Moonlight/xenoblade-bdat-tools` (`bdat2_splitter.py`, `bdat2_reader.py`). The user also
  has bdat-toolset JSON dumps. The `map` tables (`<map>_GMK_*`) come from the `map`/`sys` bdats, not `fld`.

## Traps we hit

- **The story beat list is cached in three files:** `detect/xc3_story_gates2.json`, `detect/xc3_deliver.json`, and
  `detect/xc3_extras.json`'s `deliver` dict. `write_package()` merges extras **over** deliver. An edit to one copy
  can be silently discarded. Always verify by inspecting the built `.apworld` zip, not the source.
- **Line endings are mixed** (e.g. `xc_deliver.py`, `build_worlds.py` and the detect JSONs use CRLF). Python
  text-mode rewrites silently convert them to LF and produce a whole-file diff. Preserve CRLF: open with
  `newline=''`.
- **`DeliveryState` (`state.given`) is persisted per seed+slot**, not per save. It's right for "item already
  delivered" and wrong for "this save already fixed up".
- **Multi-base writes:** `xc3_layout_ok` only validates inventory arrays. Write non-inventory regions to
  `ok_bases[0]` only. Writing all bases corrupted a live save and instantly "completed" the game.
- **Cloud-only annoyance:** the stop hook repeatedly claimed branches were unpushed. Every time,
  `git ls-remote` showed them pushed. It's caused by a narrow fetch refspec in the cloud checkout. Not a real issue.
- **False-positive checks on a fresh save:** the user's working workaround is `/autotrack baseline` right after
  connecting. Not root-caused.

## Building locally

The desktop machine has the real paths in `build_worlds.py` (`MANUAL_APWORLDS` → `F:\XCAP\...`,
`CUSTOM_WORLDS` → `G:\Archipelago\custom_worlds`).
- Build: `python worldgen/build_worlds.py --only xenoblade_3`
- Build and install: add `--install`

The cloud session built by pointing `MANUAL_APWORLDS["xenoblade_3"]` at the uploaded
`manual_xenobladechronicles3_xanderoni.apworld`.

## User preferences

- Always rebuild and send the `.apworld` after every code change, without being asked.
- Accuracy over helpfulness. Flag uncertainty. Don't guess offsets or behavior. Verify against data or ask.
- Uses Eden (Ryujinx crashes with XC3's Skyline loader).
- Explicitly dropped: the "Vale Trust (XC2)" cross-game item leak. Don't revisit unless asked.
