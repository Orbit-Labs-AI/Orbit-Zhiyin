"""DT-18 / EV-01.1: compare Claude Code ``/insights`` session metrics with Tandem (read-only).

Sessions are matched by ``session.native_id``. Per metric the score is the share of matched
sessions whose values agree within 10%. Runs only when the caller passes ``ctx.home`` (the home
holding ``.claude/usage-data``) and a tandem.db via ``params['tandem_db']`` or
``params['tandem_home']``; it never defaults to the real home.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..contract import Check, EvalContext, SuiteResult
from ..insights_reader import read_session_meta, usage_dir

ID = "insights"
TITLE = "Insights comparison (Claude /insights vs Tandem)"
EV = ("DT-18", "EV-01.1")

AGREE_SHARE = 0.8  # 待验证: placeholder threshold until compared on real data
TOLERANCE = 0.10
QUERIES = {
    "tool_calls": "SELECT COUNT(*) FROM tool_call WHERE session_uid = ?",
    "user_messages": "SELECT COUNT(*) FROM v_human_message WHERE session_uid = ?",
    "duration_minutes": "SELECT (ended_at - started_at) / 60000.0 FROM session WHERE session_uid = ?",
    "tokens": "SELECT SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) FROM model_call "
              "WHERE session_uid = ?",
}


def _insights_value(row: dict, metric: str):
    if metric == "tool_calls":
        counts = row.get("tool_counts")
        return sum(v for v in counts.values() if isinstance(v, int | float)) if counts else None
    if metric == "user_messages":
        return row.get("user_message_count")
    if metric == "duration_minutes":
        return row.get("duration_minutes")
    if row.get("input_tokens") is None and row.get("output_tokens") is None:
        return None
    return (row.get("input_tokens") or 0) + (row.get("output_tokens") or 0)


def _tandem_value(db, metric: str, uid: str):
    try:
        found = db.execute(QUERIES[metric], (uid,)).fetchone()
    except sqlite3.Error:
        return None
    return found[0] if found else None


def _agree(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b)) or a == b


def _tandem_db(ctx: EvalContext) -> Path | None:
    if ctx.params.get("tandem_db"):
        return Path(ctx.params["tandem_db"])
    if ctx.params.get("tandem_home"):
        return Path(ctx.params["tandem_home"]) / "tandem.db"
    return None


def run(ctx: EvalContext) -> SuiteResult:
    if ctx.home is None:
        return SuiteResult(ID, skipped="no home given (the real home is never used by default)")
    if not (usage_dir(ctx.home) / "session-meta").is_dir():
        return SuiteResult(ID, skipped="insights session-meta directory missing")
    db_path = _tandem_db(ctx)
    if db_path is None or not db_path.is_file():
        return SuiteResult(ID, skipped="tandem.db missing")
    warnings: list[str] = []
    rows = read_session_meta(ctx.home, warnings)
    db = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        native = {r[0]: r[1] for r in db.execute("SELECT native_id, session_uid FROM session")}
        matched = [(r, native[r["session_id"]]) for r in rows if r["session_id"] in native]
        checks, metrics = [], {}
        for metric in QUERIES:
            pairs = [(a, b) for r, uid in matched
                     if (a := _insights_value(r, metric)) is not None
                     and (b := _tandem_value(db, metric, uid)) is not None]
            metrics[f"{metric}_pairs"] = len(pairs)
            if not pairs:
                continue
            share = sum(_agree(a, b) for a, b in pairs) / len(pairs)
            metrics[f"{metric}_agree"] = share
            checks.append(Check(f"insights.{metric}.agree_within_10pct", share >= AGREE_SHARE,
                                value=share, threshold=AGREE_SHARE))
    finally:
        db.close()
    seen = {r["session_id"] for r in rows}
    metrics.update(matched=len(matched), unmatched_insights=len(rows) - len(matched),
                   unmatched_tandem=len(set(native) - seen), warnings=len(warnings))
    return SuiteResult(ID, checks, metrics=metrics)
