"""E2E for XC2 inventory delivery (blade crystals + filler) against the running emulator.
usage: python ap_e2e_inv.py <multiworld.zip> <slot> <item> [<item> ...]      (the game must have a loaded save)
Starts a server + the client, sends every item once (twice for the first one, to prove there is no duplicate), prints box contents."""
import json, os, socket, subprocess, sys, time

sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a
import xc_inventory as inv

ZIP, SLOT = sys.argv[1:3]
ITEMS = sys.argv[3:]
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"
MARKER = r"F:\XCAP\work\ryu_root\sdcard\atmosphere\contents\0100E95004039001\ap_patch.json"
DELIV = r"G:\Archipelago\xc-tools\worldgen\detect\xc2_deliver.json"


def main():
    p = a.XC2Probe()
    assert p.attach(), "game not found"
    mem, base = p.mem, p.live_bases()[0]
    table = json.load(open(DELIV, encoding="utf-8"))["items"]
    crystals = {int(k): v for k, v in json.load(open(MARKER))["blade_crystals"].items()}

    def snapshot(item):
        e = table[item]
        if e["t"] == "blade_crystal":
            return "corecrystal", crystals[e["blade"]], inv.xc2_count_item(mem, base, "corecrystal", crystals[e["blade"]])
        return e["box"], e["id"], inv.xc2_count_item(mem, base, e["box"], e["id"])

    before = {i: snapshot(i) for i in ITEMS}
    print("before:", before)
    slog = open(os.path.join(OUT, "server_i.log"), "w")
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=slog, stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
    cli = None
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 1).close(); break
            except OSError:
                time.sleep(1)
        clog = os.path.join(OUT, "client_i.log")
        env = dict(os.environ, XC_CLIENT_SCRIPT=os.path.join(OUT, "script_i.txt"), XC_PATCHER_SETTINGS=r"F:\XCAP\work\patch_test4\settings.json")
        open(env["XC_CLIENT_SCRIPT"], "w").write("#sleep 500\n/exit\n")
        cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", "Xenoblade Chronicles 2 Client", "--", "--nogui", "--connect",
                                f"127.0.0.1:{PORT}", "--name", SLOT], stdout=open(clog, "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", env=env)
        t0 = time.time()
        while time.time() - t0 < 150:                                   # wait for the client to attach and connect
            time.sleep(5)
            txt = open(clog, encoding="utf-8", errors="replace").read()
            if "attached to" in txt:
                break
        print(f"client attached after {time.time() - t0:.0f}s")
        time.sleep(6)
        for n, item in enumerate(ITEMS + ITEMS[:1]):
            srv.stdin.write(f'/send {SLOT} "{item}"\n'); srv.stdin.flush(); time.sleep(6)
            print(f"sent {item!r}; now {snapshot(item)}")
    finally:
        time.sleep(3)
        for line in open(os.path.join(OUT, "client_i.log"), encoding="utf-8", errors="replace").read().splitlines():
            if "Delivery" in line or "delivery" in line:
                print("client:", line[-170:])
        if cli and cli.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True)
        srv.kill()


main()
