# Xenoblade Chronicles 3 — Remote/archipelago.gg Setup Guide

For a multiworld where the **host** (this machine, or whoever generates the seed) and a **player** are on different
computers, and the game is hosted on the official [archipelago.gg](https://archipelago.gg) website instead of a
local server. Two roles below — do the Host section once per seed, the Player section once per remote computer.

For a fully-local setup (everyone on one machine, one local server), use [SETUP_XC3.md](SETUP_XC3.md) instead.

---

## Host: generate and put the seed online

1. Generate the multiworld exactly as in [SETUP_XC3.md](SETUP_XC3.md) steps 2–3 (write YAMLs for every player,
   including the remote one, then run `ArchipelagoGenerate.exe`). This produces `AP_<seed>.zip`.
2. Go to **[archipelago.gg/uploads](https://archipelago.gg/uploads)** ("Host Game") and upload that zip directly —
   do **not** run `ArchipelagoServer.exe` locally for this. The site hosts the server for you (no port forwarding
   needed) and gives you a room page with:
   - The server address to connect to, e.g. `archipelago.gg:PORT`.
   - A **download link for every player's own patch file** (their `.apxc3`/`.apxc2`), so you don't have to extract
     and send those by hand — just send each player the room link.
   - A live tracker.
3. Share the room link with the remote player. **Also send them the apworld file itself**,
   `G:\Archipelago\custom_worlds\xenoblade_3.apworld` — archipelago.gg only hosts the seed data, not custom worlds,
   so their own Archipelago install needs this file before the client will even exist for them (see Player step 2).
4. Keep hosting your own side (XC3 or whichever game you're playing) exactly as normal — [SETUP_XC3.md](SETUP_XC3.md)
   steps 5–8, just pointing the client at `archipelago.gg:PORT` instead of `127.0.0.1:38281` in step 7.

---

## Player (remote computer): one-time setup

This mirrors [SETUP_XC3.md](SETUP_XC3.md)'s "One-time setup" section, just done fresh on their own machine — the
patcher runs the base randomizer locally on whichever computer is patching, so all of this has to exist there too,
not just on the host's machine.

1. **Eden emulator** — install a copy (any recent build; portable, doesn't need to match the host's install path).
2. **Their own legally-dumped copy of Xenoblade Chronicles 3** (`.nsp`) and Switch `prod.keys` for Eden — the host
   cannot legally provide these; the player needs their own.
3. **A system Python 3 with tkinter** on PATH (the patcher runs the base randomizer as a local Python script).
4. **The Xenoblade Series Randomizer tool** (the same release version the host used, e.g. 1.4.2) extracted
   somewhere on their machine.
5. **Extracted XC3 BDAT data** — the randomizer needs the game's own data tables unpacked to a folder first; if the
   player doesn't already know how to do this, ask the host how they extracted theirs (`F:\XCAP\extracted\xc3_rando_bdat`
   on this machine) — the same tool/process needs to run once against the player's own dump.
6. **A portable Archipelago install** (`ArchipelagoLauncher.exe`, `ArchipelagoGenerate.exe`, etc. — the
   [Archipelago releases page](https://github.com/ArchipelagoMW/Archipelago/releases) has the portable Windows build)
   with the **`xenoblade_3.apworld` from the host** dropped into its `custom_worlds\` folder. Without this file, the
   "Xenoblade Chronicles 3 Client" and "Xenoblade Chronicles 3 Patcher" components won't exist in their Launcher at
   all — the apworld is what defines them.
7. The first time the patcher runs it will ask for the paths from steps 3–5 (Python, randomizer folder, BDAT
   folder, and their emulator's `user` folder) and remember them in `xenoblade_patcher.json` next to their
   `ArchipelagoLauncher.exe`, same as this machine's copy.

## Player: get in and play

1. From the room link the host sent, download **your own** patch file (not anyone else's — each slot gets a
   different one).
2. **Close Eden first if it's running**, then patch, exactly like [SETUP_XC3.md](SETUP_XC3.md) step 5:
   ```bash
   ArchipelagoLauncher.exe "<your downloaded file>.apxc3"
   ```
   This takes a minute or two on first run (it also needs to run the base randomizer + bridge patches locally, same
   as the host's machine). No console output doesn't mean it's stuck — check for the result marker under your own
   Eden's mod folder (`user\load\010074F013262000\` under wherever your Eden points its data at), looking for a
   fresh `ap_patch.json`.
3. Launch Eden with the base NSP and **start a New Game** (not Continue) — same reasoning as the local guide:
   autotracking baselines against whatever save exists.
4. Open the client bare (no arguments, same multiprocessing-spawn caveat as local):
   ```bash
   ArchipelagoLauncher.exe "Xenoblade Chronicles 3 Client"
   ```
   In the Server field type `archipelago.gg:PORT` (the address from the room the host sent — **not** `127.0.0.1`,
   that only works on the host's own machine), click Connect, then enter your slot name.
5. Play — see [SETUP_XC3.md](SETUP_XC3.md) step 8 for in-client commands (`/autotrack`, `/deliver`, `/check`, ...).
   Optional: the PopTracker pack (`XC2/XC3-AP-Tracker.zip` or the `-AutoOnly` variant, ask the host for a copy)
   works the same way, connecting to `archipelago.gg:PORT` from its own AP connector.

---

## Troubleshooting

- **"Open a patch file (.apxc*) with this component"**: the Patcher component was opened bare from the component
  list instead of with the downloaded `.apxc3` file — pass the file directly to `ArchipelagoLauncher.exe`, same
  as local ([SETUP_XC3.md](SETUP_XC3.md) has more on this).
- **Client won't connect / times out**: double check the room's server address and port exactly as shown on the
  archipelago.gg room page (it can differ from the default `38281` used for local hosting), and that the room is
  still open (rooms on the site eventually expire if idle).
- **Everything else** (Eden freezes, controls don't respond, a check doesn't send, shop items not registering,
  item delivery coverage) is identical to the local setup — see [SETUP_XC3.md](SETUP_XC3.md)'s own Troubleshooting
  section, it isn't specific to hosting remotely.
