"""Player-facing documentation bundled into each apworld (counts are computed from the actual data)."""

GAME_NOTES = {
    "xenoblade_de": {
        "keys": ("Every **area key** (one per region, some regions need several copies), **Progressive Hunting Licenses**, "
                 "**Memory Fragments**, the **Colony 6 reconstruction levels**, character **skill trees / affinity ranks**, Art Books "
                 "(with *Artsanity*) and the **Collectopaedia category unlocks** are shuffled through the multiworld."),
        "flow": ("The world starts in Colony 9. Leaving an area needs that area's key (and, for the story-locked ones, enough Hunting "
                 "Licenses / Memory Fragments). Enemy levels gate checks through the *Danger Tolerance* option: at 0 a check is in logic "
                 "only once you can reach an area whose enemies are about that level."),
    },
    "xenoblade_2": {
        "keys": ("**Progressive Area** unlocks, every **Blade and Driver**, all **field skills** (with their levels), the story key items "
                 "(Level 2 Access Key, Roc's Core Crystal, Keycode, ...) and character info items are shuffled through the multiworld."),
        "flow": ("Each chapter's region needs the matching number of *Progressive Area* items plus the drivers, blades and field skills "
                 "the story would normally hand you. Three goals exist: clear Chapter 5, collect Elysium Fragments, or clear Chapter 10."),
    },
    "xenoblade_3": {
        "keys": ("Every **area key** (several copies for later regions), the game's **key items** (gate keys, quest items, ...), "
                 "**Hero access**, **traversal skills** (Wall Climbing, Rope Sliding, Scree Walking, Hazard Neutralizer), **chapter clears**, "
                 "**gem crafting**, **Collectopaedia decks** and **Manana's menu** unlocks are shuffled through the multiworld."),
        "flow": ("You start on the Everblight Plain; every further region needs its key(s) and, for some, a traversal skill or hero. "
                 "The goal is the final region (Origin) with all Shards of Origin and Origin Metal."),
    },
}


def game_doc(pkg: str, cfg: dict, bundle: dict) -> str:
    notes = GAME_NOTES[pkg]
    prog = [i for i in bundle["items"] if i.get("progression") or i.get("progression_skip_balancing")]
    prog_copies = sum(i["count"] for i in prog)
    locs = [l for l in bundle["locations"] if not l.get("victory")]
    goals = [l["name"] for l in bundle["locations"] if l.get("victory")]
    cats = {}
    for l in locs:
        for c in l["category"]:
            cats[c] = cats.get(c, 0) + 1
    top = sorted(cats.items(), key=lambda kv: -kv[1])[:10]
    out = [f"# {cfg['title']}", "", "## What is randomized", "", notes["keys"], "",
           f"* **{len(prog)} kinds of progression items ({prog_copies} copies)** are placed anywhere in the multiworld, so a key item can be "
           "sitting in any player's world and any of your checks can hold another player's key item.",
           f"* **{len(locs)} location checks** in {len(bundle['regions'])} regions (largest groups: "
           + ", ".join(f"{c} {n}" for c, n in top) + ").", "",
           "## How the game flows", "", notes["flow"], "", "## Goals", ""]
    out += [f"* {g}" for g in goals]
    out += ["", "## Location checks", "",
            "A check is sent when you complete the in-game thing it is named after (kill the unique monster, finish the quest, "
            "discover the landmark, ...). Use the Archipelago client for this game (`/check`, `/checkmatch`, see the setup guide) and the "
            "matching PopTracker pack to see what is currently in logic. Items you receive are listed by the client immediately.", "",
            "## DeathLink", ""]
    out.append("Optional. `/die` in the client sends one; an incoming DeathLink is announced in the client log."
               if cfg["death_link"] else "Not available in this game.")
    out += ["", "## Logic notes", "",
            "The logic is ported from the community manual world for this game; see the repository README for the data fixes that were needed.", ""]
    return "\n".join(out)


