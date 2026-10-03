"""Rule-based key moments for one session (five rules, no model, no invented 'drift/abandon').

Rules: ``goal`` (first human message), ``lexical_correction`` (correction lexicon hit),
``failure_streak`` (same tool + command head fails >= 3 times in a row), ``validation_command``
(a test / lint / type-check / build shell command that succeeded, judged by the same
``facts.is_validation_command`` the persona's V axis and the facts rows use) and
``compaction``.
"""

from __future__ import annotations

from .facts import is_validation_command

MAX_MOMENTS = 6
STREAK_MIN = 3
# Higher priority survives the cap first; output is then re-sorted by time.
PRIORITY = {"goal": 0, "failure_streak": 1, "lexical_correction": 2,
            "validation_command": 3, "compaction": 4}
ALERT = {"failure_streak", "lexical_correction"}


def _quote(text: str | None, limit: int = 40) -> str:
    text = text or ""
    return "「" + text[:limit] + ("…" if len(text) > limit else "") + "」"


def failure_streaks(calls: list[dict]) -> list[dict]:
    """Calls in time order -> one record per streak of >= STREAK_MIN identical failures."""
    out, run = [], []

    def close():
        if len(run) >= STREAK_MIN:
            out.append({"third": run[STREAK_MIN - 1], "n": len(run)})

    for call in calls:
        key = (call.get("name"), call.get("cmd"))
        if call.get("err") and run and (run[-1].get("name"), run[-1].get("cmd")) == key:
            run.append(call)
            continue
        close()
        run = [call] if call.get("err") else []
    close()
    return out


def is_validation(call: dict) -> bool:
    return (call.get("tool_kind") == "shell" and not call.get("err")
            and call.get("status") in ("success", "completed")
            and is_validation_command(call.get("cmd")))


def detect(users: list[dict], calls: list[dict], compactions: list[dict]) -> list[dict]:
    """``users``: human events (t, txt, corr, event_uid); ``calls``: tool events in time order;
    ``compactions``: (t, event_uid). Returns <= 6 moments sorted by t, numbered from 1."""
    found = []
    if users:
        first = users[0]
        found.append({"t": first["t"], "rule": "goal", "label": "你给出目标",
                      "detail": _quote(first.get("txt")), "event_uid": first["event_uid"]})
    for user in users:
        if user.get("corr"):
            found.append({"t": user["t"], "rule": "lexical_correction", "label": "你纠偏",
                          "detail": _quote(user.get("txt")), "event_uid": user["event_uid"]})
    for streak in failure_streaks(calls):
        third = streak["third"]
        found.append({"t": third["t"], "rule": "failure_streak", "label": "连续失败",
                      "detail": f"{third.get('cmd') or third.get('name')} 连续失败 {streak['n']} 次",
                      "event_uid": third["event_uid"]})
    checks = [c for c in calls if is_validation(c)]
    if checks:
        last = checks[-1]
        found.append({"t": last["t"], "rule": "validation_command", "label": "验证通过",
                      "detail": f"{last.get('cmd')} 成功（命令候选）", "event_uid": last["event_uid"]})
    for comp in compactions:
        found.append({"t": comp["t"], "rule": "compaction", "label": "上下文压缩",
                      "detail": "Agent 压缩了上下文", "event_uid": comp["event_uid"]})
    kept = sorted(found, key=lambda m: (PRIORITY[m["rule"]], m["t"]))[:MAX_MOMENTS]
    kept.sort(key=lambda m: (m["t"], PRIORITY[m["rule"]]))
    return [{**m, "n": i + 1, "alert": m["rule"] in ALERT} for i, m in enumerate(kept)]
