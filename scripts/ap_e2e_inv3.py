"""E2E for XC3 gem / accessory filler delivery against the running emulator (loaded save).
usage: python ap_e2e_inv3.py <multiworld.zip> <slot> <item> [<item> ...]"""
import json, os, socket, struct, subprocess, sys, time

sys.path.insert(0, r"G:\Archipelago\xc-tools\worldgen")
import xc_autotrack as a
import xc_inventory as inv

ZIP, SLOT = sys.argv[1:3]
ITEMS = sys.argv[3:]
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"
DELIV = r"G:\Archipelago\xc-tools\worldgen\detect\xc3_deliver.json"


def main():
    p = a.XC3Probe()
    assert p.attach(), "game not found"
    mem, base = p.mem, p.live_bases()[0]
    table = json.load(open(DELIV, encoding="utf-8"))["items"]

    def count(item):
        e = table[item]
        off, typ, cap, _ = inv.XC3_ARRAYS[e["kind"]]
        raw = mem.read(base + inv.XC3_SHIFT + off, 16 * cap)
        n = 0
        for i in range(cap):
            it, idx, t, serial, q, fl = inv.XC3_ENTRY.unpack_from(raw, i * 16)
            if it == e["id"] and t == typ:
                n += q
        return n

    print("layout ok:", inv.xc3_layout_ok(mem, base), "before:", {i: count(i) for i in ITEMS})
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=open(os.path.join(OUT, "server_i3.log"), "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
    cli = None
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 1).close(); break
            except OSError:
                time.sleep(1)
        clog = os.path.join(OUT, "client_i3.log")
        env = dict(os.environ, XC_CLIENT_SCRIPT=os.path.join(OUT, "script_i3.txt"))
        open(env["XC_CLIENT_SCRIPT"], "w").write("#sleep 500\n/exit\n")
        cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", "Xenoblade Chronicles 3 Client", "--", "--nogui", "--connect",
                                f"127.0.0.1:{PORT}", "--name", SLOT], stdout=open(clog, "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", env=env)
        t0 = time.time()
        while time.time() - t0 < 200:
            time.sleep(5)
            if "attached to" in open(clog, encoding="utf-8", errors="replace").read():
                break
        print(f"client attached after {time.time() - t0:.0f}s")
        time.sleep(6)
        for item in ITEMS + ITEMS[:1]:
            srv.stdin.write(f'/send {SLOT} "{item}"\n'); srv.stdin.flush(); time.sleep(6)
            print(f"sent {item!r}; now {count(item)}")
    finally:
        time.sleep(3)
        for line in open(os.path.join(OUT, "client_i3.log"), encoding="utf-8", errors="replace").read().splitlines():
            if "Delivery" in line or "delivery" in line or "Error" in line:
                print("client:", line[-170:])
        if cli and cli.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True)
        srv.kill()


main()
