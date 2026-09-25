"""E2E for the XC2 client against the running emulator: art caps on connect + experience multiplier.
usage: python ap_e2e_xc2.py <multiworld.zip> <slot> [mult]"""
import os, socket, struct, subprocess, sys, time

sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a

ZIP, SLOT = sys.argv[1:3]
MULT = int(sys.argv[3]) if len(sys.argv) > 3 else 5
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"


def main():
    p = a.XC2Probe()
    assert p.attach(), "game not found"
    mem = p.mem
    base = p.live_bases()[0]
    exp = base + 0x3C + 0xB4                       # Rex BattleExp (in-level EXP)
    art = base + 0x3C + 0x2F0 + 4                  # Rex Sword Bash level
    print("Rex BattleExp", struct.unpack("<I", mem.read(exp, 4))[0], "Sword Bash level", mem.read(art, 1)[0])
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=open(os.path.join(OUT, "server_x2.log"), "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
    cli = None
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 1).close(); break
            except OSError:
                time.sleep(1)
        script = os.path.join(OUT, "script_x2.txt")
        open(script, "w").write("#sleep 300\n/exit\n")
        logp = os.path.join(OUT, "client_x2.log")
        cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", "Xenoblade Chronicles 2 Client", "--", "--nogui", "--connect",
                                f"127.0.0.1:{PORT}", "--name", SLOT], stdout=open(logp, "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago",
                               env=dict(os.environ, XC_CLIENT_SCRIPT=script))
        t0 = time.time()
        while time.time() - t0 < 240:
            txt = open(logp, encoding="utf-8", errors="replace").read()
            if "Experience multiplier" in txt and "attached to" in txt:
                break
            time.sleep(3)
        time.sleep(4)
        print(f"client ready after {time.time() - t0:.0f}s")
        before = struct.unpack("<I", mem.read(exp, 4))[0]
        mem.write(exp, struct.pack("<I", before + 100))
        time.sleep(3)
        after = struct.unpack("<I", mem.read(exp, 4))[0]
        print(f"BattleExp +100 simulated: {before} -> {after} (expect +{100 * MULT} at x{MULT})")
        mem.write(exp, struct.pack("<I", before))
    finally:
        time.sleep(1)
        for line in open(os.path.join(OUT, "client_x2.log"), encoding="utf-8", errors="replace").read().splitlines():
            if any(k in line for k in ("Delivery", "delivery", "ultiplier", "Autotracking: att")):
                print("client:", line[-150:])
        if cli and cli.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True)
        srv.kill()


main()
