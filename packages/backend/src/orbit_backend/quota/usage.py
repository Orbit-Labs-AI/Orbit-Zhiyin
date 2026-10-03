"""FE-22 usage payload: token / cost / cache buckets per agent, model or day.

Only ``model_call`` rows (observed call deltas) are summed; cumulative snapshots never are.
A bucket whose rows are not all known is ``None`` with ``known_*`` beside it, so missing
usage is never shown as zero. ``total = input + cache_read + cache_write + output``
(reasoning is already inside output).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

BUCKETS = ("input", "cache_read", "cache_write", "output", "reasoning")
GROUPS = ("agent", "model", "day")
DAY_MS = 86_400_000

CALLS_SQL = """
SELECT m.session_uid, src.agent, COALESCE(m.model_id, m.model_raw, 'unknown') AS model,
       m.ts, m.input_tokens, m.cache_read_tokens, m.cache_write_tokens, m.output_tokens,
       m.reasoning_tokens, m.cost_usd
FROM v_analysis_model_call m JOIN session s USING(session_uid)
LEFT JOIN source src ON src.source_id = s.source_id
WHERE m.ts IS NOT NULL AND m.ts >= ? AND m.ts < ?
"""


def calls(db, since_ms: int, until_ms: int, excluded=()) -> list[dict]:
    skip = set(excluded)
    return [dict(r) for r in db.execute(CALLS_SQL, (since_ms, until_ms))
            if r["session_uid"] not in skip]


def day_of(ts_ms: int, tz_offset_min: int) -> str:
    when = datetime.fromtimestamp(ts_ms / 1000, UTC) + timedelta(minutes=tz_offset_min)
    return when.date().isoformat()


def summarize(rows: list[dict]) -> dict:
    out: dict = {"requests": len(rows)}
    for bucket in BUCKETS:
        values = [r[f"{bucket}_tokens"] for r in rows]
        known = [v for v in values if v is not None]
        out[f"tokens_{bucket}"] = sum(known) if len(known) == len(values) else None
        out[f"known_tokens_{bucket}"] = sum(known)
    parts = [out[f"tokens_{b}"] for b in ("input", "cache_read", "cache_write", "output")]
    out["tokens_total"] = sum(parts) if None not in parts else None
    out["known_tokens_total"] = sum(out[f"known_tokens_{b}"]
                                    for b in ("input", "cache_read", "cache_write", "output"))
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    out["cost_usd"] = round(sum(costs), 6) if rows and len(costs) == len(rows) else None
    out["known_cost_usd"] = round(sum(costs), 6)
    out["cost_coverage"] = round(len(costs) / len(rows), 4) if rows else None
    prompt = [out[f"known_tokens_{b}"] for b in ("input", "cache_read", "cache_write")]
    out["cache_hit_rate"] = round(prompt[1] / sum(prompt), 4) if sum(prompt) else None
    return out


def usage(db, *, group_by: str, now_ms: int, days: int = 30, tz_offset_min: int = 0,
          excluded=()) -> dict:
    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {GROUPS}")
    since = now_ms - days * DAY_MS
    rows = calls(db, since, now_ms + 1, excluded)
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = (row["agent"] or "unknown") if group_by == "agent" else (
            row["model"] if group_by == "model" else day_of(row["ts"], tz_offset_min))
        groups.setdefault(key, []).append(row)
    summaries = {key: summarize(rows_) for key, rows_ in groups.items()}
    order = sorted(groups) if group_by == "day" else sorted(
        groups, key=lambda k: (-summaries[k]["known_tokens_total"], k))
    items = []
    for key in order:
        item = {group_by: key, **summaries[key]}
        if group_by == "model":
            item["agents"] = sorted({r["agent"] or "unknown" for r in groups[key]})
        items.append(item)
    return {"group_by": group_by, "days": days, "since": since, "until": now_ms,
            "tz_offset_min": tz_offset_min, "rows": items, "totals": summarize(rows),
            "basis": "measured" if rows else "insufficient"}
