"""E2E for XC2 blade trust caps against the running emulator (loaded save).
usage: python ap_e2e_trust.py <multiworld.zip> <slot>
Global mode: connect -> every blade is capped at 1 heart; send 2x 'Progressive Blade Trust' -> cap 3; write a 4-heart blade -> clamped to 3."""
import os, socket, struct, subprocess, sys, time

sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a

ZIP, SLOT = sys.argv[1:3]
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"
WATCH = {1004: "Dromarch", 1005: "Poppi a", 1034: "Adenine", 1032: "Sheba", 1050: "Dagas(rare)"}


def main():
    p = a.XC2Probe()
    assert p.attach(), "game not found"
    mem, base = p.mem, p.live_bases()[0]
    slots = {}
    for s in range(140):
        bid = struct.unpack("<H", mem.read(base + 0x5A3C + s * 0x8A4 + 6, 2))[0]
        if 1001 <= bid <= 1200:
            slots[bid] = s

    def trust(bid):
        return struct.unpack("<II", mem.read(base + 0x5A3C + slots[bid] * 0x8A4 + 0x34, 8))

    def show(tag):
        print(tag, {WATCH[b]: trust(b) for b in WATCH})

    show("before")
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=open(os.path.join(OUT, "server_t.log"), "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
    cli = None
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 1).close(); break
            except OSError:
                time.sleep(1)
        clog = os.path.join(OUT, "client_t.log")
        env = dict(os.environ, XC_CLIENT_SCRIPT=os.path.join(OUT, "script_t.txt"), XC_PATCHER_SETTINGS=r"F:\XCAP\work\patch_test4\settings.json")
        open(env["XC_CLIENT_SCRIPT"], "w").write("#sleep 500\n/exit\n")
        cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", "Xenoblade Chronicles 2 Client", "--", "--nogui", "--connect",
                                f"127.0.0.1:{PORT}", "--name", SLOT], stdout=open(clog, "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", env=env)
        t0 = time.time()
        while time.time() - t0 < 150:
            time.sleep(5)
            if "attached to" in open(clog, encoding="utf-8", errors="replace").read():
                break
        print(f"client attached after {time.time() - t0:.0f}s")
        time.sleep(8)
        show("after connect (expect all 1 heart, points <= 99)")
        for i in range(2):
            srv.stdin.write(f'/send {SLOT} "Progressive Blade Trust"\n'); srv.stdin.flush(); time.sleep(5)
        # the player 'earns' hearts: write 4 hearts on Adenine and 3 hearts on Sheba (cap is now 3)
        mem.write(base + 0x5A3C + slots[1034] * 0x8A4 + 0x34, struct.pack("<II", 5000, 4))
        mem.write(base + 0x5A3C + slots[1032] * 0x8A4 + 0x34, struct.pack("<II", 1700, 3))
        time.sleep(5)
        show("after 2 trust items + writes (expect Adenine 3 hearts <=4599, Sheba unchanged 1700/3)")
    finally:
        time.sleep(2)
        for line in open(os.path.join(OUT, "client_t.log"), encoding="utf-8", errors="replace").read().splitlines():
            if "trust" in line.lower() or "Delivery error" in line:
                print("client:", line[-170:])
        if cli and cli.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True)
        srv.kill()


main()
