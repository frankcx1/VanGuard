"""VanGuard Guardian — deterministic autonomy (P8).

The next chapter after monitoring: recognize developing risk, select a
policy-approved response, take the least disruptive corrective action,
verify it worked, and leave a complete decision trail.

Design rules (permanent):
- Guardian is a DETERMINISTIC controller: thresholds, hysteresis, action
  eligibility, cooldowns, verification, fail-safe. The language model is
  never in this loop — it only explains afterward (via get_guardian_log).
- Actions go through the same audited, sim-gated command queue as human
  controls, recorded with device=GUARDIAN. A live source refuses them —
  real actuation is phase 2 behind narrowly scoped adapters.
- Autonomy ladder, user-selected ceiling:
    observe   – monitor and log only
    advise    – log + recommend
    ask       – prepare the action, request confirmation
    protect   – auto-execute preauthorized reversible actions (default)
    emergency – also execute the hard interlocks
- Low sensor confidence WITHHOLDS autonomy. Knowing when not to act is
  part of the design, not an error path.
"""
from __future__ import annotations

import json
import logging
import time

from poller import derived
from api.outlook import compute_outlook

log = logging.getLogger("vanguard.guardian")

LEVELS = ("observe", "advise", "ask", "protect", "emergency")

# -- action registry -----------------------------------------------------------
# permission: "auto" executes at protect+; "confirm" is always a proposal;
# "interlock" executes at protect+ immediately (no verify-wait, it is the
# protective response). Nothing here touches charging protection, the BMS,
# or the vehicle — those are the permanent "never" class and simply do not
# appear in this registry.

ACTIONS = {
    "suspend_starlink": {
        "label": "Suspend Starlink dish",
        "permission": "auto",
        "command": {"target": "network", "mode": "off"},
        "cooldown_s": 900,
    },
    "inverter_standby_off": {
        "label": "Disable idle inverter",
        "permission": "auto",
        "command": {"target": "inverter", "on": False},
        "cooldown_s": 900,
    },
    "stop_cooktop": {
        "label": "Stop cooktop (electrical interlock)",
        "permission": "interlock",
        "command": {"target": "appliance", "name": "cooktop", "on": False},
        "cooldown_s": 120,
    },
    "hvac_off": {
        "label": "Turn climate control off",
        "permission": "confirm",           # comfort changes always ask
        "command": {"target": "hvac", "mode": "off"},
        "cooldown_s": 600,
    },
}


def _get(readings, source, metric):
    try:
        return readings[source][metric][1]
    except (KeyError, TypeError):
        return None


