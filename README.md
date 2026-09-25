# Xenoblade Chronicles x Archipelago (XC1 Definitive Edition, XC2, XC3)

Three **separate** Archipelago worlds (one apworld, one client, one PopTracker pack per game), built from the community
manual worlds' logic and the games' own data.

| Game | AP game name | apworld | Tracker pack |
|---|---|---|---|
| Xenoblade Chronicles DE | `Xenoblade Chronicles DE` | `custom_worlds/xenoblade_de.apworld` | `poptracker/packs/XC1-DE-AP-Tracker.zip` |
| Xenoblade Chronicles 2 | `Xenoblade Chronicles 2` | `custom_worlds/xenoblade_2.apworld` | `poptracker/packs/XC2-AP-Tracker.zip` |
| Xenoblade Chronicles 3 | `Xenoblade Chronicles 3` | `custom_worlds/xenoblade_3.apworld` | `poptracker/packs/XC3-AP-Tracker.zip` |

## Key items are randomized in all three games
Everything the manual worlds flag as progression is in the multiworld item pool and can land in any player's world:
XC1 area keys / hunting licenses / memory fragments / skill trees / collectopaedia unlocks, XC2 progressive areas / blades /
drivers / field skills / story key items, XC3 area keys / key items / heroes / traversal skills / chapter clears.
Verified by generating a three-game multiworld: XC1 checks hand out XC3 area keys and XC2 blades, and vice versa.

## Layout
```
xc-tools/
  worldgen/      xc_core.py (engine), xc_client.py (client), docgen.py, build_worlds.py  -> out/*.apworld, --install copies them
  trackergen/    common.py (pack builder), lua/xc_logic.lua (logic engine for the trackers), build_xc1|2|3.py
  scripts/       stress_worlds.py, ap_e2e_tracker.py, pt_shot.ps1, carve_xbc1.py, rar5_*.py
  nspextract/    C# (LibHac) NSP -> RomFS extractor (uses Ryujinx's prod.keys)
  xc3_lib/ xbtool/ bdat-toolset.exe   third-party extraction tools (NOT in the git repository - download them from their upstream
                                      projects and put them here; the .gitignore leaves them out, along with worldgen/out/ build output)
```
Not in the repository either: the games' extracted data (the `gen_*.py` generators read BDAT JSON dumps, and `build_worlds.py` the manual
worlds' source data, from local folders whose paths are set at the top of each script, e.g. `J = ...`), and any save files or keys.
`worldgen/detect/*.json` are the generated lookup tables the world build needs.
Rebuild everything:
```
python worldgen/build_worlds.py --install
python trackergen/build_xc1.py ; python trackergen/build_xc2.py ; python trackergen/build_xc3.py
```

## How the worlds work
* Item / location / region tables and every `requires` expression come from the manual worlds; `xc_core.RuleCompiler`
  reproduces Manual's evaluation exactly (`|item:N|`, `|@category:N|`, `{function()}`, AND/OR left-to-right, region rules apply to
  every inbound entrance *and* to the locations inside, trailing missing `)` auto-closed like Manual does).
* Game-specific hooks ported: XC1 `Danger Tolerance`, `Key Leniency`, Collectopaedia rules, game version categories; XC2 Elysium
  Fragment goal and starting-art placements; goal selection for all games.
* **Data bugs found in the manual data and fixed by the converter** (each is reported when building):
  XC3 `Eagus Wilderness Key` (rules need 3, pool had 2 -> whole region unreachable) and `Progressive Dorrick Project Phase`
  (needs 8, pool had 7). The converter also promotes any item used by a rule to progression and checks every referenced item exists.
* `xc_client.py` is the client: `/check`, `/checkmatch`, `/find`, `/missing`, `/goal`, `/die`.

## Verified
* `ArchipelagoGenerate.exe`: 3-game multiworld generates, zero unreachable locations, accessibility satisfied.
  `scripts/stress_worlds.py`: goals x options x seeds per game.
* Client against a real local server: checks route items to the other games' players.
* Trackers in a real PopTracker 0.35.4 with a real server: item + location autotracking, live logic colouring, slot options.

