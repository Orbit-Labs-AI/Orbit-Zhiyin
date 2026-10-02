"""Context pack (AI-08): read-only, redacted, token-counted input for every AI task.

`build()` is the only way data reaches a model. Each pack item is loaded from
tandem.db (read-only) or app.db, passed through `redact.redact2`, clipped to its
contract limits (C4), counted, and previewed. `content` holds only enabled items
and is exactly what gets sent; `preview_digest` binds a later job to it.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import re
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from tandem_backend import privacy

from .redact import compact, est_tokens, redact_value

log = logging.getLogger(__name__)

DAY_MS = 86_400_000
MARKER = "[tandem-analysis"
CORRECTION_RE = re.compile(r"不是|不对|我说的是|别再|wrong|no,|again", re.I)
_CORRECTION_LIKE = ("不是", "不对", "我说的是", "别再", "wrong", "no,", "again")
VERIFY_RE = re.compile(r"pytest|npm (run )?test|pnpm (check|test)|cargo test|go test|make( test)?|tsc|ruff|eslint"
                       r"|swift (build|test)|xcodebuild")
OK_STATUS = ("success", "completed", "ok")
FAIL_STATUS = ("failed", "error")
LIMITS = {"human": 500, "assistant": 300, "error": 200}
FACET_SESSION_TOKENS = 6000
FACET_MAX_SESSIONS = 200
FACET_BATCH = 8


# ---------------------------------------------------------------- helpers

def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(task: dict, goal, content: dict) -> str:
    body = canonical_json({"task": task.get("task_id"), "pv": task.get("prompt_version"), "goal": goal,
                           "content": content})
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def content_hash(payload) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def lazy(module: str, attr: str):
    """Other areas are optional at runtime: return their entry point or None."""
    try:
        return getattr(importlib.import_module(module), attr, None)
    except Exception:  # noqa: BLE001 - any import failure means "not wired yet"
        return None


def now_ms() -> int:
    return int(time.time() * 1000)


def window(scope: dict | None) -> tuple[int, int, str | None]:
    """Scope → (start_ms, end_ms, project_id); default last 30 days."""
    scope = scope or {}
    if scope.get("start_ms") is not None or scope.get("end_ms") is not None:
        end = int(scope.get("end_ms") or now_ms())
        start = int(scope.get("start_ms") if scope.get("start_ms") is not None else end - 30 * DAY_MS)
    else:
        end = now_ms()
        start = end - int(scope.get("days") or 30) * DAY_MS
    return start, end, scope.get("project_id")


def session_filter(home: Path | None, alias: str = "s") -> tuple[str, list]:
    """Exclude sessions Tandem itself started (agent-cwd or marker first line)."""
    sql = (f" AND NOT EXISTS (SELECT 1 FROM event m WHERE m.session_uid={alias}.session_uid"
           f" AND m.seq<=5 AND m.kind='message.user' AND m.text LIKE ?)")
    params: list = [MARKER + "%"]
    if home is not None:
        sql = f" AND ({alias}.cwd IS NULL OR {alias}.cwd NOT LIKE ?)" + sql
        params.insert(0, str(Path(home) / "agent-cwd") + "%")
    return sql, params


def window_sql(start: int, end: int, project_id, home, alias: str = "s", *,
               source_ids=None, exclude=None) -> tuple[str, list]:
    """WHERE fragment selecting analysed main sessions of a window (optionally limited to
    ``source_ids`` and without the ``exclude`` session uids)."""
    sql = f"{alias}.kind='main' AND {alias}.started_at>=? AND {alias}.started_at<?"
    params: list = [start, end]
    if project_id:
        sql += f" AND {alias}.project_id=?"
        params.append(project_id)
    if source_ids:
        sql += f" AND {alias}.source_id IN ({placeholders(source_ids)})"
        params.extend(source_ids)
    if exclude:
        sql += f" AND {alias}.session_uid NOT IN ({placeholders(exclude)})"
        params.extend(exclude)
    extra, extra_params = session_filter(home, alias)
    return sql + extra, params + extra_params


FAILED_SQL = "'failed','error'"
KNOWN_SQL = FAILED_SQL + ",'completed','success'"


def _correction_sql(col: str = "h.text") -> str:
    return "(" + " OR ".join(f"{col} LIKE '%{w}%'" for w in _CORRECTION_LIKE) + ")"


def metrics(conn, start: int, end: int, project_id=None, home=None, *, source_ids=None,
            exclude=None) -> dict:
    where, params = window_sql(start, end, project_id, home, source_ids=source_ids,
                               exclude=exclude)
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(MAX(COALESCE(s.ended_at,s.started_at)-s.started_at,0)),0)"
        f" FROM session s WHERE {where} LIMIT 1", params).fetchone()
    sessions, span = row[0], row[1]
    sub = f"SELECT s.session_uid FROM session s WHERE {where}"
    h = conn.execute(f"SELECT COUNT(*), COALESCE(SUM({_correction_sql()}),0) FROM v_human_message h"
                     f" WHERE h.session_uid IN ({sub}) LIMIT 1", params).fetchone()
    t = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(t.status IN ({FAILED_SQL})),0),"
                     f" COALESCE(SUM(t.status IN ({KNOWN_SQL})),0) FROM tool_call t"
                     f" WHERE t.session_uid IN ({sub}) LIMIT 1", params).fetchone()
    msgs, corr, calls, fails, known = h[0], int(h[1]), t[0], int(t[1]), int(t[2])
    # Rates use known protocol outcomes only; unknown/declined calls are not successes.
    return {"sessions": sessions, "hours": round(span / 3_600_000, 1), "human_messages": msgs,
            "corrections": corr, "correction_rate": round(corr / msgs, 3) if msgs else 0.0,
            "tool_calls": calls, "tool_failures": fails, "tool_known_results": known,
            "tool_failure_rate": round(fails / known, 3) if known else None,
            "tool_unknown_share": round((calls - known) / calls, 3) if calls else None}


def fts_query(text: str) -> str:
    try:
        import jieba
        words = jieba.cut_for_search(text or "")
    except Exception:  # noqa: BLE001 - jieba is a soft dependency here
        words = re.findall(r"\w+", text or "")
    seen: list[str] = []
    for w in words:
        w = w.strip()
        if len(w) >= 2 and w not in seen:
            seen.append(w)
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in seen[:24])


def fts_human(conn, text: str, limit: int = 5) -> list[dict]:
    query = fts_query(text)
    if not query:
        return []
    rows = conn.execute(
        "SELECT e.event_uid, e.session_uid, e.text FROM event_fts f JOIN event e ON e.rowid = f.rowid"
        " WHERE event_fts MATCH ? AND e.event_uid IN (SELECT event_uid FROM v_human_message)"
        " ORDER BY bm25(event_fts) LIMIT ?", (query, limit)).fetchall()
    return [{"event_uid": r[0], "session_uid": r[1], "kind": "human",
             "text": privacy.direct_user_text(r[2] or "")} for r in rows]


def latest_scans_sql() -> str:
    return "SELECT MAX(scan_id) FROM inventory_scan GROUP BY source_key, root_path"


def placeholders(values) -> str:
    return ",".join("?" * len(values))


def features_profile(scope) -> dict:
    fn = lazy("tandem_backend.features", "profile")
    if fn is None:
        return {}
    try:
        value = fn(scope or {})
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 - features is optional; fall back to tandem.db
        log.debug("features.profile failed", exc_info=True)
        return {}


def catalog_search(query: str, k: int = 3) -> list[dict]:
    """Catalog hits through features.search (the gateway binds it); [] when not bound."""
    fn = lazy("tandem_backend.features", "search")
    if fn is None or not query:
        return []
    try:
        hits = (fn(query, kinds=["catalog"], limit=k) or {}).get("results") or []
    except Exception:  # noqa: BLE001 - search is optional (unbound, index building)
        return []
    return [{"item_id": h.get("id"), "kind": h.get("kind"), "name": h.get("title"),
             "summary": (h.get("snippet") or "")[:200]} for h in hits[:k] if isinstance(h, dict)]


# ---------------------------------------------------------------- build context

class _Ctx:
    def __init__(self, conn, task, home, appdb, scope, goal, goal_source, params, slots):
        self.conn, self.task, self.home, self.appdb = conn, task, home, appdb
        self.scope = scope or {}
        self.start, self.end, self.project_id = window(scope)
        self.goal, self.goal_source = goal or "", goal_source or "manual"
        self.params, self.slots = params or {}, slots or {}
        self.memo: dict = {}

    def where(self, alias="s", start=None, end=None):
        return window_sql(self.start if start is None else start, self.end if end is None else end,
                          self.project_id, self.home, alias)

    def once(self, key, fn):
        if key not in self.memo:
            self.memo[key] = fn()
        return self.memo[key]

    def profile(self):
        return self.once("profile", lambda: features_profile(self.scope))

    def evidence(self) -> list[dict]:
        return self.once("evidence", lambda: _evidence(self))

    def evidence_sessions(self) -> list[str]:
        def calc():
            uids: list[str] = []
            explicit = (self.params.get("session_uids") or
                        (self.params.get("candidate") or {}).get("evidence_session_uids") or [])
            for uid in list(explicit) + [e["session_uid"] for e in self.evidence()]:
                if uid and uid not in uids:
                    uids.append(uid)
            return uids[:5]
        return self.once("evidence_sessions", calc)


# ---------------------------------------------------------------- loaders

def _human_rows(conn, session_uid, limit=50):
    return conn.execute("SELECT event_uid, text FROM v_human_message WHERE session_uid=? ORDER BY seq LIMIT ?",
                        (session_uid, limit)).fetchall()


def _evidence(c: _Ctx) -> list[dict]:
    if c.conn is None:
        return []
    out: list[dict] = []
    src, p = c.goal_source, c.params
    if src == "candidate":
        cand = p.get("candidate") or {}
        top = set(cand.get("top_signal_event_uids") or [])
        for uid in (cand.get("evidence_session_uids") or [])[:5]:
            rows = _human_rows(c.conn, uid)
            pick = next((r for r in rows if r[0] in top), None) or \
                next((r for r in rows if CORRECTION_RE.search(r[1] or "")), None)
            if pick:
                out.append({"event_uid": pick[0], "session_uid": uid, "kind": "human",
                            "text": privacy.direct_user_text(pick[1] or "")})
    elif src == "phrases":
        uids = [u for ph in p.get("phrases") or [] for u in (ph.get("event_uids") or [])][:5]
        out = _events_by_uid(c.conn, uids)
    elif src == "project":
        out = _project_evidence(c)
    elif src == "workflow":
        uids = list(p.get("session_uids") or [])[:20]
        if uids:
            rows = c.conn.execute(
                f"SELECT result_event_uid, call_event_uid, session_uid, name, command_head, error_class"
                f" FROM tool_call WHERE session_uid IN ({placeholders(uids)})"
                f" AND (status IN ('failed','error') OR error_class IS NOT NULL) ORDER BY started_at LIMIT 5",
                uids).fetchall()
            out = [{"event_uid": r[0] or r[1], "session_uid": r[2], "kind": "error",
                    "text": " ".join(x for x in (r[3], r[4], r[5]) if x)} for r in rows]
    elif src == "ask":
        events, sessions = [], []
        for ref in p.get("refs") or []:
            (events if ref.get("kind") == "event" else sessions if ref.get("kind") == "session" else []).append(
                ref.get("id"))
        out = _events_by_uid(c.conn, events[:5])
        for uid in sessions:
            if len(out) >= 5:
                break
            rows = _human_rows(c.conn, uid, 1)
            if rows:
                out.append({"event_uid": rows[0][0], "session_uid": uid, "kind": "human",
                            "text": privacy.direct_user_text(rows[0][1] or "")})
    elif c.goal:
        out = fts_human(c.conn, c.goal, 5)
    return out[:5]


def _events_by_uid(conn, uids) -> list[dict]:
    if not uids:
        return []
    rows = conn.execute(f"SELECT event_uid, session_uid, actor, text FROM event WHERE event_uid IN"
                        f" ({placeholders(uids)}) LIMIT 5", uids).fetchall()
    order = {u: i for i, u in enumerate(uids)}
    rows = sorted(rows, key=lambda r: order.get(r[0], 99))
    out = []
    for r in rows:
        kind = "human" if r[2] == "human" else "assistant" if r[2] == "assistant" else "error"
        text = privacy.direct_user_text(r[3] or "") if kind == "human" else (r[3] or "")
        out.append({"event_uid": r[0], "session_uid": r[1], "kind": kind, "text": text})
    return out


def _project_evidence(c: _Ctx) -> list[dict]:
    pid = c.params.get("project_id") or c.project_id
    start = c.end - 30 * DAY_MS
    where, params = window_sql(start, c.end, pid, c.home)
    sub = f"SELECT s.session_uid FROM session s WHERE {where}"
    problems = (_friction(c).get("problems") or [])[:3]
    out: list[dict] = []
    for prob in problems:
        for uid in (prob.get("event_uids") or [])[:2]:
            out.extend(_events_by_uid(c.conn, [uid]))
    if not out:  # no feature problems: corrections and top failing commands of the project
        rows = c.conn.execute(f"SELECT h.event_uid, h.session_uid, h.text FROM v_human_message h"
                              f" WHERE h.session_uid IN ({sub}) AND {_correction_sql()} ORDER BY h.ts DESC LIMIT 3",
                              params).fetchall()
        out = [{"event_uid": r[0], "session_uid": r[1], "kind": "human",
                "text": privacy.direct_user_text(r[2] or "")} for r in rows]
        rows = c.conn.execute(f"SELECT COALESCE(t.result_event_uid,t.call_event_uid), t.session_uid, t.name,"
                              f" t.command_head, t.error_class FROM tool_call t WHERE t.session_uid IN ({sub})"
                              f" AND t.status IN ('failed','error') ORDER BY t.started_at DESC LIMIT 2",
                              params).fetchall()
        out += [{"event_uid": r[0], "session_uid": r[1], "kind": "error",
                 "text": " ".join(x for x in (r[2], r[3], r[4]) if x)} for r in rows]
    return out[:5]


def _goal(c: _Ctx):
    return {"text": c.goal, "source": c.goal_source}


def _sessions(c: _Ctx):
    if c.conn is None:
        return []
    where, params = c.where()
    uids = list(c.params.get("session_uids") or [])
    if uids:
        where, params = f"s.session_uid IN ({placeholders(uids)})", uids
    rows = c.conn.execute(
        f"SELECT s.session_uid, s.title, p.name, s.started_at,"
        f" MAX(COALESCE(s.ended_at,s.started_at)-s.started_at,0) FROM session s"
        f" LEFT JOIN project p ON p.project_id=s.project_id WHERE {where}"
        f" ORDER BY s.started_at DESC LIMIT 30", params).fetchall()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    ph = placeholders(ids)
    tools = {r[0]: (r[1], int(r[2] or 0)) for r in c.conn.execute(
        f"SELECT session_uid, COUNT(*), SUM(status IN ('failed','error')) FROM tool_call"
        f" WHERE session_uid IN ({ph}) GROUP BY session_uid LIMIT 30", ids)}
    corr = {r[0]: int(r[1] or 0) for r in c.conn.execute(
        f"SELECT h.session_uid, SUM({_correction_sql()}) FROM v_human_message h"
        f" WHERE h.session_uid IN ({ph}) GROUP BY h.session_uid LIMIT 30", ids)}
    facets = _facet_rows(c.appdb, ids)
    out = []
    for r in rows:
        t = tools.get(r[0], (0, 0))
        item = {"session_uid": r[0], "title": (r[1] or "")[:80], "project": r[2], "started_at": r[3],
                "minutes": round((r[4] or 0) / 60000, 1), "tools": t[0], "errors": t[1],
                "corrections": corr.get(r[0], 0)}
        f = facets.get(r[0])
        if f:
            item["task_type"], item["summary"] = f.get("task_type"), f.get("summary")
        out.append(item)
    return out


def _facet_rows(appdb, uids) -> dict:
    """task_type/summary from app.db ai_facet (owned by the ai runtime); absent table → {}."""
    if appdb is None or not uids:
        return {}
    try:
        with appdb.read() as db:
            rows = db.execute(f"SELECT session_uid, json FROM ai_facet WHERE status='ok' AND session_uid IN"
                              f" ({placeholders(uids)}) ORDER BY created_at LIMIT 1000", list(uids)).fetchall()
    except Exception:  # noqa: BLE001 - table not created yet
        return {}
    return {r[0]: json.loads(r[1]) for r in rows if r[1]}


def _friction(c: _Ctx):
    def calc():
        problems = []
        for p in (c.profile().get("problems") or [])[:10]:
            if isinstance(p, dict):
                problems.append({"problem_id": p.get("problem_id") or p.get("id"), "type": p.get("type"),
                                 "key": p.get("key"), "sessions": p.get("sessions"),
                                 "weekly_count": p.get("weekly_count"),
                                 "event_uids": list(p.get("event_uids") or p.get("evidence_event_uids") or [])[:2]})
        if c.conn is None:
            return {"problems": problems, "error_classes": [], "corrections": 0}
        where, params = c.where()
        sub = f"SELECT s.session_uid FROM session s WHERE {where}"
        classes = [{"error_class": r[0], "count": r[1]} for r in c.conn.execute(
            f"SELECT error_class, COUNT(*) n FROM tool_call WHERE session_uid IN ({sub})"
            f" AND error_class IS NOT NULL GROUP BY error_class ORDER BY n DESC, error_class LIMIT 8", params)]
        corr = c.conn.execute(f"SELECT COALESCE(SUM({_correction_sql()}),0) FROM v_human_message h"
                              f" WHERE h.session_uid IN ({sub}) LIMIT 1", params).fetchone()[0]
        return {"problems": problems, "error_classes": classes, "corrections": int(corr)}
    value = c.once("friction", calc)
    return value


def _friction_item(c: _Ctx):
    value = _friction(c)
    return {**value, "problems": [{k: v for k, v in p.items() if k != "event_uids"} for p in value["problems"]]}


def _tool_rows(c: _Ctx, uids, limit=1000):
    if not uids:
        return []
    return c.conn.execute(
        f"SELECT session_uid, name, kind, command_head, status, error_class, exit_code, files FROM tool_call"
        f" WHERE session_uid IN ({placeholders(uids)}) ORDER BY session_uid, started_at, call_uid LIMIT ?",
        [*uids, limit]).fetchall()


def _exts(files_json) -> list[str]:
    try:
        files = json.loads(files_json or "[]")
    except ValueError:
        return []
    exts = []
    for f in files:
        name = f if isinstance(f, str) else (f or {}).get("path", "") if isinstance(f, dict) else ""
        suffix = Path(name).suffix.lower()
        if suffix and suffix not in exts:
            exts.append(suffix)
    return exts


def _failure_runs(rows) -> list[dict]:
    """Same command_head failing ≥2 times in a row within one session."""
    runs: dict[tuple, int] = {}
    key, streak, cls = None, 0, None
    for r in list(rows) + [None]:
        failed = r is not None and bool(r[3]) and (r[4] in FAIL_STATUS or r[5] is not None)
        if failed and (r[0], r[3]) == key:
            streak, cls = streak + 1, r[5] or cls
            continue
        if streak >= 2:
            runs[(key[1], cls)] = runs.get((key[1], cls), 0) + 1
        key, streak, cls = ((r[0], r[3]), 1, r[5]) if failed else (None, 0, None)
    return [{"command_head": k[0], "error_class": k[1], "runs": n}
            for k, n in sorted(runs.items(), key=lambda x: -x[1])]


def _tool_evidence(c: _Ctx):
    if c.conn is None:
        return {"command_heads": [], "file_exts": [], "verify_commands": [], "failure_runs": []}
    rows = _tool_rows(c, c.evidence_sessions())
    heads, exts, verify = [], [], []
    for r in rows:
        if r[3] and r[3] not in heads:
            heads.append(r[3])
        for e in _exts(r[7]):
            if e not in exts:
                exts.append(e)
        if r[3] and r[4] in OK_STATUS and VERIFY_RE.search(r[3]) and r[3] not in verify:
            verify.append(r[3])
    return {"command_heads": heads[:30], "file_exts": exts[:20], "verify_commands": verify[:10],
            "failure_runs": _failure_runs(rows)[:10]}


def _replay_calls(c: _Ctx):
    if c.conn is None:
        return []
    evidence = c.evidence_sessions()[:3]
    normal: list[str] = []
    where, params = c.where()
    pid = c.params.get("project_id") or c.project_id
    if evidence and not pid:
        row = c.conn.execute("SELECT project_id FROM session WHERE session_uid=? LIMIT 1", (evidence[0],)).fetchone()
        pid = row[0] if row else None
    if pid:
        where, params = window_sql(c.start, c.end, pid, c.home)
    excl = f" AND s.session_uid NOT IN ({placeholders(evidence)})" if evidence else ""
    for (uid,) in c.conn.execute(f"SELECT s.session_uid FROM session s WHERE {where}{excl}"
                                 f" ORDER BY s.started_at DESC LIMIT 20", params + evidence):
        if len(normal) >= 5:
            break
        if not _failure_runs(_tool_rows(c, [uid], 200)):
            normal.append(uid)
    uids = evidence + normal
    titles = {r[0]: r[1] for r in c.conn.execute(
        f"SELECT session_uid, title FROM session WHERE session_uid IN ({placeholders(uids)}) LIMIT 8", uids)} \
        if uids else {}
    out = []
    for uid in uids:
        calls = [{"tool_name": r[1], "kind": r[2], "command_head": r[3], "status": r[4], "error_class": r[5],
                  "exit_code": r[6], "file_exts": _exts(r[7])} for r in _tool_rows(c, [uid], 200)]
        out.append({"session_uid": uid, "title": titles.get(uid) or "", "evidence": uid in evidence, "calls": calls})
    return out


def _metrics(c: _Ctx):
    if c.conn is None:
        return {}
    cur = metrics(c.conn, c.start, c.end, c.project_id, c.home)
    span = c.end - c.start
    prev = metrics(c.conn, c.start - span, c.start, c.project_id, c.home)
    return {**cur, "prev": prev if prev["sessions"] else None}


def _transitions(c: _Ctx):
    if c.conn is None:
        return []
    where, params = c.where()
    rows = c.conn.execute(
        f"SELECT prev, kind, COUNT(*) n FROM (SELECT t.kind, LAG(t.kind) OVER"
        f" (PARTITION BY t.session_uid ORDER BY t.started_at, t.call_uid) prev FROM tool_call t"
        f" WHERE t.session_uid IN (SELECT s.session_uid FROM session s WHERE {where}))"
        f" WHERE prev IS NOT NULL GROUP BY prev, kind ORDER BY n DESC LIMIT 400", params).fetchall()
    out_degree: dict[str, int] = {}
    for r in rows:
        out_degree[r[0]] = out_degree.get(r[0], 0) + r[2]
    return [{"from": r[0], "to": r[1], "count": r[2], "probability": round(r[2] / out_degree[r[0]], 3)}
            for r in rows[:15]]


def _rule_files(c: _Ctx) -> list[Path]:
    user_home = Path.home().resolve()
    paths: list[Path] = []
    if c.conn is not None:
        try:
            for (p,) in c.conn.execute(f"SELECT DISTINCT config_path FROM inventory_item WHERE type='rule'"
                                       f" AND scan_id IN ({latest_scans_sql()}) LIMIT 50"):
                paths.append(Path(p).expanduser())
        except Exception:  # noqa: BLE001 - inventory tables may be absent
            pass
    paths += [user_home / ".claude" / "CLAUDE.md", user_home / ".codex" / "AGENTS.md"]
    out = []
    for p in paths:
        try:
            r = p.resolve()
        except OSError:
            continue
        if r.is_relative_to(user_home) and r.is_file() and r.stat().st_size <= 256_000 and r not in out:
            out.append(r)
    return out


def _keywords(text: str) -> set[str]:
    try:
        import jieba
        words = jieba.cut_for_search(text)
    except Exception:  # noqa: BLE001
        words = re.findall(r"\w+", text)
    return {w.lower() for w in words if len(w.strip()) >= 2}


def _existing_rules(c: _Ctx):
    query = " ".join([c.goal] + [e["text"] for e in c.evidence()])
    keys = _keywords(query) if query.strip() else set()
    user_home = Path.home().resolve()
    scored = []
    order = 0
    for path in _rule_files(c):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for seg in re.split(r"\n\s*\n|\n(?=#)", text):
            seg = seg.strip()
            if len(seg) < 8:
                continue
            score = len(keys & _keywords(seg)) if keys else 0
            if keys and score == 0:
                continue
            norm = re.sub(r"\s+", " ", seg).strip().lower()
            label = "~/" + str(path.relative_to(user_home))
            scored.append((-score, order, {"path_label": label, "anchor_hash": hashlib.sha256(
                norm.encode()).hexdigest()[:16], "text": seg}))
            order += 1
    return [s[2] for s in sorted(scored, key=lambda s: (s[0], s[1]))[:3]]


def _inventory(c: _Ctx):
    if c.conn is None:
        return []
    try:
        rows = c.conn.execute(f"SELECT type, name, enabled FROM inventory_item WHERE scan_id IN"
                              f" ({latest_scans_sql()}) ORDER BY type, name LIMIT 200").fetchall()
    except Exception:  # noqa: BLE001
        return []
    seen, out = set(), []
    for r in rows:
        if (r[0], r[1]) not in seen:
            seen.add((r[0], r[1]))
            out.append({"type": r[0], "name": r[1], "enabled": None if r[2] is None else bool(r[2])})
    return out


def _catalog_items(c: _Ctx):
    return catalog_search(c.goal, 3)


def candidates(scope, limit=10, appdb=None) -> list[dict]:
    """Passed candidates of the newest recommendation run, read from app.db (AI never imports
    recommend; ``rec_candidate`` is its published table)."""
    if appdb is None:
        return []
    try:
        with appdb.read() as db:
            rows = db.execute(
                "SELECT candidate_id, title, kind, priority, card FROM rec_candidate WHERE passed = 1"
                " AND run_id = (SELECT run_id FROM rec_run ORDER BY created_at DESC LIMIT 1)"
                " ORDER BY rank, priority DESC LIMIT ?", (limit,)).fetchall()
    except Exception:  # noqa: BLE001 - recommend schema absent: no candidates yet
        return []
    out = []
    for r in rows:
        card = json.loads(r["card"] or "{}")
        out.append({"candidate_id": r["candidate_id"], "title": r["title"], "kind": r["kind"],
                    "priority": r["priority"], "reason": card.get("reason") or card.get("why"),
                    "evidence_counts": card.get("evidence_counts")})
    return out


def _candidates(c: _Ctx):
    return candidates(c.scope, 10, c.appdb)


def _profile(c: _Ctx):
    return c.profile()


# ---------------------------------------------------------------- facet items (AI-03)

def facet_sessions(c: _Ctx) -> list[str]:
    uids = list(c.params.get("session_uids") or [])
    if uids:
        return uids
    end = c.end
    extra, params = session_filter(c.home)
    rows = c.conn.execute(
        f"SELECT s.session_uid, EXISTS(SELECT 1 FROM v_human_message h WHERE h.session_uid=s.session_uid"
        f" AND {_correction_sql()}) cand FROM session s WHERE s.kind='main' AND s.status<>'active'"
        f" AND s.started_at>=? AND s.started_at<? AND COALESCE(s.ended_at,s.started_at)-s.started_at>=60000"
        f" AND (SELECT COUNT(*) FROM v_human_message h WHERE h.session_uid=s.session_uid)>=2{extra}"
        f" ORDER BY cand DESC, s.started_at DESC LIMIT 600", [end - 90 * DAY_MS, end, *params]).fetchall()
    return [r[0] for r in rows]


def _seq(kinds: list[str]) -> list[str]:
    out: list[list] = []
    for k in kinds:
        if out and out[-1][0] == k:
            out[-1][1] += 1
        else:
            out.append([k, 1])
    return [k if n == 1 else f"{k}×{n}" for k, n in out][:60]


def facet_payload(conn, uid: str) -> dict:
    s = conn.execute("SELECT s.title, p.name, s.started_at, MAX(COALESCE(s.ended_at,s.started_at)-s.started_at,0),"
                     " s.status, s.client FROM session s LEFT JOIN project p ON p.project_id=s.project_id"
                     " WHERE s.session_uid=? LIMIT 1", (uid,)).fetchone()
    tools = conn.execute("SELECT name, status, error_class FROM tool_call WHERE session_uid=?"
                         " ORDER BY started_at, call_uid LIMIT 400", (uid,)).fetchall()
    humans = conn.execute("SELECT event_uid, text FROM v_human_message WHERE session_uid=? ORDER BY seq LIMIT 200",
                          (uid,)).fetchall()
    replies = conn.execute("SELECT event_uid, text FROM event WHERE session_uid=? AND actor='assistant'"
                           " AND kind LIKE 'message.%' AND text IS NOT NULL ORDER BY seq LIMIT 200", (uid,)).fetchall()
    errors = sum(1 for t in tools if t[1] in FAIL_STATUS or t[2])
    row = {"title": ((s[0] if s else "") or "")[:60], "project": s[1] if s else None,
           "minutes": round((s[3] if s else 0) / 60000, 1), "status": s[4] if s else None,
           "client": s[5] if s else None, "tools": len(tools), "tool_errors": errors,
           "error_classes": sorted({t[2] for t in tools if t[2]})[:5]}
    texts = [(r[0], privacy.direct_user_text(r[1] or "")) for r in humans]
    texts = [t for t in texts if t[1]]
    cands = [{"signal_id": "sig:" + e, "event_uid": e, "kind": "correction", "snippet": t[:120]}
             for e, t in texts if CORRECTION_RE.search(t)][:10]
    if len(texts) > 12:
        texts = texts[:4] + texts[-8:]
    return {"row": row, "tool_sequence": _seq([t[0] for t in tools]),
            "human_messages": [{"event_uid": e, "text": t} for e, t in texts],
            "assistant_replies": [{"event_uid": r[0], "text": r[1]} for r in replies[-12:]],
            "candidates": cands}


def clip_facet(payload: dict) -> dict:
    payload = {**payload,
               "human_messages": [{**m, "text": m["text"][:500]} for m in payload["human_messages"]],
               "assistant_replies": [{**m, "text": m["text"][:300]} for m in payload["assistant_replies"]]}
    if est_tokens(payload) > FACET_SESSION_TOKENS:
        payload["chunked"] = True
        payload["assistant_replies"] = []
        while est_tokens(payload) > FACET_SESSION_TOKENS and len(payload["human_messages"]) > 1:
            payload["human_messages"] = payload["human_messages"][1:]
    return payload


def _existing_facets(appdb, uids, prompt_version) -> dict:
    if appdb is None or not uids:
        return {}
    try:
        with appdb.read() as db:
            out = {}
            for i in range(0, len(uids), 500):
                chunk = uids[i:i + 500]
                out.update({r[0]: r[1] for r in db.execute(
                    f"SELECT session_uid, content_hash FROM ai_facet WHERE prompt_version=? AND session_uid IN"
                    f" ({placeholders(chunk)}) LIMIT 1000", [prompt_version, *chunk])})
            return out
    except Exception:  # noqa: BLE001 - ai_facet not created yet
        return {}


def _items(c: _Ctx):
    """Per-session payloads, redacted and clipped here so content_hash covers exactly what is sent.

    Sessions whose facet already exists with the same prompt_version and content_hash are skipped.
    """
    if c.conn is None:
        return {}
    uids = facet_sessions(c)
    known = _existing_facets(c.appdb, uids, c.task.get("prompt_version"))
    out, hits = {}, 0
    for uid in uids:
        if len(out) >= FACET_MAX_SESSIONS:
            break
        payload, n = redact_value(facet_payload(c.conn, uid))
        payload = clip_facet(payload)
        if known.get(uid) == content_hash(payload):
            continue
        out[uid] = payload
        hits += n
    c.memo["items:hits"] = hits
    return out


def _raw(c: _Ctx):
    return None


# key: (label, desc, data_class, loader)
ITEMS = {
    "goal": ("目标", "本次分析或生成要解决的问题", "summary", _goal),
    "sessions": ("会话摘要", "近期会话的标题、时长、工具与纠偏计数（≤30 条）", "summary", _sessions),
    "friction": ("摩擦统计", "问题、错误类别与纠偏计数", "summary", _friction_item),
    "evidence": ("证据片段", "≤5 条已脱敏的原话或错误片段", "snippets", lambda c: c.evidence()),
    "existing_rules": ("现有规则", "本机规则文件中最相关的 ≤3 段（只读）", "rules", _existing_rules),
    "inventory": ("已装组件", "最近一次扫描到的 Skill / MCP / Hook / 插件 / 规则", "summary", _inventory),
    "catalog_items": ("目录条目", "与目标相关的 ≤3 个目录条目", "summary", _catalog_items),
    "tool_evidence": ("工具证据", "证据会话中的命令、文件类型、验证命令与连续失败", "summary", _tool_evidence),
    "replay_calls": ("回放调用", "证据会话与正常会话的工具调用序列，用于回放自检", "summary", _replay_calls),
    "metrics": ("指标", "本期与上一等长周期的会话、纠偏、工具失败指标", "summary", _metrics),
    "transitions": ("工具转移", "相邻工具类别的 top 15 转移", "summary", _transitions),
    "candidates": ("候选建议", "当前 top 10 推荐候选", "summary", _candidates),
    "profile": ("用户画像", "features.profile() 的特征与权重", "summary", _profile),
    "items": ("逐会话材料", "每个会话的压缩行、工具序列、原话与答复（facet 专用）", "snippets", _items),
    "raw": ("原文", "完整原文永远不发送给本机 Agent 或 API", "raw", _raw),
}
_ORDER = ["goal", "evidence"]  # loaders others depend on run first


def _clip(key: str, value):
    if key == "evidence":
        return [{**e, "text": (e.get("text") or "")[:LIMITS.get(e.get("kind"), 300)]} for e in (value or [])][:5]
    if key == "existing_rules":
        return [{**r, "text": r["text"][:400]} for r in (value or [])][:3]
    if key == "catalog_items":
        return (value or [])[:3]
    if key == "items":
        return {uid: clip_facet(p) for uid, p in (value or {}).items()}
    return value


def _preview(key: str, value) -> list[str]:
    if value in (None, [], {}):
        return []
    if key == "items":
        lines = [f"{uid[:12]} · {p['row'].get('title') or ''} · {len(p['human_messages'])} 条原话"
                 for uid, p in value.items()]
    elif isinstance(value, list):
        lines = [compact(v) for v in value]
    elif isinstance(value, dict):
        lines = [f"{k}: {compact(v)}" for k, v in value.items()]
    else:
        lines = [compact(value)]
    return [ln if len(ln) <= 160 else ln[:157] + "…" for ln in lines[:8]]


_REF_KEYS = {"session_uid": "session", "event_uid": "event", "problem_id": "problem", "candidate_id": "candidate"}


def collect_refs(value, refs: dict, numbers: set, *, numeric: bool) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k in _REF_KEYS and isinstance(v, str) and v not in refs[_REF_KEYS[k]]:
                refs[_REF_KEYS[k]].append(v)
            elif k in ("evidence_session_uids",) and isinstance(v, list):
                refs["session"].extend(x for x in v if isinstance(x, str) and x not in refs["session"])
            collect_refs(v, refs, numbers, numeric=numeric)
    elif isinstance(value, list):
        for v in value:
            collect_refs(v, refs, numbers, numeric=numeric)
    elif numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
        numbers.add(float(value))


@contextmanager
def _maybe_conn(reads):
    """Enter `reads()`; a missing tandem.db degrades items to empty instead of failing."""
    try:
        cm = reads()
        conn = cm.__enter__()
    except Exception:  # noqa: BLE001
        log.debug("tandem.db unavailable for pack", exc_info=True)
        yield None
        return
    try:
        yield conn
    finally:
        cm.__exit__(None, None, None)


def build(task: dict, *, reads, appdb, home, scope=None, selection=None, goal=None, goal_source="manual",
          params=None, slots=None) -> dict:
    """Assemble the C3 pack for `task` (a C1 TaskSpec dict)."""
    selection = (selection or {}).get("items") or {}
    slots = slots or {}
    home = Path(home) if home is not None else None
    pack_items = list(task.get("pack_items") or [("goal", True)])
    keys = [k for k, _ in pack_items]
    order = [k for k in _ORDER if k in keys] + [k for k in keys if k not in _ORDER]
    defaults = dict(pack_items)
    items: dict[str, dict] = {}
    content: dict = {}
    refs = {"session": [], "event": [], "problem": [], "candidate": [], "metric": []}
    numbers: set[float] = set()
    batches = None
    with (_maybe_conn(reads) if reads is not None else nullcontext()) as conn:
        c = _Ctx(conn, task, home, appdb, scope, goal, goal_source, params, slots)
        for key in order:
            label, desc, data_class, loader = ITEMS[key]
            enabled = bool(selection.get(key, defaults[key])) and data_class != "raw"
            unavailable = False
            if key in slots:
                value = slots[key]
            else:
                try:
                    value = loader(c)
                except Exception:  # noqa: BLE001 - one broken loader must not sink the pack
                    log.warning("pack item %s failed", key, exc_info=True)
                    value, unavailable = None, True
                if conn is None and key not in ("goal", "raw", "existing_rules", "catalog_items", "candidates",
                                                "profile"):
                    unavailable = True
            pre_hits = c.memo.pop(f"{key}:hits", None)
            if pre_hits is None:
                value, hits = redact_value(value)
                value = _clip(key, value)
            else:
                hits = pre_hits
            if key == "items":
                ids = list(value or {})
                batches = [ids[i:i + FACET_BATCH] for i in range(0, len(ids), FACET_BATCH)]
            tokens = 0 if value is None else est_tokens(value)
            items[key] = {"key": key, "label": label, "desc": desc + ("（不可用）" if unavailable else ""),
                          "data_class": data_class, "enabled": enabled, "tokens": tokens,
                          "redaction_hits": hits, "preview": _preview(key, value)}
            if enabled:
                content[key] = value
                collect_refs(value, refs, numbers, numeric=key in ("metrics", "friction", "transitions"))
        if "metrics" in content and content["metrics"]:
            refs["metric"] = [k for k in content["metrics"] if k != "prev"]
    ordered = [items[k] for k in keys]
    enabled_items = [i for i in ordered if i["enabled"]]
    goal_text = goal or ""
    return {"task_id": task.get("task_id"), "goal": goal_text, "goal_source": goal_source,
            "items": ordered, "content": content, "refs": refs, "numbers": sorted(numbers),
            "total_tokens": sum(i["tokens"] for i in enabled_items),
            "redaction_hits": sum(i["redaction_hits"] for i in enabled_items),
            "batches": batches, "preview_digest": digest(task, goal_text, content)}
