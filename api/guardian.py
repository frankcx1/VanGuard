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
    "set_mode_camp": {
        "label": "Switch operating mode to Camp",
        "permission": "auto",              # app policy, not hardware
        "command": None,                   # executed via meta, not the queue
        "cooldown_s": 1800,
    },
}


def _get(readings, source, metric):
    try:
        return readings[source][metric][1]
    except (KeyError, TypeError):
        return None


# Detection metrics worth putting on camera, in display order. Only keys
# actually present in the episode's metrics are rendered.
_CARD_METRICS = (
    ("soc_at_sunrise_pct", "projected SOC at sunrise", "{:.0f}%"),
    ("reserve_pct", "policy reserve", "{:.0f}%"),
    ("voltage_v", "battery voltage", "{:.2f} V"),
    ("ac_w", "AC load at detection", "{:.0f} W"),
    ("alt_w", "alternator input", "{:.0f} W"),
    ("chassis_v", "chassis bus", "{:.1f} V"),
)


class Guardian:
    """Per-process state machine. Episodes: detect → verify → decide →
    act → confirm; or withheld/proposed branches."""

    def __init__(self, app):
        self.app = app
        self.pending = {}        # risk_id → consecutive detection count
        self.active = None       # current episode dict
        self.last_action_ts = {}  # action_id → ts (cooldowns)
        self.last_withheld_ts = 0.0
        self._was_moving = False  # arrival-transition tracking (P9)

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
        if action_id == "set_mode_camp":
            await self.app.state.store.set_meta("operating_mode", "camp")
        elif cmd is not None:
            await self.app.state.store.enqueue_command(json.dumps(cmd))
        await self.app.state.store.audit(
            tool=f"guardian_{action_id}", args_json=json.dumps(cmd or {}),
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
                        "soc_at_sunrise_pct": outlook["soc_at_sunrise_pct"],
                        "reserve_pct": outlook["assumptions"]["reserve_pct"]},
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
        """Cross-system charging-path anomaly (P9 fusion).

        With chassis telemetry we can say something neither subsystem can
        alone: the Mercedes side is demonstrably healthy (engine running,
        chassis bus at charging voltage) yet no alternator energy reaches
        the house battery. Without chassis data, falls back to GPS motion.
        No component is blamed and nothing is 'repaired' — restraint is
        the correct autonomous behaviour here.
        """
        alt = _get(readings, "dcc50s", "alt_power_w") or 0.0
        soc = _get(readings, "shunt", "soc_pct") or 0.0
        engine = _get(readings, "chassis", "engine_running")
        chassis_v = _get(readings, "chassis", "chassis_v")
        speed = _get(readings, "gps", "speed_mph") or 0.0
        if alt > 25 or soc > 95:      # charging fine, or battery full enough
            return None                # to legitimately suppress charge
        if engine is not None:
            if engine != 1.0:
                return None
            chassis_txt = (f"engine running, chassis bus at "
                           f"{chassis_v:.1f}V" if chassis_v else "engine running")
        elif speed > 5:
            chassis_txt = f"vehicle moving at {speed:.0f}mph"
        else:
            return None
        # Restraint about the fault itself — nothing can "repair" a charging
        # path. But conservation is a legitimate response: if nonessential
        # travel loads are burning watts while charging is down, shed them.
        shed = []
        if _get(readings, "network", "mode") == 3.0:
            shed.append("suspend_starlink")
        if (_get(readings, "inverter", "state") == 1.0
                and (_get(readings, "inverter", "ac_out_w") or 0) < 5):
            shed.append("inverter_standby_off")
        return {
            "id": "charging-path",
            "severity": "warning" if shed else "advisory",
            "title": "Charging-path anomaly",
            "detail": (f"Mercedes electrical state appears active ({chassis_txt}) "
                       "but no alternator energy is reaching the house system. "
                       "Possible: DC-DC path, BT-2/DCC50S input, or sensor "
                       "disagreement - no single component can be blamed yet. "
                       "The charging path cannot be repaired autonomously; "
                       + ("conserving instead by shedding nonessential loads"
                          if shed else "monitoring conservatively")),
            "actions": shed,
            "proposals": [],
            "metrics": {"alt_w": alt, "engine_running": engine,
                        "chassis_v": chassis_v, "speed_mph": speed},
        }

    def detect_arrival(self, readings) -> dict | None:
        """Arrival-state cleanup (P9 fusion): moving → parked with the
        ignition off, while travel-mode loads keep burning watts."""
        engine = _get(readings, "chassis", "engine_running")
        speed = _get(readings, "chassis", "speed_mph")
        if engine is None or speed is None:
            return None
        moving_now = engine == 1.0 or speed > 5
        was_moving = self._was_moving
        self._was_moving = moving_now
        if moving_now or not was_moving:
            return None                    # fires exactly on the transition
        travel_loads = []
        if _get(readings, "network", "mode") == 3.0:
            travel_loads.append("suspend_starlink")
        if (_get(readings, "inverter", "state") == 1.0
                and (_get(readings, "inverter", "ac_out_w") or 0) < 5):
            travel_loads.append("inverter_standby_off")
        return {
            "id": "arrival",
            "severity": "advisory",
            "title": "Arrived - travel loads still active",
            "detail": ("vehicle parked and ignition off; "
                       + (f"{len(travel_loads)} travel-mode load(s) still "
                          "drawing power" if travel_loads else
                          "loads already minimal")
                       + "; switching policy to Camp and recalculating the "
                         "overnight reserve"),
            "actions": ["set_mode_camp"] + travel_loads,
            "proposals": [],
            "metrics": {"travel_loads": len(travel_loads)},
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
                f"battery net power {before.get('net_w', 0):+.0f}W → "
                f"{(net_after or 0):+.0f}W; sunrise battery forecast "
                f"{before.get('soc_at_sunrise_pct', 0):.0f}% → "
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
            self.detect_arrival(readings),
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
            # Hysteresis, except interlocks and one-shot transitions (an
            # arrival event doesn't repeat, so it can't wait a second look).
            needed = 1 if (interlock or rid == "arrival") else 2
            if self.pending[rid] < needed:
                continue
            if self.active and self.active["risk_id"] == rid:
                continue    # episode in flight or confirmed-awaiting-resolution
            # Uniform before-metrics so every confirmation has a real
            # baseline regardless of which detector fired.
            risk["metrics"].setdefault("net_w",
                                       derived.net_power_w(readings) or 0.0)
            risk["metrics"].setdefault("soc_at_sunrise_pct",
                                       outlook.get("soc_at_sunrise_pct", 0.0))
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

        plan_labels = [ACTIONS[a]["label"] for a in eligible]
        if level in ("observe",):
            await self._emit(episode, "decided", risk["title"],
                             f"autonomy level is observe - logging only "
                             f"(would have: {plan_txt})",
                             {"recommended": plan_labels})
            self.active["stage"] = "confirmed"
            return
        if level == "advise" or not sim_only:
            await self._emit(episode, "decided", risk["title"],
                             f"recommendation: {plan_txt} "
                             f"(~{savings:.0f}W); autonomy "
                             + ("level is advise" if sim_only else
                                "suspended on live hardware (phase 2)"),
                             {"recommended": plan_labels, "savings_w": savings})
            self.active["stage"] = "confirmed"
            return
        if level == "ask" and eligible:
            self.active["stage"] = "proposed"
            self.active["proposal"] = eligible + proposals
            await self._emit(episode, "proposed", risk["title"],
                             f"awaiting approval: {plan_txt} (~{savings:.0f}W)",
                             {"actions": plan_labels, "savings_w": savings})
            return

        # protect / emergency: execute auto+interlock class, propose the rest.
        executed = []
        for a in eligible:
            if ACTIONS[a]["permission"] in ("auto", "interlock"):
                await self._execute(a)
                executed.append(a)
        if executed:
            done_labels = [ACTIONS[a]["label"] for a in executed]
            reco_labels = [ACTIONS[p]["label"] for p in proposals]
            await self._emit(
                self.active["episode"], "decided", risk["title"],
                f"policy-approved plan: {plan_txt}, estimated saving "
                f"~{savings:.0f}W" + (f"; also recommending: "
                + ", ".join(reco_labels) if proposals else ""),
                {"actions": done_labels, "savings_w": savings,
                 "recommended": reco_labels})
            await self._emit(self.active["episode"], "acted", risk["title"],
                             "issued: " + ", ".join(done_labels),
                             {"actions": done_labels})
            self.active["stage"] = "acted"
            self.active["acted_ts"] = int(time.time())
        else:
            await self._emit(self.active["episode"], "decided", risk["title"],
                             "no eligible automatic action; " +
                             (f"recommending: {plan_txt}" if proposals else
                              "monitoring"),
                             {"recommended": plan_labels})
            self.active["stage"] = "confirmed"

    async def approve(self) -> bool:
        if not self.active or self.active.get("stage") != "proposed":
            return False
        for a in self.active.get("proposal", []):
            await self._execute(a)
        labels = [ACTIONS[a]["label"] for a in self.active.get("proposal", [])]
        await self._emit(self.active["episode"], "acted", self.active["title"],
                         "human approved: " + ", ".join(labels),
                         {"actions": labels})
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

    async def reset_take(self) -> None:
        """Park-button reset: fresh episode state and cleared cooldowns so
        every demo take plays identically; autonomy re-armed to Protect."""
        self.pending = {}
        self.active = None
        self.last_action_ts = {}
        self.last_withheld_ts = 0.0
        self._was_moving = False
        await self.app.state.store.set_meta("autonomy_level", "protect")

    def _build_card(self, events, readings, now, level, mode) -> dict | None:
        """One camera-ready summary of the active episode: the risk numbers,
        what Guardian did, whether it worked, and the decision receipt.
        Everything here is copied from logged events — never recomputed, so
        the card can't disagree with the audit trail."""
        if not self.active:
            return None
        ep = self.active["episode"]
        mine = sorted((e for e in events
                       if e["episode"] == ep or e.get("id") == ep),
                      key=lambda e: e.get("id", 0))
        stages = {e["stage"]: e for e in mine}
        metrics = self.active.get("metrics", {})
        risk = [[label, fmt.format(metrics[k])]
                for k, label, fmt in _CARD_METRICS
                if metrics.get(k) is not None]
        ddata = (stages.get("decided") or stages.get("proposed") or {}) \
            .get("data") or {}
        cdata = (stages.get("confirmed") or {}).get("data") or {}
        result = None
        if cdata.get("net_w_after") is not None:
            nb, na = cdata.get("net_w_before") or 0, cdata["net_w_after"] or 0
            sb, sa = cdata.get("sunrise_before"), cdata.get("sunrise_after")
            result = {"net_before_w": nb, "net_after_w": na,
                      "sunrise_before_pct": sb, "sunrise_after_pct": sa,
                      "recovered": na > nb or (sb is not None and sa is not None
                                               and sa >= sb)}
        fresh = sum(1 for per in readings.values()
                    for ts, _v in per.values() if now - ts <= 60)
        engine = getattr(self.app.state, "engine", None)
        return {
            "stage": self.active["stage"],
            "title": self.active["title"],
            "detected_ts": mine[0]["ts"] if mine else now,
            "risk": risk,
            "actions": ddata.get("actions") or [],
            "recommended": ddata.get("recommended") or [],
            "savings_w": ddata.get("savings_w"),
            "result": result,
            "receipt": {
                "evidence": f"{fresh} fresh readings · " +
                            ("high confidence" if not self.data_confidence_low(
                                readings, now) else "LOW confidence"),
                "policy": f"{mode.title()} · {level.title()}",
                "ai": ("decision deterministic · explanation on "
                       f"{engine.device}" if engine
                       else "decision deterministic · no model in the loop"),
                "external": "0 external calls",
            },
        }

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
        events = await store.guardian_events(limit=24)
        card = None
        if self.active:
            card = self._build_card(events, await store.latest(),
                                    int(time.time()), level, mode)
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
            "card": card,
            "events": events,
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
