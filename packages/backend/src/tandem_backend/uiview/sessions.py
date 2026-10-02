"""A3 / Lite session list: L1 fact rows, filters, day grouping and the tool barcode.

Read-only over tandem.db (``session, source, event, tool_call, turn, model_call``); never
touches the heavy analytics snapshot. Every field that the logs cannot establish stays
``None`` (never 0) and carries a ``*_basis`` naming the rule that produced it. When P1's
``uiview_facts`` rows are available they are overlaid on these L1 rows by session id.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta, tzinfo
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tandem_data.privacy import redact

from ..analytics.interaction import correction_terms
from ..analytics.lexicon import CORRECTION_EXTRA_HINT

ACTIVE_GAP_MS = 5 * 60_000
TICKS_MAX = 90
KNOWN_STATUS = {"success", "completed", "failed", "rejected", "interrupted"}
FAILED = {"failed"}
AGENTS = {"claude_code": ("Claude Code", "CC"), "codex": ("Codex", "Codex"),
          "gemini": ("Gemini CLI", "Gemini"), "opencode": ("OpenCode", "OC"),
          "hermes": ("Hermes", "Hermes"), "kimi": ("Kimi CLI", "Kimi")}
WEEK = "一二三四五六日"
HOME_RE = re.compile(r"(?:/Users|/home)/[^/\s\"']+")
# Loose prefilter for ``correction_terms`` (which parses markdown, ~0.3 ms per message):
# every term it can return contains one of these substrings.
CORRECTION_HINT = re.compile(
    r"不对|不是我说的|还是不行|我说的是|你理解错了|重新|改成|wrong|not what I meant|try again|instead",
    re.I)
LIST_FIELDS = ("id", "a", "title", "title_source", "p", "d", "h", "mi", "dur", "out",
               "out_basis", "live", "tools", "errors", "corr", "excluded")

SESSIONS_SQL = """
SELECT s.session_uid, s.title, s.title_source, s.project_id, s.cwd, s.started_at, s.ended_at,
       s.status, s.native_id, src.agent
FROM session s LEFT JOIN source src ON src.source_id = s.source_id
WHERE s.kind = 'main'
"""
ACTIVE_SQL = """
SELECT root, MIN(ts), MAX(ts), SUM(MIN(COALESCE(gap, 0), ?)) FROM (
  SELECT s.root_uid AS root, e.ts AS ts,
         e.ts - LAG(e.ts) OVER (PARTITION BY s.root_uid ORDER BY e.ts) AS gap
  FROM event e JOIN session s ON s.session_uid = e.session_uid WHERE e.ts IS NOT NULL
) GROUP BY root
"""
HUMAN_WHERE = ("e.kind = 'message.user' AND json_extract(e.attrs, '$.origin') = 'human' "
               "AND e.actor IN ('human', 'user')")
HUMAN_SQL = f"""
SELECT e.session_uid, e.text FROM event e JOIN session s ON s.session_uid = e.session_uid
WHERE s.kind = 'main' AND {HUMAN_WHERE} ORDER BY e.session_uid, e.seq
"""
CALLS_SQL = """
SELECT s.root_uid, t.status, t.started_at FROM tool_call t
JOIN session s ON s.session_uid = t.session_uid ORDER BY s.root_uid, t.started_at, t.call_uid
"""
TOKENS_SQL = """
SELECT s.root_uid, COUNT(*),
       SUM(CASE WHEN m.input_tokens IS NULL AND m.output_tokens IS NULL THEN 1 ELSE 0 END),
       SUM(COALESCE(m.input_tokens, 0) + COALESCE(m.cache_read_tokens, 0)
           + COALESCE(m.cache_write_tokens, 0) + COALESCE(m.output_tokens, 0))
FROM model_call m JOIN session s ON s.session_uid = m.session_uid GROUP BY s.root_uid
"""
LAST_TURN_SQL = """
SELECT session_uid, status FROM (
  SELECT session_uid, status, ROW_NUMBER() OVER (PARTITION BY session_uid ORDER BY idx DESC) r
  FROM turn) WHERE r = 1
"""


# -- shared helpers --------------------------------------------------------------------------

def zone(name: str | None) -> tzinfo:
    """IANA name, or the machine's local zone for ``None`` / ``local``."""
    if name and name != "local":
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"未知时区：{name}") from None
    return datetime.now().astimezone().tzinfo


def agent_name(agent: str | None) -> str | None:
    if agent is None:
        return None
    return AGENTS.get(agent, (agent.replace("_", " ").title(), agent))[0]


@cache
def _home() -> str:
    return str(Path.home())


def is_correction(text: str | None) -> bool:
    """Same verdict as the analytics lexical rule, without parsing messages that cannot hit."""
    return bool(text and (CORRECTION_HINT.search(text) or CORRECTION_EXTRA_HINT.search(text))
                and correction_terms(text))


