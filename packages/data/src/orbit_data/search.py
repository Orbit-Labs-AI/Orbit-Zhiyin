"""DT-23 unified local search over the published projection (read-only).

Message and title text come from the full-text index. When the optional trigram table
``event_search`` exists it is used directly (substring semantics, including Chinese);
otherwise ``event_fts`` (unicode61) answers word queries and a bounded ``LIKE`` scan over
message/title events answers substrings the word index cannot (CJK, very short queries).
Session titles, project names, ``tool_call.command_head`` and ``tool_call.files`` are
matched by bounded ``LIKE`` on their columns. Snippets are redacted again before return.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from orbit_data.privacy import redact
from orbit_data.store import readonly_connection

# The kinds event_search indexes (migration 008); contract.KINDS has no message.summary.
SEARCH_KINDS = ("message.user", "message.assistant", "session.title")
HIT_TYPES = ("title", "project", "message", "command", "file")
# Ranking constants are a product default chosen against the constructed judgement set in
# packages/data/tests/test_search_ranking_eval.py (pairwise preferences such as "a session
# titled for the query a month ago beats a weak mention today" and "a two-year-old title
# beats a stale weak message"). They are not calibrated on real user click data. The grid
# test there shows the feasible region: floor must be > 0, half-life 7 days is too short,
# and these values sit inside it. Score = rel x WEIGHTS[type] x decay(age).
WEIGHTS = {"title": 3.0, "project": 2.0, "command": 1.5, "file": 1.5, "message": 1.0}
HALF_LIFE_DAYS = 30.0
# Old hits keep this share of their weight so archived sessions stay findable.
DECAY_FLOOR = 0.25
MAX_QUERY_CHARS = 200
DAY_MS = 86_400_000


@dataclass(frozen=True)
class SearchScope:
    source_ids: tuple[str, ...] | None = None
    from_ts: int | None = None
    until_ts: int | None = None


def search(
    home: str | Path,
    query: str,
    scope: SearchScope | None = None,
    *,
    limit: int = 20,
    offset: int = 0,
    max_hits: int = 1000,
    now_ms: int | None = None,
) -> dict:
    """Search ``home/orbit.db`` read-only. Raises FileNotFoundError when no database exists."""
    db_path = Path(home).expanduser() / "orbit.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"No Orbit database at {db_path}")
    with readonly_connection(db_path) as db:
        return search_connection(
            db, query, scope, limit=limit, offset=offset, max_hits=max_hits, now_ms=now_ms
        )


def search_connection(
    db: sqlite3.Connection,
    query: str,
    scope: SearchScope | None = None,
    *,
    limit: int = 20,
    offset: int = 0,
    max_hits: int = 1000,
    now_ms: int | None = None,
) -> dict:
    query = " ".join((query or "").split())
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be at most {MAX_QUERY_CHARS} characters")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if not 1 <= max_hits <= 10_000:
        raise ValueError("max_hits must be between 1 and 10000")
    scope = scope or SearchScope()
    if scope.from_ts is not None and scope.until_ts is not None and scope.from_ts > scope.until_ts:
        raise ValueError("from_ts must not be after until_ts")
    if scope.source_ids is not None and not scope.source_ids:
        raise ValueError("source_ids must not be empty when given")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    db.row_factory = sqlite3.Row

    engine = _engine(db)
    hits: dict[tuple[str, str], dict] = {}
    truncated = False

    def add(kind: str, key: str, row, rel: float, text: str | None, ts):
        nonlocal truncated
        if (kind, key) in hits:
            hits[(kind, key)]["rel"] = max(hits[(kind, key)]["rel"], rel)
            return
        if len(hits) >= max_hits:
            truncated = True
            return
        hits[(kind, key)] = {
            "hit_type": kind,
            "session_uid": row["session_uid"],
            "event_uid": row["event_uid"] if "event_uid" in row.keys() else None,
            "call_uid": row["call_uid"] if "call_uid" in row.keys() else None,
            "ts": ts,
            "rel": rel,
            "_text": text,
        }

    like = "%" + _escape_like(query) + "%"
    # Session-level matches first: they are few and rank highest.
    where, params = _session_filter(scope, "s.started_at")
    for row in db.execute(
        f"SELECT s.session_uid, s.title, s.started_at FROM session s WHERE s.title LIKE ? ESCAPE '\\' {where} "
        "ORDER BY s.started_at DESC LIMIT ?",
        (like, *params, max_hits),
    ):
        add("title", row["session_uid"], row, 1.0, row["title"], row["started_at"])
    for row in db.execute(
        f"SELECT s.session_uid, p.name, s.started_at FROM session s JOIN project p USING(project_id) "
        f"WHERE p.name LIKE ? ESCAPE '\\' {where} ORDER BY s.started_at DESC LIMIT ?",
        (like, *params, max_hits),
    ):
        add("project", row["session_uid"], row, 1.0, row["name"], row["started_at"])
    where_t, params_t = _session_filter(scope, "COALESCE(t.started_at, s.started_at)")
    for column, kind in (("command_head", "command"), ("files", "file")):
        for row in db.execute(
            f"SELECT t.call_uid, t.session_uid, t.{column} AS value, COALESCE(t.started_at, s.started_at) AS ts "
            f"FROM tool_call t JOIN session s USING(session_uid) WHERE t.{column} LIKE ? ESCAPE '\\' {where_t} "
            "ORDER BY ts DESC LIMIT ?",
            (like, *params_t, max_hits),
        ):
            value = _matching_files(row["value"], query) if kind == "file" else row["value"]
            add(kind, row["call_uid"], row, 1.0, value, row["ts"])

    where_e, params_e = _session_filter(scope, "e.ts")
    kinds = ",".join("?" * len(SEARCH_KINDS))
    base = (
        "SELECT e.event_uid, e.session_uid, e.kind, e.ts, e.text{rank} FROM {source} "
        f"JOIN session s ON s.session_uid = e.session_uid WHERE e.kind IN ({kinds}) {where_e} "
    )
    substring = engine == "event_search" or _needs_substring(query)
    if engine == "event_search" and len(query) >= 3:
        rows = db.execute(
            base.format(
                rank=", bm25(event_search) AS rank",
                source="event_search JOIN event e ON e.rowid = event_search.rowid",
            )
            + "AND event_search MATCH ? ORDER BY rank LIMIT ?",
            (*SEARCH_KINDS, *params_e, _phrase(query), max_hits),
        )
        for row in rows:
            _add_event(add, row, _bm25_rel(row["rank"]))
    elif not substring:
        try:
            rows = db.execute(
                base.format(
                    rank=", bm25(event_fts) AS rank",
                    source="event_fts JOIN event e ON e.rowid = event_fts.rowid",
                )
                + "AND event_fts MATCH ? ORDER BY rank LIMIT ?",
                (*SEARCH_KINDS, *params_e, _terms(query), max_hits),
            ).fetchall()
        except sqlite3.OperationalError:
            rows, substring = [], True
        for row in rows:
            _add_event(add, row, _bm25_rel(row["rank"]))
    if substring and not (engine == "event_search" and len(query) >= 3):
        # Bounded substring fallback: message/title kinds only (never tool output),
        # newest first so the bound keeps the most relevant recent evidence.
        for row in db.execute(
            base.format(rank="", source="event e")
            + "AND e.text LIKE ? ESCAPE '\\' ORDER BY e.ts DESC LIMIT ?",
            (*SEARCH_KINDS, *params_e, like, max_hits),
        ):
            _add_event(add, row, 1.0)

    ranked = sorted(
        hits.values(),
        key=lambda hit: (
            -_score(hit, now_ms),
            -(hit["ts"] or 0),
            hit["hit_type"],
            hit["call_uid"] or hit["event_uid"] or hit["session_uid"],
        ),
    )
    page = ranked[offset : offset + limit]
    meta = _session_meta(db, {hit["session_uid"] for hit in page})
    results = []
    for hit in page:
        info = meta.get(hit["session_uid"], {})
        results.append(
            {
                "session_uid": hit["session_uid"],
                "source_id": info.get("source_id"),
                "agent": info.get("agent"),
                "title": _clean(info.get("title")),
                "project": _clean(info.get("project")),
                "hit_type": hit["hit_type"],
                "event_uid": hit["event_uid"],
                "call_uid": hit["call_uid"],
                "ts": hit["ts"],
                "score": round(_score(hit, now_ms), 6),
                "snippet": snippet(hit["_text"] or "", query),
            }
        )
    return {
        "query": query,
        "engine": engine,
        "substring": substring,
        "total": len(hits),
        "truncated": truncated,
        "counts": {kind: sum(1 for k in hits if k[0] == kind) for kind in HIT_TYPES},
        "offset": offset,
        "limit": limit,
        "hits": results,
    }


def _add_event(add, row, rel):
    kind = "title" if row["kind"] == "session.title" else "message"
    key = row["session_uid"] if kind == "title" else row["event_uid"]
    add(kind, key, row, rel, row["text"], row["ts"])


def _matching_files(value: str, query: str) -> str:
    try:
        names = [name for name in json.loads(value) if isinstance(name, str)]
    except ValueError:
        return value
    folded = query.casefold()
    return " ".join(name for name in names if folded in name.casefold()) or value


def _engine(db) -> str:
    row = db.execute("SELECT 1 FROM sqlite_master WHERE name='event_search'").fetchone()
    if row:
        columns = {item[1] for item in db.execute("PRAGMA table_info(event_search)")}
        if "text" in columns:
            return "event_search"
    return "event_fts"


def _session_filter(scope: SearchScope, ts_column: str) -> tuple[str, list]:
    clauses, params = [], []
    if scope.source_ids is not None:
        clauses.append(f"s.source_id IN ({','.join('?' * len(scope.source_ids))})")
        params.extend(scope.source_ids)
    if scope.from_ts is not None:
        clauses.append(f"{ts_column} >= ?")
        params.append(int(scope.from_ts))
    if scope.until_ts is not None:
        # Half-open [from_ts, until_ts), the same window as analysis_input.
        clauses.append(f"{ts_column} < ?")
        params.append(int(scope.until_ts))
    return "".join(" AND " + clause for clause in clauses), params


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _phrase(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _terms(text: str) -> str:
    return " AND ".join(_phrase(term) for term in text.split())


def _needs_substring(query: str) -> bool:
    """unicode61 only matches whole tokens; CJK runs and fragments need substring search."""
    return len(query) < 3 or any(ord(char) > 127 for char in query)


def _bm25_rel(rank) -> float:
    # SQLite bm25 is negative-better and unbounded; squash it into [1, 2) so a ranked FTS
    # match is never weaker than a LIKE match (1.0) and at most doubles it. The evaluation
    # cases use this range for "weak" (1.0-1.1) and "strong" (1.9) message hits.
    strength = max(0.0, -(rank or 0.0))
    return 1.0 + strength / (1.0 + strength)


def _score(hit: dict, now_ms: int) -> float:
    if hit["ts"] is None:
        # Unknown age ranks like the oldest dated hits, never above a dated one.
        decay = DECAY_FLOOR
    else:
        age_days = max(0.0, (now_ms - hit["ts"]) / DAY_MS)
        decay = DECAY_FLOOR + (1.0 - DECAY_FLOOR) * math.pow(0.5, age_days / HALF_LIFE_DAYS)
    return hit["rel"] * WEIGHTS[hit["hit_type"]] * decay


def _session_meta(db, session_uids) -> dict:
    if not session_uids:
        return {}
    uids = sorted(session_uids)
    rows = db.execute(
        "SELECT s.session_uid, s.source_id, src.agent, s.title, p.name AS project FROM session s "
        "JOIN source src USING(source_id) LEFT JOIN project p USING(project_id) "
        f"WHERE s.session_uid IN ({','.join('?' * len(uids))})",
        uids,
    )
    return {row["session_uid"]: dict(row) for row in rows}


def _clean(value):
    return redact(value) if isinstance(value, str) else value


def snippet(text: str, query: str, *, before: int = 40, after: int = 80) -> str:
    """Redacted single-line excerpt around the first case-insensitive match."""
    if not text:
        return ""
    folded = text.casefold()
    position = folded.find(query.casefold())
    # Redact a bounded window first so secrets cut at the window edge are still recognised.
    start = max(0, position - 2000) if position >= 0 else 0
    window = redact(text[start : start + 4000 + len(query)])
    found = window.casefold().find(query.casefold())
    if found < 0:
        found = 0
    left = max(0, found - before)
    right = min(len(window), found + len(query) + after)
    excerpt = re.sub(r"\s+", " ", window[left:right]).strip()
    if left > 0 or start > 0:
        excerpt = "…" + excerpt
    if right < len(window) or start + len(window) < len(text):
        excerpt += "…"
    return excerpt
