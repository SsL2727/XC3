"""Archipelago client shared by the Xenoblade worlds.

The games are played on a Switch/emulator, so this client is the bridge between the player and the multiworld:

  /check <name>       send one location (exact name, or a unique/best fuzzy match)
  /checkmatch <text>  send every still-missing location whose name contains <text> (e.g. an area or quest name)
  /find <text>        list missing locations that match <text>
  /missing [region]   summary of missing locations by region / list for one region
  /goal               report game completion
  /die                send a DeathLink (only when the slot has DeathLink enabled)

  /deliver [status|on|off]
                      apply received items in the running game
  /autotrack [status|on|off|baseline|send]
                      automatic check detection: the client reads the running game's save data out of the emulator's memory
                      and sends checks as the game sets them (start a NEW game for a new multiworld; `baseline` ignores what a
                      loaded save already has, `send` sends it)

XC2 also arms a landmark-teleport failsafe (see xc_failsafe.py): hold L3+R3+L2+R2 on the controller for 1.5s to warp
to wherever you last activated a landmark, in case the game ever softlocks on a cutscene waiting for a story item
that hasn't arrived yet.

Received items appear in the client log the moment the multiworld sends them; the per-game PopTracker pack tracks them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pkgutil
import re
import time
from typing import Dict, List, Optional

import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, logger, server_loop
from NetUtils import ClientStatus

DEATH_LINK_COOLDOWN = 10.0
GOAL_KEY = "\0goal"


class XCCommandProcessor(ClientCommandProcessor):
    ctx: "XCContext"

    # -- helpers ---------------------------------------------------------------------------------------------------
    def _missing_by_name(self) -> Dict[str, int]:
        return {name: lid for name, lid in self.ctx.location_name_to_id.items() if lid in self.ctx.missing_locations}

    def _need_connection(self) -> bool:
        if not self.ctx.server or not self.ctx.slot:
            logger.info("Not connected to a multiworld yet.")
            return False
        return True

    # -- commands --------------------------------------------------------------------------------------------------
    def _cmd_check(self, *args: str) -> bool:
        """Send a location check: /check <location name>"""
        if not self._need_connection() or not args:
            logger.info("usage: /check <location name>")
            return False
        query = " ".join(args).strip()
        missing = self._missing_by_name()
        if query in missing:
            self.ctx.send_checks([missing[query]])
            return True
        lowered = query.lower()
        exact = [n for n in missing if n.lower() == lowered]
        if exact:
            self.ctx.send_checks([missing[exact[0]]])
            return True
        contains = [n for n in missing if lowered in n.lower()]
        if len(contains) == 1:
            self.ctx.send_checks([missing[contains[0]]])
            return True
        candidates = contains or [w for w, _ in Utils.get_fuzzy_results(query, list(missing), limit=8)]
        if not candidates:
            logger.info(f"No missing location matches '{query}'.")
            return False
        logger.info(f"'{query}' is ambiguous; did you mean:")
        for n in candidates[:12]:
            logger.info(f"  {n}")
        return False

    def _cmd_checkmatch(self, *args: str) -> bool:
        """Send every missing location whose name contains the text: /checkmatch <text>"""
        if not self._need_connection() or not args:
            logger.info("usage: /checkmatch <text>")
            return False
        text = " ".join(args).lower()
        hits = {n: i for n, i in self._missing_by_name().items() if text in n.lower()}
        if not hits:
            logger.info(f"No missing location contains '{text}'.")
            return False
        self.ctx.send_checks(list(hits.values()))
        logger.info(f"Sent {len(hits)} location check(s).")
        return True

    def _cmd_find(self, *args: str) -> bool:
        """List missing locations containing the text: /find <text>"""
        if not self._need_connection():
            return False
        text = " ".join(args).lower()
        hits = sorted(n for n in self._missing_by_name() if text in n.lower())
        logger.info(f"{len(hits)} missing location(s) match '{text}'")
        for n in hits[:40]:
            logger.info(f"  {n}")
        if len(hits) > 40:
            logger.info(f"  ... and {len(hits) - 40} more")
        return True

    def _cmd_missing(self, *args: str) -> bool:
        """Missing locations by region, or the list for one region: /missing [region]"""
        if not self._need_connection():
            return False
        regions = self.ctx.location_regions
        missing = self._missing_by_name()
        if args:
            want = " ".join(args).lower()
            hits = sorted(n for n in missing if want in regions.get(n, "").lower())
            for n in hits[:60]:
                logger.info(f"  {n}")
            logger.info(f"{len(hits)} missing in regions matching '{want}'")
            return True
        counts: Dict[str, int] = {}
        for n in missing:
            counts[regions.get(n, "?")] = counts.get(regions.get(n, "?"), 0) + 1
        for r, c in sorted(counts.items()):
            logger.info(f"  {r}: {c} missing")
        logger.info(f"{len(missing)} location(s) missing in total")
        return True

    def _cmd_goal(self) -> bool:
        """Report that you completed the game's goal."""
        if not self._need_connection():
            return False
        self.ctx.finished_game = True
        asyncio.create_task(self.ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}]))
        logger.info("Goal reported.")
        return True

    def _cmd_autotrack(self, mode: str = "status") -> bool:
        """Automatic check detection from the emulator: /autotrack [status|on|off|baseline|send]"""
        ctx = self.ctx
        mode = mode.lower()
        if mode == "on":
            ctx.autotrack_enabled = True
            logger.info("Autotracking on.")
        elif mode == "off":
            ctx.autotrack_enabled = False
            logger.info("Autotracking off (use /check for manual checks).")
        elif mode == "baseline":
            ctx.autotrack_ignore |= ctx.autotrack_last_true
            ctx.autotrack_held = False
            ctx.autotrack_pending, ctx.autotrack_pending_polls, ctx.autotrack_pending_pid = None, 0, None
            logger.info(f"Baseline set: ignoring {len(ctx.autotrack_ignore)} check(s) the loaded save already has.")
        elif mode == "send":
            ctx.autotrack_held = False
            ctx.autotrack_pending, ctx.autotrack_pending_polls, ctx.autotrack_pending_pid = None, 0, None
            logger.info("Sending everything the loaded save has set.")
        else:
            state = "on" if ctx.autotrack_enabled else "off"
            attached = "attached to " + ctx.autotrack_target if ctx.autotrack_target else "game not found"
            held = ""
            if ctx.autotrack_held:
                left = max(0, ctx.AUTOTRACK_STABLE_POLLS - ctx.autotrack_pending_polls) * 2
                held = (f" (HELD - auto-confirming {len(ctx.autotrack_pending or ())} check(s), ~{left}s left if stable; "
                        f"/autotrack send|baseline to resolve now)")
            logger.info(f"Autotracking {state}; {attached}; {len(ctx.autotrack_detectors)} detectable of "
                        f"{len(ctx.location_name_to_id)} locations; {len(ctx.autotrack_sent)} sent this session{held}.")
        return True

    def _cmd_deliver(self, mode: str = "status") -> bool:
        """Apply received items to the running game: /deliver [status|on|off|reset]  (reset = forget what was delivered, e.g. for a new game)"""
        ctx = self.ctx
        mode = mode.lower()
        if mode == "reset":
            state = getattr(ctx._deliverer, "state", None)
            if state is not None:
                state.reset()
                logger.info("Delivery history cleared: crystals and filler received so far will be delivered again.")
            return True
        if mode == "on":
            ctx.deliver_enabled = True
        elif mode == "off":
            ctx.deliver_enabled = False
        state = "on" if ctx.deliver_enabled else "off"
        n = len(ctx.deliver_table)
        logger.info(f"Item delivery {state}; {n} item type(s) can be delivered in-game; {ctx.deliver_writes} memory write(s) so far.")
        return True

    def _cmd_die(self) -> bool:
        """Send a DeathLink to the other players (needs DeathLink enabled in your options)."""
        if not self._need_connection():
            return False
        if "DeathLink" not in self.ctx.tags:
            logger.info("DeathLink is not enabled for this slot.")
            return False
        asyncio.create_task(self.ctx.send_death(f"{self.ctx.auth} died in {self.ctx.game}."))
        return True


