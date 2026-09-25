"""Write example player YAMLs (all options, defaults, with comments) for the three worlds into ../yaml_examples."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "yaml_examples"
OUT.mkdir(exist_ok=True)


def slug(text):
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")


def ident(text):
    out = re.sub(r"[^0-9a-zA-Z_]", "_", text.strip())
    return "_" + out if out and out[0].isdigit() else out


for pkg in ("xenoblade_de", "xenoblade_2", "xenoblade_3"):
    data = HERE / "out" / pkg / "data"
    g = json.loads((data / "game.json").read_text(encoding="utf-8"))
    locs = json.loads((data / "locations.json").read_text(encoding="utf-8"))
    victories = [l["name"] for l in locs if l.get("victory")]
    L = [f"# {g['game']} - example player options (generated from the world data)", "name: YourSlotName", f"game: {g['game']}", "",
         "requires:", "  version: 0.6.0", "", f"{g['game']}:"]
    if len(victories) > 1:
        default = victories[g.get("default_goal", 0)]
        L += ["  # Goal (victory condition): " + ", ".join(slug(v) for v in victories), f"  goal: {slug(default)}"]
    if g.get("has_traps"):
        L += ["  # Percentage of filler items replaced by trap items (0-100)", "  filler_traps: 0"]
    if g.get("game") in ("Xenoblade Chronicles 2", "Xenoblade Chronicles 3"):
        L += ["  # Multiplies experience-type gains (EXP, WP/SP, class points) while you play so runs go faster: 1 = normal, up to 50",
              "  experience_multiplier: 1"]
    if g.get("death_link"):
        L += ["  # Send / receive DeathLinks (use /die in the client)", "  death_link: false"]
    for name, spec in g.get("options", {}).items():
        desc = spec.get("description", "")
        if isinstance(desc, list):
            desc = " ".join(desc)
        L.append("  # " + desc.replace("\n", " ")[:300])
        if spec["type"] == "Choice":
            labels = ", ".join(slug(k) for k in spec["values"])
            inv = {v: k for k, v in spec["values"].items()}
            L += [f"  #   choices: {labels}", f"  {ident(name)}: {slug(inv.get(spec.get('default', 0), ''))}"]
        elif spec["type"] == "Range":
            L += [f"  #   range {spec['range_start']}..{spec['range_end']}", f"  {ident(name)}: {spec.get('default', spec['range_start'])}"]
        else:
            L.append(f"  {ident(name)}: {'true' if spec.get('default') else 'false'}")
    toggles = {}
    for cat, cd in g.get("categories", {}).items():
        for raw in cd.get("yaml_option", []):
            name = raw[1:] if raw.startswith("!") else raw
            toggles[name] = g.get("toggle_names", {}).get(name, name)
    if toggles:
        L += ["", "  # Location / item groups - switch groups off to shorten your world"]
        for name, disp in toggles.items():
            if ident(name) not in {ident(n) for n in g.get("options", {})}:
                L.append(f"  {ident(name)}: true    # {disp}")
    (OUT / f"{g['game']}.yaml").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", OUT / f"{g['game']}.yaml")
