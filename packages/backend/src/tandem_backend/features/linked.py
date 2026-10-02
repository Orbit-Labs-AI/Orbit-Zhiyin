"""Entity linking: installed component <-> catalog item <-> session usage (DT-09, AN-11, RC-07).

``compute_linked`` reads one connection laid out as main=app.db, t=tandem.db and an optional
c=catalog.db. It never writes tandem.db or catalog.db; link and size caches go to app.db only
through the caller's ``write(fn)`` callback. A component whose usage cannot be attributed is
reported as ``unknown_usage`` -- never as zero calls.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

DAY_MS = 86_400_000
MAX_TEXT = 256 * 1024
CATALOG_TYPE = {"skill": "skill", "mcp": "mcp_server", "hook": "hook", "plugin": "plugin",
                "rule": "rule"}
ATTRIBUTABLE = {"skill": "tool_call.skill", "mcp": "tool_call.mcp_server"}
CJK = re.compile(r"[　-ヿ㐀-鿿가-힯豈-﫿＀-￯]")

_catalog_cache: dict[tuple, dict] = {}
_result_cache: OrderedDict[tuple, dict] = OrderedDict()
_lock = threading.Lock()


def norm(name: str | None) -> str:
    value = re.sub(r"[-_ .:/@]+", "_", (name or "").casefold()).strip("_")
    for prefix in ("plugin_", "mcp_"):
        if value.startswith(prefix) and len(value) > len(prefix):
            value = value[len(prefix):]
    return value


def default_read_text(path: str) -> str | None:
    try:
        target = Path(path)
        if target.is_dir():
            target = target / "SKILL.md"
        if target.stat().st_size > MAX_TEXT:
            with target.open("rb") as handle:
                return handle.read(MAX_TEXT).decode("utf-8", "ignore")
        return target.read_text(encoding="utf-8", errors="ignore")
    except (OSError, ValueError):
        return None


def estimate_tokens(text: str) -> int:
    cjk = len(CJK.findall(text))
    return math.ceil((len(text) - cjk) / 3.6 + cjk * 1.5)


SKILL_BASIS, FILE_BASIS = "skill_frontmatter", "file_bytes_estimate"
_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")


def _frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Top-level ``key: value`` pairs of a YAML header (block scalars and indented
    continuations folded in) plus the body; None without a header."""
    if not text.startswith("---"):
        return None
    parts = text[3:].split("\n---", 1)
    if len(parts) != 2:
        return None
    header, body = parts
    keys: dict[str, str] = {}
    current = None
    for line in header.splitlines():
        match = _KEY.match(line)
        if match and not line[:1].isspace():
            current = match.group(1)
            value = match.group(2).strip()
            keys[current] = "" if value in ("|", ">", "|-", ">-", "|+", ">+") else value.strip("'\"")
        elif current and line[:1].isspace():
            keys[current] = (keys[current] + " " + line.strip()).strip()
    return keys, body


def resident_text(kind: str, text: str) -> str:
    """What loads up front: a skill only puts its ``name`` + ``description`` in context (the
    body and other metadata load on use); rules load in full."""
    if kind != "skill":
        return text
    parsed = _frontmatter(text)
    if parsed is not None:
        keys, body = parsed
        if keys.get("name") or keys.get("description"):
            return f"{keys.get('name', '')}: {keys.get('description', '')}"
        text = body
    first = next((p for p in re.split(r"\n\s*\n", text.lstrip("-\n")) if p.strip()), "")
    return first[:1024]


def size_basis(kind: str) -> str:
    return SKILL_BASIS if kind == "skill" else FILE_BASIS


def clear_cache() -> None:
    with _lock:
        _catalog_cache.clear()
        _result_cache.clear()


def _has(conn: sqlite3.Connection, schema: str, table: str, columns=()) -> bool:
    try:
        if not conn.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name=?",
                            (table,)).fetchone():
            return False
        names = {row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})")}
    except sqlite3.Error:
        return False
    return all(column in names for column in columns)


