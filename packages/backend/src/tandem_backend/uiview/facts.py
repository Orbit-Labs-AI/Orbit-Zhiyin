"""Session fact rows shaped like the prototype's ``ALL`` array (one row per main session).

Inputs: the memoised analysis result (``sessions`` / ``overview`` / ``instruction`` /
``tasks`` / ``bottleneck_recommendations``) plus read-only L1 SQL. Analysis numbers are
copied, never recomputed: ``msgs`` = ``user_message_count``, ``tools`` = ``tool_call_count``
(+ merged children), ``corr`` = ``correction_signal_count``. Everything else is a
deterministic rule with a basis; a value the logs cannot support stays ``None``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextvars import ContextVar
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from . import CONTRACT, outcome

UIDS = "(SELECT value FROM json_each(?))"
IDLE_CAP_MS = 5 * 60_000
FAILED = frozenset(("failed", "error", "failure"))
UNKNOWN_STATUS = frozenset((None, "", "unknown", "running", "pending"))
FRIC = ("方向错误", "工具 / 环境失败", "改动过度", "误解需求", "并行会话冲突",
        "流程过重（子代理）", "额度 / 用量中断")
TOPICS = ("git", "design", "paper", "data", "quant", "net", "other")
# Same candidate regex as analytics.outcome.validation (validation_runs candidates).
VALIDATION_RE = re.compile(r"\b(test|pytest|lint|typecheck|build|check)\b", re.I)
FRIC_LEXICON = (
    ("方向错误", re.compile(r"不要用|别用|换成|改用|方向(?:错|不对)|不是这个方案|用\S{1,20}而不是")),
    ("工具 / 环境失败", re.compile(r"别重复试|先检查|环境|认证|权限|command not found|装不上|"
                                r"超时|timeout|报错", re.I)),
    ("改动过度", re.compile(r"改多了|改太多|只改|别动|不要动|多余的改动|范围太大")),
    ("误解需求", re.compile(r"不是我要的|理解错|误解|我的意思是|不是这个意思|重新来")),
    ("并行会话冲突", re.compile(r"冲突|另一个会话|别的会话|worktree", re.I)),
    ("流程过重（子代理）", re.compile(r"子代理|subagent|太重了|别开代理", re.I)),
    ("额度 / 用量中断", re.compile(r"额度|用量|限额|rate limit|quota|usage limit", re.I)),
)
SIGNAL_FRIC = {"correction_density": "方向错误", "repeated_requirements": "误解需求",
               "identical_retries": "工具 / 环境失败", "tool_failures": "工具 / 环境失败"}
TOPIC_TEXT = (("git", re.compile(r"\bgit\b|\bPR\b|pull request|\bcommit\b|rebase|合并请求|分支|"
                                 r"仓库规范", re.I)),
              ("net", re.compile(r"代理规则|\bproxy\b|\bsurge\b|\bclash\b|分流|\bvpn\b", re.I)),
              ("paper", re.compile(r"论文|latex|\.tex\b|审稿|参考文献", re.I)))
DOMAIN_TOPIC = {"software.frontend": "design", "software.devops": "design", "design": "design",
                "writing.research": "paper", "data.engineering": "data",
                "software.ai_engineering": "data", "software.database": "data",
                "data.statistics": "quant", "data.visualization": "quant",
                "data.machine_learning": "quant", "mathematics": "quant"}
STRUCTURED_RE = re.compile(
    r"(?:^|\n)\s*(?:[-*•]|\d+[.、)])\s+\S.*(?:\n\s*(?:[-*•]|\d+[.、)])\s+\S)"  # ≥ 2 list items
    r"|验收|完成标准|预期结果|acceptance|done when|definition of done"
    r"|\b[\w./-]+\.(?:md|txt|ya?ml|json)\b|规格|\bspec\b|\bPRD\b|计划文档", re.I | re.S)
STRUCTURED_LEN = 200
TITLE_LEN = 60
NULLABLE = ("d", "h", "mi", "a", "p", "title", "dur", "span", "errors", "steps", "verify",
            "out", "fric", "topic", "tok", "model", "effort")
AGENT_NAMES = {"claude_code": ("Claude Code", "Claude"), "codex": ("Codex", "Codex"),
               "gemini": ("Gemini CLI", "Gemini"), "gemini_cli": ("Gemini CLI", "Gemini"),
               "deepseek": ("DeepSeek Harness", "DeepSeek"), "dsh": ("DeepSeek Harness", "DeepSeek"),
               "copilot": ("Copilot CLI", "Copilot"), "opencode": ("OpenCode", "OpenCode"),
               "pi": ("Pi", "Pi"), "hermes": ("Hermes Agent", "Hermes"),
               "kimi": ("Kimi CLI", "Kimi")}


def _tz(name: str | None):
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001 - unknown zone degrades to UTC, recorded in meta
        return UTC


# Fields that fell back to null because the store lacks a table/column (meta.degraded).
_DEGRADED: ContextVar[set[str] | None] = ContextVar("uiview_facts_degraded", default=None)
SCHEMA_GAPS = ("no such column", "no such table")


def is_schema_gap(error: BaseException) -> bool:
    """An older store lacks a table/column: degrade. Anything else is a bug and raises."""
    return isinstance(error, sqlite3.OperationalError) and any(
        gap in str(error).lower() for gap in SCHEMA_GAPS)


def degrade(*fields: str) -> None:
    seen = _DEGRADED.get()
    if seen is not None:
        seen.update(fields)


def _rows(conn, sql: str, *params, fields: tuple[str, ...] = ()):
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as error:
        if not is_schema_gap(error):
            raise
        degrade(*fields)
        return []


def _split(result: dict) -> tuple[list[dict], dict[str, str]]:
    sessions = result.get("sessions") or []
    mains = [s for s in sessions if s.get("session_uid") and (s.get("kind") or "main") == "main"]
    main_ids = {s["session_uid"] for s in mains}
    root_of = {uid: uid for uid in main_ids}
    for row in sessions:
        uid = row.get("session_uid")
        if uid and uid not in main_ids:
            root = row.get("root_uid")
            if root in main_ids:
                root_of[uid] = root
    return mains, root_of


def _children_tools(result: dict, root_of: dict) -> dict[str, int]:
    extra: dict[str, int] = defaultdict(int)
    for row in result.get("sessions") or []:
        uid = row.get("session_uid")
        if uid and root_of.get(uid, uid) != uid:
            extra[root_of[uid]] += (row.get("features") or {}).get("tool_call_count") or 0
    return extra


def _active(conn, uids: str, root_of: dict) -> dict[str, float]:
    stamps: dict[str, list[int]] = defaultdict(list)
    for uid, ts in _rows(conn, f"SELECT session_uid, ts FROM event WHERE ts IS NOT NULL AND "
                               f"session_uid IN {UIDS}", uids, fields=('dur',)):
        stamps[root_of.get(uid, uid)].append(ts)
    out = {}
    for root, values in stamps.items():
        values.sort()
        gaps = (min(b - a, IDLE_CAP_MS) for a, b in zip(values, values[1:], strict=False))
        out[root] = sum(gaps) / 60_000
    return out


def _turns(conn, uids: str, root_of: dict, verify_events: set[str]):
    """Human-triggered turns per root: [[steps, verify]] plus the last turn's status."""
    calls = dict(_rows(conn, f"SELECT turn_uid, count(*) FROM tool_call WHERE turn_uid IS NOT "
                             f"NULL AND session_uid IN {UIDS} GROUP BY turn_uid", uids,
                             fields=('steps',)))
    finals = dict(_rows(conn, f"SELECT turn_uid, count(*) FROM event WHERE kind = "
                              f"'message.assistant' AND turn_uid IS NOT NULL AND "
                              f"json_extract(attrs, '$.phase') IN ('final', 'final_answer') AND "
                              f"session_uid IN {UIDS} GROUP BY turn_uid", uids,
                              fields=('steps', 'out')))
    checked: set[str] = set()
    for turn, head, command in _rows(
            conn, f"SELECT tc.turn_uid, tc.command_head, json_extract(e.attrs, '$.input.command')"
                  f" FROM tool_call tc LEFT JOIN event e ON e.event_uid = tc.call_event_uid "
                  f"WHERE tc.turn_uid IS NOT NULL AND tc.kind = 'shell' AND tc.session_uid IN "
                  f"{UIDS}", uids, fields=('verify',)):
        text = head or ""
        if command:
            try:
                parsed = json.loads(command)
                text += " " + (" ".join(map(str, parsed)) if isinstance(parsed, list)
                               else str(parsed))
            except ValueError:
                text += " " + str(command)
        if VALIDATION_RE.search(text):
            checked.add(turn)
    requested: set[str] = set()
    if verify_events:
        for (turn,) in _rows(conn, f"SELECT turn_uid FROM event WHERE turn_uid IS NOT NULL AND "
                                   f"event_uid IN {UIDS}", json.dumps(sorted(verify_events)),
                                   fields=('verify',)):
            requested.add(turn)
    per_root: dict[str, list[list[int]]] = defaultdict(list)
    last: dict[str, tuple[int, str | None, bool]] = {}
    for turn, uid, idx, status in _rows(
            conn, f"SELECT turn_uid, session_uid, idx, status FROM turn WHERE trigger = 'human' "
                  f"AND session_uid IN {UIDS} ORDER BY session_uid, idx", uids,
                  fields=('steps', 'verify', 'out')):
        root = root_of.get(uid, uid)
        if uid == root:
            per_root[root].append([calls.get(turn, 0) + finals.get(turn, 0),
                                   int(turn in checked or turn in requested)])
            if root not in last or (idx or 0) >= last[root][0]:
                last[root] = (idx or 0, status, finals.get(turn, 0) > 0)
    return per_root, {k: (v[1], v[2]) for k, v in last.items()}


