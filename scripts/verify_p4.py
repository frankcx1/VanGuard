"""P4 verification harness — tools, audit, and the real tool-calling loop.

Two stages:
1. Fast checks: tool implementations + audit rows + tool-call parsing,
   no model involved.
2. The real thing: load the exported model and ask THE cooktop question
   against a seeded ``dusk_low`` database over /v1/chat/completions.
   This stage loads a 4B model — expect ~15s (GPU) to ~90s (NPU first).

Run:  .venv\\Scripts\\python.exe scripts\\verify_p4.py [--skip-model]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.chat import parse_tool_calls
from api.main import create_app
from api.tools import TOOL_SCHEMAS, ToolRunner
from poller.store import Store
from verify_p2 import seed

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = REPO_ROOT / "sim" / "captures"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


async def tool_checks(db: Path) -> None:
    store = await Store(db).open()
    runner = ToolRunner(store)

    batt = await runner.call("get_battery_state", {}, device="TEST")
    check("get_battery_state: SOC + volts, compact",
          isinstance(batt.get("soc_pct"), (int, float))
          and 12.0 < batt["voltage_v"] < 14.6
          and len(json.dumps(batt)) < 400,
          f"soc={batt.get('soc_pct')}%, {len(json.dumps(batt))}B")

    solar = await runner.call("get_solar_state", {}, device="TEST")
    check("get_solar_state: dusk → 0W PV", solar.get("pv_w") == 0)

    loads = await runner.call("get_loads", {}, device="TEST")
    check("get_loads: off-grid load derivable",
          (loads.get("load_w") or 0) > 10, f"{loads.get('load_w')}W")

    hist = await runner.call("get_history", {"metric": "soc", "window_h": 4}, device="TEST")
    check("get_history: stats not series",
          hist.get("n", 0) > 100 and "mean" in hist and "min" in hist
          and len(json.dumps(hist)) < 250,
          f"n={hist.get('n')}, {len(json.dumps(hist))}B")

    bad = await runner.call("get_history", {"metric": "nope"}, device="TEST")
    check("get_history: unknown metric → error, not crash", "error" in bad)

    tanks = await runner.call("get_tanks", {}, device="TEST")
    check("get_tanks: honest stub", tanks.get("available") is False)

    rt = await runner.call("estimate_runtime", {"load_watts": 1700}, device="TEST")
    # dusk_low after 2h sim: SOC ~38%: (38-20)% × 3840Wh / 1700W ≈ 24 min.
    check("estimate_runtime: cooktop math in range",
          rt.get("minutes_to_20pct") is not None and 18 <= rt["minutes_to_20pct"] <= 42,
          f"{rt.get('minutes_to_20pct')}min to 20%")

    rtv = await runner.call("estimate_runtime",
                            {"load_watts": 1700, "duration_min": 25}, device="TEST")
    check("estimate_runtime: verdict computed by the tool, not the model",
          rtv.get("stays_above_20pct") is False
          and rtv.get("soc_after_pct") is not None,
          f"soc_after={rtv.get('soc_after_pct')}%, "
          f"stays_above={rtv.get('stays_above_20pct')}")

    unknown = await runner.call("write_register", {"addr": 1}, device="TEST")
    check("unknown/write tool refused", "error" in unknown)

    audit = await store.audit_recent(limit=20)
    check("every call audited (9 calls → 9 rows)",
          len(audit) == 9 and all(a["device"] == "TEST" for a in audit),
          f"{len(audit)} rows")
    check("audit rows carry args + result hash",
          all(a["result_hash"] and a["args"] is not None for a in audit))
    await store.close()


def parsing_checks() -> None:
    text = ('I will check.\n<tool_call>\n{"name": "get_battery_state", '
            '"arguments": {}}\n</tool_call>\n<tool_call>{"name": '
            '"estimate_runtime", "arguments": {"load_watts": 1700}}</tool_call>')
    calls = parse_tool_calls(text)
    check("parses multiple Hermes-style tool_call blocks",
          [c["name"] for c in calls] == ["get_battery_state", "estimate_runtime"]
          and calls[1]["arguments"] == {"load_watts": 1700})
    check("malformed JSON flagged, not fatal",
          parse_tool_calls('<tool_call>{"name": broken}</tool_call>')[0]["name"] == "_malformed")
    check("plain text → no calls", parse_tool_calls("SOC is 42%.") == [])
    check("6 tool schemas, all read-only names",
          len(TOOL_SCHEMAS) == 6
          and all(f["function"]["name"].startswith(("get_", "estimate_"))
                  for f in TOOL_SCHEMAS))


def model_checks(db: Path) -> None:
    app = create_app({
        "source": "sim", "db_path": str(db),
        "inference": {"model_dir": "ov_qwen3_4b_instruct_2507_int4_npu",
                      "device_order": ["GPU", "NPU", "CPU"]},
    })
    with TestClient(app) as c:
        r = c.post("/v1/chat/completions", json={"messages": [{
            "role": "user",
            "content": "Can I run the induction cooktop for 25 minutes right "
                       "now without dropping below 20% battery? Show the math.",
        }]})
        check("chat endpoint 200", r.status_code == 200,
              f"{r.status_code}: {r.text[:120] if r.status_code != 200 else 'ok'}")
        if r.status_code != 200:
            return
        data = r.json()
        answer = data["choices"][0]["message"]["content"]
        vg = data["vanguard"]
        tools_used = [t["tool"] for t in vg["tool_calls"]]
        print(f"\n  --- cooktop answer ({vg['device']}, {vg['tokens_per_s']} tok/s, "
              f"{vg['rounds']} rounds, tools: {tools_used}) ---\n"
              + "\n".join("  | " + ln for ln in answer.splitlines()) + "\n")
        check("integrity: simulated=true in chat payload", vg["simulated"] is True)
        check("used telemetry tools (no guessed numbers)",
              len(tools_used) >= 1 and "estimate_runtime" in tools_used,
              str(tools_used))

        # The check that matters on camera: the spoken verdict must agree
        # with the tool's deterministic verdict.
        tool_verdicts = [t["result"].get("stays_above_20pct")
                         for t in vg["tool_calls"]
                         if t["tool"] == "estimate_runtime"
                         and "stays_above_20pct" in t["result"]]
        first_sentence = answer.split(".")[0].lower()
        says_no = ("no" in first_sentence.split() or "cannot" in first_sentence
                   or "can't" in first_sentence or "not" in first_sentence.split())
        if tool_verdicts:
            expected_no = tool_verdicts[-1] is False
            check("verdict matches the tool's deterministic verdict",
                  says_no == expected_no,
                  f"tool says stays_above={tool_verdicts[-1]}, answer opens: "
                  f"'{answer.splitlines()[0][:80]}'")
        else:
            check("verdict matches the tool's deterministic verdict", False,
                  "model never passed duration_min")
        check("answer shows the numbers",
              len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|min|minutes|h\b|hours|W\b)", answer)) >= 3,
              "≥3 quantities with units")
        check("answer is dashboard-sized", 30 < len(answer) < 1600,
              f"{len(answer)} chars")
        check("serving device recorded", vg["device"] in ("NPU", "GPU", "CPU"),
              vg["device"])

        audit = c.get("/api/audit").json()
        check("audit endpoint shows the calls with serving device",
              any(e["tool"] == "get_battery_state" and e["device"] == vg["device"]
                  for e in audit["entries"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-model", action="store_true",
                    help="fast checks only, no model load")
    a = ap.parse_args()

    print("== seeding dusk_low (2h) ==")
    db = CAPTURE_DIR / "_verify_p4.db"
    asyncio.run(seed(db, "dusk_low", 2.0))

    print("== tools + audit ==")
    asyncio.run(tool_checks(db))
    print("== tool-call parsing ==")
    parsing_checks()

    if not a.skip_model:
        print("== end-to-end: the cooktop question (loads the model) ==")
        model_checks(db)

    fails = [x for x in CHECKS if not x[1]]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