def scrub(text: str | None, limit: int = 120) -> str | None:
    """Redacted, home-free, single-line excerpt; ``None`` stays ``None``."""
    if text is None:
        return None
    text = redact(str(text)).replace(_home(), "~")
    text = HOME_RE.sub("~", text)
    text = " ".join(text.split())
    return text[:limit]


def is_failed(status: str | None) -> bool:
    return status in FAILED


def errors_of(statuses: list[str]) -> int | None:
    """Known failures; ``None`` when calls exist but none has a protocol status."""
    if statuses and not any(s in KNOWN_STATUS for s in statuses):
        return None
    return sum(is_failed(s) for s in statuses)


def estimate_outcome(live: bool, session_status: str | None, last_turn: str | None,
                     statuses: list[str]) -> str | None:
    """Estimate only: no user confirmation exists. Never claims 'abandoned'."""
    if live:
        return "live"
    tail = statuses[-3:]
    if len(tail) == 3 and all(is_failed(s) for s in tail):
        return "part"
    if "failed" in (session_status, last_turn) or "interrupted" in (session_status, last_turn):
        return "part"
    if "completed" in (session_status, last_turn):
        return "ok"
    return None


def local_parts(ts: int | None, tz: tzinfo) -> tuple[str | None, int | None, int | None]:
    if ts is None:
        return None, None, None
    at = datetime.fromtimestamp(ts / 1000, tz)
    return at.date().isoformat(), at.hour, at.minute


def day_label(day: str, today: str) -> str:
    at = datetime.fromisoformat(day).date()
    now = datetime.fromisoformat(today).date()
    if at == now:
        return "今天"
    if at == now - timedelta(days=1):
        return "昨天"
    return f"{at.month}月{at.day}日 周{WEEK[at.weekday()]}"


def title_from(text: str | None) -> str | None:
    clean = scrub(text, 200)
    if not clean:
        return None
    return clean[:40] + ("…" if len(clean) > 40 else "")


# -- fact rows -------------------------------------------------------------------------------

def l1_facts(conn: sqlite3.Connection, tz: tzinfo, *, excluded: Iterable[str] = (),
             live: Iterable[str] = ()) -> list[dict]:
    """One row per main session, newest first, shaped like the prototype's ``ALL`` rows."""
    excluded, live = set(excluded), set(live)
    active = {r[0]: r[1:] for r in conn.execute(ACTIVE_SQL, (ACTIVE_GAP_MS,))}
    humans: dict[str, list[str]] = defaultdict(list)
    for uid, text in conn.execute(HUMAN_SQL):
        humans[uid].append(text or "")
    calls: dict[str, list[str]] = defaultdict(list)
    for root, status, _ in conn.execute(CALLS_SQL):
        calls[root].append(status)
    tokens = {r[0]: r[1:] for r in conn.execute(TOKENS_SQL)}
    last_turn = dict(conn.execute(LAST_TURN_SQL).fetchall())
    rows = []
    for s in conn.execute(SESSIONS_SQL).fetchall():
        uid = s[0]
        first, last, active_ms = active.get(uid, (None, None, None))
        started = s[5] if s[5] is not None else first
        d, h, mi = local_parts(started, tz)
        texts = humans.get(uid, [])
        statuses = calls.get(uid, [])
        n_tok = tokens.get(uid)
        tok = None if not n_tok or n_tok[1] == n_tok[0] else n_tok[2]
        title, title_source = (s[1], s[2] or "native") if (s[1] or "").strip() else (
            title_from(texts[0]) if texts else None, "first_message" if texts else None)
        if title is None:
            title_source = None
        rows.append({
            "id": uid, "a": s[9], "p": s[3], "cwd": s[4], "title": title,
            "title_source": title_source, "started_at": started, "d": d, "h": h, "mi": mi,
            "dur": round(active_ms / 60_000, 1) if active_ms is not None else None,
            "dur_basis": "active_estimate", "span": round((last - first) / 60_000, 1)
            if first is not None else None,
            "msgs": len(texts), "tools": len(statuses), "errors": errors_of(statuses),
            "corr": sum(is_correction(t) for t in texts) if texts else None,
            "corr_basis": "lexical_candidate",
            "out": estimate_outcome(uid in live, s[7], last_turn.get(uid), statuses),
            "out_basis": "estimate", "live": uid in live, "excluded": uid in excluded,
            "tok": tok, "tok_basis": "l1_model_call", "topic": None, "fric": None,
            "native_id": s[8], "status": s[7],
        })
    rows.sort(key=lambda r: (r["started_at"] or 0, r["id"]), reverse=True)
    return rows