def _attached(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT file FROM pragma_database_list WHERE name=?", (name,)).fetchone()
    return None if row is None else (row[0] or "")


def _inventory(conn, project_ids, agent) -> tuple[list[dict], list[dict]]:
    """Latest scan per source_key; same semantics as tandem_data.inventory, under ``t.``."""
    if not _has(conn, "t", "inventory_scan"):
        return [], []
    projects = json.dumps(sorted(project_ids)) if project_ids is not None else None
    scans = [dict(row) for row in conn.execute(
        "SELECT * FROM t.inventory_scan WHERE scan_id IN (SELECT MAX(scan_id) FROM t.inventory_scan "
        "WHERE (:p IS NULL OR scope='global' OR project_id IN (SELECT value FROM json_each(:p))) "
        "GROUP BY source_key) AND (:a IS NULL OR agent=:a) ORDER BY scan_id",
        {"p": projects, "a": agent})]
    if not scans:
        return [], []
    paths = {}
    for project in conn.execute("SELECT project_id,key_type,key,paths FROM t.project"):
        for path in json.loads(project["paths"]):
            paths[path] = project["project_id"]
        if project["key_type"] == "path":
            paths[project["key"]] = project["project_id"]
    items = []
    for scan in scans:
        for row in conn.execute("SELECT * FROM t.inventory_item WHERE scan_id=? "
                                "ORDER BY type,name,inv_id", (scan["scan_id"],)):
            item = dict(row)
            item["config"] = json.loads(item["config"])
            item.update({k: scan[k] for k in ("agent", "scope", "project_id", "observed_at")})
            project_path = item["config"].get("project_path")
            if project_path is not None or item["config"].get("scope") in ("project", "local"):
                item["scope"] = "project"
                item["project_id"] = paths.get(project_path)
            if (project_ids is not None and item["scope"] == "project"
                    and item["project_id"] not in project_ids):
                continue
            items.append(item)
    return scans, items


def _catalog(conn, rev) -> dict | None:
    path = _attached(conn, "c")
    if path is None or not _has(conn, "c", "catalog_item"):
        return None
    key = (path, rev)
    with _lock:
        cached = _catalog_cache.get(key)
    if cached is not None:
        return cached
    by_name, by_hash, by_id = {}, {}, {}
    for row in conn.execute("SELECT item_id,type,name,url,official,content_hash,metadata "
                            "FROM c.catalog_item WHERE status='active' "
                            "ORDER BY official DESC, item_id"):
        item = {k: row[k] for k in ("item_id", "type", "name", "url", "official")}
        by_id[item["item_id"]] = item
        by_name.setdefault((row["type"], norm(row["name"])), item)
        try:
            body = json.loads(row["metadata"] or "{}").get("body_sha256")
        except (ValueError, AttributeError):
            body = None
        if isinstance(body, str) and body:  # raw-byte sha256 hex, optionally "sha256:"-prefixed
            by_hash.setdefault(body.removeprefix("sha256:").lower(), item)
    index = {"name": by_name, "hash": by_hash, "id": by_id}
    with _lock:
        for stale in [k for k in _catalog_cache if k[0] == path]:
            del _catalog_cache[stale]
        _catalog_cache[key] = index
    return index


def _match(item, catalog) -> tuple[dict, str, float] | None:
    ctype = CATALOG_TYPE.get(item["type"])
    if ctype is None:
        return None
    hit = catalog["hash"].get(item["content_hash"])
    if hit is not None and hit["type"] == ctype:
        return hit, "hash", 0.95
    hit = catalog["name"].get((ctype, norm(item["name"])))
    if hit is not None:
        return hit, "name", 0.8
    base = re.split(r"[@:]", item["name"], maxsplit=1)
    if len(base) == 2:
        for part in base:
            hit = catalog["name"].get((ctype, norm(part)))
            if hit is not None:
                return hit, "alias", 0.6
    return None


def _ledger(conn, items, catalog) -> dict[str, str]:
    """inv_id -> catalog item id for components Tandem installed from the catalog.

    Explicit ``inv_id``/``catalog_item_id`` ledger columns win; rows without them (older
    entries, installs whose inventory id was unknown) fall back to install's real tables: live
    ``install_state`` rows with ``source_type='catalog'`` and the paths their ``install`` ledger
    entries wrote. A shared config file (e.g. several MCP servers in one JSON) only links when
    the catalog name matches the component.
    """
    explicit: dict[str, str] = {}
    if _has(conn, "main", "install_ledger", ("inv_id", "catalog_item_id")):
        explicit = {r[0]: r[1] for r in conn.execute(
            "SELECT inv_id, catalog_item_id FROM main.install_ledger "
            "WHERE inv_id IS NOT NULL AND catalog_item_id IS NOT NULL ORDER BY rowid")}
    if not (_has(conn, "main", "install_ledger", ("path",))
            and _has(conn, "main", "install_state", ("source_type", "source_id", "state"))):
        return explicit
    by_path: dict[str, set[str]] = {}
    for path, item_id in conn.execute(
            "SELECT l.path, s.source_id FROM main.install_ledger l "
            "JOIN main.install_state s ON s.install_id = l.install_id "
            "WHERE l.action = 'install' AND l.path IS NOT NULL AND s.source_type = 'catalog' "
            "AND s.source_id IS NOT NULL AND s.state != 'reverted'"):
        by_path.setdefault(_norm_path(path), set()).add(item_id)
    out = {}
    for item in items:
        ids = by_path.get(_norm_path(item["config_path"]))
        if not ids:
            continue
        if len(ids) == 1:
            out[item["inv_id"]] = next(iter(ids))
            continue
        known = (catalog or {}).get("id", {})
        named = [i for i in sorted(ids) if i in known and norm(known[i]["name"]) == norm(item["name"])]
        if named:
            out[item["inv_id"]] = named[0]
    return out | explicit


def _norm_path(path: str) -> str:
    return os.path.normpath(os.path.expanduser(path))


def _usage(conn, column, d30, d90, project_ids) -> dict[tuple[str, str], dict]:
    """One grouped query per usage column; keys are (normalized name, agent)."""
    sql = (f"SELECT lower(t.{column}) k, src.agent agent, COUNT(*) total, "
           "SUM(t.started_at>=:d30) c30, SUM(t.started_at>=:d90) c90, "
           "COUNT(DISTINCT t.session_uid) sessions, MAX(t.started_at) last_used, "
           "SUM(t.status IN ('error','failed')) errors FROM t.tool_call t "
           "JOIN t.session s ON s.session_uid=t.session_uid "
           "JOIN t.source src ON src.source_id=s.source_id "
           f"WHERE t.{column} IS NOT NULL AND (:p IS NULL OR t.project_id IN "
           "(SELECT value FROM json_each(:p))) GROUP BY 1,2")
    params = {"d30": d30, "d90": d90,
              "p": json.dumps(sorted(project_ids)) if project_ids is not None else None}
    out: dict[tuple[str, str], dict] = {}
    for row in conn.execute(sql, params):
        keys = {norm(row["k"])}
        if ":" in row["k"]:
            keys.add(norm(row["k"].split(":", 1)[1]))
        for key in keys:
            slot = out.setdefault((key, row["agent"]), {
                "total": 0, "c30": 0, "c90": 0, "sessions": 0, "last_used": None, "errors": 0})
            for field in ("total", "c30", "c90", "sessions", "errors"):
                slot[field] += row[field] or 0
            if row["last_used"] is not None:
                slot["last_used"] = max(slot["last_used"] or 0, row["last_used"])
    return out


def _usage_for(item, table) -> dict:
    basis = ATTRIBUTABLE.get(item["type"])
    if basis is None or table is None:
        return {"calls_total": None, "calls_30d": None, "calls_90d": None, "sessions": None,
                "last_used_at": None, "error_rate": None, "attributable": False,
                "basis": "not_attributable" if basis is None else "usage_unavailable"}
    key = norm(item["name"])
    keys = {key} | ({norm(item["name"].split(":", 1)[1])} if ":" in item["name"] else set())
    every_agent = item["agent"] == "common" or item["scope"] == "project"
    total = {"total": 0, "c30": 0, "c90": 0, "sessions": 0, "last_used": None, "errors": 0}
    for (name, agent), slot in table.items():
        if name in keys and (every_agent or agent == item["agent"]):
            for field in ("total", "c30", "c90", "sessions", "errors"):
                total[field] += slot[field]
            if slot["last_used"] is not None:
                total["last_used"] = max(total["last_used"] or 0, slot["last_used"])
    return {"calls_total": total["total"], "calls_30d": total["c30"], "calls_90d": total["c90"],
            "sessions": total["sessions"], "last_used_at": total["last_used"],
            "error_rate": round(total["errors"] / total["total"], 4) if total["total"] else None,
            "attributable": True, "basis": basis}


def compute_linked(conn: sqlite3.Connection, *, revs: dict, now_ms: int | None = None,
                   project_ids=None, agent: str | None = None,
                   write: Callable[[Callable[[sqlite3.Connection], None]], None] | None = None,
                   read_text: Callable[[str], str | None] | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    projects = frozenset(project_ids) if project_ids is not None else None
    catalog_rev = str(revs.get("catalog"))
    cache_key = (_attached(conn, "t"), _attached(conn, "c"), revs.get("data"),
                 revs.get("inventory"), catalog_rev, projects, agent)
    with _lock:
        if cache_key in _result_cache:
            _result_cache.move_to_end(cache_key)
            return _result_cache[cache_key]
    read_text = read_text or default_read_text
    scans, items = _inventory(conn, projects, agent)

    # Catalog links: confirmed > ledger > cached same-rev > hash > name > alias.
    catalog = _catalog(conn, catalog_rev)
    has_links = _has(conn, "main", "inv_link")
    links = ({r["inv_id"]: dict(r) for r in conn.execute("SELECT * FROM main.inv_link")}
             if has_links else {})
    ledger = _ledger(conn, items, catalog)
    upserts, matches = [], {}
    for item in items:
        inv_id, link = item["inv_id"], links.get(item["inv_id"])
        if link and link["confirmed"]:
            matches[inv_id] = (link["catalog_item_id"], link["method"], link["confidence"])
            continue
        if inv_id in ledger:
            found = (ledger[inv_id], "ledger", 1.0)
        elif link and link["catalog_rev"] == catalog_rev:
            found = (link["catalog_item_id"], link["method"], link["confidence"])
        elif catalog is not None:
            hit = _match(item, catalog)
            found = (hit[0]["item_id"], hit[1], hit[2]) if hit else None
        else:
            found = None
        if found is None:
            continue
        matches[inv_id] = found
        if not link or (link["catalog_item_id"], link["method"], link["catalog_rev"]) != (
                found[0], found[1], catalog_rev):
            upserts.append((inv_id, found[0], found[1], found[2], catalog_rev))

    # Usage: one grouped query per attributable column, plus agent-level hook runs.
    d30, d90 = now_ms - 30 * DAY_MS, now_ms - 90 * DAY_MS
    usage = {}
    if _has(conn, "t", "tool_call"):
        usage = {"skill": _usage(conn, "skill", d30, d90, projects),
                 "mcp": _usage(conn, "mcp_server", d30, d90, projects)}
    hook_runs = {}
    if _has(conn, "t", "event"):
        hook_runs = {r[0]: r[1] for r in conn.execute(
            "SELECT src.agent, COUNT(*) FROM t.event e JOIN t.session s ON s.session_uid=e.session_uid "
            "JOIN t.source src ON src.source_id=s.source_id WHERE e.kind='hook.run' GROUP BY 1")}
    first = None
    if _has(conn, "t", "session"):
        first = conn.execute(
            "SELECT MIN(s.started_at) FROM t.session s JOIN t.source src ON src.source_id=s.source_id "
            "WHERE :a IS NULL OR src.agent=:a", {"a": agent}).fetchone()[0]
    span_days = (now_ms - first) / DAY_MS if first is not None else 0.0

    # Resident overhead, cached by content_hash in inv_size.
    has_size = _has(conn, "main", "inv_size")
    sizes = {}
    if has_size:
        hashes = sorted({i["content_hash"] for i in items if i["type"] in ("skill", "rule")})
        for start in range(0, len(hashes), 500):
            chunk = hashes[start:start + 500]
            sizes.update({r[0]: (r[1], r[2]) for r in conn.execute(
                f"SELECT content_hash,tokens_est,basis FROM main.inv_size WHERE content_hash IN "
                f"({','.join('?' * len(chunk))})", chunk)})
    measured = []

    out, summary = [], {"total": 0, "unused": 0, "unknown_usage": 0, "disabled": 0,
                        "tandem_installed": 0, "resident_tokens_est": 0, "by_type": {}}
    for item in items:
        found = matches.get(item["inv_id"])
        entry = None
        if found is not None:
            row = (catalog or {}).get("id", {}).get(found[0], {})
            entry = {"item_id": found[0], "name": row.get("name"), "method": found[1],
                     "confidence": found[2], "url": row.get("url")}
        used = _usage_for(item, usage.get(item["type"]))
        if item["type"] in ("skill", "rule"):
            cached = sizes.get(item["content_hash"])
            if cached is not None and cached[1] == size_basis(item["type"]):  # older bases re-measure
                tokens, basis = cached
            else:
                text = read_text(item["config_path"])
                tokens = estimate_tokens(resident_text(item["type"], text)) if text is not None \
                    else None
                basis = size_basis(item["type"]) if text is not None else "unreadable"
                if text is not None:  # unreadable may be transient; retry next time
                    sizes[item["content_hash"]] = (tokens, basis)
                    measured.append((item["content_hash"], tokens, basis, now_ms))
        else:
            tokens, basis = None, "unknown"
        unused_days = None
        if item["enabled"] == 0:
            status = "disabled"
        elif not used["attributable"]:
            status = "unknown_usage"
        elif used["calls_90d"] == 0 and span_days >= 30:
            status = "unused"
            since = used["last_used_at"] if used["last_used_at"] is not None else first
            unused_days = int((now_ms - since) // DAY_MS)
        else:
            status = "active"
        installed = bool(found and found[1] == "ledger")
        out.append({
            "inv_id": item["inv_id"], "type": item["type"], "name": item["name"],
            "agent": item["agent"], "scope": item["scope"], "project_id": item["project_id"],
            "enabled": item["enabled"], "config_path": item["config_path"],
            "evidence": item["evidence"], "catalog": entry, "tandem_installed": installed,
            "usage": used, "resident": {"tokens_est": tokens, "basis": basis},
            "status": status, "unused_days": unused_days})
        bucket = summary["by_type"].setdefault(item["type"], {"total": 0, "unused": 0,
                                                              "unknown_usage": 0})
        bucket["total"] += 1
        summary["total"] += 1
        if status in ("unused", "unknown_usage", "disabled"):
            summary[status] += 1
            if status in bucket:
                bucket[status] += 1
        summary["tandem_installed"] += installed
        if tokens and item["enabled"] != 0:
            summary["resident_tokens_est"] += tokens
    summary["hook_runs_by_agent"] = hook_runs

    if write is not None and ((has_links and upserts) or (has_size and measured)):
        def persist(db: sqlite3.Connection) -> None:
            if has_links and upserts:
                db.executemany(
                    "INSERT INTO inv_link(inv_id,catalog_item_id,method,confidence,catalog_rev) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(inv_id) DO UPDATE SET "
                    "catalog_item_id=excluded.catalog_item_id, method=excluded.method, "
                    "confidence=excluded.confidence, catalog_rev=excluded.catalog_rev "
                    "WHERE inv_link.confirmed=0", upserts)
            if has_size and measured:
                db.executemany("INSERT OR REPLACE INTO inv_size VALUES(?,?,?,?)", measured)
        write(persist)

    observed = max((s["observed_at"] for s in scans), default=None)
    result = {
        "items": out, "summary": summary,
        "coverage": {"inventory": {"status": "available" if scans else "unavailable",
                                   "scans": len(scans), "observed_at": observed},
                     "catalog": "available" if catalog is not None else "unavailable",
                     "data_span_days": round(span_days, 2)},
        "revs": revs}
    with _lock:
        _result_cache[cache_key] = result
        while len(_result_cache) > 32:
            _result_cache.popitem(last=False)
    return result


def open_connection(home: Path) -> sqlite3.Connection:
    """main=app.db, t=tandem.db, c=catalog.db (when present), all read-only."""
    conn = sqlite3.connect(Path(home, "app.db").resolve().as_uri() + "?mode=ro", uri=True,
                           check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("ATTACH DATABASE ? AS t", (Path(home, "tandem.db").resolve().as_uri() + "?mode=ro",))
    catalog = Path(home, "catalog.db")
    if catalog.is_file():
        conn.execute("ATTACH DATABASE ? AS c", (catalog.resolve().as_uri() + "?mode=ro",))
    return conn


def catalog_rev(conn: sqlite3.Connection) -> str | None:
    if not _has(conn, "c", "catalog_meta"):
        return None
    row = conn.execute("SELECT value FROM c.catalog_meta WHERE key='generation'").fetchone()
    return row[0] if row else None