class XCContext(CommonContext):
    command_processor = XCCommandProcessor
    items_handling = 0b111       # the multiworld sends every item (also our own) so the log / tracker stay in sync

    def __init__(self, game: str, server_address: Optional[str], password: Optional[str]):
        self.game = game
        super().__init__(server_address, password)
        self.slot_data: dict = {}
        self.location_name_to_id: Dict[str, int] = {}
        self.location_regions: Dict[str, str] = {}
        self.finished_game = False
        self._last_death = 0.0
        # automatic check detection (see xc_autotrack.py)
        self.autotrack_enabled = True
        self.autotrack_detectors: Dict[str, dict] = {}
        self.autotrack_goals: Dict[str, dict] = {}
        self.autotrack_sent: set = set()
        self.autotrack_ignore: set = set()
        self.autotrack_last_true: set = set()
        self.autotrack_target: str = ""
        self.autotrack_held = False
        self._autotrack_first = True
        self.autotrack_pending: Optional[set] = None    # last-confirmed superset of a burst being auto-verified, see _autotrack_apply
        self.autotrack_pending_polls = 0
        self.autotrack_pending_pid: Optional[int] = None
        self.autotrack_pid: Optional[int] = None
        self.deliver_enabled = True
        self.deliver_table: Dict[str, dict] = {}
        self.deliver_writes = 0
        self._deliverer = None
        self._autotrack_task: Optional[asyncio.Task] = None
        self._probe = None
        self._landmark_tracker = None                    # xc_failsafe.LandmarkTracker, built once detect.json is loaded
        self._failsafe_combo = None                       # xc_failsafe.ControllerCombo
        self._failsafe_task: Optional[asyncio.Task] = None
        try:
            from worlds import AutoWorldRegister
            world = AutoWorldRegister.world_types[game]
            self.location_name_to_id = dict(world.location_name_to_id)
            self.location_regions = {l["name"]: l["region"] for l in world.xc.locations if not l.get("victory")}
        except Exception as ex:  # pragma: no cover
            logger.warning(f"Could not load the {game} location table: {ex}")

    def send_checks(self, location_ids) -> None:
        asyncio.create_task(self.check_locations(list(location_ids)))

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        super().on_package(cmd, args)          # RoomInfo sets self.seed_name here - needed to scope DeliveryState per multiworld
        # (was missing: every slot's delivery-state file resolved to "..._None_..." regardless of which seed was connected,
        # so re-testing the same slot name across different multiworld generations silently reused old "already delivered"
        # bookkeeping - live-confirmed 2026-09-22: several received accessories never got written to the game's item box
        # because an earlier test session's state file already marked them as given)
        if cmd == "Connected":
            self.slot_data = args.get("slot_data", {})
            if self.slot_data.get("death_link"):
                asyncio.create_task(self.update_death_link(True))
            logger.info(f"Connected to the multiworld as {self.auth} ({self.game}); goal: {self.slot_data.get('goal')}")
            logger.info("Use /check <location>, /checkmatch <text>, /find <text>, /missing, /goal. /help lists everything.")
            self._start_autotrack()
            script = os.environ.get("XC_CLIENT_SCRIPT")      # test hook: run commands from a file after connecting
            if script and os.path.exists(script):
                asyncio.create_task(self._run_script(script))

    # -- automatic check detection -----------------------------------------------------------------------------------
    def _start_autotrack(self) -> None:
        if self._autotrack_task is not None and not self._autotrack_task.done():
            return
        probes, raw = {}, None
        try:
            from .xc_autotrack import PROBES as probes
            raw = pkgutil.get_data(__package__, "data/detect.json")
        except Exception as ex:
            logger.info(f"Autotracking unavailable: {ex}")
        if not raw or self.game not in probes:
            logger.info(f"Autotracking is not available for {self.game} yet - use /check.")
            return
        detect = json.loads(raw.decode("utf-8"))
        self.autotrack_detectors = {n: d for n, d in detect.get("locations", {}).items() if n in self.location_name_to_id}
        self.autotrack_goals = detect.get("goals", {})
        self._probe = probes[self.game]()
        self._autotrack_task = asyncio.create_task(self._autotrack_loop(), name="Autotrack")
        self._start_delivery()
        self._start_failsafe(detect)
        logger.info(f"Autotracking: {len(self.autotrack_detectors)} of {len(self.location_name_to_id)} locations can be detected "
                    f"automatically; start the emulator and load your game. (/autotrack for status)")

    # -- landmark-teleport failsafe (softlock recovery) ---------------------------------------------------------------
    def _start_failsafe(self, detect: dict) -> None:
        """Hold L3+R3+L2+R2 for 1.5s to warp to wherever the player last activated a landmark - see
        xc_failsafe.py. XC2 only for now (detect.json's landmark src tagging is XC2-specific)."""
        if self.game != "Xenoblade Chronicles 2" or self._failsafe_task is not None:
            return
        try:
            from . import xc_failsafe
        except Exception as ex:
            logger.info(f"Landmark-teleport failsafe unavailable: {ex}")
            return
        landmark_names = {n for n, d in detect.get("locations", {}).items()
                          if n in self.location_name_to_id and str(d.get("src", "")).startswith("landmark:")}
        self._landmark_tracker = xc_failsafe.LandmarkTracker(landmark_names)
        self._failsafe_combo = xc_failsafe.ControllerCombo()
        self._failsafe_task = asyncio.create_task(self._failsafe_loop(), name="Failsafe")
        note = "" if xc_failsafe.WRITE_WORKS else " (combo detection and landmark tracking are live, but the actual warp isn't yet - the position mirror found so far reverts writes instantly, so it will only log until a writable address is found)"
        logger.info(f"Landmark-teleport failsafe armed: hold L3+R3+L2+R2 for 1.5s to warp to your "
                    f"last-activated landmark if the game ever softlocks on a cutscene{note}.")

    async def _failsafe_loop(self) -> None:
        loop = asyncio.get_running_loop()
        combo = self._failsafe_combo
        while not self.exit_event.is_set():
            await asyncio.sleep(0.15)
            try:
                fired = await loop.run_in_executor(None, combo.poll)
            except Exception as ex:
                logger.error(f"Failsafe combo read error: {ex!r}")
                await asyncio.sleep(5.0)
                continue
            if not fired:
                continue
            probe = self._probe
            if probe is None or probe.mem is None:
                logger.info("Failsafe: combo detected, but not attached to the game right now.")
                continue
            bases = probe.live_bases()
            if not bases:
                logger.info("Failsafe: combo detected, but no live save copy found right now.")
                continue
            await loop.run_in_executor(None, self._landmark_tracker.teleport, probe.mem, bases[0], logger.info)

    def _start_multiplier(self) -> None:
        try:
            from .xc_deliver import MULTIPLIERS
        except Exception:
            return
        if self.game not in MULTIPLIERS:
            return
        self._gain = MULTIPLIERS[self.game]()
        asyncio.create_task(self._multiplier_loop(), name="ExpMultiplier")

    async def _multiplier_loop(self) -> None:
        loop = asyncio.get_running_loop()
        told = 0
        while not self.exit_event.is_set():
            await asyncio.sleep(0.5)
            probe = self._probe
            mult = int(self.slot_data.get("experience_multiplier", 1) or 1)
            if not (self.slot and probe is not None and probe.mem is not None and probe.copies):
                continue
            if mult != told:
                told = mult
                logger.info(f"Experience multiplier x{mult} {'active' if mult > 1 else '(off)'}.")
            try:
                await loop.run_in_executor(None, self._gain.apply, probe, mult, logger.info)
            except Exception as ex:
                logger.error(f"Multiplier error: {ex!r}")

    def _start_delivery(self) -> None:
        self._start_multiplier()
        try:
            from .xc_deliver import DELIVERERS
            raw = pkgutil.get_data(__package__, "data/deliver.json")
        except Exception:
            return
        if not raw or self.game not in DELIVERERS:
            return
        table = json.loads(raw.decode("utf-8"))
        self.deliver_table = table.get("items", {})
        self._deliverer = DELIVERERS[self.game](table)
        asyncio.create_task(self._deliver_loop(), name="Deliver")
        logger.info(f"Item delivery: {len(self.deliver_table)} item type(s) are applied in-game automatically (/deliver off to stop).")

    async def _deliver_loop(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            from worlds import AutoWorldRegister
            names = AutoWorldRegister.world_types[self.game].item_id_to_name
        except Exception:
            names = {}
        while not self.exit_event.is_set():
            await asyncio.sleep(1.5)
            probe = self._probe
            if not (self.deliver_enabled and self.slot and probe is not None and probe.mem is not None and probe.copies):
                continue
            state = getattr(self._deliverer, "state", None)
            self._deliverer.slot_data = self.slot_data or {}
            if state is not None:                        # what was already handed over is remembered per multiworld + slot
                self._deliverer.seed_name = str(getattr(self, "seed_name", "") or "")
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{self.game}_{self.seed_name}_{self.auth}")
                state.bind(Utils.user_path("xenoblade_state", f"{safe}.json"))
            counts: Dict[str, int] = {}
            for it in self.items_received:
                nm = names.get(it.item)
                if nm:
                    counts[nm] = counts.get(nm, 0) + 1
            try:
                self.deliver_writes += await loop.run_in_executor(None, self._deliverer.apply, probe, counts, logger.info)
                pending = getattr(self._deliverer, "pending_checks", None)
                if pending:                                  # checks the deliverer found (shop purchases)
                    ids = [self.location_name_to_id[n] for n in pending if n in self.location_name_to_id]
                    pending.clear()
                    if ids:
                        await self.check_locations(ids)
            except Exception as ex:
                logger.error(f"Delivery error: {ex!r}")

    async def _autotrack_loop(self) -> None:
        loop = asyncio.get_running_loop()
        probe = self._probe
        attached = False
        while not self.exit_event.is_set():
            await asyncio.sleep(2.0)
            if not self.autotrack_enabled or not self.slot:
                continue
            try:
                if not attached:
                    attached = await loop.run_in_executor(None, probe.attach)
                    if attached:
                        self.autotrack_pid = probe.mem.pid
                        self.autotrack_target = f"{probe.game} in emulator pid {probe.mem.pid} ({len(probe.copies)} save copies)"
                        logger.info(f"Autotracking: attached to {self.autotrack_target}.")
                    else:
                        await asyncio.sleep(6.0)
                        continue
                wanted = dict(self.autotrack_detectors)
                goal = self.slot_data.get("goal")
                if goal in self.autotrack_goals:
                    wanted[GOAL_KEY] = self.autotrack_goals[goal]
                true_now = await loop.run_in_executor(None, probe.true_locations, wanted)
                if true_now is None:                               # emulator closed, or the save moved: rescan
                    attached, self.autotrack_target, self.autotrack_pid = False, "", None
                    probe.detach()
                    logger.info("Autotracking: lost the game, waiting for it to come back...")
                    continue
                self._autotrack_apply(true_now)
            except Exception as ex:
                logger.error(f"Autotracking error: {ex!r}")
                attached = False
                probe.detach()

    # 30 was tuned against one specific incident (a stale copy showing 271 false locations) and implicitly assumed
    # any SMALLER simultaneous burst was safe to send immediately, unconfirmed - live-confirmed 2026-09-24 that's
    # wrong: a stale save-buffer copy firing a more modest burst (well under 30) on a fresh client attach sailed
    # straight through with no hold at all, since the whole confirm-over-several-polls mechanism below is gated on
    # this threshold. A false, unconfirmed check-send is a far worse outcome than delaying a legitimate multi-check
    # moment by ~50s, so this is deliberately conservative: normal play very rarely completes more than a couple
    # checks in one ~2s poll anyway (that many at once is itself a signal worth the confirmation window).
    AUTOTRACK_BURST = 3
    # ~50s at the 2s poll interval - see _autotrack_apply. MUST stay >= xc_autotrack.Probe.STALE_POLLS (20 polls):
    # true_now (the input here) is already the OR of every live memory copy, and Probe has its own, separate
    # staleness exclusion that drops a frozen-but-still-plausible copy (e.g. a leftover save slot from an earlier
    # session, still resident in the emulator's memory) out of that OR after STALE_POLLS unchanged polls. If this
    # window were shorter, the client would auto-accept the still-contaminated OR result before the probe ever gets
    # a chance to clean it up - live-confirmed 2026-09-22: a leftover save (clear_count 1, 271 locations true) sat
    # alongside a genuinely fresh new game (clear_count 0, 2 locations true) in the same 4 memory copies, and the
    # old 10s window accepted the contaminated 271 well before the probe's 40s exclusion could drop it.
    AUTOTRACK_STABLE_POLLS = 25

    def _autotrack_apply(self, true_now: set) -> None:
        goal_hit = GOAL_KEY in true_now
        names = {n for n in true_now if n in self.location_name_to_id}
        if self._landmark_tracker is not None and self._probe is not None and self._probe.mem is not None:
            bases = self._probe.live_bases()
            if bases:
                self._landmark_tracker.update(self._probe.mem, bases[0], names, self.autotrack_last_true, logger.info)
        self.autotrack_last_true = names
        fresh = [n for n in sorted(names) if n not in self.autotrack_ignore and n not in self.autotrack_sent
                 and self.location_name_to_id[n] in self.missing_locations]
        fresh_set = set(fresh)
        if self._autotrack_first:
            self._autotrack_first = False
        # A burst this big is never real progress from one poll to the next, but for async play it very often IS
        # real: a save that kept progressing while no client was connected, or the first attach of a session against
        # an already-progressed save, both legitimately produce a big batch of "already true" locations on arrival.
        # Rather than freezing until a human runs /autotrack send, confirm it automatically by requiring the SAME
        # (or a growing) set to read true across several consecutive polls: a bad/transient read - the emulator
        # dying mid-poll, a wrong memory copy, a save file being rebuilt - won't reproduce identically poll after
        # poll, but real save data will. Real save progress also never un-sets a flag, so any check that was seen
        # true and then reads false again is a strong tell of a bad read and restarts confirmation from scratch
        # (live-confirmed 2026-09-22: bursts of 1500+ false checks, including a false goal completion, arrived on
        # the poll right as an emulator process was killed, and again during "New Game" creation on a freshly
        # booted one - both would fail to reproduce identically on the next poll). Stability alone is not quite
        # enough, though: a frozen-but-wrong memory copy (a stale save-slot preview still resident after a restart,
        # live-confirmed 2026-09-22 - see xc_autotrack.py) reads just as consistently as real data. So confirmation
        # ALSO requires the emulator attachment itself to have stayed continuous throughout - any reattach (a new
        # pid) restarts the count too, since that is exactly the moment a different/wrong copy could get picked up.
        if len(fresh) > self.AUTOTRACK_BURST:
            pid_changed = self.autotrack_pending_pid is not None and self.autotrack_pending_pid != self.autotrack_pid
            reverted = self.autotrack_pending is not None and not (self.autotrack_pending <= fresh_set)
            if self.autotrack_pending is None or reverted or pid_changed:
                if pid_changed:
                    logger.warning("Autotracking: the emulator reattached while a burst was pending confirmation - "
                                   "restarting confirmation in case a different memory copy is now being read.")
                elif reverted:
                    logger.warning("Autotracking: the pending burst partly reverted (some checks that read true went "
                                   "false again) - treating this as a bad read and restarting confirmation.")
                else:
                    logger.warning(f"Autotracking: {len(fresh)} checks appeared at once - holding for automatic "
                                   f"confirmation over the next ~{self.AUTOTRACK_STABLE_POLLS * 2}s (a real, already-"
                                   f"progressed save reads the same or grows every poll; a bad read will not). "
                                   f"/autotrack send confirms immediately, /autotrack baseline discards them instead.")
                self.autotrack_pending, self.autotrack_pending_polls, self.autotrack_held = fresh_set, 1, True
                self.autotrack_pending_pid = self.autotrack_pid
            else:
                self.autotrack_pending = fresh_set                 # absorb any further growth, never resets the count
                self.autotrack_pending_polls += 1
                if self.autotrack_pending_polls >= self.AUTOTRACK_STABLE_POLLS:
                    logger.info(f"Autotracking: {len(fresh_set)} checks held stable for "
                                f"{self.autotrack_pending_polls} polls - accepting as real progress.")
                    self.autotrack_held = False
                    self.autotrack_pending = self.autotrack_pending_pid = None
        elif self.autotrack_pending is not None and not self.autotrack_held:
            self.autotrack_pending = self.autotrack_pending_pid = None   # cleared out from under us (baseline/send) - drop stale state
        if fresh and not self.autotrack_held:
            for n in fresh:
                logger.info(f"Autotracking: {n}")
            self.autotrack_sent.update(fresh)
            self.send_checks([self.location_name_to_id[n] for n in fresh])
        if goal_hit and not self.finished_game and not self.autotrack_held:
            self.finished_game = True
            logger.info(f"Autotracking: goal '{self.slot_data.get('goal')}' reached!")
            asyncio.create_task(self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}]))

    async def _run_script(self, path: str):
        await asyncio.sleep(2.0)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                logger.info(f"[script] {line}")
                if line.startswith("#sleep "):
                    await asyncio.sleep(float(line.split()[1]))
                    continue
                if line == "/exit":
                    await self.disconnect()
                    self.exit_event.set()
                    return
                self.command_processor(self)(line)
                await asyncio.sleep(1.0)

    def on_deathlink(self, data: dict):
        now = time.time()
        if now - self._last_death > DEATH_LINK_COOLDOWN:
            self._last_death = now
            logger.info(f"DeathLink from {data.get('source', '?')}: {data.get('cause', 'no reason given')} - take a defeat in-game!")
        super().on_deathlink(data)

    def make_gui(self):
        ui = super().make_gui()

        class XCManager(ui):
            base_title = f"Archipelago {self.game} Client"
        return XCManager


def run_client(game: str, args_list: List[str]) -> None:
    Utils.init_logging(f"{game.replace(' ', '')}Client", exception_logger="Client")

    async def main(args):
        ctx = XCContext(game, args.connect, args.password)
        ctx.auth = args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")
        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()
        await ctx.exit_event.wait()
        await ctx.shutdown()

    import colorama
    parser = get_base_parser(description=f"{game} client")
    parser.add_argument("--name", default=None, help="Slot name to connect as")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")
    args = parser.parse_args(args_list)
    if args.url:
        from CommonClient import handle_url_arg
        args = handle_url_arg(args, parser=parser)
    colorama.init()
    asyncio.run(main(args))
    colorama.deinit()