def _tails(conn, uids: str, root_of: dict) -> dict[str, list[str | None]]:
    """Last ``outcome.TAIL_FAILED`` tool-call statuses of each main session, oldest first."""
    out: dict[str, list[str | None]] = defaultdict(list)
    for uid, status in _rows(conn, f"SELECT session_uid, status FROM tool_call WHERE "
                                   f"session_uid IN {UIDS} ORDER BY session_uid, started_at, "
                                   f"call_uid", uids, fields=('out',)):
        if root_of.get(uid, uid) == uid:
            tail = out[uid]
            tail.append(status)
            del tail[:-outcome.TAIL_FAILED]
    return out


def _tools(conn, uids: str, root_of: dict):
    per_root: dict[str, dict[str, list]] = defaultdict(dict)
    for uid, name, kind, status, n in _rows(
            conn, f"SELECT session_uid, COALESCE(name, name_raw), kind, status, count(*) FROM "
                  f"tool_call WHERE session_uid IN {UIDS} GROUP BY 1, 2, 3, 4", uids,
                  fields=('errors',)):
        entry = per_root[root_of.get(uid, uid)].setdefault(name or "unknown", [kind, 0, 0, 0])
        entry[1] += n
        if status not in UNKNOWN_STATUS:
            entry[3] += n
            if status in FAILED:
                entry[2] += n
    return per_root


