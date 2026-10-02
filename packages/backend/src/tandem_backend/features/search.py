"""Unified search (DT-23, SB-03 / ⌘K): parallel sources fused with RRF and time decay.

Sources run on a shared pool. Each source gets its own deadline that starts when it begins
running (time spent queued behind other clients does not count against it), and every request
has a hard wall-clock cap. The pool queue is bounded; work that would overflow it is not queued.
A slow, failing or shed source is listed in ``partial`` with a reason in ``partial_reasons``
instead of failing the request, so an empty result list is never silent. A source that could only
search part of its data (a short query over events) is listed there too, next to the hits it
found. All databases are opened read-only; the only write is the disposable trigram index
(``search_index``). Text comes from redacted L2 rows as-is.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .search_index import SearchIndex, get_index

try:  # imported up front: a first-query import (~140 ms) would blow the source deadline
    from tandem_catalog.features import lexical_tokens
except ImportError:  # pragma: no cover - catalog package is optional at runtime
    lexical_tokens = None

INDEX_KINDS = ("session", "message", "command", "file")
KINDS = INDEX_KINDS + ("project", "inventory", "catalog", "recommendation", "event")
DEFAULT_KINDS = tuple(k for k in KINDS if k != "event")
WEIGHTS = {"session": 1.2, "message": 1.0, "project": 1.1, "command": 0.8, "file": 0.8,
           "inventory": 0.9, "catalog": 0.9, "recommendation": 0.9, "event": 0.5}
PAGES = {"session": "session", "message": "session", "command": "session", "file": "session",
         "event": "session", "project": "project", "inventory": "local_library",
         "catalog": "library", "recommendation": "recs"}
TIMEOUT_S = 0.15  # per-source run budget, counted from when the source starts running
MAX_WAIT_S = 2.0  # hard per-request cap, including time queued behind other clients
POOL_SIZE = 16
MAX_QUEUED = 64  # source tasks queued or running across all requests
PER_SOURCE = 100
BM25_CAP = 1000
FUSE_TOP = 50
MAX_MESSAGES_PER_SESSION = 2
SYNC_INLINE_SESSIONS = 20_000
DAY_MS = 86_400_000
# Storage v8 ``event_search`` (contentless trigram) indexes these kinds only.
EVENT_KINDS = ("message.user", "message.assistant", "session.title")
EVENT_LIKE_ROWS = 50_000  # newest event rows a query with no indexable term scans with LIKE
PARTIAL = "_partial"  # optional key of a source result: {kind: reason} for incomplete kinds

_executor = ThreadPoolExecutor(POOL_SIZE, thread_name_prefix="tandem-search")
_local = threading.local()
_inflight = 0
_inflight_lock = threading.Lock()


class _Task:
    """One source run: records its start so the deadline excludes queue time."""

    def __init__(self, group, fn, args, budget_s):
        self.group, self.fn, self.args, self.budget_s = group, fn, args, budget_s
        self.started: float | None = None

    @property
    def deadline(self) -> float | None:
        return None if self.started is None else self.started + self.budget_s

    def __call__(self):
        global _inflight
        self.started = time.perf_counter()
        try:
            return self.fn(*self.args, deadline=self.deadline) \
                if self.fn in (_index_source, _event_source) else self.fn(*self.args)
        finally:
            with _inflight_lock:
                _inflight -= 1


def _admit(n: int) -> bool:
    global _inflight
    with _inflight_lock:
        if _inflight + n > MAX_QUEUED:
            return False
        _inflight += n
        return True


def _release(n: int) -> None:
    global _inflight
    with _inflight_lock:
        _inflight -= n


# -- parsing -------------------------------------------------------------------------------
def parse(q: str) -> dict:
    q = (q or "").strip()[:200]
    terms = q.split()
    if not terms:
        raise ValueError("empty query")
    long_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]
    match = " AND ".join('"' + t.replace('"', '""') + '"' for t in long_terms) or None
    return {"q": q, "terms": terms, "match": match, "like": short_terms}


def like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _like_all(column: str, terms: list[str]) -> tuple[str, list[str]]:
    return (" AND ".join(f"{column} LIKE ? ESCAPE '\\'" for _ in terms), [like(t) for t in terms])


def _ro(path: Path | None) -> sqlite3.Connection | None:
    if path is None or not Path(path).is_file():
        return None
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = _local.conns = {}
    key = str(Path(path).resolve())
    conn = cache.get(key)
    if conn is None:
        conn = sqlite3.connect(Path(key).as_uri() + "?mode=ro", uri=True, isolation_level=None,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 1000")
        cache[key] = conn
    return conn


def _has_table(conn, table, column=None) -> bool:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
        return False
    return column is None or any(r[1] == column for r in conn.execute(
        f"PRAGMA table_info({table})"))


# -- snippets ------------------------------------------------------------------------------
def snippet(text: str, terms: list[str], width: int = 96) -> tuple[str, list[list[int]]]:
    """Window around the first hit with [start, end) marks for every term occurrence."""
    text = (text or "").replace("\n", " ")
    folded = text.casefold()
    hits = [folded.find(t.casefold()) for t in terms]
    first = min((h for h in hits if h >= 0), default=0)
    start = max(0, first - width // 3)
    end = min(len(text), start + width)
    window = text[start:end]
    prefix = "…" if start > 0 else ""
    out = prefix + window + ("…" if end < len(text) else "")
    marks = []
    lowered = window.casefold()
    for term in terms:
        needle, pos = term.casefold(), 0
        while needle and (pos := lowered.find(needle, pos)) >= 0:
            marks.append([pos + len(prefix), pos + len(prefix) + len(needle)])
            pos += len(needle)
    return out, sorted(marks)


def strip_marks(raw: str) -> tuple[str, list[list[int]]]:
    """Turn FTS ``snippet()`` markers \\x01 / \\x02 into plain text plus marks."""
    out, marks, start = [], [], None
    for ch in raw or "":
        if ch == "\x01":
            start = len(out)
        elif ch == "\x02":
            if start is not None:
                marks.append([start, len(out)])
            start = None
        else:
            out.append(ch)
    return "".join(out), marks


def _line(text: str, terms: list[str]) -> str:
    folded = [t.casefold() for t in terms]
    for line in (text or "").split("\n"):
        if all(t in line.casefold() for t in folded):
            return line
    return (text or "").split("\n", 1)[0]


# -- sources -------------------------------------------------------------------------------
def _scope_sql(scope: dict, prefix: str) -> tuple[str, list]:
    sql, args = "", []
    for key, column in (("project_ids", "project_id"), ("agent_ids", "agent")):
        values = scope.get(key)
        if values:
            sql += f" AND {prefix}{column} IN ({','.join('?' * len(values))})"
            args += list(values)
    if scope.get("from_ts") is not None:
        sql += f" AND {prefix}ts >= ?"
        args.append(scope["from_ts"])
    if scope.get("until_ts") is not None:
        sql += f" AND {prefix}ts < ?"
        args.append(scope["until_ts"])
    return sql, args


def _index_source(index: SearchIndex, kinds, parsed, scope, deadline=None) -> dict[str, list[dict]]:
    conn = index.reader()
    if deadline is not None:  # abort the query once the result can no longer be used
        conn.set_progress_handler(lambda: time.perf_counter() > deadline + 0.05, 2000)
    try:
        return _index_query(conn, kinds, parsed, scope)
    finally:
        if deadline is not None:
            conn.set_progress_handler(None, 0)


def _index_query(conn, kinds, parsed, scope) -> dict[str, list[dict]]:
    terms = parsed["terms"]
    scope_sql, scope_args = _scope_sql(scope, "m.")
    cols = "m.id, m.kind, m.ref, m.session_uid, m.project_id, m.agent, m.ts, m.title, d.text"
    out = {}
    for kind in kinds:
        table = f"doc_{kind}"
        like_sql, like_args = _like_all("d.text", parsed["like"]) if parsed["like"] else ("", [])
        if parsed["match"]:
            # bm25 must score every match; for very common terms recency (rowid) is as good
            # and lets FTS stop after LIMIT rows.
            common = conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} WHERE {table} "
                                  f"MATCH ? LIMIT {BM25_CAP})", (parsed["match"],)).fetchone()[0]
            order = "d.rowid DESC" if common >= BM25_CAP else f"bm25({table})"
            sql = (f"SELECT {cols} FROM {table} d JOIN doc_meta m ON m.id=d.rowid "
                   f"WHERE {table} MATCH ?{' AND ' + like_sql if like_sql else ''}{scope_sql} "
                   f"ORDER BY {order} LIMIT {PER_SOURCE}")
            args = [parsed["match"], *like_args, *scope_args]
        else:
            sql = (f"SELECT {cols} FROM {table} d JOIN doc_meta m ON m.id=d.rowid "
                   f"WHERE {like_sql}{scope_sql} ORDER BY d.rowid DESC LIMIT {PER_SOURCE}")
            args = [*like_args, *scope_args]
        hits = []
        for row in conn.execute(sql, args):
            if kind in ("command", "file"):
                line = _line(row["text"], terms)
                text, marks = snippet(line, terms)
                hits.append(_hit(kind, f"{kind}:{row['session_uid']}:{line}", line, text, marks,
                                 row, {"id": row["session_uid"], "match": line}))
            else:
                text, marks = snippet(row["text"], terms)
                ref = {"id": row["session_uid"]}
                if kind == "message":
                    ref["event_uid"] = row["ref"]
                hits.append(_hit(kind, row["ref"], row["title"] or text[:60], text, marks, row,
                                 ref))
        out[kind] = hits
    return out


def _hit(kind, id_, title, text, marks, row=None, ref=None) -> dict:
    row = row or {}
    get = (lambda k: row[k] if k in row.keys() else None) if row else (lambda _k: None)
    return {"kind": kind, "id": id_, "title": title, "snippet": text, "marks": marks,
            "session_uid": get("session_uid"), "project_id": get("project_id"),
            "agent": get("agent"), "ts": get("ts"), "score": 0.0,
            "ref": {"page": PAGES[kind], **(ref or {"id": id_})}}


def _project_source(tandem_db, parsed, scope) -> dict[str, list[dict]]:
    conn = _ro(tandem_db)
    if conn is None:
        return {"project": []}
    where, args = _like_all("p.name", parsed["terms"])
    if scope.get("project_ids"):
        where += f" AND p.project_id IN ({','.join('?' * len(scope['project_ids']))})"
        args += list(scope["project_ids"])
    rows = conn.execute(
        "SELECT p.project_id, p.name, (SELECT MAX(started_at) FROM session s "
        f"WHERE s.project_id=p.project_id) AS ts FROM project p WHERE {where} "
        f"ORDER BY length(p.name), p.name LIMIT {PER_SOURCE}", args).fetchall()
    hits = []
    for r in rows:
        text, marks = snippet(r["name"], parsed["terms"])
        hit = _hit("project", r["project_id"], r["name"], text, marks, r)
        hit["project_id"] = r["project_id"]
        hits.append(hit)
    return {"project": hits}


def _inventory_source(tandem_db, linked, parsed, scope) -> dict[str, list[dict]]:
    terms = [t.casefold() for t in parsed["terms"]]
    agents = set(scope.get("agent_ids") or ())
    rows = []
    if linked is not None:
        data = linked()
        items = data.get("items", []) if isinstance(data, dict) else list(data or [])
        rows = [i for i in items if all(t in str(i.get("name", "")).casefold() for t in terms)]
    else:
        conn = _ro(tandem_db)
        if conn is not None and _has_table(conn, "inventory_item"):
            where, args = _like_all("i.name", parsed["terms"])
            rows = [dict(r) for r in conn.execute(
                "SELECT i.inv_id, i.name, i.type, s.agent, s.project_id FROM inventory_item i "
                "JOIN inventory_scan s ON s.scan_id=i.scan_id WHERE i.scan_id IN "
                "(SELECT MAX(scan_id) FROM inventory_scan GROUP BY source_key) "
                f"AND {where} ORDER BY length(i.name), i.name LIMIT {PER_SOURCE}", args)]
    hits = []
    for item in rows:
        if agents and item.get("agent") not in agents:
            continue
        text, marks = snippet(f"{item['name']} · {item.get('type', '')}", parsed["terms"])
        hit = _hit("inventory", item["inv_id"], item["name"], text, marks)
        hit.update(agent=item.get("agent"), project_id=item.get("project_id"))
        hits.append(hit)
    return {"inventory": hits[:PER_SOURCE]}


def _catalog_tokens(q: str) -> list[str]:
    return lexical_tokens(q) if lexical_tokens is not None else q.lower().split()


def _catalog_source(catalog_db, parsed) -> dict[str, list[dict]]:
    conn = _ro(catalog_db)
    if conn is None or not _has_table(conn, "catalog_item"):
        return {"catalog": []}
    name_where, name_args = _like_all("name", parsed["terms"])
    summary_where, summary_args = _like_all("summary", parsed["terms"])
    rows = list(conn.execute(
        "SELECT item_id, type, name, summary FROM catalog_item WHERE status='active' AND "
        f"(({name_where}) OR ({summary_where})) ORDER BY ({name_where}) DESC, official DESC, "
        "item_id LIMIT 5", [*name_args, *summary_args, *name_args]))
    seen = {r["item_id"] for r in rows}
    tokens = _catalog_tokens(parsed["q"])
    if len(rows) < 5 and tokens and _has_table(conn, "chunk_fts"):
        expr = " AND ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(tokens))
        ids = [r[0] for r in conn.execute(
            "SELECT item_id FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY bm25(chunk_fts) "
            "LIMIT 20", (expr,)) if r[0] not in seen]
        ids = list(dict.fromkeys(ids))[:5 - len(rows)]
        if ids:
            extra = {r["item_id"]: r for r in conn.execute(
                f"SELECT item_id, type, name, summary FROM catalog_item WHERE item_id IN "
                f"({','.join('?' * len(ids))}) AND status='active'", ids)}
            rows += [extra[i] for i in ids if i in extra]
    hits = []
    for r in rows:
        text, marks = snippet(f"{r['name']} — {r['summary']}", parsed["terms"])
        hits.append(_hit("catalog", r["item_id"], r["name"], text, marks))
    return {"catalog": hits}


def _recommendation_source(app_db, parsed) -> dict[str, list[dict]]:
    """Titles of passed candidates in recommend's ``rec_candidate`` (newest run per rec_key);
    a legacy ``candidate(candidate_id?, title)`` table is still read when present."""
    conn = _ro(app_db)
    if conn is None:
        return {"recommendation": []}
    hits = []
    if _has_table(conn, "rec_candidate", "rec_key"):
        where, args = _like_all("title", parsed["terms"])
        sql = ("SELECT candidate_id, rec_key, title, MAX(created_at) AS ts FROM rec_candidate "
               f"WHERE passed = 1 AND {where} GROUP BY rec_key ORDER BY ts DESC "
               f"LIMIT {PER_SOURCE}")
        for r in conn.execute(sql, args):
            text, marks = snippet(r["title"], parsed["terms"])
            hits.append(_hit("recommendation", r["candidate_id"], r["title"], text, marks, r,
                             ref={"id": r["candidate_id"], "rec_key": r["rec_key"]}))
    elif _has_table(conn, "candidate", "title"):
        columns = {r[1] for r in conn.execute("PRAGMA table_info(candidate)")}
        key = "candidate_id" if "candidate_id" in columns else "rowid"
        where, args = _like_all("title", parsed["terms"])
        for r in conn.execute(f"SELECT {key} AS id, title FROM candidate WHERE {where} "
                              f"LIMIT {PER_SOURCE}", args):
            text, marks = snippet(r["title"], parsed["terms"])
            hits.append(_hit("recommendation", str(r["id"]), r["title"], text, marks))
    return {"recommendation": hits}


def _event_source(tandem_db, parsed, scope, deadline=None) -> dict[str, list[dict]]:
    """Events from tandem.db's own text index (messages and titles on v8+ stores).

    Storage v8+ has ``event_search``: contentless trigram, so terms of 3+ characters (CJK
    included) match as substrings, shorter terms filter the matched rows with LIKE, and
    ``snippet()`` is unavailable. Older stores have unicode61 ``event_fts``, which matches
    latin words by prefix. A query with no term the index can match scans the newest
    ``EVENT_LIKE_ROWS`` events with LIKE; when that leaves older events unsearched the kind
    is reported partial (``short_query_window``). Snippets are cut in Python for both.
    """
    conn = _ro(tandem_db)
    if conn is None:
        return {"event": []}
    if deadline is not None:  # a LIKE scan must not outlive its budget
        conn.set_progress_handler(lambda: time.perf_counter() > deadline + 0.05, 2000)
    try:
        return _event_query(conn, parsed, scope)
    finally:
        if deadline is not None:
            conn.set_progress_handler(None, 0)


def _event_query(conn, parsed, scope) -> dict:
    terms = parsed["terms"]
    if _has_table(conn, "event_search"):
        table, match, rest = "event_search", parsed["match"], parsed["like"]
    elif _has_table(conn, "event_fts"):
        latin = [t for t in terms if re.fullmatch(r"[A-Za-z0-9_]+", t)]
        table, match = "event_fts", " AND ".join(f'"{t}"*' for t in latin) or None
        rest = [t for t in terms if t not in latin]
    else:
        table, match, rest = None, None, terms
    if match is None:
        rest = terms
    like_sql, like_args = _like_all("e.text", rest) if rest else ("", [])
    scope_sql, scope_args = _scope_sql(scope, "x.")
    cols = "e.event_uid, e.session_uid, e.ts, e.text, s.project_id, s.title, src.agent"
    joins = ("LEFT JOIN session s ON s.session_uid=e.session_uid "
             "LEFT JOIN source src ON src.source_id=s.source_id")
    out: dict = {}
    if match:
        # Same trade-off as the index source: past BM25_CAP matches, newest first.
        common = conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} WHERE {table} "
                              f"MATCH ? LIMIT {BM25_CAP})", (match,)).fetchone()[0]
        order = "x.rid DESC" if common >= BM25_CAP else "x.b"
        sql = (f"SELECT * FROM (SELECT {cols}, f.rowid AS rid, bm25({table}) AS b "
               f"FROM {table} f JOIN event e ON e.rowid=f.rowid {joins} "
               f"WHERE {table} MATCH ?{' AND ' + like_sql if like_sql else ''}) x "
               f"WHERE 1{scope_sql} ORDER BY {order} LIMIT {PER_SOURCE}")
        args = [match, *like_args, *scope_args]
    else:
        low, high = conn.execute("SELECT (SELECT MIN(rowid) FROM event), "
                                 "(SELECT MAX(rowid) FROM event)").fetchone()
        floor = (high or 0) - EVENT_LIKE_ROWS
        sql = (f"SELECT * FROM (SELECT {cols}, e.rowid AS rid FROM event e {joins} "
               f"WHERE e.rowid > ? AND +e.kind IN ({','.join('?' * len(EVENT_KINDS))}) "
               f"AND {like_sql}) x WHERE 1{scope_sql} ORDER BY x.rid DESC LIMIT {PER_SOURCE}")
        args = [floor, *EVENT_KINDS, *like_args, *scope_args]
    hits = []
    for r in conn.execute(sql, args):
        text, marks = snippet(r["text"], terms)
        hits.append(_hit("event", r["event_uid"], r["title"] or text[:60], text, marks, r,
                         {"id": r["session_uid"], "event_uid": r["event_uid"]}))
    out["event"] = hits
    # A full page is the exact newest-first top; a short page from a window that did not
    # reach the oldest event may be missing older matches.
    if not match and low is not None and low <= floor and len(hits) < PER_SOURCE:
        out[PARTIAL] = {"event": "short_query_window"}
    return out


# -- index lifecycle -----------------------------------------------------------------------
def _ensure_index(index: SearchIndex, tandem_db: Path | None, data_rev) -> dict:
    status = index.status()
    if tandem_db is None or not Path(tandem_db).is_file() or status["state"] == "building":
        return status
    if status["state"] == "empty":
        conn = _ro(tandem_db)
        sessions = conn.execute("SELECT COUNT(*) FROM session").fetchone()[0]
        if sessions <= SYNC_INLINE_SESSIONS:
            index.sync(tandem_db, data_rev)
            return index.status()
    elif not data_rev or status["data_rev"] == str(data_rev):
        return status
    threading.Thread(target=index.sync, args=(tandem_db, data_rev), kwargs={"wait": False},
                     daemon=True, name="tandem-search-index").start()
    return {**status, "state": "building"} if status["state"] == "empty" else status


# -- entry point ---------------------------------------------------------------------------
def search(home: Path, q: str, *, kinds=None, scope=None, limit: int = 20, data_rev=0,
           tandem_db: Path | None = None, catalog_db: Path | None = None,
           app_db: Path | None = None, linked=None, executor=None,
           index: SearchIndex | None = None, now_ms: int | None = None,
           timeout_s: float = TIMEOUT_S, max_wait_s: float = MAX_WAIT_S) -> dict:
    started = time.perf_counter()
    parsed = parse(q)
    wanted = tuple(dict.fromkeys(kinds or DEFAULT_KINDS))
    unknown = [k for k in wanted if k not in KINDS]
    if unknown:
        raise ValueError(f"unknown kinds: {', '.join(unknown)}")
    scope = {k: v for k, v in (scope or {}).items() if v not in (None, [], ())}
    limit = max(1, min(50, int(limit)))
    home = Path(home)
    tandem_db = tandem_db or home / "tandem.db"
    catalog_db = catalog_db or home / "catalog.db"
    app_db = app_db or home / "app.db"
    index = index or get_index(home)
    index_status = _ensure_index(index, tandem_db, data_rev)

    tasks = {}
    index_kinds = tuple(k for k in wanted if k in INDEX_KINDS)
    if index_kinds and (index_status["state"] == "ready" or index_status["docs"]):
        for kind in index_kinds:  # one task per kind: a slow kind does not drop the others
            tasks[(kind,)] = (_index_source, index, (kind,), parsed, scope)
    if "project" in wanted:
        tasks[("project",)] = (_project_source, tandem_db, parsed, scope)
    if "inventory" in wanted:
        tasks[("inventory",)] = (_inventory_source, tandem_db, linked, parsed, scope)
    if "catalog" in wanted:
        tasks[("catalog",)] = (_catalog_source, catalog_db, parsed)
    if "recommendation" in wanted:
        tasks[("recommendation",)] = (_recommendation_source, app_db, parsed)
    if "event" in wanted:
        tasks[("event",)] = (_event_source, tandem_db, parsed, scope)

    lists, reasons = _run_sources(tasks, executor or _executor, timeout_s,
                                  started + max(max_wait_s, timeout_s))
    # First build still running in the background: those kinds are missing, not empty.
    if index_kinds and not any((k,) in tasks for k in index_kinds) \
            and index_status["state"] == "building":
        reasons.update({k: "index_building" for k in index_kinds})
    partial = list(reasons)

    # Fusion: per-source RRF, weighted by kind, decayed by age.
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    counts = {kind: len(hits) for kind, hits in lists.items()}
    fused = []
    for kind, hits in lists.items():
        for rank, hit in enumerate(hits[:FUSE_TOP], 1):
            score = WEIGHTS[kind] / (60 + rank)
            ts = hit.get("ts")
            score *= 0.85 if ts is None else (
                0.7 + 0.3 * math.exp(-max(0.0, now_ms - ts) / DAY_MS / 90))
            hit["score"] = round(score, 6)
            fused.append(hit)
    fused.sort(key=lambda h: (-h["score"], h["kind"], str(h["id"])))
    results, per_session = [], {}
    for hit in fused:
        if hit["kind"] == "message":
            seen = per_session.get(hit["session_uid"], 0)
            if seen >= MAX_MESSAGES_PER_SESSION:
                continue
            per_session[hit["session_uid"]] = seen + 1
        results.append(hit)
        if len(results) >= limit:
            break
    return {"q": parsed["q"], "took_ms": round((time.perf_counter() - started) * 1000, 2),
            "index": index_status, "counts": counts,
            # A kind that hit the per-source cap has at least this many matches.
            "counts_at_least": sorted(k for k, n in counts.items() if n >= PER_SOURCE),
            "results": results, "partial": sorted(set(partial)),
            "partial_reasons": dict(sorted(reasons.items())), "complete": not partial}


def _run_sources(tasks: dict, pool, budget_s: float, hard_deadline: float):
    """Run source tasks; returns (hits by kind, {kind: reason} for missing or partial kinds).

    A task's deadline starts when it starts running. A task still queued at the request's
    hard deadline is cancelled. When the bounded queue is full, sources are shed up front.
    A source may add ``{PARTIAL: {kind: reason}}`` to its result for hits it knows are incomplete.
    """
    lists: dict[str, list[dict]] = {}
    reasons: dict[str, str] = {}
    if not tasks:
        return lists, reasons
    if not _admit(len(tasks)):
        return lists, {k: "overloaded" for group in tasks for k in group}
    futures = {}
    for group, (fn, *args) in tasks.items():
        task = _Task(group, fn, args, budget_s)
        try:
            futures[pool.submit(task)] = task
        except RuntimeError:  # pool shut down
            _release(1)
            reasons.update({k: "error" for k in group})
    pending = set(futures)
    while pending:
        now = time.perf_counter()
        next_at = hard_deadline
        for future in list(pending):
            if future.done():
                pending.discard(future)
                continue
            task = futures[future]
            at = hard_deadline if task.deadline is None else min(task.deadline, hard_deadline)
            if now >= at:
                pending.discard(future)
                if future.cancel():  # never started: give its slot back
                    _release(1)
                    reasons.update({k: "queued_timeout" for k in task.group})
                else:
                    reasons.update({k: "timeout" for k in task.group})
            else:
                next_at = min(next_at, at)
        if pending:
            wait(pending, timeout=max(0.0, next_at - now), return_when=FIRST_COMPLETED)
    for future, task in futures.items():
        if not future.done() or future.cancelled() or any(k in reasons for k in task.group):
            continue
        if future.exception() is not None:
            reasons.update({k: "error" for k in task.group})
            continue
        result = dict(future.result())
        reasons.update(result.pop(PARTIAL, {}))
        lists.update(result)
    return lists, reasons


def scope_from_query(project_ids=None, agent_ids=None, from_ts=None, until_ts=None) -> dict:
    split = lambda v: [x for x in (v or "").split(",") if x]  # noqa: E731
    return {"project_ids": split(project_ids), "agent_ids": split(agent_ids),
            "from_ts": from_ts, "until_ts": until_ts}

