"""Unified search (DT-23, SB-03 / ⌘K): parallel sources fused with RRF and time decay.

Sources run on a small pool with a per-request deadline; a slow or failing source is listed in
``partial`` instead of failing the request. All databases are opened read-only; the only write
is the disposable trigram index (``search_index``). Text comes from redacted L2 rows as-is.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
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
TIMEOUT_S = 0.15
PER_SOURCE = 100
BM25_CAP = 1000
FUSE_TOP = 50
MAX_MESSAGES_PER_SESSION = 2
SYNC_INLINE_SESSIONS = 20_000
DAY_MS = 86_400_000

_executor = ThreadPoolExecutor(4, thread_name_prefix="tandem-search")
_local = threading.local()


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


def _index_source(index: SearchIndex, kinds, parsed, scope) -> dict[str, list[dict]]:
    conn = index.reader()
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


def _event_source(tandem_db, parsed, scope) -> dict[str, list[dict]]:
    conn = _ro(tandem_db)
    latin = [t for t in parsed["terms"] if re.fullmatch(r"[A-Za-z0-9_]+", t)]
    if conn is None or not latin or not _has_table(conn, "event_fts"):
        return {"event": []}
    expr = " AND ".join(f'"{t}"*' for t in latin)
    scope_sql, scope_args = _scope_sql({k: v for k, v in scope.items() if k != "agent_ids"},
                                       "x.")
    sql = ("SELECT * FROM (SELECT e.event_uid, e.session_uid, e.ts, s.project_id, s.title, "
           "snippet(event_fts,0,'\x01','\x02','…',12) AS sn, bm25(event_fts) AS b "
           "FROM event_fts JOIN event e ON e.rowid=event_fts.rowid "
           "LEFT JOIN session s ON s.session_uid=e.session_uid WHERE event_fts MATCH ?) x "
           f"WHERE 1{scope_sql} ORDER BY b LIMIT 50")
    hits = []
    for r in conn.execute(sql, [expr, *scope_args]):
        text, marks = strip_marks(r["sn"])
        hits.append(_hit("event", r["event_uid"], r["title"] or text[:60], text, marks, r,
                         {"id": r["session_uid"], "event_uid": r["event_uid"]}))
    return {"event": hits}


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
           timeout_s: float = TIMEOUT_S) -> dict:
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
        tasks[index_kinds] = (_index_source, index, index_kinds, parsed, scope)
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

    pool = executor or _executor
    futures = {pool.submit(fn, *args): group for group, (fn, *args) in tasks.items()}
    done, _pending = wait(futures, timeout=timeout_s)
    lists: dict[str, list[dict]] = {}
    # First build still running in the background: those kinds are missing, not empty.
    building = index_status["state"] == "building" and index_kinds not in tasks
    partial = list(index_kinds) if index_kinds and building else []
    for future, group in futures.items():
        if future not in done or future.exception() is not None:
            partial += list(group)
            continue
        lists.update(future.result())

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
            "index": index_status, "counts": counts, "results": results,
            "partial": sorted(set(partial))}


def scope_from_query(project_ids=None, agent_ids=None, from_ts=None, until_ts=None) -> dict:
    split = lambda v: [x for x in (v or "").split(",") if x]  # noqa: E731
    return {"project_ids": split(project_ids), "agent_ids": split(agent_ids),
            "from_ts": from_ts, "until_ts": until_ts}

