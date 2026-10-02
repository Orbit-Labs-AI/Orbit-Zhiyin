"""AN-09 rule key moments: numbered, deduplicated and capped per session.

Labels are fixed descriptive strings; they never quote user text (evidence is fetched
through the redacted ``/v1/evidence`` endpoint by ``event_uid``).
"""

from typing import Any

from ...models import stable_id
from .detectors import SessionView
from .dictionary import MAX_MOMENTS, RULES_VERSION
from .outcome import verification_state

Record = dict[str, Any]

OUTCOME_LABELS = {"completed": "完成", "partial": "部分完成", "failed": "验证失败",
                  "abandoned": "中止", "unknown": "未知"}


def _moment(view: SessionView, kind: str, anchor: Record, label: str, signal_id=None) -> Record:
    ref = anchor.get("event_uid") or anchor.get("call_uid")
    return {"moment_id": stable_id(view.session_uid, kind, ref), "session_uid": view.session_uid,
            "member_session_uid": anchor["session_uid"], "kind": kind, "origin": "rule",
            "ts": anchor.get("ts"), "seq": anchor.get("seq"), "event_uid": anchor.get("event_uid"),
            "call_uid": anchor.get("call_uid"), "label": label, "signal_id": signal_id,
            "rules_version": RULES_VERSION}


def _sort_key(member_order: dict, m: Record) -> tuple:
    return (m["ts"] is None, m["ts"] or 0, member_order.get(m["member_session_uid"], 0), m["seq"] or 0)


def key_moments(view: SessionView, detected: dict, outcome: Record) -> Record:
    """Return ``{status, moments, total_n}``; ``status = unavailable`` without events."""
    if view.events is None:
        return {"status": "unavailable", "moments": None, "total_n": None}
    moments = []
    humans = [e for e in view.events if e["kind"] == "message.user" and e["session_uid"] in view.main_ids
              and e.get("attrs", {}).get("origin") == "human" and e.get("actor") in ("human", "user")]
    if humans:
        first = humans[0]
        moments.append(_moment(view, "goal", {**first, "call_uid": None}, "首条真人目标"))
    for i, occ in enumerate(o for s in detected.get("correction") or [] for o in s["occurrences"]):
        sig = next(s["signal_id"] for s in detected["correction"] if occ in s["occurrences"])
        moments.append(_moment(view, "correction", occ, f"纠偏（第 {i + 1} 次）", sig))
    for s in detected.get("retry_loop") or []:
        for occ in s["occurrences"]:
            moments.append(_moment(view, "failure_streak", occ,
                                   f"同参数重试连续失败 {occ['failures']} 次", s["signal_id"]))
    state = verification_state(view)
    passed = [r for r in state["runs_after_edit"] or [] if r["validation_result"] == "passed"]
    if passed:
        r = passed[0]
        call = next((c for c in view.calls or [] if c["call_uid"] == r["call_uid"]), {})
        moments.append(_moment(view, "verify_pass", {
            "session_uid": r["session_uid"], "event_uid": r["validation_evidence"]["call_event_uid"],
            "call_uid": r["call_uid"], "seq": r.get("seq"), "ts": call.get("started_at")},
            "最后一次编辑后验证通过"))
    for e in [*view.events, *view.context_events]:
        if e["kind"] == "context.compaction":
            moments.append(_moment(view, "compaction", {**e, "call_uid": None}, "上下文压缩"))
    own = [e for e in view.events if e["session_uid"] == view.session_uid]
    if own:
        moments.append(_moment(view, "end", {**own[-1], "call_uid": None},
                               f"会话结束（结果：{OUTCOME_LABELS[outcome['outcome']]}）"))
    unique = list({(m["kind"], m["event_uid"] or m["call_uid"]): m for m in moments}.values())
    order = {sid: i for i, sid in enumerate(view.member_ids)}
    unique.sort(key=lambda m: _sort_key(order, m))
    pinned = [m for m in unique if m["kind"] in ("goal", "end")]
    rest = [m for m in unique if m["kind"] not in ("goal", "end")][: MAX_MOMENTS - len(pinned)]
    kept = sorted(pinned + rest, key=lambda m: _sort_key(order, m))
    for i, m in enumerate(kept, 1):
        m["index"] = i
    return {"status": "available", "moments": kept, "total_n": len(unique)}