def _models(conn, uids: str, root_of: dict):
    tok: dict[str, int] = {}
    cumulative: set[str] = set()
    models: dict[str, Counter] = defaultdict(Counter)
    efforts: dict[str, Counter] = defaultdict(Counter)
    for uid, model, effort, coverage, *parts in _rows(
            conn, f"SELECT session_uid, model_id, effort_raw, coverage, input_tokens, "
                  f"cache_read_tokens, cache_write_tokens, output_tokens FROM model_call WHERE "
                  f"session_uid IN {UIDS}", uids, fields=('tok', 'model', 'effort')):
        root = root_of.get(uid, uid)
        if model:
            models[root][model] += 1
        if effort:
            efforts[root][effort] += 1
        known = [p for p in parts if p is not None]
        if known:
            tok[root] = tok.get(root, 0) + sum(known)
            if coverage and "cumulative" in str(coverage):
                cumulative.add(root)
    return tok, cumulative, models, efforts


def _human(conn, mains: str):
    """First human message per main session plus all texts (for lexical friction only)."""
    first: dict[str, tuple[str, str]] = {}
    texts: dict[str, list[str]] = defaultdict(list)
    for uid, event_uid, text in _rows(
            conn, f"SELECT session_uid, event_uid, text FROM v_human_message WHERE session_uid "
                  f"IN {UIDS} ORDER BY session_uid, seq", mains, fields=('title', 'topic', 'fric')):
        if uid not in first:
            first[uid] = (event_uid, text or "")
        if text:
            texts[uid].append(text)
    return first, texts


