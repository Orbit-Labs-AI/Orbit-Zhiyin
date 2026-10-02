"""Replay harness for the live-state classifier (EV-15).

Each synthetic case is a list of timed rows. A virtual clock steps every ``STEP_S`` seconds;
at each step the rows seen so far become a ``SessionTail`` and go through ``classify`` (no
database, no threads). We record when each state first appears, check the expectations and
count states listed under ``never`` as false alarms. ``service: "paused"`` cases run through
``Realtime`` with a fake gateway instead. The eval-suites package imports ``run_cases``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from .classify import classify
from .model import SessionTail, TailCall, TailEvent

STEP_S = 5
T0_MS = 1_800_000_000_000
DEFAULT_CASES = (Path(__file__).resolve().parents[3] / "tests" / "realtime" / "fixtures"
                 / "replay-cases-v1.json")
LATENCY_TYPES = ("failing", "just_finished", "awaiting_approval")


def build_tail(case: dict, upto_s: float) -> SessionTail:
    rows = [r for r in case["rows"] if r["t"] <= upto_s]
    tail = SessionTail(case["id"], agent=case.get("agent", "claude_code"),
                       title=case.get("title", case["id"]), status="active",
                       started_at=T0_MS)
    for row in rows:
        ts = T0_MS + int(row["t"] * 1000)
        if "status" in row:
            tail.status, tail.ended_at = row["status"], ts
        if "usage" in row:
            tail.usage = dict(row["usage"])
        if "call" in row:
            call = row["call"]
            tail.calls.append(TailCall(
                call_uid=f"c{len(tail.calls)}", name=call.get("name", "bash"),
                command_head=call.get("command_head"), argument_digest=call.get("digest", "d"),
                status=call.get("status", "ok"), error_class=call.get("error_class"),
                started_at=ts, ended_at=None if call.get("open") else ts + 100))
        if "kind" in row:
            tail.events.append(TailEvent(ts, row["kind"], row.get("actor", "assistant")))
            tail.last_event_ts, tail.last_actor = ts, row.get("actor", "assistant")
            tail.pending_permission = ({"ts": ts, "command": row.get("command")}
                                       if row["kind"] == "permission.request" else None)
    return tail


def _observed(state) -> set[str]:
    return {state.state, *state.flags}


def _run_classifier(case: dict) -> tuple[dict[str, float], list[tuple[float, set[str]]]]:
    first: dict[str, float] = {}
    timeline = []
    t = 0.0
    end = case.get("until", max(r["t"] for r in case["rows"]) + 60)
    while t <= end:
        seen = _observed(classify(build_tail(case, t), T0_MS + int(t * 1000)))
        timeline.append((t, seen))
        for name in seen:
            first.setdefault(name, t)
        t += STEP_S
    return first, timeline


def _at(timeline, t: float) -> set[str]:
    return next((seen for when, seen in reversed(timeline) if when <= t), set())


def _run_paused(case: dict) -> tuple[bool, str]:
    from .service import Realtime

    calls = []
    gw = SimpleNamespace(reads=None, appdb=None, platform=SimpleNamespace(
        collection=SimpleNamespace(paused=True), notifier=None))
    rt = Realtime(gw, clock=lambda: T0_MS / 1000, notify=calls.append,
                  resolve=calls.append)
    end = case.get("until", 60)
    rt._tails = lambda now_ms: [build_tail(case, (now_ms - T0_MS) / 1000)]
    snap = rt.snapshot(now=(T0_MS + end * 1000) / 1000)
    ok = snap["status"] == "paused" and not calls
    return ok, f"status={snap['status']} notifications={len(calls)}"


def run_case(case: dict) -> tuple[dict, dict[str, float], int]:
    if case.get("service") == "paused":
        ok, detail = _run_paused(case)
        return {"id": case["id"], "passed": ok, "detail": detail}, {}, 0
    first, timeline = _run_classifier(case)
    problems = []
    for expect in case.get("expect", []):
        seen = _at(timeline, expect["at"])
        if "state" in expect and expect["state"] not in seen:
            problems.append(f"t={expect['at']} want {expect['state']} got {sorted(seen)}")
        if "absent" in expect and expect["absent"] in seen:
            problems.append(f"t={expect['at']} unexpected {expect['absent']}")
    alarms = [name for name in case.get("never", []) if name in first]
    problems += [f"false alarm {name} at t={first[name]}" for name in alarms]
    latency = {name: first[name] - onset for name, onset in case.get("onset", {}).items()
               if name in first}
    detail = "; ".join(problems) or f"first seen {dict(sorted(first.items()))}"
    return {"id": case["id"], "passed": not problems, "detail": detail}, latency, len(alarms)


def run_cases(cases_path=None) -> dict:
    path = Path(cases_path) if cases_path else DEFAULT_CASES
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    results, latencies, false_alarms = [], {name: [] for name in LATENCY_TYPES}, 0
    for case in cases:
        result, latency, alarms = run_case(case)
        results.append(result)
        false_alarms += alarms
        for name, value in latency.items():
            if name in latencies:
                latencies[name].append(value)
    return {"cases": results,
            "detect_latency_s": {name: (max(values) if values else None)
                                 for name, values in latencies.items()},
            "false_alarms": false_alarms}