## Trackers and maps
* XC1: the game's own area maps (all floors composited), 407 landmark / location-discovery pins at their real coordinates
  (BDAT `landmarklist` + `FLD_maplist` bounds); other checks are grouped per area next to the map.
* XC2: the game's own area maps; XC2 keeps landmark/chest coordinates in map object files rather than BDAT, so checks are
  grouped per area next to the map.
* XC3: the game's own area maps (stitched from its map tiles); checks are grouped per region next to the map.

## XC3 game data
The XC3 base game was re-supplied intact; the pack now has real stitched in-game area maps (`trackergen/xc3_maps.py`) and the extra
BDAT tables needed for detection are carved into `F:/XCAP/extracted/xc3_bdat2` (`scripts/carve_at.py`).

## Automatic check detection (Ryujinx, Eden)
The clients read the running game's save/flag memory out of the emulator (`worldgen/xc_autotrack.py`, ctypes only, bundled in each
apworld) and send checks as the game sets them.  `/autotrack [status|on|off|baseline|send]`.  Start a **new** game for a new multiworld
(a loaded save far ahead of the multiworld is held until you `/autotrack send` or `/autotrack baseline`).  Supported emulators: Ryujinx and the yuzu family (process names eden / yuzu / citron / sudachi are matched).
Item delivery *into* the game is not implemented (items are shown in the client log and the PopTracker pack).

| Game | Detectable | How | Status |
|---|---|---|---|
| XC2 | 467 / 728 + goal | landmarks/locations = 1-bit flags (FLD_LandmarkPop), heart-to-hearts = 2-bit flags (state 2), goal = GameClearCount | e2e verified (286 checks from a real save) |
| XC3 | 1125 + goal | locations/landmarks/rest spots = 1-bit flag 17720+(GMK_Location row-1), quests = 2-bit FlagPrt >= 2, unique monsters = enemy tombstone defeated (needs a save), **containers = 1-bit flag 6914 + SequentialID (one per container, 346)**, goal = game-clear flag | e2e verified live (Torchlight Hill, Riccalo Pond); container flags verified on 3 live containers + the chapter-5 test save |
| XC1 DE | 0 | not reverse-engineered yet | use `/check` |

