"""E2E for the XC3 client against the running emulator: outfit lock on connect, outfit grant via server /send, experience multiplier.
usage: python ap_e2e_xc3.py <multiworld.zip> <slot> [mult]    (the multiworld must contain the slot with experience_multiplier == mult)"""
import os, socket, struct, subprocess, sys, time

sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a
import xc_deliver as d

ZIP, SLOT = sys.argv[1:3]
MULT = int(sys.argv[3]) if len(sys.argv) > 3 else 10
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"
ITEM, FLAG = "Yumsmith Outfit - Noah", 6299


def flag2(mem, live, idx):
    return (mem.read(live + 0x2710 + (idx >> 2), 1)[0] >> ((idx & 3) * 2)) & 3


def main():
    p = a.XC3Probe()
    assert p.attach(), "game not found"
    mem = p.mem
    live = p.live_bases()[0]
    g = d.XC3GainMultiplier()
    g.counters(p)
    exp_addr = g.chars + 4
    print("Yumsmith(Noah) flag before:", flag2(mem, live, FLAG))
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=open(os.path.join(OUT, "server_x3.log"), "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
    cli = None
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 1).close(); break
            except OSError:
                time.sleep(1)
        script = os.path.join(OUT, "script_x3.txt")
        open(script, "w").write("#sleep 300\n/exit\n")
        cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", "Xenoblade Chronicles 3 Client", "--", "--nogui", "--connect",
                                f"127.0.0.1:{PORT}", "--name", SLOT], stdout=open(os.path.join(OUT, "client_x3.log"), "w"), stderr=subprocess.STDOUT,
                               cwd=r"G:\Archipelago", env=dict(os.environ, XC_CLIENT_SCRIPT=script))
        logp = os.path.join(OUT, "client_x3.log")
        t0 = time.time()
        while time.time() - t0 < 240:                      # wait for the client to attach, lock and start the multiplier
            txt = open(logp, encoding="utf-8", errors="replace").read()
            if "Experience multiplier" in txt and "attached to" in txt:
                break
            time.sleep(3)
        time.sleep(4)
        print(f"client ready after {time.time() - t0:.0f}s; after connect (expect locked = 0):", flag2(mem, live, FLAG))
        srv.stdin.write(f'/send {SLOT} "{ITEM}"\n'); srv.stdin.flush(); time.sleep(6)
        print("after /send (expect unlocked >= 1):", flag2(mem, live, FLAG))
        # multiplier: simulate a game gain of +100 exp on Noah and see the client add the rest
        before = struct.unpack("<I", mem.read(exp_addr, 4))[0]
        time.sleep(1.5)
        mem.write(exp_addr, struct.pack("<I", before + 100))
        time.sleep(3)
        after = struct.unpack("<I", mem.read(exp_addr, 4))[0]
        print(f"exp +100 simulated: {before} -> {after} (expect +{100 * MULT} at x{MULT})")
        mem.write(exp_addr, struct.pack("<I", before))
    finally:
        time.sleep(1)
        for line in open(os.path.join(OUT, "client_x3.log"), encoding="utf-8", errors="replace").read().splitlines():
            if any(k in line for k in ("Delivery", "delivery", "multiplier", "Autotracking:")):
                print("client:", line[-150:])
        if cli and cli.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True)
        srv.kill()


main()