def _moods(conn, mains: list[str]) -> dict[str, float]:
    """Mean emotion score per main session in −1..1 (same rule as ``/v1/uiview/sentiment``)."""
    from .a4a6_sentiment import fetch_humans, session_balances

    try:
        balances, _ = session_balances(fetch_humans(conn, mains))
    except sqlite3.OperationalError as error:  # older stores lack the view; mood stays null
        if not is_schema_gap(error):
            raise
        degrade("mood")
        return {}
    return {uid: round(v, 3) for uid, v in balances.items()}


def _instruction_index(result: dict):
    verify, structured = set(), set()
    for rec in ((result.get("instruction") or {}).get("records")) or []:
        feats = rec.get("features") or {}
        uid = rec.get("event_uid")
        if not uid:
            continue
        if feats.get("verification_requirements"):
            verify.add(uid)
        if feats.get("execution_order") or feats.get("acceptance_criteria"):
            structured.add(uid)
    return verify, structured


def _topics(result: dict, root_of: dict) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for task in ((result.get("tasks") or {}).get("records")) or []:
        details = task.get("domain_details") or []
        ids = [d.get("id") for d in details if isinstance(d, dict)]
        ids += [d.get("parent_id") for d in details if isinstance(d, dict)]
        mapped = [DOMAIN_TOPIC[i] for i in ids if i in DOMAIN_TOPIC]
        has_domain = bool(task.get("domain"))
        for uid in task.get("related_session_ids") or []:
            root = root_of.get(uid)
            if root is None:
                continue
            for topic in mapped:
                out[root][topic] += 1
            if has_domain and not mapped:
                out[root]["other"] += 0  # keeps the key: a domain was seen, none mapped
    return out


def topic_of(first_text: str | None, counts: Counter | None) -> str | None:
    for topic, pattern in TOPIC_TEXT:
        if first_text and pattern.search(first_text):
            return topic
    if counts:
        best = [t for t, n in counts.most_common() if n > 0]
        return best[0] if best else "other"
    return None


def structured_opening(text: str | None, flagged: bool) -> int | None:
    if text is None:
        return None
    return int(flagged or len(text) >= STRUCTURED_LEN or bool(STRUCTURED_RE.search(text)))


def friction_of(corr: int | None, texts: list[str], signals: Counter) -> tuple[str | None,
                                                                             str | None]:
    scores: Counter = Counter()
    if corr:
        for text in texts:
            for label, pattern in FRIC_LEXICON:
                if pattern.search(text):
                    scores[label] += 1
    lexical = bool(scores)
    for label, n in signals.items():
        scores[label] += n
    if not scores:
        return None, None
    best = max(FRIC, key=lambda label: (scores[label], -FRIC.index(label)))
    return best, "lexical_candidate" if lexical else "rule_signal"


def outcome_of(last_turn: tuple[str | None, bool] | None, corr: int | None,
               msgs: int | None, tail: list[str | None] | None) -> str | None:
    """Estimate only, via the shared ``uiview.outcome`` rule (same as the A3 list/detail).

    ``last_turn`` = (status, has_final_reply) of the last human turn, ``None`` without turns.
    """
    status, has_final = last_turn if last_turn else (None, None)
    return outcome.estimate(last_turn=status, corr=corr, msgs=msgs, tail=tail,
                            has_final=has_final)


def _clock(ts: int | None, tz) -> tuple[str | None, int | None, int | None]:
    if ts is None:
        return None, None, None
    dt = datetime.fromtimestamp(ts / 1000, tz)
    return dt.date().isoformat(), dt.hour, dt.minute


def _projects(conn, ids: set[str]) -> dict[str, dict]:
    out = {}
    for pid, name, key, paths in _rows(conn, f"SELECT project_id, name, key, paths FROM project "
                                             f"WHERE project_id IN {UIDS}",
                                       json.dumps(sorted(ids)), fields=('projects',)):
        try:
            parsed = json.loads(paths) if paths else []
        except ValueError:
            parsed = []
        path = parsed[0] if isinstance(parsed, list) and parsed else key
        out[pid] = {"id": pid, "name": name or (path or pid).rstrip("/").split("/")[-1],
                    "path": path}
    return out