def setup_doc(pkg: str, cfg: dict) -> str:
    title = cfg["title"]
    return f"""# {title} - setup guide

## Requirements
* Archipelago 0.6.x with this `.apworld` in `custom_worlds/` (it registers the game **{cfg['game']}**).
* The game itself (Nintendo Switch / emulator) - it is played normally; the multiworld is driven by the client below.

## Options
Create a YAML with the *Generate Template Options* button of the launcher (or use the Options Creator). Every location group can be
switched off; `filler_traps` controls how much of the filler is replaced by trap items; `experience_multiplier` (XC2 / XC3, 1-50) speeds
the game up by multiplying experience-type gains.

## Patching the game (XC2 / XC3)
Generation adds a small patch file next to the multiworld (`.apxc2` / `.apxc3`). Open it with the launcher's **{title} Patcher** (or run
`ArchipelagoLauncher.exe "{title} Patcher"` and pick the file). The first time it asks for the folder of the extracted Xenoblade Series
Randomizer, the folder with your game's extracted BDAT files and your emulator data folder (the Ryujinx data folder, or the `user` folder of
Eden / yuzu / Citron / Sudachi); it then builds the game-data mod (QoL options from your YAML, and for Xenoblade 2 one core crystal per
rare blade so every blade can be sent as its own item) and installs it. Start a **new** game afterwards. Patch again for every new multiworld.
Settings live in `xenoblade_patcher.json` (`ryujinx_dir`, and a list `emulator_dirs` for yuzu-family emulators; both can be set).

With **Story Gating** (default on, both games) every main story step is locked behind a key item ("Story Step 007 (Gormott)" / "Story Step 012 (Chapter
5)"): the client hands them out one by one as you receive *Progressive Story Quest* items, so the story is played in order as the unlocks are found.
With **Shop Checks** (default: per slot, both games) every shop slot is its own check: it costs 100 G, is named after the multiworld item it holds
(every slot in a shop shows a different item), and buying it sends the check; purchases a quest needs you to make stay on their vanilla item. XC3 only:
**Hero Randomization** (default on) lets every wired-up Hero be recruited the moment you find them, no story wait. **Manual Checks** (default off, both
games) adds back the checks the client cannot send by itself (sent by hand with `/check`); off, the location pool only ever holds checks the client
sends automatically.
Xenoblade 3 game-data mods (QoL options, shop checks, story gating, hero randomization) need the randomizer's Skyline loader. **Ryujinx crashes with it**, so XC3 mods need
**Eden** (tested: 0.0.3 with the 2.2.1 update installed through Eden's own "Install Files to NAND") or another yuzu-family emulator, or a real Switch
(`"xc3_loader": true`). Keep the emulator's `user` folder in `emulator_dirs`: the patcher installs the mod into `user/load/<title id>/Archipelago`.

## Playing
1. Generate the multiworld and host it (or upload it).
2. Open the launcher and start **{title} Client**, or run
   `ArchipelagoLauncher.exe "{title} Client" -- --connect host:port --name YourSlot`.
3. Play the game (start a **new** game for a new multiworld). On Ryujinx and Eden the client reads the running game's memory and sends most checks
   by itself (`/autotrack` shows its state; `/autotrack baseline` ignores what a loaded save already has). `/deliver` shows the in-game
   item delivery (XC2: driver art level caps, blade core crystals, accessory / pouch-item filler; XC3: outfits; `/deliver reset` forgets
   what was already handed over, e.g. for a new game), and the `experience_multiplier` option multiplies EXP-type gains while you
   play. Checks the client cannot detect yet are sent by hand:
   * `/check <name>` - exact name, unique part of a name, or a fuzzy match (it lists close matches when ambiguous)
   * `/checkmatch <text>` - send every missing check whose name contains the text (e.g. everything in an area you just cleared)
   * `/find <text>`, `/missing [region]` - see what is still open
   * `/goal` - report that you finished the game
4. Received items show up in the client log; use them as the multiworld intends (do not use a key item / skill before you receive it).

## Tracker
The matching PopTracker pack connects to the same server, tracks items and checks automatically and colours every check by what is
currently in logic.
"""
