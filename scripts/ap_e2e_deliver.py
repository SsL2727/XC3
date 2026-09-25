"""E2E for XC2 art-cap delivery against the running emulator: clamp on connect, then send copies of an item from the server console.
usage: python ap_e2e_deliver.py <multiworld.zip> <slot> <item> [copies]     (reads Rex Sword Bash art levels from the live struct)"""
import os, socket, subprocess, sys, time

sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a

ZIP, SLOT, ITEM = sys.argv[1:4]
COPIES = int(sys.argv[4]) if len(sys.argv) > 4 else 2
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"
MAGIC = bytes.fromhex("5ba10300f3f3f3f3")


def art_levels(mem, base):
    return list(mem.read(base + 0x3C + 0x2F0 + 4, 4))       # Rex arts 4..7 (Sword Bash is the first)


def main():
    p = a.XC2Probe()
    assert p.attach(), "game not found"
    mem = p.mem
    base = p.live_bases()[0]
    print("levels before:", art_levels(mem, base))
    slog = open(os.path.join(OUT, "server_d.log"), "w")
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=slog, stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
    cli = None
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 1).close(); break
            except OSError:
                time.sleep(1)
        clog = open(os.path.join(OUT, "client_d.log"), "w")
        env = dict(os.environ, XC_CLIENT_SCRIPT=os.path.join(OUT, "script_d.txt"))
        open(env["XC_CLIENT_SCRIPT"], "w").write("#sleep 400\n/exit\n")
        cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", "Xenoblade Chronicles 2 Client", "--", "--nogui", "--connect",
                                f"127.0.0.1:{PORT}", "--name", SLOT], stdout=clog, stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", env=env)
        t0 = time.time()
        while time.time() - t0 < 60:
            time.sleep(5)
            lv = art_levels(mem, base)
            print(f"{time.time() - t0:4.0f}s levels {lv}")
            if lv[0] == 1:
                break
        print("after connect (expect Sword Bash clamped to 1):", art_levels(mem, base))
        for i in range(COPIES):
            srv.stdin.write(f'/send {SLOT} "{ITEM}"\n'); srv.stdin.flush(); time.sleep(4)
            print(f"sent copy {i + 1}; levels {art_levels(mem, base)}")
    finally:
        time.sleep(3)
        for line in open(os.path.join(OUT, "client_d.log"), encoding="utf-8", errors="replace").read().splitlines():
            if "Delivery" in line or "delivery" in line:
                print("client:", line[-160:])
        if cli and cli.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True)
        srv.kill()


main()
