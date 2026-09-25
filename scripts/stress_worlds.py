"""Stress-test the three Xenoblade worlds with the real ArchipelagoGenerate.exe across seeds and option combinations."""
import itertools
import os
import shutil
import subprocess
import sys
import tempfile

GEN = r"G:\Archipelago\ArchipelagoGenerate.exe"
ROOT = os.environ.get("XC_STRESS_ROOT", r"F:\XCAP\work\stress")

XC1 = "Xenoblade Chronicles DE"
XC2 = "Xenoblade Chronicles 2"
XC3 = "Xenoblade Chronicles 3"

CASES = []


def add(game, name, opts):
    CASES.append((game, name, opts))


# ---- XC1
for goal in ("zanza_the_divine", "sightseer", "collector_goal", "monster_hunter_goal", "super_monster_hunter_goal", "ngp_champion", "ngp_grand_champion"):
    add(XC1, f"goal_{goal}", {"goal": goal, "GameVersion": "switch_2_version" if goal.startswith("ngp") else "definitive_edition"})
add(XC1, "danger_hard", {"Danger_Tolerance": 30, "Key_Leniency": 5})
add(XC1, "danger_easy", {"Danger_Tolerance": -10, "Key_Leniency": 0})
add(XC1, "wii_version", {"GameVersion": "wii_wii_u_new_3ds"})
add(XC1, "no_collectopaedia", {"Collectopaedia": "false", "collectopaediasanity": "false"})
add(XC1, "no_artsanity", {"Artsanity": "false"})
add(XC1, "spoilers_traps", {"Spoilers": "true", "filler_traps": 60})
add(XC1, "minimal", {k: "false" for k in ("locations", "landmarks", "AffinityQuests", "Achievements", "AffinityChart", "UniqueMonsters",
                                             "Collectopaedia", "collectopaediasanity", "NoponGrandPrix", "HeartToHearts", "Artsanity")})
add(XC1, "maximal_danger", {"Danger_Tolerance": 119})

# ---- XC2
for goal in ("clear_chapter_5", "collect_elysium_fragments", "clear_chapter_10"):
    add(XC2, f"goal_{goal}", {"goal": goal})
add(XC2, "fragments", {"goal": "collect_elysium_fragments", "fragments_required": 5, "total_fragments": 5})
add(XC2, "fragments_many", {"goal": "collect_elysium_fragments", "fragments_required": 300, "total_fragments": 400})
add(XC2, "no_post5", {"enable_post_chp5": "false", "goal": "clear_chapter_5"})
add(XC2, "traps", {"filler_traps": 100})
add(XC2, "no_locations", {"enable_locations": "false", "enable_landmarks": "false", "enable_chest_checks": "false"})
add(XC2, "urq_blades", {"enable_unrequiredblades": "true"})
add(XC2, "trust_per_blade", {"trust_per_blade": "true"})
add(XC2, "trust_off", {"progressive_blade_trust": "false"})
add(XC2, "slots_1", {"blade_slots_per_driver": 1, "trust_per_blade": "true"})
add(XC2, "skills_items", {"field_skill_logic": "false"})
add(XC2, "slots_1_global", {"blade_slots_per_driver": 1})
add(XC2, "manual_checks", {"manual_checks": "true"})

# ---- XC3
add(XC3, "default", {})
add(XC3, "traps", {"filler_traps": 50})
add(XC3, "no_story_gating", {"story_gating": "false"})
add(XC3, "no_hero_rando", {"hero_randomization": "false"})
add(XC3, "no_container_gating", {"container_gating": "false"})
add(XC3, "no_colony_affinity", {"progressive_colony_affinity": "false"})
add(XC3, "shops_per_shop", {"shop_checks": "per_shop"})
add(XC3, "shops_off", {"shop_checks": "off"})
add(XC3, "manual_checks", {"manual_checks": "true"})
add(XC3, "everything_off", {"story_gating": "false", "hero_randomization": "false", "progressive_colony_affinity": "false", "shop_checks": "off", "container_gating": "false"})

SEEDS = [11, 222, 3333]


def yaml_for(game, opts, name="Tester"):
    lines = [f"name: {name}", f"game: {game}", f"{game}:"]
    if not opts:
        lines[-1] += " {}"
    for k, v in opts.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines) + "\n"


def main(argv):
    only = argv[1] if len(argv) > 1 else None
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT)
    fails = []
    total = 0
    for game, name, opts in CASES:
        if only and only not in name and only not in game:
            continue
        for seed in SEEDS:
            total += 1
            d = os.path.join(ROOT, f"{game.replace(' ', '')}_{name}_{seed}")
            os.makedirs(os.path.join(d, "p"))
            os.makedirs(os.path.join(d, "o"))
            open(os.path.join(d, "p", "t.yaml"), "w", encoding="utf-8").write(yaml_for(game, opts))
            r = subprocess.run([GEN, "--player_files_path", os.path.join(d, "p"), "--outputpath", os.path.join(d, "o"), "--seed", str(seed)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=r"G:\Archipelago", timeout=280)
            out = r.stdout + r.stderr
            ok = "Done. Enjoy." in out and "Traceback" not in out and "Could not access required locations" not in out
            warn = [l for l in out.splitlines() if "logic self-check" in l or "more items than locations" in l]
            status = "ok  " if ok else "FAIL"
            print(f"{status} {game} / {name} / seed {seed}" + (f"  WARN: {warn[0][:160]}" if warn else ""), flush=True)
            if not ok:
                fails.append((game, name, seed, [l for l in out.splitlines() if l.strip()][-6:]))
    print(f"\n{total - len(fails)}/{total} generations succeeded")
    for f in fails:
        print("FAILED:", f[0], f[1], f[2])
        for l in f[3]:
            print("   ", l[:200])


main(sys.argv)
