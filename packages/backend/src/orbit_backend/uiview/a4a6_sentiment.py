"""A6 情绪与语义 adapter: ``GET /v1/uiview/sentiment``.

Deterministic only: lexical detectors over confirmed, redacted human messages (``v_human_message``),
optional AI-03 facets read from app.db. Never calls a model; every rate carries its ``n``.
Sections: language mix, mood / correction series, friction, high-frequency feedback phrases and the
everyday word cloud (``terms``, built in ``a6_terms``). The former semantic topics and mood drivers
were removed from the page and are no longer computed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..analytics.common import quantile
from ..analytics.interaction.rules import correction_kind, correction_verdict
from ..analytics.products.feedback import classify_emotion
from ..features.vocab import command_info
from ..privacy import direct_user_text, redact
from .a4a6_common import ManyQuery
from .a6_terms import build_terms

DAY_MS = 86_400_000
DEFINITION_VERSION = "a6-corr-v3"  # v3: 复用 analytics.interaction.rules 的唯一纠偏判定
EXPERIMENTAL_NOTE = "词面候选规则，未经人工标注验证；仅供趋势参考"

# 待验证 V-A13：语言占比阈值。
ZH_MIN, EN_MAX, MIN_CHARS = 0.7, 0.1, 3
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_LATIN = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")

EMOTION_SCORE = {"positive": 1.0, "negative": -1.0, "mixed": 0.0, "neutral": 0.0}

FRICTION_LABELS = {
    "misunderstood_request": "误解需求", "wrong_approach": "方向错误",
    "excessive_changes": "改动过度", "tool_env_failure": "工具 / 环境失败",
    "parallel_conflict": "并行会话冲突", "process_overhead": "流程过重（子代理）",
    "permission_friction": "权限询问打断", "context_loss": "上下文丢失",
    "quota_interrupt": "额度中断", "other": "其他",
}
READ_ONLY_KINDS = {"read", "search", "file.read", "list"}
FAILED = ("failed", "error")

PHRASE_MAX = 40
PHRASE_RULES = (  # priority: 纠偏 > 验证 > 规划 > 风格 > 偏好
    ("验证", re.compile(r"验证|测试|跑一下|\b(?:check|verify|test)\b", re.I)),
    ("规划", re.compile(r"先|计划|只读|审查|\bplan\b", re.I)),
    ("风格", re.compile(r"简洁|详细|格式|\bconcise\b", re.I)),
    ("偏好", re.compile(r"用中文|用英文|默认")),
)


# ------------------------------------------------------------------ pure text helpers

def semantic_text(text: str | None) -> str:
    """Local copy of ``analytics.common.semantic_messages`` quote stripping (pure)."""
    clean = direct_user_text(text or "")
    return re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"|`[^`\n]*`', "", clean).strip()


def corrections(text: str | None) -> list[dict]:
    """Per-rule hits of the single correction verdict (``analytics.interaction.rules``);
    empty unless the message is a correction (result feedback alone is not)."""
    if correction_kind(text) != "correction":
        return []
    hits, seen = [], set()
    for hit in correction_verdict(text)["hits"]:
        if hit["term"] not in seen:
            seen.add(hit["term"])
            hits.append({"detector": "interaction.correction_terms", "rule": hit["rule"],
                         "term": hit["term"]})
    return hits


def language_of(text: str | None) -> str:
    text = text or ""
    cjk, latin = len(_CJK.findall(text)), len(_LATIN.findall(text))
    if cjk + latin + len(_DIGIT.findall(text)) < MIN_CHARS or cjk + latin == 0:
        return "unknown"
    share = cjk / (cjk + latin)
    return "zh" if share >= ZH_MIN else "en" if share <= EN_MAX else "mixed"


def normalize_phrase(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded
                   if not unicodedata.category(ch).startswith(("P", "Z", "S", "C")))


def phrase_category(text: str) -> str:
    if corrections(text):
        return "纠偏"
    for label, pattern in PHRASE_RULES:
        if pattern.search(text):
            return label
    return "其他"


def emotion_score(text: str) -> float | None:
    label = classify_emotion(text) if text else None
    return EMOTION_SCORE.get(label) if label else None


# ------------------------------------------------------------------ data access

def scope_sql(scope: dict | None, alias: str = "s") -> tuple[str, list]:
    scope = scope or {}
    sql, params = [f"{alias}.kind='main'"], []
    if scope.get("project_ids"):
        ids = list(scope["project_ids"])
        sql.append(f"{alias}.project_id IN ({','.join('?' * len(ids))})")
        params += ids
    if scope.get("agent_ids"):
        ids = list(scope["agent_ids"])
        sql.append(f"{alias}.source_id IN (SELECT source_id FROM source WHERE agent IN "
                   f"({','.join('?' * len(ids))}))")
        params += ids
    if scope.get("from_ts") is not None:
        sql.append(f"{alias}.started_at >= ?")
        params.append(scope["from_ts"])
    if scope.get("until_ts") is not None:
        sql.append(f"{alias}.started_at < ?")
        params.append(scope["until_ts"])
    if scope.get("session_uids") is not None:
        sql.append(f"{alias}.session_uid IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(list(scope["session_uids"])))
    # Same source range and exclusion list as A1/A3/A4 (services.routes_analytics.analytics_scope):
    # ``source_ids`` None = every source, [] = none; excluded sessions never reach A5/A6 text.
    if scope.get("source_ids") is not None:
        sql.append(f"{alias}.source_id IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(list(scope["source_ids"])))
    if scope.get("excluded_session_uids"):
        sql.append(f"{alias}.session_uid NOT IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(list(scope["excluded_session_uids"])))
    if scope.get("excluded_cwd_prefix"):
        sql.append(f"({alias}.cwd IS NULL OR {alias}.cwd NOT LIKE ?)")
        params.append(scope["excluded_cwd_prefix"] + "%")
    return " AND ".join(sql), params


def fetch_sessions(conn, scope) -> dict[str, dict]:
    where, params = scope_sql(scope)
    rows = conn.execute(
        f"SELECT s.session_uid, s.project_id, s.cwd, s.git_remote, s.started_at, s.ended_at, "
        f"src.agent, (SELECT MAX(e.ts) FROM event e WHERE e.session_uid=s.session_uid) AS last_ts "
        f"FROM session s JOIN source src ON src.source_id=s.source_id WHERE {where} "
        f"ORDER BY s.started_at, s.session_uid", params).fetchall()
    out = {}
    for r in rows:
        start = r["started_at"]
        end = r["ended_at"] if r["ended_at"] is not None else r["last_ts"]
        if start is not None and (end is None or end < start):
            end = start
        out[r["session_uid"]] = {**dict(r), "end": end}
    return out


def _in(ids) -> str:
    return ",".join("?" * len(ids))


def _chunks(ids, size=500):
    ids = list(ids)
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def fetch_humans(conn, session_ids) -> list[dict]:
    out = []
    for chunk in _chunks(session_ids):
        for r in conn.execute(
                f"SELECT h.event_uid, h.session_uid, h.seq, h.ts, h.text, h.attrs FROM v_human_message h "
                f"WHERE h.session_uid IN ({_in(chunk)}) ORDER BY h.session_uid, h.seq", chunk):
            attrs = json.loads(r["attrs"] or "{}")
            if attrs.get("replayed_from") or attrs.get("duplicate_of"):
                continue
            out.append({"event_uid": r["event_uid"], "session_uid": r["session_uid"],
                        "seq": r["seq"], "ts": r["ts"], "raw": r["text"] or "",
                        "text": semantic_text(r["text"])})
    return out


def fetch_calls(conn, session_ids) -> list[dict]:
    """Tool calls attributed to their root (main) session, ordered by event seq."""
    out = []
    for chunk in _chunks(session_ids):
        for r in conn.execute(
                f"SELECT t.call_uid, t.root_uid, t.session_uid, t.name, t.name_raw, t.kind, "
                f"t.command_head, t.files, t.status, t.approval, t.started_at, e.seq, "
                f"json_extract(e.attrs, '$.input.command') AS command "
                f"FROM v_analysis_tool_call t LEFT JOIN event e ON e.event_uid=t.call_event_uid "
                f"WHERE t.root_uid IN ({_in(chunk)})", chunk):
            out.append(dict(r))
    out.sort(key=lambda c: (c["root_uid"], c["session_uid"] != c["root_uid"],
                            c["seq"] if c["seq"] is not None else 1 << 62,
                            c["started_at"] or 0, c["call_uid"]))
    return out


def _appdb_rows(appdb, sql, params=()) -> list:
    if appdb is None:
        return []
    from .facts import is_schema_gap

    try:
        with appdb.read() as db:
            return db.execute(sql, params).fetchall()
    except sqlite3.OperationalError as error:  # older app.db without the table/column only
        if not is_schema_gap(error):
            raise
        return []


# ------------------------------------------------------------------ builders

def bucket_mode(since: int, until: int, requested: str = "auto") -> str:
    if requested in ("day", "week"):
        return requested
    return "week" if until - since > 31 * DAY_MS else "day"


def bucket_key(ts: int, mode: str, zone) -> str:
    date = datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone(zone).date()
    if mode == "week":
        year, week, _ = date.isocalendar()
        return f"{year}-W{week:02d}"
    return date.isoformat()


def _round(value, digits=3):
    return None if value is None else round(value, digits)


def session_balances(humans) -> tuple[dict[str, float], dict[str, int]]:
    scores: dict[str, list[float]] = defaultdict(list)
    for m in humans:
        score = emotion_score(m["text"])
        if score is not None:
            scores[m["session_uid"]].append(score)
    return ({uid: sum(v) / len(v) for uid, v in scores.items()},
            {uid: len(v) for uid, v in scores.items()})


def build_series(humans, sessions, mode, zone) -> list[dict]:
    per: dict[str, dict] = defaultdict(lambda: {"sessions": set(), "scores": defaultdict(list),
                                                "corr": 0})
    for m in humans:
        ts = m["ts"] if m["ts"] is not None else sessions[m["session_uid"]]["started_at"]
        if ts is None:
            continue
        b = per[bucket_key(ts, mode, zone)]
        b["sessions"].add(m["session_uid"])
        score = emotion_score(m["text"])
        if score is not None:
            b["scores"][m["session_uid"]].append(score)
        if corrections(m["raw"]):
            b["corr"] += 1
    hot_line = quantile([b["corr"] for b in per.values()], 0.75) or 0
    out = []
    for key in sorted(per):
        b = per[key]
        balances = [sum(v) / len(v) for v in b["scores"].values()]
        spread = len(balances) >= 2 and len(b["sessions"]) >= 2
        out.append({"bucket": key, "n_sessions": len(b["sessions"]),
                    "explicit_n": sum(len(v) for v in b["scores"].values()),
                    "p25": _round(quantile(balances, 0.25)) if spread else None,
                    "p50": _round(quantile(balances, 0.5)) if balances else None,
                    "p75": _round(quantile(balances, 0.75)) if spread else None,
                    "corr": b["corr"], "corr_hot": b["corr"] >= max(hot_line, 2)})
    return out


def _facets(appdb, session_ids) -> dict[str, list[str]]:
    out: dict[str, tuple[int, list[str]]] = {}
    ids = list(session_ids)
    for chunk in _chunks(ids):
        for row in _appdb_rows(appdb, f"SELECT session_uid, json, created_at FROM ai_facet "
                                      f"WHERE status='ok' AND session_uid IN ({_in(chunk)})", chunk):
            try:
                types = json.loads(row[1] or "{}").get("friction_types") or []
            except (ValueError, AttributeError):
                continue
            if row[0] not in out or row[2] > out[row[0]][0]:
                out[row[0]] = (row[2], [t for t in types if isinstance(t, str)])
    return {uid: types for uid, (_, types) in out.items()}


def _rule_frictions(calls) -> dict[str, set[str]]:
    failed: Counter = Counter()
    asked: Counter = Counter()
    for c in calls:
        if c["status"] in FAILED:
            failed[c["root_uid"]] += 1
        # One read-only definition with A4 (features.vocab.command_info, argument-aware).
        if c["approval"] is not None and (
                (c["command_head"] and command_info(c["command_head"], c.get("command"))["cls"]
                 == "readonly") or c["kind"] in READ_ONLY_KINDS):
            asked[c["root_uid"]] += 1
    out: dict[str, set[str]] = defaultdict(set)
    for uid, n in failed.items():
        if n >= 2:
            out[uid].add("tool_env_failure")
    for uid, n in asked.items():
        if n >= 1:
            out[uid].add("permission_friction")
    return out


def session_frictions(appdb, session_ids, calls) -> dict[str, tuple[set[str], str]]:
    facets = _facets(appdb, session_ids)
    rules = _rule_frictions(calls)
    out = {}
    for uid in session_ids:
        if uid in facets:
            out[uid] = (set(facets[uid]), "facet")
        elif rules.get(uid):
            out[uid] = (rules[uid], "rule")
    return out


def _typical(humans_by_session, uids, limit=3) -> list[str]:
    picked: list[str] = []
    for uid in uids:
        msgs = humans_by_session.get(uid, [])
        best = next((m for m in msgs if corrections(m["raw"])), msgs[0] if msgs else None)
        if best and best["text"]:
            picked.append(redact(best["text"])[:80])
        if len(picked) >= limit:
            break
    return picked


def build_friction(cur, prev, balances, humans_by_session) -> list[dict]:
    now_types: dict[str, list[str]] = defaultdict(list)
    sources: dict[str, set[str]] = defaultdict(set)
    for uid, (types, source) in cur.items():
        for t in sorted(types):
            key = t if t in FRICTION_LABELS else "other"
            now_types[key].append(uid)
            sources[key].add(source)
    prev_counts: Counter = Counter()
    for types, _ in prev.values():
        for t in set(t if t in FRICTION_LABELS else "other" for t in types):
            prev_counts[t] += 1
    out = []
    for key in sorted(set(now_types) | set(prev_counts),
                      key=lambda k: (-len(now_types.get(k, [])), k)):
        uids = sorted(set(now_types.get(key, [])))
        vals = [balances[u] for u in uids if u in balances]
        src = sources.get(key) or set()
        out.append({"type": key, "label": FRICTION_LABELS[key], "sessions": len(uids),
                    "prev": prev_counts[key], "delta": len(uids) - prev_counts[key],
                    "avg_balance": _round(sum(vals) / len(vals)) if vals else None,
                    "type_source": src.pop() if len(src) == 1 else "mixed" if src else None,
                    "typical": _typical(humans_by_session, uids),
                    "session_uids": uids})
    return out


def build_phrases(humans, limit=30) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in humans:
        text = m["text"]
        if not text or len(text) > PHRASE_MAX:
            continue
        key = normalize_phrase(text)
        if key:
            groups[key].append(m)
    out = []
    for msgs in groups.values():
        sessions = {m["session_uid"] for m in msgs}
        if len(sessions) < 2:
            continue
        text = Counter(m["text"] for m in msgs).most_common(1)[0][0]
        out.append({"text": redact(text), "n": len(msgs), "sessions": len(sessions),
                    "category": phrase_category(text),
                    "event_uids": [m["event_uid"] for m in msgs[:3]]})
    out.sort(key=lambda p: (-p["sessions"], -p["n"], p["text"]))
    return out[:limit]


def build_meta(appdb) -> dict:
    settings = {r[0]: r[1] for r in _appdb_rows(
        appdb, "SELECT key, value FROM ai_setting WHERE key IN ('mode','default_engine')")}

    def val(key, default):
        try:
            return json.loads(settings[key]) if key in settings else default
        except ValueError:
            return default

    last = _appdb_rows(appdb, "SELECT MAX(COALESCE(finished_at, created_at)) FROM ai_job")
    return {"engine": val("default_engine", None), "mode": val("mode", "stats"),
            "last_job_at": last[0][0] if last else None, "remote": True,
            "method": "lexical_rules+ai_facet", "definition_version": DEFINITION_VERSION,
            "experimental": True, "note": EXPERIMENTAL_NOTE,
            "privacy": "脱敏后的文本在启用 AI 引擎时会发往该引擎的服务商"}


def _window(params, now_ms):
    until = params.get("until") or now_ms
    since = params.get("since") or until - int(params.get("days") or 30) * DAY_MS
    return int(since), int(until)


def build_sentiment(conn, appdb, scope, params, *, now_ms: int) -> dict:
    params = params or {}
    since, until = _window(params, now_ms)
    zone = ZoneInfo(params["tz"]) if params.get("tz") else datetime.now().astimezone().tzinfo
    base = {k: v for k, v in (scope or {}).items() if k not in ("from_ts", "until_ts")}
    sessions = fetch_sessions(conn, {**base, "from_ts": since, "until_ts": until})
    prev_sessions = fetch_sessions(conn, {**base, "from_ts": since - (until - since),
                                          "until_ts": since})
    humans = fetch_humans(conn, sessions)
    by_session: dict[str, list[dict]] = defaultdict(list)
    for m in humans:
        by_session[m["session_uid"]].append(m)
    calls = fetch_calls(conn, sessions)
    balances, _ = session_balances(humans)
    mix = Counter(language_of(m["text"]) for m in humans)
    mode = bucket_mode(since, until, params.get("bucket") or "auto")
    cur = session_frictions(appdb, sessions, calls)
    prev = session_frictions(appdb, prev_sessions, fetch_calls(conn, prev_sessions))
    return {
        "meta": {**build_meta(appdb), "window": {"since": since, "until": until},
                 "bucket": mode, "n_sessions": len(sessions), "n_messages": len(humans)},
        "language_mix": {k: mix.get(k, 0) for k in ("zh", "en", "mixed", "unknown")}
        | {"n": len(humans)},
        "series": build_series(humans, sessions, mode, zone),
        "friction": build_friction(cur, prev, balances, by_session),
        "phrases": build_phrases(humans),
        "terms": build_terms(humans, sessions, zone),
    }


# ------------------------------------------------------------------ route

def register(api, gw) -> None:
    from pathlib import Path

    from fastapi import Depends, Query

    from ..services.auth import ApiError
    from ..services.routes_data import mark_empty
    from . import a4a6_common as common

    range_dependency = Depends(common.range_scope)

    @api.get("/v1/uiview/sentiment")
    def sentiment(project_id: ManyQuery = None, agent: ManyQuery = None, agents: str | None = None,
                  since: int | None = None, until: int | None = None,
                  days: int = Query(30, ge=1, le=730), bucket: str = "auto",
                  tz: str | None = None, topic: str | None = None, outcome: str | None = None,
                  fric: str | None = None, hour: int | None = Query(None, ge=0, le=23),
                  wait_ms: int = Query(0, ge=0, le=3000),
                  ranges: dict = range_dependency):
        if bucket not in ("auto", "day", "week"):
            raise ApiError(400, "invalid_request", "bucket 只接受 auto|day|week")
        if since is not None and until is not None and since >= until:
            raise ApiError(400, "invalid_request", "since 必须早于 until")
        if tz:
            try:
                ZoneInfo(tz)
            except Exception as exc:  # noqa: BLE001
                raise ApiError(400, "invalid_request", "tz 不是有效的 IANA 时区") from exc
        ids, early = common.facet_sessions(
            gw, {"topic": topic, "outcome": outcome, "fric": fric, "hour": hour}, tz, wait_ms)
        if early is not None:
            return early
        scope = {"project_ids": project_id or None,
                 "agent_ids": common.agent_list(agent, agents), "session_uids": ids, **ranges,
                 "excluded_cwd_prefix": str(Path(gw.home) / "agent-cwd")}
        params = {"since": since, "until": until, "days": days, "bucket": bucket, "tz": tz}
        with gw.reads.read(empty=True) as conn:
            body = build_sentiment(conn, gw.appdb, scope, params, now_ms=int(time.time() * 1000))
            return mark_empty(body) if gw.reads.is_empty(conn) else body