def _excluded(conn, uids: list[str], tz) -> list[dict]:
    if not uids:
        return []
    rows = []
    for uid, agent, pid, title, _title_source, started in _rows(
            conn, f"SELECT s.session_uid, src.agent, s.project_id, s.title, s.title_source, "
                  f"s.started_at FROM session s LEFT JOIN source src ON src.source_id = "
                  f"s.source_id WHERE s.session_uid IN {UIDS} AND COALESCE(s.kind, 'main') = "
                  f"'main'", json.dumps(sorted(uids)), fields=('excluded',)):
        d, h, mi = _clock(started, tz)
        row = {k: None for k in ROW_KEYS}
        row.update(id=uid, d=d, h=h, mi=mi, a=agent, p=pid, title=title,
                   title_source="native" if title else None, live=False, excluded=True)
        rows.append(row)
    return rows


ROW_KEYS = ("id", "d", "h", "mi", "a", "p", "title", "title_source", "dur", "span", "msgs",
            "tools", "errors", "corr", "corr_basis", "steps", "verify", "out", "out_basis",
            "fric", "fric_basis", "topic", "mood", "tok", "tok_basis", "model", "effort", "live",
            "excluded")


def build_facts(conn, result: dict, scope) -> dict:
    """Rows + per-session auxiliaries (tool mix, turn units, opening, interval)."""
    token = _DEGRADED.set(set())
    try:
        body = _build_facts(conn, result, scope)
        body["meta"]["degraded"] = sorted(_DEGRADED.get() or ())
        return body
    finally:
        _DEGRADED.reset(token)


def _build_facts(conn, result: dict, scope) -> dict:
    tz_name = getattr(scope, "display_timezone", None) or "UTC"
    tz = _tz(tz_name)
    mains, root_of = _split(result)
    uids = json.dumps(sorted(root_of))
    main_json = json.dumps(sorted(s["session_uid"] for s in mains))
    verify_events, structured_events = _instruction_index(result)
    active = _active(conn, uids, root_of)
    turns, last_turn = _turns(conn, uids, root_of, verify_events)
    tails = _tails(conn, uids, root_of)
    tools = _tools(conn, uids, root_of)
    tok, cumulative, models, efforts = _models(conn, uids, root_of)
    first, texts = _human(conn, main_json)
    topics = _topics(result, root_of)
    moods = _moods(conn, [s["session_uid"] for s in mains])
    extra_tools = _children_tools(result, root_of)
    signals: dict[str, Counter] = defaultdict(Counter)
    for signal in ((result.get("bottleneck_recommendations") or {}).get("signals")) or []:
        label = SIGNAL_FRIC.get(signal.get("rule_id"))
        for ev in signal.get("evidence") or []:
            root = root_of.get(ev.get("session_uid"))
            if label and root:
                signals[root][label] += 1
    rows, aux = [], {}
    for s in mains:
        uid = s["session_uid"]
        f = s.get("features") or {}
        start = f.get("first_observed_ts") or s.get("started_at")
        end = f.get("last_observed_ts") or s.get("ended_at")
        d, h, mi = _clock(start, tz)
        unit_rows = turns.get(uid, [])
        steps = sum(t[0] for t in unit_rows) if unit_rows else None
        tool_map = tools.get(uid, {})
        known = sum(v[3] for v in tool_map.values())
        n_tools = (f.get("tool_call_count") or 0) + extra_tools.get(uid, 0)
        errors = sum(v[2] for v in tool_map.values()) if known or not n_tools else None
        corr = f.get("correction_signal_count")
        fric, fric_basis = friction_of(corr, texts.get(uid, []), signals.get(uid, Counter()))
        first_event, first_text = first.get(uid, (None, None))
        title, title_source = s.get("title"), "native" if s.get("title") else None
        if not title and first_text:
            title, title_source = " ".join(first_text.split())[:TITLE_LEN], "first_message"
        verify = (any(t[1] for t in unit_rows) or None) if unit_rows else None
        if unit_rows and verify is None:
            verify = False
        out = outcome_of(last_turn.get(uid), corr, f.get("user_message_count"), tails.get(uid))
        span = f.get("observed_session_span_ms")
        row = {
            "id": uid, "d": d, "h": h, "mi": mi, "a": s.get("agent"), "p": s.get("project_id"),
            "title": title, "title_source": title_source,
            "dur": round(active[uid], 2) if uid in active else None,
            "span": round(span / 60_000, 2) if span is not None else None,
            "msgs": f.get("user_message_count"), "tools": n_tools, "errors": errors,
            "corr": corr, "corr_basis": "lexical_candidate" if corr is not None else None,
            "steps": steps, "verify": verify, "out": out,
            "out_basis": "estimate" if out else None, "fric": fric, "fric_basis": fric_basis,
            "topic": topic_of(first_text, topics.get(uid)), "mood": moods.get(uid),
            "tok": tok.get(uid), "tok_basis": (None if uid not in tok else "cumulative_estimate"
                                               if uid in cumulative else "l1_model_call"),
            "model": models[uid].most_common(1)[0][0] if models.get(uid) else None,
            "effort": efforts[uid].most_common(1)[0][0] if efforts.get(uid) else None,
            "live": False, "excluded": False,
        }
        rows.append(row)
        aux[uid] = {"t0": start, "t1": end, "turns": unit_rows,
                    "open": structured_opening(first_text, first_event in structured_events),
                    "tools": tool_map}
    rows.sort(key=lambda r: (r["d"] or "", r["h"] or 0, r["mi"] or 0, r["id"]))
    excluded = _excluded(conn, list(getattr(scope, "excluded_session_uids", None) or []), tz)
    projects = _projects(conn, {r["p"] for r in rows + excluded if r["p"]})
    counts = ((result.get("overview") or {}).get("counts")) or {}
    body = {"contract": CONTRACT, "rows": rows + excluded, "aux": aux,
            "meta": _meta(rows, excluded, counts, tz_name), "agents": _agents(rows),
            "projects": _project_rows(rows, projects)}
    timestamps(body)
    return body


