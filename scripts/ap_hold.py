"""Keep a local AP server + XC2 client running (with N copies of one item sent) for hands-on testing. usage: ap_hold.py <zip> <slot> <item> <copies> <seconds>"""
import os, socket, subprocess, sys, time
ZIP, SLOT, ITEM, COPIES, SECS = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5])
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"
srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                       stdin=subprocess.PIPE, stdout=open(os.path.join(OUT, "server_h.log"), "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
for _ in range(60):
    try:
        socket.create_connection(("127.0.0.1", PORT), 1).close(); break
    except OSError:
        time.sleep(1)
script = os.path.join(OUT, "script_h.txt")
open(script, "w").write(f"#sleep {SECS}\n/exit\n")
cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", "Xenoblade Chronicles 2 Client", "--", "--nogui", "--connect",
                        f"127.0.0.1:{PORT}", "--name", SLOT], stdout=open(os.path.join(OUT, "client_h.log"), "w"), stderr=subprocess.STDOUT,
                       cwd=r"G:\Archipelago", env=dict(os.environ, XC_CLIENT_SCRIPT=script))
time.sleep(45)
for i in range(COPIES):
    srv.stdin.write(f'/send {SLOT} "{ITEM}"\n'); srv.stdin.flush(); time.sleep(3)
open(os.path.join(OUT, "hold_ready.txt"), "w").write("ready")
time.sleep(SECS)
subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True); srv.kill()
