"""E2E: local AP server + scripted game client + PopTracker (scratch copy) autotracking check.

usage: python ap_e2e_tracker.py <multiworld.zip> <pack.zip> <slot name> <game name> <tab_x,tab_y> [<send item name>]
Screenshots land in F:\\XCAP\\work\\e2e_<slot>_*.png
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

ZIP, PACK, SLOT, GAME = sys.argv[1:5]
TAB = sys.argv[5] if len(sys.argv) > 5 else ""
ITEM = sys.argv[6] if len(sys.argv) > 6 else ""
PORT = 38281
SHOT = r"G:\Archipelago\xc-tools\scripts\pt_shot.ps1"


def shot(name, clicks="", launch=False):
    out = rf"F:\XCAP\work\e2e_{SLOT}_{name}.png"
    cmd = ["powershell", "-NoProfile", "-File", SHOT, "-Out", out]
    env = dict(os.environ, PT_KEEP="1")
    if launch:
        cmd += ["-Pack", PACK, "-ApHost", f"127.0.0.1:{PORT}", "-ApSlot", SLOT, "-Wait", "10"]
    else:
        cmd += ["-NoLaunch"]
    if clicks:
        cmd += ["-Clicks", clicks]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(name, r.stdout.strip(), r.stderr.strip()[:200])


async def client_checks(location_ids):
    async with websockets.connect(f"ws://127.0.0.1:{PORT}", max_size=None) as ws:
        await ws.recv()  # RoomInfo
        await ws.send(json.dumps([{"cmd": "Connect", "password": None, "game": GAME, "name": SLOT, "uuid": str(uuid.uuid4()),
                                   "version": {"major": 0, "minor": 6, "build": 7, "class": "Version"}, "items_handling": 0,
                                   "tags": [], "slot_data": False}]))
        msgs = json.loads(await ws.recv())
        connected = [m for m in msgs if m["cmd"] == "Connected"]
        if not connected:
            print("connect failed:", msgs)
            return None
        info = connected[0]
        missing = info["missing_locations"]
        print(f"connected as {SLOT}: {len(info['checked_locations'])} checked, {len(missing)} missing")
        pick = location_ids if location_ids else missing[:5]
        await ws.send(json.dumps([{"cmd": "LocationChecks", "locations": pick}]))
        await asyncio.sleep(1.5)
        return pick, missing


def main():
    log = open(r"F:\XCAP\work\e2e_server.log", "w")
    srv = subprocess.Popen([r"G:\Archipelago\ArchipelagoServer.exe", ZIP, "--host", "127.0.0.1", "--port", str(PORT), "--disable_save"],
                           stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, cwd=r"G:\Archipelago", text=True)
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
        shot("1_connected", TAB, launch=True)
        if ITEM:
            srv.stdin.write(f'/send {SLOT} "{ITEM}"\n')
            srv.stdin.flush()
            time.sleep(3)
            shot("2_after_item", TAB)
        res = asyncio.run(client_checks([]))
        time.sleep(2)
        shot("3_after_checks", TAB)
        print("checked ids:", res[0] if res else None)
    finally:
        srv.terminate()
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-Process poptracker -ErrorAction SilentlyContinue | Where-Object { $_.Path -like 'F:\\XCAP\\work\\pt_test*' } | Stop-Process -Force"])
        log.close()


main()