def _meta(rows: list[dict], excluded: list[dict], counts: dict, tz_name: str) -> dict:
    days = [r["d"] for r in rows if r["d"]]
    stamps = [r for r in rows if r["d"]]
    return {
        "display_timezone": tz_name, "day0": min(days) if days else None,
        "first_day": min(days) if days else None, "last_day": max(days) if days else None,
        "first_ts": None, "last_ts": None,
        "counts": {"sessions": len(rows), "excluded": len(excluded),
                   "main_sessions": counts.get("main_sessions"),
                   "human_messages": counts.get("human_messages"),
                   "correction_signals": counts.get("correction_signals"),
                   "dated": len(stamps)},
        "null_fields": {k: sum(1 for r in rows if r.get(k) is None) for k in NULLABLE},
        "basis": {"dur": "active_estimate", "span": "observed_span", "msgs": "analysis",
                  "tools": "analysis", "errors": "l1_tool_status", "steps": "l1_turn_steps",
                  "verify": "instruction_or_validation_candidate", "topic": "rule_mapping",
                  "mood": "lexical_emotion_mean"},
    }


def _agents(rows: list[dict]) -> list[dict]:
    counts = Counter(r["a"] for r in rows if r["a"])
    out = []
    for agent, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        name, short = AGENT_NAMES.get(agent, (agent, agent))
        out.append({"id": agent, "name": name, "short": short, "n": n})
    return out


