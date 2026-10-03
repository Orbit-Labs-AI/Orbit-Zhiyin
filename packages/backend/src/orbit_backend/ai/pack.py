"""Context pack (AI-08): read-only, redacted, token-counted input for every AI task.

`build()` is the only way data reaches a model. Each pack item is loaded from
orbit.db (read-only) or app.db, passed through `redact.redact2`, clipped to its
contract limits (C4), counted, and previewed. `content` holds only enabled items
and is exactly what gets sent; `preview_digest` binds a later job to it.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import re
import sqlite3
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from orbit_data import legacy

from orbit_backend import privacy

from .redact import compact, est_tokens, redact_value

log = logging.getLogger(__name__)

DAY_MS = 86_400_000
MARKER = "[orbit-analysis"
# Corrections are short pushback near the start of a message (B8): a bare "不是" inside a long
# prompt is a copula, "again" is mostly a client retry ("Try again").
CORRECTION_MAX_CHARS = 200
_CORRECTION_HEAD = 60
_CORRECTION_ZH = re.compile(r"^(?:不是|错了|搞错)|(?<!对)不对(?![应称劲齐])|我说的是|别再|不是这样|不是这个|不是我要"
                            r"|不是让你|理解错|搞错了|还是不行")
# English pushback only counts at the start of a sentence ("No, use X", "That's wrong",
# "Wrong file", "Still failing"): mid-sentence "wrong" is mostly a request about an object
# ("fix the wrong import", "what's wrong with this test"). Unambiguous phrases count anywhere.
_CORRECTION_EN_START = re.compile(
    r"^(?:(?:no|nope|hmm+|ugh|wait|actually|again)[,.!\s]+)?"
    r"(?:no|nope)\b(?=[\s,.!]|$)(?!\s+(?:problem|worries|thanks|rush|idea|need)\b)"
    r"|^(?:(?:no|nope|hmm+|ugh|wait|actually)[,.!\s]+)?"
    r"(?:that'?s|this is|it'?s|you'?re|you are)\s+(?:still\s+)?(?:not right|not correct|wrong|incorrect|not it|not what)"
    r"|^(?:(?:no|nope|hmm+|ugh|wait|actually)[,.!\s]+)?(?:wrong|incorrect)\b(?!\s+with)"
    r"|^(?:(?:no|nope|hmm+|ugh|wait|actually)[,.!\s]+)?(?:i said|i meant|i asked (?:you )?(?:to|for))\b"
    r"|^(?:(?:no|nope|hmm+|ugh|wait|actually)[,.!\s]+)?(?:still (?:wrong|broken|failing|not working|doesn'?t work)"
    r"|don'?t do that|stop doing|you (?:did|got) (?:it|that) wrong|you broke)",
    re.I)
_CORRECTION_EN_ANY = re.compile(r"\bnot what i (?:asked|meant|wanted|said)\b|\byou misunderstood\b"
                                r"|\bthat'?s not what\b|\bi told you (?:not )?to\b", re.I)
_SENTENCES = re.compile(r"(?<=[.!?。！？;；])\s*|\n+")
# Cues that the agent misread the request (vs. a wrong approach / buggy output), used by the
# rule fallback of classify.feedback to pick friction_type.
MISUNDERSTOOD = re.compile(r"我说的是|不是我要|不是让你|理解错|没听懂|not what i (?:asked|meant|wanted|said)"
                           r"|you misunderstood|\bi meant\b|\bi said\b|\bi asked (?:you )?(?:to|for)\b", re.I)
_CLIENT_RETRY = re.compile(r"^(?:try again|retry|continue|please continue|go on|keep going)[.!。！]?$", re.I)
# No protocol outcome: not counted in failure-rate denominators (declined = user refused).
UNKNOWN_STATUS = ("unknown", "orphan_result", "declined", "denied")
VERIFY_RE = re.compile(r"pytest|npm (run )?test|pnpm (check|test)|cargo test|go test|make( test)?|tsc|ruff|eslint"
                       r"|swift (build|test)|xcodebuild")
OK_STATUS = ("success", "completed", "ok")
FAIL_STATUS = ("failed", "error")
LIMITS = {"human": 500, "assistant": 300, "error": 200}
FACET_SESSION_TOKENS = 6000
FACET_MAX_SESSIONS = 200
FACET_BATCH = 8
FACET_RESERVE_TOKENS = 2000  # room for goal and the other items of a facet pack
REPLAY_CALLS_MAX = 40  # per session, before the token budget halves it further
REPLAY_TOKENS = 4000


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
        end = int(scope["end_ms"] if scope.get("end_ms") is not None else now_ms())
        start = int(scope.get("start_ms") if scope.get("start_ms") is not None else end - 30 * DAY_MS)
    else:
        end = now_ms()
        start = end - int(scope.get("days") or 30) * DAY_MS
    return start, end, scope.get("project_id")


def session_filter(home: Path | None, alias: str = "s") -> tuple[str, list]:
    """Exclude sessions Orbit itself started (agent-cwd or marker first line)."""
    sql = (f" AND NOT EXISTS (SELECT 1 FROM event m WHERE m.session_uid={alias}.session_uid"
           f" AND m.seq<=5 AND m.kind='message.user' AND (m.text LIKE ? OR m.text LIKE ?))")
    params: list = [MARKER + "%", legacy.AI_MARKER + "%"]
    if home is not None:
        sql = f" AND ({alias}.cwd IS NULL OR {alias}.cwd NOT LIKE ?)" + sql
        params.insert(0, str(Path(home) / "agent-cwd") + "%")
    return sql, params


def window_sql(start: int, end: int, project_id, home, alias: str = "s", *,
               source_ids=None, exclude=None, session_uids=None) -> tuple[str, list]:
    """WHERE fragment selecting analysed main sessions of a window (optionally limited to
    ``source_ids`` and without the ``exclude`` session uids)."""
    sql = f"{alias}.kind='main' AND {alias}.started_at>=? AND {alias}.started_at<?"
    params: list = [start, end]
    if project_id:
        sql += f" AND {alias}.project_id=?"
        params.append(project_id)
    if source_ids is not None:
        sql += f" AND {alias}.source_id IN (SELECT value FROM json_each(?))"
        params.append(json.dumps(list(source_ids)))
    if session_uids is not None:
        sql += f" AND {alias}.session_uid IN (SELECT value FROM json_each(?))"
        params.append(json.dumps(list(session_uids)))
    if exclude:
        sql += f" AND {alias}.session_uid NOT IN ({placeholders(exclude)})"
        params.extend(exclude)
    extra, extra_params = session_filter(home, alias)
    return sql + extra, params + extra_params


def is_correction(text) -> bool:
    """A short human message that pushes back on the agent (see ``CORRECTION_MAX_CHARS``)."""
    t = (text or "").strip()
    if not t or len(t) > CORRECTION_MAX_CHARS or _CLIENT_RETRY.match(t):
        return False
    head = t[:_CORRECTION_HEAD]
    if _CORRECTION_ZH.search(head) or _CORRECTION_EN_ANY.search(head):
        return True
    return any(_CORRECTION_EN_START.match(part.strip()) for part in _SENTENCES.split(head) if part.strip())


def union_ms(intervals, lo: int | None = None, hi: int | None = None) -> int:
    """Wall-clock length of the union of ``(start, end)`` intervals clipped to ``[lo, hi)`` (B7):
    overlapping sessions count once, so hours never exceed the window."""
    spans = []
    for a, b in intervals:
        if a is None:
            continue
        b = a if b is None or b < a else b
        if lo is not None:
            a, b = max(a, lo), max(b, lo)
        if hi is not None:
            a, b = min(a, hi), min(b, hi)
        if b > a:
            spans.append((a, b))
    total, cur_a, cur_b = 0, None, None
    for a, b in sorted(spans):
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += cur_b - cur_a
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += cur_b - cur_a
    return total


def _chunks(values, size: int = 500):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i:i + size]


def human_texts(conn, uids, since: int | None = None) -> dict[str, list[str]]:
    """Human message texts per session, in order; driven by the session list (B9)."""
    out: dict[str, list[str]] = {}
    for chunk in _chunks(dict.fromkeys(uids)):
        extra, args = ("", []) if since is None else (" AND h.ts>=?", [since])
        for uid, text in conn.execute(
                f"SELECT h.session_uid, h.text FROM v_human_message h WHERE h.session_uid IN"
                f" ({placeholders(chunk)}){extra} ORDER BY h.session_uid, h.seq", [*chunk, *args]):
            out.setdefault(uid, []).append(text or "")
    return out


def correction_counts(conn, uids) -> dict[str, int]:
    return {uid: sum(map(is_correction, texts)) for uid, texts in human_texts(conn, uids).items()}


def with_children(conn, uids) -> dict[str, str]:
    """{session_uid: main uid} for the main sessions and their subagent/workflow children, so
    tool counts include delegated work (the analytics views do the same)."""
    out = {u: u for u in uids}
    try:
        for chunk in _chunks(uids):
            for uid, root in conn.execute(
                    f"SELECT session_uid, root_uid FROM session WHERE root_uid IN ({placeholders(chunk)})"
                    f" AND kind IN ('subagent','workflow_agent') AND lineage_unresolved=0", chunk):
                out.setdefault(uid, root)
    except sqlite3.OperationalError:  # pre-lineage schema: main sessions only
        pass
    return out


def tool_stats(conn, uids) -> dict[str, list[int]]:
    """{main uid: [calls, known, failures]} (known = a status other than unknown/orphan)."""
    owner = with_children(conn, uids)
    out: dict[str, list[int]] = {}
    for chunk in _chunks(owner):
        for uid, calls, known, fails in conn.execute(
                f"SELECT session_uid, COUNT(*), SUM(status IN ({placeholders((*OK_STATUS, *FAIL_STATUS))})),"
                f" SUM(status IN ({placeholders(FAIL_STATUS)})) FROM tool_call WHERE session_uid IN"
                f" ({placeholders(chunk)}) GROUP BY session_uid", [*OK_STATUS, *FAIL_STATUS, *FAIL_STATUS, *chunk]):
            acc = out.setdefault(owner[uid], [0, 0, 0])
            acc[0] += calls
            acc[1] += int(known or 0)
            acc[2] += int(fails or 0)
    return out


def _metric_values(rows, start: int, end: int, humans: dict, tools: dict) -> dict:
    uids = [r[0] for r in rows]
    msgs = sum(len(humans.get(u, ())) for u in uids)
    corr = sum(is_correction(t) for u in uids for t in humans.get(u, ()))
    calls = sum(tools.get(u, (0, 0, 0))[0] for u in uids)
    known = sum(tools.get(u, (0, 0, 0))[1] for u in uids)
    fails = sum(tools.get(u, (0, 0, 0))[2] for u in uids)
    span = union_ms(((r[1], r[2]) for r in rows), start, end)
    return {"sessions": len(rows), "hours": round(span / 3_600_000, 1), "human_messages": msgs,
            "corrections": corr, "correction_rate": round(corr / msgs, 3) if msgs else 0.0,
            "tool_calls": calls, "tool_failures": fails, "tool_known_results": known,
            # Rates use known protocol outcomes only; unknown/declined calls are not successes.
            "tool_failure_rate": round(fails / known, 3) if known else None,
            "tool_unknown_share": round((calls - known) / calls, 3) if calls else None}


_METRICS_CACHE: dict = {}
_METRICS_TTL_S = 60


def _data_rev(conn):
    try:
        path = conn.execute("PRAGMA database_list").fetchone()[2]
        rev = conn.execute("SELECT (SELECT MAX(rowid) FROM event), (SELECT MAX(rowid) FROM tool_call),"
                           " (SELECT COUNT(*) FROM session)").fetchone()
        return path, tuple(rev)
    except Exception:  # noqa: BLE001 - unknown connection type: no caching
        return None


def metrics_pair(conn, start: int, end: int, project_id=None, home=None, *, source_ids=None,
                 exclude=None, session_uids=None) -> tuple[dict, dict]:
    """Metrics of ``[start, end)`` and of the preceding window of equal length, in one pass (B9).

    Hours are the union of session spans clipped to the window (B7); the tool failure rate uses
    calls with a known status as denominator. Cached for a minute per (db, data revision, scope).
    """
    span = end - start
    rev = _data_rev(conn)
    key = None
    if rev is not None:
        key = (rev, start // 60_000, end // 60_000, project_id, str(home) if home else None,
               None if source_ids is None else tuple(source_ids), tuple(sorted(exclude or ())),
               None if session_uids is None else tuple(session_uids))
        hit = _METRICS_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < _METRICS_TTL_S:
            return hit[1]
    where, params = window_sql(start - span, end, project_id, home, source_ids=source_ids,
                               exclude=exclude, session_uids=session_uids)
    rows = conn.execute(f"SELECT s.session_uid, s.started_at, s.ended_at FROM session s WHERE {where}",
                        params).fetchall()
    uids = [r[0] for r in rows]
    humans = human_texts(conn, uids, since=start - span - DAY_MS)
    tools = tool_stats(conn, uids)
    cur = _metric_values([r for r in rows if r[1] >= start], start, end, humans, tools)
    prev = _metric_values([r for r in rows if r[1] < start], start - span, start, humans, tools)
    if key is not None:
        if len(_METRICS_CACHE) > 64:
            _METRICS_CACHE.clear()
        _METRICS_CACHE[key] = (time.monotonic(), (cur, prev))
    return cur, prev


def metrics(conn, start: int, end: int, project_id=None, home=None, *, source_ids=None,
            exclude=None) -> dict:
    return metrics_pair(conn, start, end, project_id, home, source_ids=source_ids, exclude=exclude)[0]


def fts_query(text: str, min_len: int = 2) -> str:
    try:
        import jieba
        words = jieba.cut_for_search(text or "")
    except Exception:  # noqa: BLE001 - jieba is a soft dependency here
        words = re.findall(r"\w+", text or "")
    seen: list[str] = []
    for w in words:
        w = w.strip()
        if len(w) >= min_len and w not in seen:
            seen.append(w)
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in seen[:24])


def fts_human(conn, text: str, limit: int = 5, *, session_where=None, session_params=()) -> list[dict]:
    # Schema v8 replaced unicode61 ``event_fts`` with trigram ``event_search`` (messages and
    # titles only); a trigram index cannot match terms shorter than three characters.
    table = "event_search" if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='event_search'").fetchone() else "event_fts"
    query = fts_query(text, 3 if table == "event_search" else 2)
    if not query:
        return []
    selected = (f" AND e.session_uid IN (SELECT s.session_uid FROM session s WHERE {session_where})"
                if session_where else "")
    rows = conn.execute(
        f"SELECT e.event_uid, e.session_uid, e.text FROM {table} f JOIN event e ON e.rowid = f.rowid"
        f" WHERE {table} MATCH ? AND e.event_uid IN (SELECT event_uid FROM v_human_message)"
        f"{selected} ORDER BY bm25({table}) LIMIT ?", (query, *session_params, limit)).fetchall()
    return [{"event_uid": r[0], "session_uid": r[1], "kind": "human",
             "text": privacy.direct_user_text(r[2] or "")} for r in rows]


def latest_scans_sql() -> str:
    return "SELECT MAX(scan_id) FROM inventory_scan GROUP BY source_key, root_path"


def placeholders(values) -> str:
    return ",".join("?" * len(values))


def features_profile(scope) -> dict:
    fn = lazy("orbit_backend.features", "profile")
    if fn is None:
        return {}
    try:
        selected = dict(scope or {})
        if selected.get("source_ids") == [] or selected.get("session_uids") == []:
            return {}
        start, end, pid = window(selected)
        selected.update(from_ts=start, until_ts=end)
        if pid:
            selected["project_ids"] = [pid]
        if selected.get("session_uids") is not None:
            selected["root_session_uids"] = selected["session_uids"]
        value = fn(selected)
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 - features is optional; fall back to orbit.db
        log.debug("features.profile failed", exc_info=True)
        return {}


def catalog_search(query: str, k: int = 3) -> list[dict]:
    """Catalog hits through features.search (the gateway binds it); [] when not bound."""
    fn = lazy("orbit_backend.features", "search")
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
        self.scope = dict(scope or {})
        if (params or {}).get("session_uid"):
            uid = params["session_uid"]
            selected = self.scope.get("session_uids")
            self.scope["session_uids"] = [uid] if selected is None or uid in selected else []
        self.start, self.end, self.project_id = window(scope)
        self.goal, self.goal_source = goal or (params or {}).get("question") or "", goal_source or "manual"
        self.params, self.slots = params or {}, slots or {}
        self.memo: dict = {}

    def where(self, alias="s", start=None, end=None):
        return window_sql(self.start if start is None else start, self.end if end is None else end,
                          self.project_id, self.home, alias,
                          source_ids=self.scope.get("source_ids"),
                          exclude=self.scope.get("excluded_session_uids"),
                          session_uids=self.scope.get("session_uids"))

    def allowed_sessions(self, uids):
        if self.conn is None or not uids:
            return []
        where, params = self.where()
        rows = self.conn.execute(
            f"SELECT s.session_uid FROM session s WHERE {where} "
            "AND s.session_uid IN (SELECT value FROM json_each(?))",
            [*params, json.dumps(list(uids))])
        allowed = {r[0] for r in rows}
        return list(dict.fromkeys(u for u in uids if u in allowed))

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
            return self.allowed_sessions(uids)[:5]
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
                next((r for r in rows if is_correction(r[1])), None)
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
        where, args = c.where()
        out = fts_human(c.conn, c.goal, 5, session_where=where, session_params=args)
    allowed = set(c.allowed_sessions([row["session_uid"] for row in out]))
    return [row for row in out if row["session_uid"] in allowed][:5]


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
                              f" WHERE h.session_uid IN ({sub}) ORDER BY h.ts DESC LIMIT 400",
                              params).fetchall()
        out = [{"event_uid": r[0], "session_uid": r[1], "kind": "human",
                "text": privacy.direct_user_text(r[2] or "")} for r in rows if is_correction(r[2])][:3]
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
        where += f" AND s.session_uid IN ({placeholders(uids)})"
        params = [*params, *uids]
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
    corr = correction_counts(c.conn, ids)
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
        uids = [r[0] for r in c.conn.execute(sub, params)]
        corr = sum(correction_counts(c.conn, uids).values())
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
    rows: dict[str, list] = {}
    for (uid,) in c.conn.execute(f"SELECT s.session_uid FROM session s WHERE {where}{excl}"
                                 f" ORDER BY s.started_at DESC LIMIT 20", params + evidence):
        if len(normal) >= 5:
            break
        rows[uid] = _tool_rows(c, [uid], 200)
        if not _failure_runs(rows[uid]):
            normal.append(uid)
    uids = evidence + normal
    titles = {r[0]: r[1] for r in c.conn.execute(
        f"SELECT session_uid, title FROM session WHERE session_uid IN ({placeholders(uids)}) LIMIT 8", uids)} \
        if uids else {}
    out = []
    for uid in uids:
        calls = []
        for r in rows.get(uid) or _tool_rows(c, [uid], 200):
            call = {"tool_name": r[1], "kind": r[2], "command_head": r[3], "status": r[4], "error_class": r[5],
                    "exit_code": r[6], "file_exts": _exts(r[7])}
            calls.append({k: v for k, v in call.items() if v not in (None, [], "")})
        out.append({"session_uid": uid, "title": titles.get(uid) or "", "evidence": uid in evidence, "calls": calls})
    return out


def _replay_keep(calls: list[dict], cap: int) -> list[int]:
    """Indices to keep: head and tail plus a window around each failure (what hooks react to)."""
    n = len(calls)
    if n <= cap:
        return list(range(n))
    keep: dict[int, None] = {}
    for i, call in enumerate(calls):
        if call.get("status") in FAIL_STATUS or call.get("error_class"):
            keep.update(dict.fromkeys(range(max(0, i - 2), min(n, i + 3))))
    edge = max(1, cap // 8)
    head_tail = list(range(min(edge, n))) + list(range(max(0, n - edge), n))
    picked = sorted(dict.fromkeys(head_tail))
    for i in keep:
        if len(picked) >= cap:
            break
        if i not in picked:
            picked.append(i)
    return sorted(picked[:cap])


def clip_replay(sessions, cap: int = REPLAY_CALLS_MAX, budget: int = REPLAY_TOKENS) -> list[dict]:
    """Clip each session's calls (B11) until the item fits ``budget`` tokens; ``omitted_calls``
    says how many were left out so the replay result is read as a sample."""
    sessions = list(sessions or [])
    while True:
        out = []
        for s in sessions:
            calls = s.get("calls") or []
            idx = _replay_keep(calls, cap)
            item = {**s, "calls": [calls[i] for i in idx]}
            if len(idx) < len(calls):
                item["omitted_calls"] = len(calls) - len(idx) + int(s.get("omitted_calls") or 0)
            out.append(item)
        if cap <= 4 or est_tokens(out) <= budget:
            return out
        cap //= 2


def _metrics(c: _Ctx):
    if c.conn is None:
        return {}
    cur, prev = metrics_pair(c.conn, c.start, c.end, c.project_id, c.home,
                             source_ids=c.scope.get("source_ids"),
                             exclude=c.scope.get("excluded_session_uids"),
                             session_uids=c.scope.get("session_uids"))
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
        return c.allowed_sessions(uids)
    where, params = c.where()
    uids = [r[0] for r in c.conn.execute(
        f"SELECT s.session_uid FROM session s WHERE {where} AND s.status<>'active'"
        " AND COALESCE(s.ended_at,s.started_at)-s.started_at>=60000"
        " ORDER BY s.started_at DESC", params)]
    humans = human_texts(c.conn, uids)
    keep = [u for u in uids if len(humans.get(u, ())) >= 2]
    cand = {u for u in keep if any(map(is_correction, humans[u]))}
    return sorted(keep, key=lambda u: u not in cand)[:600]


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
    # Keep actual latest delivery/feedback, even after hundreds of earlier messages.
    head = conn.execute("SELECT event_uid, text, seq, ts FROM v_human_message WHERE session_uid=?"
                        " ORDER BY seq LIMIT 4", (uid,)).fetchall()
    tail = conn.execute("SELECT event_uid, text, seq, ts FROM v_human_message WHERE session_uid=?"
                        " ORDER BY seq DESC LIMIT 8", (uid,)).fetchall()
    humans = sorted({r[0]: r for r in [*head, *tail]}.values(), key=lambda r: r[2])
    replies = list(reversed(conn.execute(
        "SELECT event_uid, text, seq, ts FROM event WHERE session_uid=? AND actor='assistant'"
        " AND kind LIKE 'message.%' AND text IS NOT NULL ORDER BY seq DESC LIMIT 12", (uid,)).fetchall()))
    human_n = conn.execute("SELECT COUNT(*) FROM v_human_message WHERE session_uid=?", (uid,)).fetchone()[0]
    reply_n = conn.execute("SELECT COUNT(*) FROM event WHERE session_uid=? AND actor='assistant'"
                           " AND kind LIKE 'message.%' AND text IS NOT NULL", (uid,)).fetchone()[0]
    tool_n, errors = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(status IN ('failed','error') OR error_class IS NOT NULL),0)"
        " FROM tool_call WHERE session_uid=?", (uid,)).fetchone()
    row = {"title": ((s[0] if s else "") or "")[:60], "project": s[1] if s else None,
           "minutes": round((s[3] if s else 0) / 60000, 1), "status": s[4] if s else None,
           "client": s[5] if s else None, "tools": tool_n, "tool_errors": errors,
           "error_classes": sorted({t[2] for t in tools if t[2]})[:5]}
    messages = [{"event_uid": r[0], "text": privacy.direct_user_text(r[1] or ""),
                 "seq": r[2], "ts": r[3], "role": "human"} for r in humans]
    messages = [m for m in messages if m["text"]]
    cands = [{"signal_id": "sig:" + m["event_uid"], "event_uid": m["event_uid"],
              "kind": "correction", "snippet": m["text"][:120]}
             for m in messages if is_correction(m["text"])][:10]
    return {"row": row, "tool_sequence": _seq([t[0] for t in tools]),
            "human_messages": messages,
            "assistant_replies": [{"event_uid": r[0], "text": r[1], "seq": r[2], "ts": r[3],
                                   "role": "assistant"} for r in replies],
            "candidates": cands,
            "chunked": human_n > len(humans) or reply_n > len(replies) or tool_n > len(tools),
            "coverage": {"human_messages": human_n, "retained_human_messages": len(messages),
                         "assistant_replies": reply_n, "retained_assistant_replies": len(replies),
                         "tool_calls": tool_n, "retained_tool_calls": len(tools)}}


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
    budget = max(FACET_SESSION_TOKENS, int(c.task.get("input_budget") or 40_000) - FACET_RESERVE_TOKENS)
    out, hits, tokens, queued = {}, 0, 0, 0
    for k, uid in enumerate(uids):
        if len(out) >= FACET_MAX_SESSIONS:
            queued = len(uids) - k
            break
        payload, n = redact_value(facet_payload(c.conn, uid))
        payload = clip_facet(payload)
        if known.get(uid) == content_hash(payload):
            continue
        size = est_tokens({uid: payload})
        if out and tokens + size > budget:  # B12: stay within the task budget; the rest waits
            queued = len(uids) - k
            break
        out[uid] = payload
        hits += n
        tokens += size
    c.memo["items:hits"] = hits
    c.memo["items:queued"] = queued
    return out


def _raw(c: _Ctx):
    return None


# key: (label, desc, data_class, loader)
ITEMS = {
    "problems": ("诊断问题", "已确认的范围内问题摘要；仅接受调用方显式提供", "summary", lambda c: []),
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


def _item(key: str):
    """Pack item spec; v1 task items live in ``pack_v1`` (imported lazily: it imports this module)."""
    if key not in ITEMS:
        from .pack_v1 import ITEMS_V1

        ITEMS.update(ITEMS_V1)
    return ITEMS[key]


def _clip(key: str, value):
    if key == "evidence":
        return [{**e, "text": (e.get("text") or "")[:LIMITS.get(e.get("kind"), 300)]} for e in (value or [])][:5]
    if key == "existing_rules":
        return [{**r, "text": r["text"][:400]} for r in (value or [])][:3]
    if key == "catalog_items":
        return (value or [])[:3]
    if key == "items":
        return {uid: clip_facet(p) for uid, p in (value or {}).items()}
    if key == "replay_calls":
        return clip_replay(value)
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
    """Enter `reads()`; a missing orbit.db degrades items to empty instead of failing."""
    try:
        cm = reads()
        conn = cm.__enter__()
    except Exception:  # noqa: BLE001
        log.debug("orbit.db unavailable for pack", exc_info=True)
        yield None
        return
    try:
        yield conn
    finally:
        cm.__exit__(None, None, None)


def build(task: dict, *, reads, appdb, home, scope=None, selection=None, goal=None, goal_source="manual",
          params=None, slots=None) -> dict:
    """Assemble the C3 pack for `task` (a C1 TaskSpec dict)."""
    from .queries import _excluded

    scope = dict(scope or {})
    scope["excluded_session_uids"] = sorted(set(scope.get("excluded_session_uids") or []) |
                                            set(_excluded(appdb)))
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
            label, desc, data_class, loader = _item(key)
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
            queued = c.memo.pop(f"{key}:queued", 0)
            if queued:
                items[key]["queued"] = queued
                items[key]["desc"] += (f"（按输入预算先处理 {len(value or {})} 个会话，"
                                       f"其余最多 {queued} 个排队，下次提交继续）")
            if enabled:
                content[key] = value
                collect_refs(value, refs, numbers, numeric=key in ("metrics", "friction", "transitions"))
        if "metrics" in content and content["metrics"]:
            refs["metric"] = [k for k in content["metrics"] if k != "prev"]
    ordered = [items[k] for k in keys]
    enabled_items = [i for i in ordered if i["enabled"]]
    goal_text = goal or ""
    return {"task_id": task.get("task_id"), "goal": goal_text, "goal_source": goal_source, "scope": c.scope,
            "items": ordered, "content": content, "refs": refs, "numbers": sorted(numbers),
            "total_tokens": sum(i["tokens"] for i in enabled_items),
            "redaction_hits": sum(i["redaction_hits"] for i in enabled_items),
            "batches": batches, "preview_digest": digest(task, goal_text, content)}