def overlay(rows: list[dict], facts: dict[str, dict] | None) -> list[dict]:
    """Prefer P1 ``uiview_facts`` values (same field names) where they are present."""
    if not facts:
        return rows
    return [{**r, **{k: v for k, v in (facts.get(r["id"]) or {}).items()
                     if v is not None or k in ("errors", "corr", "tok", "out")}}
            for r in rows]


def ticks(conn: sqlite3.Connection, rows: list[dict]) -> dict[str, dict]:
    """Tool barcode per row: start times normalized to [0, 1]; failures always kept."""
    out: dict[str, dict] = {}
    uids = [r["id"] for r in rows]
    stamps: dict[str, list[tuple[int, bool]]] = defaultdict(list)
    for start in range(0, len(uids), 500):
        part = uids[start:start + 500]
        sql = ("SELECT s.root_uid, t.started_at, t.status FROM tool_call t JOIN session s "
               "ON s.session_uid = t.session_uid WHERE t.started_at IS NOT NULL AND s.root_uid "
               f"IN ({','.join('?' * len(part))}) ORDER BY t.started_at")
        for root, at, status in conn.execute(sql, part):
            stamps[root].append((at, is_failed(status)))
    bounds = {r["id"]: (r["started_at"], r["span"]) for r in rows}
    for uid in uids:
        points = stamps.get(uid, [])
        if not points:
            out[uid] = {"t": [], "e": []}
            continue
        lo = min(points[0][0], bounds[uid][0] or points[0][0])
        hi = max(points[-1][0], lo + int((bounds[uid][1] or 0) * 60_000))
        width = max(hi - lo, 1)
        norm = [(round((at - lo) / width, 4), err) for at, err in points]
        oks = [t for t, err in norm if not err]
        if len(oks) > TICKS_MAX:
            step = len(oks) / TICKS_MAX
            oks = [oks[int(i * step)] for i in range(TICKS_MAX)]
        out[uid] = {"t": oks, "e": [t for t, err in norm if err][:TICKS_MAX]}
    return out


# -- list ------------------------------------------------------------------------------------

def _window_start(range_days: int, now_ms: int, tz: tzinfo) -> int | None:
    if not range_days:
        return None
    today = datetime.fromtimestamp(now_ms / 1000, tz).replace(hour=0, minute=0, second=0,
                                                              microsecond=0)
    return int((today - timedelta(days=range_days - 1)).timestamp() * 1000)


def _matches(row: dict, q: str | None, q_uids: set[str] | None, projects: dict[str, str]) -> bool:
    if not q:
        return True
    if q_uids and row["id"] in q_uids:
        return True
    needle = q.casefold()
    hay = (row.get("title"), row.get("p"), projects.get(row.get("p") or ""), row.get("a"),
           agent_name(row.get("a")))
    return any(needle in str(v).casefold() for v in hay if v)


def list_sessions(rows: list[dict], *, now_ms: int, tz: tzinfo, q: str | None = None,
                  q_uids: set[str] | None = None, range_days: int = 0,
                  agents: list[str] | None = None, project: str | None = None,
                  topic: str | None = None, outcome: str | None = None,
                  fric: str | None = None, hour: int | None = None, offset: int = 0,
                  limit: int = 120, projects: dict[str, str] | None = None) -> dict:
    """Filter + page the fact rows. Excluded sessions stay listed with ``excluded=True``."""
    start = _window_start(range_days, now_ms, tz)
    today, _, _ = local_parts(now_ms, tz)
    window = [r for r in rows if start is None or (r["started_at"] or 0) >= start]
    picked = [r for r in window
              if (not agents or r["a"] in agents) and (not project or r["p"] == project)
              and (topic is None or r.get("topic") == topic)
              and (outcome is None or r.get("out") == outcome)
              and (fric is None or r.get("fric") == fric)
              and (hour is None or r.get("h") == hour)
              and _matches(r, q, q_uids, projects or {})]
    page = picked[offset:offset + limit]
    days, seen = [], set()
    for r in page:
        if r["d"] not in seen:
            seen.add(r["d"])
            days.append({"day": r["d"], "label": day_label(r["d"], today) if r["d"] else "未知日期"})
    nxt = offset + limit if offset + limit < len(picked) else None
    return {
        "meta": {"count_label": {"in_window": len(picked),
                                 "today": sum(r["d"] == today for r in picked),
                                 "live": sum(bool(r["live"]) for r in picked),
                                 "excluded": sum(bool(r["excluded"]) for r in picked)},
                 "basis": {"dur": "active_estimate", "out": "estimate",
                           "corr": "lexical_candidate"}},
        "days": days,
        "rows": [{k: r.get(k) for k in LIST_FIELDS} for r in page],
        "total": len(picked), "next_offset": nxt,
    }