def _project_rows(rows: list[dict], projects: dict) -> list[dict]:
    counts = Counter(r["p"] for r in rows if r["p"])
    return [{**projects.get(pid, {"id": pid, "name": pid, "path": None}), "n": n}
            for pid, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def timestamps(body: dict) -> None:
    """Fill meta.first_ts / last_ts from aux intervals (kept separate for testability)."""
    starts = [a["t0"] for a in body.get("aux", {}).values() if a.get("t0") is not None]
    ends = [a["t1"] for a in body.get("aux", {}).values() if a.get("t1") is not None]
    body["meta"]["first_ts"] = min(starts) if starts else None
    body["meta"]["last_ts"] = max(ends) if ends else None


# -- gateway-side helpers ---------------------------------------------------------------
LIVE_STATES = frozenset(("running", "awaiting_approval", "failing"))
DICT_FIELDS = ("a", "p", "corr_basis", "out", "out_basis", "fric", "fric_basis", "topic",
               "tok_basis", "model", "effort", "title_source")
ID_PREFIX = "session_"
# Per-session persona units (from ``aux``) so the client can re-derive the persona on any
# subset: dk/dn = turns with ≥ STEP_THRESHOLD steps / turns, vk = verified turns,
# op = structured opening (0 / 1 / null), t0 / t1 = observed interval (ms).
AUX_KEYS = ("dk", "dn", "vk", "op", "t0", "t1")
STEP_THRESHOLD = 5
WIRE_TITLE_LEN = 40


def overlay_live(body: dict, realtime: dict | None) -> dict:
    """Mark sessions the realtime snapshot reports as running (``out`` → ``live``)."""
    live = {s.get("session_uid") for s in (realtime or {}).get("sessions") or []
            if s.get("state") in LIVE_STATES}
    if not live:
        return body
    rows = []
    for row in body.get("rows") or []:
        if row["id"] in live and not row.get("excluded"):
            row = {**row, "live": True, "out": "live", "out_basis": "realtime"}
        rows.append(row)
    return {**body, "rows": rows}


WIRE_KEYS = (*ROW_KEYS, *AUX_KEYS)


def aux_units(a: dict | None) -> dict:
    if not a:
        return dict.fromkeys(AUX_KEYS)
    turns = a.get("turns") or []
    return {"dk": sum(1 for t in turns if t[0] >= STEP_THRESHOLD), "dn": len(turns),
            "vk": sum(1 for t in turns if t[1]), "op": a.get("open"), "t0": a.get("t0"),
            "t1": a.get("t1")}


def compact(body: dict) -> dict:
    """Columnar wire form: ``fields`` + ``rows`` (lists), dictionary-coded strings.

    ``dicts[field]`` holds the distinct values; the row stores the index (null stays null).
    A column with one value across all rows moves to ``constants`` (decoded value).
    Session ids drop the shared ``session_`` prefix (``meta.id_prefix``); booleans are 0 / 1;
    floats keep one decimal. Keeps ≈ 200 KB per 1000 sessions.
    """
    rows = [{**r, **aux_units((body.get("aux") or {}).get(r["id"]))}
            for r in body.get("rows") or []]
    dicts: dict[str, list] = {f: [] for f in DICT_FIELDS}
    index: dict[str, dict] = {f: {} for f in DICT_FIELDS}
    out = []
    for row in rows:
        values = []
        for key in WIRE_KEYS:
            value = row.get(key)
            if key == "id" and isinstance(value, str) and value.startswith(ID_PREFIX):
                value = value[len(ID_PREFIX):]
            elif key in index and value is not None:
                if value not in index[key]:
                    index[key][value] = len(dicts[key])
                    dicts[key].append(value)
                value = index[key][value]
            elif key == "title" and isinstance(value, str):
                value = value[:WIRE_TITLE_LEN]
            elif isinstance(value, bool):
                value = int(value)
            elif isinstance(value, float):
                value = round(value, 1)
            values.append(value)
        out.append(values)
    fields = list(WIRE_KEYS)
    constants = {}
    if out:
        for i in range(len(fields) - 1, 0, -1):  # never fold ``id``
            first = out[0][i]
            if all(values[i] == first for values in out):
                key = fields.pop(i)
                constants[key] = dicts[key][first] if key in dicts and first is not None \
                    else first
                for values in out:
                    del values[i]
    meta = {**(body.get("meta") or {}), "id_prefix": ID_PREFIX, "encoding": "columnar-v1"}
    return {"meta": meta, "fields": fields, "constants": constants,
            "dicts": {k: v for k, v in dicts.items() if k in fields}, "rows": out,
            "agents": body.get("agents") or [], "projects": body.get("projects") or []}


def expand(wire: dict) -> list[dict]:
    """Inverse of ``compact`` (used by tests and Python clients)."""
    fields, dicts = wire["fields"], wire["dicts"]
    prefix = wire["meta"].get("id_prefix") or ""
    constants = wire.get("constants") or {}
    out = []
    for values in wire["rows"]:
        row = {k: (bool(v) if k in ("verify", "live", "excluded") and v is not None else v)
               for k, v in constants.items()}
        for key, value in zip(fields, values, strict=False):
            if key == "id":
                value = prefix + value
            elif key in dicts and value is not None:
                value = dicts[key][value]
            elif key in ("verify", "live", "excluded") and value is not None:
                value = bool(value)
            row[key] = value
        out.append(row)
    return out
