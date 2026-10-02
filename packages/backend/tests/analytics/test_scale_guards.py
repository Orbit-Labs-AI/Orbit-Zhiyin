"""Long synthetic sessions: per-message work stays linear and wrappers are parsed once."""

import random

from tandem_backend.analytics.common import human, task_uid
from tandem_backend.analytics.interaction import features
from tandem_backend.analytics.interaction.rules import EXECUTION_KINDS


def _reference(events, main_ids):
    """The original quadratic scan, kept as the oracle for the indexed version."""
    points = []
    groups = {}
    for e in events:
        groups.setdefault(e["session_uid"], []).append(e)
    for es in groups.values():
        es = sorted(es, key=lambda e: (e["seq"], e["event_uid"]))
        steps = [e for e in es if e["kind"] in EXECUTION_KINDS]
        for e in es:
            if not human(e, main_ids):
                continue
            eligible = [s for s in steps if task_uid(e) is None or task_uid(s) == task_uid(e)]
            before = [s for s in eligible if s["seq"] < e["seq"]]
            after = [s for s in eligible if s["seq"] > e["seq"]]
            previous, following = (before[-1] if before else None), (after[0] if after else None)
            points.append({"event_uid": e["event_uid"], "session_uid": e["session_uid"],
                           "task_uid": task_uid(e), "turn_uid": e.get("turn_uid"), "seq": e["seq"],
                           "previous_step_uid": previous["event_uid"] if previous else None,
                           "next_step_uid": following["event_uid"] if following else None,
                           "next_step_available_at": following.get("ts") if following else None,
                           "relation_scope": "task" if task_uid(e) else "session_only"})
    return points


def _session(sid, size, rng):
    kinds = ["message.user", "message.assistant", "tool.call", "tool.result", "model.usage"]
    rows = []
    for seq in range(size):
        kind = rng.choice(kinds)
        attrs = {"origin": "human"} if kind == "message.user" else {}
        task = rng.choice([None, "", "t1", "t2"])
        if task is not None:
            attrs["task_uid"] = task
        rows.append({"event_uid": f"{sid}-{seq:05d}", "session_uid": sid, "seq": seq,
                     "ts": 1_000 + seq, "kind": kind,
                     "actor": "human" if kind == "message.user" else "assistant",
                     "turn_uid": f"{sid}-turn-{seq // 7}", "text": "synthetic", "attrs": attrs})
    rng.shuffle(rows)
    return rows


def test_locate_interventions_matches_reference_and_stays_linear(monkeypatch):
    rng = random.Random(7)
    events = [*_session("a", 400, rng), *_session("b", 250, rng), *_session("sub", 60, rng)]
    main_ids = {"a", "b"}
    assert features.locate_interventions(list(events), main_ids) == _reference(events, main_ids)

    calls = 0

    def counted(event):
        nonlocal calls
        calls += 1
        return task_uid(event)

    monkeypatch.setattr(features, "task_uid", counted)
    long_session = _session("long", 3_000, random.Random(11))
    features.locate_interventions(long_session, {"long"})
    # The quadratic scan evaluated task_uid ~2 × humans × steps (millions) times.
    assert calls < 5 * len(long_session)