class Guardian:
    """Per-process state machine. Episodes: detect → verify → decide →
    act → confirm; or withheld/proposed branches."""

    def __init__(self, app):
        self.app = app
        self.pending = {}        # risk_id → consecutive detection count
        self.active = None       # current episode dict
        self.last_action_ts = {}  # action_id → ts (cooldowns)
        self.last_withheld_ts = 0.0

    # -- helpers ----------------------------------------------------------------

    async def _emit(self, episode, stage, title, detail, data=None):
        await self.app.state.store.add_guardian_event(
            episode, stage, title, detail,
            json.dumps(data or {}, separators=(",", ":")))
        log.info("guardian %s: %s - %s", stage, title, detail)

    def _eligible(self, action_id, readings, level) -> bool:
        a = ACTIONS[action_id]
        now = time.time()
        if now - self.last_action_ts.get(action_id, 0) < a["cooldown_s"]:
            return False
        if action_id == "suspend_starlink":
            return _get(readings, "network", "mode") == 3.0
        if action_id == "inverter_standby_off":
            return (_get(readings, "inverter", "state") == 1.0
                    and (_get(readings, "inverter", "ac_out_w") or 0) < 5)
        if action_id == "hvac_off":
            return (_get(readings, "hvac", "mode") or 0) != 0.0
        return True

    def _savings_w(self, action_id, readings) -> float:
        if action_id == "suspend_starlink":
            return _get(readings, "starlink", "power_w") or 22.0
        if action_id == "inverter_standby_off":
            return 18.0
        if action_id == "hvac_off":
            return _get(readings, "hvac", "hvac_power_w") or 0.0
        return 0.0

    async def _execute(self, action_id) -> None:
        cmd = ACTIONS[action_id]["command"]
        payload = {"source_of_command": "guardian", **cmd}
        await self.app.state.store.enqueue_command(
            json.dumps({k: v for k, v in payload.items()
                        if k != "source_of_command"}))
        await self.app.state.store.audit(
            tool=f"guardian_{action_id}", args_json=json.dumps(cmd),
            result_hash="-", device="GUARDIAN", duration_ms=0)
        self.last_action_ts[action_id] = time.time()

    # -- risk detectors (deterministic; each returns a risk dict or None) --------

    def detect_reserve_risk(self, readings, outlook) -> dict | None:
        if not outlook.get("available") or outlook.get("reserve_ok_overnight", True):
            return None
        net = derived.net_power_w(readings)
        if net is None or net > -5:
            return None                     # charging/idle: no drain to correct
        return {
            "id": "reserve",
            "severity": "warning",
            "title": "Overnight reserve at risk",
            "detail": (f"battery charge projected to fall to "
                       f"{outlook['soc_at_sunrise_pct']:.0f}% by sunrise, below "
                       f"the {outlook['assumptions']['reserve_pct']:.0f}% "
                       "reserve policy; cause: overnight loads with no solar"),
            "actions": ["suspend_starlink", "inverter_standby_off"],
            "proposals": ["hvac_off"],
            "metrics": {"net_w": net,
                        "soc_at_sunrise_pct": outlook["soc_at_sunrise_pct"]},
        }

    def detect_voltage_sag(self, readings) -> dict | None:
        v = _get(readings, "shunt", "voltage_v")
        ac = _get(readings, "inverter", "ac_out_w") or 0.0
        if v is None or ac < 800 or v > 12.0:
            return None
        return {
            "id": "sag",
            "severity": "critical",
            "title": "Voltage sag under inverter load",
            "detail": f"battery at {v:.2f}V with {ac:.0f}W AC load - "
                      "demo electrical interlock",
            "actions": ["stop_cooktop"],
            "proposals": [],
            "metrics": {"voltage_v": v, "ac_w": ac},
        }

    def detect_alternator_gap(self, readings) -> dict | None:
        speed = _get(readings, "gps", "speed_mph") or 0.0
        alt = _get(readings, "dcc50s", "alt_power_w") or 0.0
        if speed < 5 or alt > 25:
            return None
        return {
            "id": "alt-gap",
            "severity": "advisory",
            "title": "No alternator charge while moving",
            "detail": "probable charging-path issue; monitoring conservatively "
                      "- no autonomous repair is possible or attempted",
            "actions": [],                 # intelligent restraint
            "proposals": [],
            "metrics": {"speed_mph": speed, "alt_w": alt},
        }

    def data_confidence_low(self, readings, now) -> str | None:
        i = _get(readings, "shunt", "current_a")
        p = _get(readings, "shunt", "power_w")
        if i is not None and p is not None and i * p < -1.0:
            return "battery current and power disagree on direction"
        per = readings.get("shunt", {})
        if not per or now - max(ts for ts, _ in per.values()) > 60:
            return "battery telemetry stale"
        return None

    # -- the evaluation cycle -----------------------------------------------------

    async def evaluate(self) -> dict:
        app = self.app
        store = app.state.store
        cfg = app.state.cfg
        now = int(time.time())
        level = (await store.get_meta("autonomy_level")) or \
            (cfg.get("guardian") or {}).get("default_level", "protect")
        readings = await store.latest()
        pv_hist = await store.history("dcc50s", "pv_power_w", 24 * 3600)
        from api.main import cfg_for_mode
        mode = (await store.get_meta("operating_mode")) or "camp"
        outlook = compute_outlook(readings, pv_hist, cfg_for_mode(cfg, mode))

        # Confirmation stage for a previously acted episode.
        if self.active and self.active.get("stage") == "acted" \
                and now - self.active["acted_ts"] >= 8:
            before = self.active["metrics"]
            net_after = derived.net_power_w(readings)
            soc_after = outlook.get("soc_at_sunrise_pct")
            await self._emit(
                self.active["episode"], "confirmed", self.active["title"],
                f"battery drain reduced from {-before.get('net_w', 0):.0f}W to "
                f"{-(net_after or 0):.0f}W; battery charge forecast at sunrise "
                f"improved from {before.get('soc_at_sunrise_pct', 0):.0f}% to "
                f"{(soc_after or 0):.0f}%",
                {"net_w_before": before.get("net_w"), "net_w_after": net_after,
                 "sunrise_before": before.get("soc_at_sunrise_pct"),
                 "sunrise_after": soc_after})
            self.active["stage"] = "confirmed"

        # Sensor confidence gates everything.
        low = self.data_confidence_low(readings, now)
        risks = [r for r in (
            self.detect_voltage_sag(readings),
            self.detect_reserve_risk(readings, outlook),
            self.detect_alternator_gap(readings),
        ) if r]

        if low and risks:
            if now - self.last_withheld_ts > 300:
                self.last_withheld_ts = now
                await self._emit(0, "withheld", "Autonomous action withheld",
                                 f"{low}; VanGuard will not change power-system "
                                 "state until readings recover")
            return await self.status()

        for risk in risks:
            rid = risk["id"]
            self.pending[rid] = self.pending.get(rid, 0) + 1
            interlock = any(ACTIONS[a]["permission"] == "interlock"
                            for a in risk["actions"])
            needed = 1 if interlock else 2      # hysteresis, except interlocks
            if self.pending[rid] < needed:
                continue
            if self.active and self.active["risk_id"] == rid:
                continue    # episode in flight or confirmed-awaiting-resolution
            await self._run_episode(risk, readings, level, cfg)
        for rid in list(self.pending):
            if rid not in {r["id"] for r in risks}:
                if self.active and self.active.get("risk_id") == rid \
                        and self.active.get("stage") == "confirmed":
                    await self._emit(self.active["episode"], "resolved",
                                     self.active["title"], "risk cleared")
                    self.active = None
                self.pending.pop(rid, None)
        return await self.status()

    async def _run_episode(self, risk, readings, level, cfg):
        sim_only = cfg.get("source") == "sim"
        episode = await self.app.state.store.add_guardian_event(
            0, "detected", risk["title"], risk["detail"],
            json.dumps(risk["metrics"]))
        await self._emit(episode, "verified", risk["title"],
                         "condition persisted across consecutive checks; "
                         "readings fresh")
        eligible = [a for a in risk["actions"]
                    if self._eligible(a, readings, level)]
        proposals = [p for p in risk["proposals"]
                     if self._eligible(p, readings, level)]
        savings = sum(self._savings_w(a, readings) for a in eligible)
        plan_txt = (" + ".join(ACTIONS[a]["label"] for a in eligible)
                    or "no eligible automatic action")

        self.active = {"episode": episode, "risk_id": risk["id"],
                       "title": risk["title"], "stage": "decided",
                       "metrics": risk["metrics"], "acted_ts": 0}

        if level in ("observe",):
            await self._emit(episode, "decided", risk["title"],
                             f"autonomy level is observe - logging only "
                             f"(would have: {plan_txt})")
            self.active["stage"] = "confirmed"
            return
        if level == "advise" or not sim_only:
            await self._emit(episode, "decided", risk["title"],
                             f"recommendation: {plan_txt} "
                             f"(~{savings:.0f}W); autonomy "
                             + ("level is advise" if sim_only else
                                "suspended on live hardware (phase 2)"))
            self.active["stage"] = "confirmed"
            return
        if level == "ask" and eligible:
            self.active["stage"] = "proposed"
            self.active["proposal"] = eligible + proposals
            await self._emit(episode, "proposed", risk["title"],
                             f"awaiting approval: {plan_txt} (~{savings:.0f}W)")
            return

        # protect / emergency: execute auto+interlock class, propose the rest.
        executed = []
        for a in eligible:
            if ACTIONS[a]["permission"] in ("auto", "interlock"):
                await self._execute(a)
                executed.append(a)
        if executed:
            await self._emit(
                self.active["episode"], "decided", risk["title"],
                f"policy-approved plan: {plan_txt}, estimated saving "
                f"~{savings:.0f}W" + (f"; also recommending: "
                + ", ".join(ACTIONS[p]["label"] for p in proposals)
                if proposals else ""))
            await self._emit(self.active["episode"], "acted", risk["title"],
                             "issued: " + ", ".join(
                                 ACTIONS[a]["label"] for a in executed))
            self.active["stage"] = "acted"
            self.active["acted_ts"] = int(time.time())
        else:
            await self._emit(self.active["episode"], "decided", risk["title"],
                             "no eligible automatic action; " +
                             (f"recommending: {plan_txt}" if proposals else
                              "monitoring"))
            self.active["stage"] = "confirmed"

    async def approve(self) -> bool:
        if not self.active or self.active.get("stage") != "proposed":
            return False
        for a in self.active.get("proposal", []):
            await self._execute(a)
        await self._emit(self.active["episode"], "acted", self.active["title"],
                         "human approved: " + ", ".join(
                             ACTIONS[a]["label"]
                             for a in self.active.get("proposal", [])))
        self.active["stage"] = "acted"
        self.active["acted_ts"] = int(time.time())
        return True

    async def dismiss(self) -> bool:
        if not self.active or self.active.get("stage") != "proposed":
            return False
        await self._emit(self.active["episode"], "dismissed",
                         self.active["title"], "human dismissed the proposal")
        self.active = None
        return True

    async def status(self) -> dict:
        store = self.app.state.store
        cfg = self.app.state.cfg
        level = (await store.get_meta("autonomy_level")) or \
            (cfg.get("guardian") or {}).get("default_level", "protect")
        mode = (await store.get_meta("operating_mode")) or "camp"
        auto = [a["label"] for a in ACTIONS.values()
                if a["permission"] in ("auto", "interlock")]
        confirm = [a["label"] for a in ACTIONS.values()
                   if a["permission"] == "confirm"]
        return {
            "armed": level not in ("observe",) and cfg.get("source") == "sim",
            "level": level,
            "levels": list(LEVELS),
            "mode": mode,
            "allowed_auto": auto,
            "requires_approval": confirm + ["charging-source changes"],
            "never": ["vehicle controls", "BMS/protection limits",
                      "any action on low sensor confidence"],
            "active": ({k: v for k, v in self.active.items()
                        if k != "metrics"} if self.active else None),
            "events": await store.guardian_events(limit=24),
        }


async def guardian_loop(app, interval_s: float) -> None:
    import asyncio
    await asyncio.sleep(20)
    while True:
        try:
            await app.state.guardian.evaluate()
        except Exception as e:
            log.warning("guardian evaluation failed: %s", e)
        await asyncio.sleep(max(10.0, interval_s))
