"""Long-running local AP session for live tests: server + XC2 client, server console commands are read from F:/XCAP/work/e2e_auto/cmd.txt (one per line).
usage: python ap_session.py <multiworld.zip> <slot> [game]      (kill with taskkill /F /T /PID; logs: server_s.log / client_s.log in F:/XCAP/work/e2e_auto)"""
import os, socket, subprocess, sys, time

ZIP, SLOT = sys.argv[1:3]
GAME = sys.argv[3] if len(sys.argv) > 3 else "Xenoblade Chronicles 2"
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"
CMD = os.path.join(OUT, "cmd.txt")
open(CMD, "w").close()
srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                       stdin=subprocess.PIPE, stdout=open(os.path.join(OUT, "server_s.log"), "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
for _ in range(60):
    try:
        socket.create_connection(("127.0.0.1", PORT), 1).close(); break
    except OSError:
        time.sleep(1)
env = dict(os.environ, XC_CLIENT_SCRIPT=os.path.join(OUT, "script_s.txt"), XC_PATCHER_SETTINGS=os.environ.get("XC_PATCHER_SETTINGS", r"F:\XCAP\work\patch_test4\settings.json"))
open(env["XC_CLIENT_SCRIPT"], "w").write(os.environ.get("XC_SESSION_SCRIPT") or f"#sleep {os.environ.get('XC_SESSION_SLEEP', '20000')}\n/exit\n")
cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", f"{GAME} Client", "--", "--nogui", "--connect", f"127.0.0.1:{PORT}", "--name", SLOT],
                       stdout=open(os.path.join(OUT, "client_s.log"), "w"), stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", env=env)
print("session up: server pid", srv.pid, "client pid", cli.pid, flush=True)
done = 0
while srv.poll() is None:
    lines = open(CMD).read().splitlines()
    for line in lines[done:]:
        srv.stdin.write(line + "\n"); srv.stdin.flush()
    done = len(lines)
    time.sleep(1)
