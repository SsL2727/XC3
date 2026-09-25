"""E2E: local AP server + the world's client with autotracking against the running (isolated) emulator.

usage: python ap_e2e_autotrack.py <multiworld.zip> <slot> "<game> Client" <script.txt> [wait_seconds]
The client script is fed through XC_CLIENT_SCRIPT; supports '#sleep N'.  Output: F:\\XCAP\\work\\e2e_auto\\{server,client}.log
After the run the server's checked-location count is reported via a second, plain websocket connection.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import websockets

ZIP, SLOT, CLIENT, SCRIPT = sys.argv[1:5]
WAIT = int(sys.argv[5]) if len(sys.argv) > 5 else 120
GAME = CLIENT.replace(" Client", "")
PORT = 38281
OUT = r"F:\XCAP\work\e2e_auto"


async def status():
    async with websockets.connect(f"ws://127.0.0.1:{PORT}", max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps([{"cmd": "Connect", "password": None, "game": GAME, "name": SLOT, "uuid": str(uuid.uuid4()),
                                   "version": {"major": 0, "minor": 6, "build": 7, "class": "Version"}, "items_handling": 0,
                                   "tags": ["TextOnly"], "slot_data": False}]))
        for m in json.loads(await ws.recv()):
            if m["cmd"] == "Connected":
                return len(m["checked_locations"]), len(m["missing_locations"])
    return None


def main():
    slog = open(os.path.join(OUT, "server.log"), "w")
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=slog, stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
    cli = None
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 1).close()
                break
            except OSError:
                time.sleep(1)
        else:
            print("server did not start")
            return
        print("server up")
        env = dict(os.environ, XC_CLIENT_SCRIPT=SCRIPT)
        clog = open(os.path.join(OUT, "client.log"), "w")
        cli = subprocess.Popen([r"G:\Archipelago\ArchipelagoLauncherDebug.exe", CLIENT, "--", "--nogui", "--connect", f"127.0.0.1:{PORT}",
                                "--name", SLOT], stdout=clog, stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", env=env)
        t0 = time.time()
        while time.time() - t0 < WAIT and cli.poll() is None:
            time.sleep(2)
        print("client exit:", cli.poll(), f"after {time.time() - t0:.0f}s")
        print("server (checked, missing):", asyncio.run(status()))
    finally:
        if cli and cli.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(cli.pid)], capture_output=True)
        srv.kill()


main()