Not detectable yet (use `/check`): XC2 story / pouch / blade awakenings / chests; XC3 normal-enemy kills, affinity chart, shops,
bosses, husks.  Tools: `memscan/` (C# scanner), `scripts/flag_watch.py` (live flag-change logger), `scripts/ryu_tools.py`,
`scripts/ap_e2e_autotrack.py`, `worldgen/gen_detect_xc2.py` / `gen_detect_xc3.py` (detector tables in `worldgen/detect/`).

## Patch step (game-data mod) and QoL options
Generation writes a per-player patch file (`.apxc2` / `.apxc3`, a zip holding `patch.json`) into the multiworld zip.  The launcher component
**"<game> Patcher"** (`worldgen/xc_patch.py`) opens it, runs the third-party Series Randomizer headlessly through `rando_bridge/run_randomizer.py`
(system Python with tkinter; option objects driven exactly like the GUI's) and installs the resulting romfs mod into Ryujinx
(`<ryujinx data>/sdcard/atmosphere/contents/<title id>/`, marker `ap_patch.json`).  Settings (randomizer folder, extracted BDAT folder per game,
Ryujinx folder) are asked once and remembered in `Utils.user_path('xenoblade_patcher.json')` (env `XC_PATCHER_SETTINGS` overrides, used by tests).
YAML options `qol_*` map to randomizer options (`worldgen/qol.py`).  XC2 always also applies the `xc2_blade_crystals` bridge patch (see below).
Gotcha: the randomizer's `RareBladeProbabilityEqualizer` (gacha probabilities) hangs the game on its boot loading spinner and is always skipped.

## Item delivery and experience multiplier
`worldgen/xc_deliver.py` applies received items to the running game (`/deliver [status|on|off|reset]`, on by default) and runs the experience
multiplier.  Two kinds of effect: *state* effects are recomputed from the full received-item list every 1.5 s (art caps, trust caps, outfits); *inventory*
effects (crystals, filler) are handed over ONCE, tracked in `DeliveryState` (`Utils.user_path('xenoblade_state')/<game>_<seed>_<slot>.json`;
`/deliver reset` for a new game).  Rules learned from live tests: only write values the game itself would accept (a level of 5 written into Rex's
art table froze the Arts screen), and only ever clamp DOWN.

| Game | Delivered | How |
|---|---|---|
| XC2 | 24 driver-art items | each art's level capped at max(1, copies received); the player still buys levels with WP (live-verified) |
| XC2 | 18 rare blades + 17 extra rare blades | the randomizer's custom core crystals give every rare blade its own crystal (`xc2_blade_crystals` bridge patch; blade -> crystal map in the mod marker); the blade's crystal is added to the inventory (live-verified: "Roc's Core Crystal 1/1" in the Item List). 9 story blades (Pyra, Aegis, Dromarch, Poppi x3, Pandoria, Sever, Dagas) have no crystal: they are the story's to hand out |
| XC2 | blade trust | options `progressive_blade_trust` (default on) and `trust_per_blade`; hearts capped at 1 + copies of `Progressive Blade Trust` (x4) or of `<Blade> Trust` (x4, 43 blades); clamp-only, live-verified. Trust points are also multiplied by the experience multiplier |
| XC2 | filler | 155 accessories (`Accessory: <name>`) and 420 pouch items (`Pouch: <name> x5`, bundles of 5) written into the live item box (live-verified) |
| XC3 | 106 outfit items (`<Class> Outfit - <Char>`) | 2-bit flag from RSC_PcCostumeOpen (0 hidden, 1 unlocked); 10 DLC-class outfits unmapped |
| XC3 | filler | 200 gems (`Gem: <name>`, every level) and 261 accessories written into the live item arrays (live-verified in Items > Most Recent / Accessories) |

Item-box layouts: see `worldgen/xc_inventory.py` (XC2 ItemBox 12-byte entries, `row id - base`; XC3 16-byte entries at live base + 0x7FF68 + save offset,
serial counter at live base + 0xE5B4C).  Test scripts: `scripts/ap_e2e_deliver.py` (arts), `ap_e2e_inv.py` (XC2 crystals/filler), `ap_e2e_trust.py`,
`ap_e2e_inv3.py` (XC3 filler), `ap_e2e_xc3.py` (outfits).

**Experience multiplier** (`experience_multiplier` YAML option, 1-50, both games): the client watches EXP-type counters and, when one rises by d,
adds d*(m-1) more; spending is never touched.  XC2 counters: driver EXP / BattleExp / SP / total SP, every weapon's WP and every blade's trust points; XC3
counters: the live Character objects' exp / bonus_exp and every class's CP (array at the live save struct + 0x113C0, stride 0x3100, class entries at
+0xF8+k*0xC0).  A per-emulator mutex stops a second client from multiplying the same emulator.  Verified live: XC3 with a real fight, both games with
simulated gains through the full client (XC2 not yet with a real fight).

## Story gating (XC2, built, live-verified)
The main story is driven by cutscene triggers (rows of `common_gmk/maNNa_FLD_EventPop.json`: scenario range + `Condition` = FLD_ConditionList id); quest tasks
only *track* progress (gating them does nothing - tested).  `worldgen/gen_gates_xc2.py` turns the 113 narrow story triggers into 116 locked steps (every step
from the Maelstrom on; the Argentum prologue stays open because the manual world's 'Free' region needs no items).  Each locked step is one new key item
(`ITM_PreciousList` 25500+, named `Story Step 007 (Gormott)`), and the bridge patch `xc2_story_gates` adds `FLD_ConditionItem` (player has that item) to the
triggers of the step.  The item `Progressive Story Quest` (x116, replaces the manual world's 18 `Progressive Area`) hands them out in order: the client
(`XC2Deliverer._open_gates`) puts key item n into the inventory when n copies have been received, so the story is played in order as the unlocks are found.
Region rules are rewritten by `build_worlds` (`story_gates_file`): tier k needs `Progressive Story Quest:R_k` (1, 4, 19, 32, ... 116) = the number of locked steps
before the story enters the next known tier.  Option `story_gating` (default on).  Findings: writing new 1-bit flag ids (65000+) into the live save is NOT seen by
the game, but the inventory is; 'loading hangs' were slow loads.  Test helpers: `F:/XCAP/work/bis/run_gate_test.py` (`XC2_GATE_FIRST=1004`, `ALWAYS=1`), `scripts/ap_session.py`.

## Shop checks (XC2 + XC3, both live-verified on Eden)
`worldgen/xc2_shops.py` / `xc3_shops.py`: every item shop / commissary / caravan slot becomes a check (placeholder item named after the multiworld item
behind it, 100 G; buying it is the check).  Option `shop_checks` (default **Per Slot** for both games): Off / Per Shop (one check for buying anything in
the shop; every slot then shows the *same* item) / Per Slot (one check per slot; every slot's label is deduplicated with a counter prefix -
`XCMixin.shop_labels` - so a shop never visibly sells the same name in two slots, which is what "sell different items" needs).  Two safety
rules apply to both games: (1) a slot that a quest reads as a *required purchase* (XC2 `FLD_QuestCollect.ItemID`, XC3 `QST_TaskCollect.TargetID`, plus
XC3's tutorial "Buy a Bronze Temple Guard from Camilla") keeps its vanilla item and is never turned into a placeholder, so that purchase always works;
(2) a handful of shops a quest also *reads the whole stock of* (XC2 Llysiau Greens / Belchett Recycling / Pookapoo, XC3 Wellwell's store) are skipped
entirely.  XC2: 92 shops / 469 slots.  XC3: 38 shops / 240 slots, needs the patcher AND the Skyline loader (Eden; crashes Ryujinx).

## Emulators for XC3 mods (tested 2026-09-21)
**Xenoblade 3 only reads loose BDATs through the randomizer's Skyline plugin (`XC3/Loader`: exefs `subsdk9` + `main.npdm`, `romfs/skyline/plugins/libxcnx_file_loader.nro`).**
| emulator | result |
|---|---|
| Ryujinx 1.3.3 (Ryubing) and 1.1.1376 | crash at boot with the loader (null access in the game's main NSO; svc GetInfo / MapPhysicalMemory failures) |
| yuzu Early Access 4176 (portable) | boots the loader; but the update's ticket key made it crash at start, so it only ever ran the 1.0.0 base game (loader targets 2.2.x) |
| **Eden 0.0.3** (portable, `D:/Emulators/Eden-Windows-v0.0.3-amd64`) | **works**: game 2.2.1 boots, Skyline plugin loads and hooks (`libxcnx_file_loader`), title screen shows `(c) Randomizer v1.2.2` = the mod's text is live |
| Citron / Sudachi | not tested (Eden was enough) |
Eden setup that worked: portable `user` folder next to `eden.exe`; keys (`prod.keys`, `title.keys`) + firmware 22.1 in `user/keys` / `user/nand/system`; game **and update installed with
Eden's own File > Install Files to NAND** (copying the NCAs by hand is not enough: the update NCA needs its ticket imported, otherwise the emulator silently runs the base game);
the mod goes into `user/load/010074F013262000/Archipelago/{exefs,romfs}` (the patcher does that for every folder in the `emulator_dirs` setting).  Keyboard input has to be
mapped by hand in Eden (its default is a gamepad).  No change to Ryujinx was needed.
**Autotracking on Eden (verified live, XC3 prologue):** the process is matched by name; the big 4 GB `MEM_MAPPED` region is only the fragmented backing file, so `XC3Probe.locate`
scans the guest's contiguous views instead (`Memory.view_regions`, address-adjacent readable mapped regions) and skips that region; the live struct there has a zero 16-byte prefix
but a running play time at +0x10 (the pristine template has play time 0); guest pages the game never touched are inaccessible, so `read_view` uses `Memory.read_sparse` (unreadable pages count as
zeros).  The detectors then read the flags correctly (Riccalo Pond / Torchlight Hill / Colony 9 Assembly Square in the prologue), the inventory layout check passes and
`xc3_add_item` wrote an accessory into the running game.  A stale copy of an old save file that sits in Eden's save folder shows up as a second copy - hold it with `/autotrack baseline`.
**End to end on Eden (verified 2026-09-21, local server + XC3 client + the running prologue with the QoL mod installed by the patcher):** the client attached ("1 save copies"), autotracking sent
Torchlight Hill and Riccalo Pond (server: "sent ... (Torchlight Hill)"), and `/send` of an accessory and a gem from the server console arrived in the game's inventory arrays (`Delivery: ... added to the inventory`).
The live struct only exists once the game is past loading - a scan made too early finds only the pristine template.

## Field skills (XC2): logic follows the blades, nothing is locked in game
Memory locking does not work (the game rewrites blade skill levels every frame), so field skills are not items any more: the option `field_skill_logic` (default on)
derives the party's level of each of the 16 field skills from what the player could really field.  Data (`worldgen/xc2_skills.py` -> `detect/xc2_skills.json`, packaged as
`data/skills.json`): `CHR_Bl.FSkill1..3` + `FskillAchivement1..3` -> `FLD_AchievementSet.AchievementID1..5`; every non-empty id is an affinity chart node that raises the skill
by one level and its position 1..5 is the trust heart the ring opens at, so a blade's level at h hearts = non-empty ids among the first h (capped by
`FLD_FieldSkillList.MaxLevel`).  Only the multiworld's rare blades are counted (common blades are random).  `XCMixin.field_level` (xc_core.py): blades received x hearts
from *Progressive Blade Trust* (or the per-blade trust items; hearts = 5 when progressive trust is off, and for Nia (Blade) / Brighid which have no trust item) summed over the
slots of Rex + the two best drivers received (`blade_slots_per_driver`, default 3); Pyra/Mythra share one slot, Poppi a/QT/QT pi share one slot, Dromarch / Poppi / Pandoria / Brighid
need Nia / Tora / Zeke / Morag in the party.  Requirements like `|Fire Mastery:5|` in the manual rules read this level.  Trust items and the 17 extra rare blades became progression
items for that reason; the 16 skill items are only in the pool with `field_skill_logic: false`.  The PopTracker Lua evaluator mirrors it (`xc_logic.lua`, cross-checked against
Python by `scripts/check_skill_logic.py`).  Assumptions: any equipped-blade combination can be re-arranged between checks; the affinity tasks of a chart node are doable.

## Removed XC2 checks
'Clear Chapter N' / 'Complete chapter N' and every boss 'Defeat ...' / '... Defeated' location (53) are dropped from the world (`drop_location_regex` in `build_worlds.py`)
until the client can detect them; the two goal events (Clear Chapter 5 / 10) stay.

## Manual checks (both games, default off): every location in the pool sends its own check
Every location that the client cannot detect on its own (no memory detector in `detect/xc{2,3}.json`, and not a shop, which is detected by watching the
placeholder appear/disappear in the item box) is moved into a `Manual Check` category that is *disabled by default* (`manual_checks_option` in
`build_worlds.py`, option `manual_checks`, default off).  So out of the box the location pool only ever contains checks the running client actually
sends by itself: XC2 1028 of 1236 non-shop/-goal locations, XC3 1057 of 1852.  Turning `manual_checks` on adds the rest back in (sent by hand with the
client's `/check <name>` / `/checkmatch <text>`) for players who want the larger, more manual location pool.

## XC3 story gating (built, patch-verified; same design as XC2, mirrored to XC3's data)
XC3's cutscene triggers are `map/<map>_GMK_Event.json` rows whose `Condition` resolves (through `fld/FLD_ConditionList`, `ConditionType` 2) to a
`fld/FLD_ConditionScenario` range - the equivalent of XC2's EventPop rows, just one indirection deeper.  `worldgen/gen_gates_xc3.py` turns the 23 distinct
scenario values found this way (37 triggers, chapters 1-7) into locked "Story Step" beats exactly like `gen_gates_xc2.py`; a single `Progressive Story
Quest` item (x23) hands the beats out one at a time.  **`FLD_ConditionList` is not a table of arbitrary-id links**: unlike XC2's 8-inline-slot row,
XC3 stores one clause per row and `NextPremise` only ever holds 0 (end), 1 (AND with the row at the *next* `$id`) or 2 (OR with it) - a chain is a run of
consecutive ids, not a pointer.  So the bridge patch (`xc3_story_gates`) cannot "insert" a clause into the middle of an existing chain; instead it copies
the trigger's whole original chain to fresh consecutive ids right after a new item-clause, and only repoints the trigger's own `Condition` field.  (An
earlier version wrote the original condition's row id straight into `NextPremise`, which is not a valid value there - `bdat-toolset` rejected the pack
with "invalid value: integer `<id>`, expected u8"; this is what the fix above corrects.)  Option `story_gating` (default on).  Coverage is sparser than
XC2's 116 beats because far fewer of XC3's story scenes are gated through map-placed triggers (many appear to run through internal quest/event chains
instead, which were out of scope for this pass) - confirmed live: the patched mod boots to the title screen on Eden without error after this change.

## XC3 hero randomization (built, patch-verified)
Every Hero's `MNU_HeroDictionary.WakeupCondition` is a `FLD_ConditionList` row; `worldgen/gen_heroes_xc3.py` cross-references each Hero's recruit-quest
title (`WakeupQuest` -> `QST_List.QuestTitle` -> quest text) against the location names the manual world's own `requires` already gate behind that
Hero's item (e.g. item "Zeon" gates location "Reasons to Evolve", which is also `PC_ZEON`'s recruit quest title) to find out which PcID each of the
manual world's 21 "Hero Access" items unlocks - only pairs confirmed this way are used (14 of 21; the rest are crossover guests with no in-game gate, or
have an untitled/hidden recruit quest, so are left on their original behaviour).  The bridge patch (`xc3_hero_access`) overwrites the Hero's condition
row in place with a plain item check (drops the original quest/scenario prerequisite entirely), so receiving the item lets the Hero be recruited as soon
as they are found, wherever that is in the run.  Option `hero_randomization` (default on).

## Progressive region affinity (both games)
XC3 has a real per-colony affinity gauge (`FLD_ColonyList`, a 16-bit point flag per colony, 5 level thresholds); `xc3_extras.py` adds one
`Progressive Affinity: <colony>` item per colony (x4; 15 colonies) and the client holds the live point flag below the next level's threshold until
enough copies have arrived (`XC3Deliverer._cap_affinity`).  Option `progressive_colony_affinity` (default on).  XC2 has no separate per-region affinity
system (its regional NPC-relationship content is driven by blade trust, not an area gauge), so `Progressive Blade Trust` (already built, see below)
is the equivalent there.

## Still open (design notes)
* **XC3 class levels** progressive: class-rank writes had no UI effect so far.  Not built.
* XC2 story checks ('Clear Chapter N', boss defeats, 'Talk to ...') have no auto-detection yet.
* **Chest / landmark map pins**: XC2's BDAT tables carry no world-space coordinates for chests or landmarks (`FLD_TboxPop` / `FLD_MapObjPop` hold
  visibility radii and resource ids only), so the XC2 tracker groups every check into a labelled panel next to its area map (`trackergen/common.py`).
  XC3 does have them: `prg/SYS_GimmickLocation` lists every placed gimmick (containers, landmarks, enemies, ...) with MapID and world X/Y/Z, and its
  containers link to `GMK_TreasureBox` (contents) by GimmickID.  The XC3 world uses this: **each of the 346 containers is its own check**
  ("<place> Container N", `worldgen/gen_container_locations_xc3.py`), detected by its own 1-bit save flag (6914 + SequentialID), placed in logic by
  the region of the place it is in and (with Container Gating) by its Progressive Container Access batch, and pinned on the tracker at its real position
  (`scripts/xc3_world_register.py` registers world coordinates onto the map images: Gamer Guides native px = 2 x world + offset).
* XC1 is out of scope (stopped by the user).
