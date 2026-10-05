"""A4 工具调用 + Lite 工具页 presentation adapter: ``GET /v1/uiview/tools``.

One scan over ``v_analysis_tool_call`` (joined to session/source; ``seq`` via covering indexes) builds
every block of the page: KPIs with previous window and 12 weekly buckets, the per-tool
table, the kind transition matrix, repeated-failure runs, failure reasons, approval
waits, MCP servers (calls ∪ linked inventory) and sub-agent parallelism.

Rules kept honest:
- status: ``metrics.tool_state`` (ok / failed / stopped / unknown, shared with A1 and A3);
  interrupted or refused calls are known results that are not failures.
  Error rates use known results only; text never decides success.
- failure reasons: ``error_class`` first, else regex rules over the redacted result text.
- resident tokens of an MCP server are only filled when inventory measured them.
- tool rows group by ``sessionops.toolcalls.tool_name_key`` (case-folded + a short alias
  map), so one tool spelled Bash / bash by two agents is one row; ``aliases`` keeps the
  original spellings and the drilldown accepts the key or any of them.
- every constant below marked 待验证 is a first guess to be checked against real data.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, Query
from orbit_data.privacy import redact

from ..features.vocab import command_info
from ..sessionops.toolcalls import args_summary, tool_name_key
from . import a4a6_common as common
from . import metrics

NAME = "tools"
PARALLEL_WINDOW_MS = 5000  # 待验证: sub-agents started within 5 s of a batch's first one.
MIN_CHAIN_SUPPORT = 3  # 待验证: a kind triple must appear in ≥3 sessions.
TYPICAL_CHARS = 200
MAX_SESSIONS = 10
MAX_DAYS = 366
MAX_RETRIES = 10
CHUNK = 500

OK = metrics.TOOL_OK
FAILED = metrics.TOOL_FAILED
NODES = ("read", "search", "edit", "shell", "subagent", "web")
NODE_OF = {"file.read": "read", "search": "search", "file.edit": "edit", "file.write": "edit",
           "shell": "shell", "subagent": "subagent", "web.search": "web", "web.fetch": "web"}
WAIT_BUCKETS = (  # 待验证: left-closed, right-open, in ms.
    ("<5s", 0, 5_000), ("5–15s", 5_000, 15_000), ("15–30s", 15_000, 30_000),
    ("30–60s", 30_000, 60_000), ("1–2m", 60_000, 120_000), ("2–5m", 120_000, 300_000),
    (">5m", 300_000, None))
FAILURE_RULES = (  # 待验证: first match wins, case-insensitive.
    ("env_missing", "环境/命令不存在", r"command not found|not found|no such file"),
    ("permission", "权限被拒", r"permission denied|eacces|eperm"),
    ("timeout", "超时", r"timed? ?out|timeout"),
    ("network", "网络", r"could not resolve|econn|network"),
    ("arguments", "参数/语法", r"unknown option|usage:|invalid (option|argument)|syntax error"),
)
OTHER = ("other", "其他")
PARALLEL_DEGREES = ("1", "2", "3", "4+")

CALLS_SQL = """
SELECT tc.call_uid, tc.session_uid, s.root_uid, s.kind AS session_kind,
       COALESCE(tc.project_id, s.project_id) AS project_id, src.agent, tc.name_raw, tc.kind,
       tc.mcp_server, tc.command_head, tc.status, tc.error_class, tc.exit_code, tc.duration_ms,
       tc.duration_quality, tc.started_at, tc.approval, tc.approval_wait_ms,
       tc.argument_digest, tc.subagent_session_uid, tc.result_event_uid, tc.call_event_uid,
       {rowid} AS call_event_rowid
FROM v_analysis_tool_call tc
JOIN session s ON s.session_uid = tc.session_uid
LEFT JOIN source src ON src.source_id = s.source_id
WHERE {{where}}
""".format(rowid=common.CALL_EVENT_ROWID_SQL.format(col="tc.call_event_uid"))


def node_of(kind: str | None) -> str:
    return NODE_OF.get(kind or "", "other")


def tool_key(row: dict, group_by: str = "name") -> str:
    """Row key: the kind, ``mcp·<server>``, or the normalised tool name, so Bash / bash from
    two agents are one row. ``GET /v1/analytics/tool_calls?name=`` takes the key or any alias."""
    if group_by == "kind":
        return row["kind"] or "other"
    if row["kind"] == "mcp" and row["mcp_server"]:
        return f"mcp·{row['mcp_server']}"
    return tool_name_key(row["name_raw"])


def aliases(items) -> list[dict]:
    """Original spellings behind one row: ``[{name, agents, n}]``, most used first."""
    seen: dict[str, dict] = {}
    for r in items:
        a = seen.setdefault(r["name_raw"], {"name": r["name_raw"], "agents": set(), "n": 0})
        a["n"] += 1
        if r["agent"]:
            a["agents"].add(r["agent"])
    return [{**a, "agents": sorted(a["agents"])}
            for a in sorted(seen.values(), key=lambda a: (-a["n"], a["name"]))]


# -- reads -------------------------------------------------------------------------------

def fetch_calls(conn, scope, *, agents=None, from_ts=None, until_ts=None) -> list[dict]:
    where, params = common.scope_where(scope, "s", agents=agents, time_col="tc.started_at",
                                       from_ts=from_ts, until_ts=until_ts)
    cursor = conn.cursor()
    cursor.row_factory = None  # Plain tuples: ~2x faster than sqlite3.Row → dict at 100k rows.
    cursor.execute(CALLS_SQL.format(where=where), params)
    names = [d[0] for d in cursor.description]
    rows = []
    for values in cursor:
        row = dict(zip(names, values, strict=True))
        row["state"] = metrics.tool_state(row["status"])
        rows.append(row)
    return common.attach_call_command(conn, common.attach_event_seq(conn, rows))


def _texts(conn, uids) -> dict[str, str]:
    uids = sorted({u for u in uids if u})
    out = {}
    for start in range(0, len(uids), CHUNK):
        part = uids[start:start + CHUNK]
        sql = (f"SELECT event_uid, text, attrs FROM event WHERE event_uid IN "
               f"({','.join('?' * len(part))})")
        out.update((r[0], (r[1], r[2])) for r in conn.execute(sql, part))
    return out


# -- blocks ------------------------------------------------------------------------------

def _counts(rows) -> dict:
    states = Counter(r["state"] for r in rows)
    known = len(rows) - states["unknown"]
    return {"n": len(rows), "failed": states["failed"], "known": known,
            "unknown": len(rows) - known}


def day_of(tz: ZoneInfo):
    """ts → local ISO date, memoised per 15 minutes (every UTC offset is a multiple)."""
    memo: dict[int, str] = {}

    def day(ts: int) -> str:
        slot = ts // 900_000
        value = memo.get(slot)
        if value is None:
            value = memo[slot] = datetime.fromtimestamp(slot * 900, UTC).astimezone(
                tz).date().isoformat()
        return value

    return day


def day_axis(rows, tz: ZoneInfo) -> list[str]:
    day = day_of(tz)
    dated = sorted({day(r["started_at"]) for r in rows if r["started_at"] is not None})
    if not dated:
        return []
    first = datetime.fromisoformat(dated[0]).date()
    last = datetime.fromisoformat(dated[-1]).date()
    span = min((last - first).days + 1, MAX_DAYS)
    return [(last.fromordinal(last.toordinal() - span + 1 + i)).isoformat() for i in range(span)]


def table(rows, group_by: str = "name", tz: ZoneInfo | None = None) -> list[dict]:
    tz = tz or ZoneInfo("UTC")
    days = day_axis(rows, tz)
    day = day_of(tz)
    index = {d: i for i, d in enumerate(days)}
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[tool_key(row, group_by)].append(row)
    out = []
    for key, items in groups.items():
        c = _counts(items)
        lo, hi = common.wilson(c["failed"], c["known"])
        durations = [r["duration_ms"] for r in items if r["duration_ms"] is not None]
        quality = Counter(r["duration_quality"] for r in items if r["duration_ms"] is not None)
        daily = [0] * len(days)
        for r in items:
            if r["started_at"] is not None:
                i = index.get(day(r["started_at"]))
                if i is not None:
                    daily[i] += 1
        first = items[0]
        names = aliases(items) if group_by == "name" else []
        out.append({
            "key": key, "name": key if group_by == "kind" else names[0]["name"],
            "aliases": names,
            "kind": first["kind"], "mcp_server": first["mcp_server"] if group_by == "name"
            else None, **c, "err": common.rate(c["failed"], c["known"]), "lo": lo, "hi": hi,
            "p50_ms": common.quantile(durations, 0.5), "p90_ms": common.quantile(durations, 0.9),
            "p95_ms": common.quantile(durations, 0.95),
            "duration_quality": {"reported": quality.get("reported", 0),
                                 "estimated": quality.get("estimated", 0)},
            "approval_rate": common.rate(sum(r["approval"] is not None for r in items),
                                         len(items)),
            "daily": daily, "days": days})
    out.sort(key=lambda t: (-t["n"], t["key"]))
    return out


def _session_order(rows) -> dict[str, list[dict]]:
    sessions: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sessions[row["session_uid"]].append(row)
    return sessions


def ordered_sessions(rows) -> tuple[list[list[dict]], int]:
    """Calls per session sorted by event ``seq``; a session with a NULL or repeated seq is
    dropped whole (its order cannot back an adjacency claim) and counted as excluded."""
    runs, excluded = [], 0
    for items in _session_order(rows).values():
        seqs = [r["seq"] for r in items]
        if any(not isinstance(s, int) or isinstance(s, bool) for s in seqs) \
                or len(set(seqs)) != len(seqs):
            excluded += len(items)
            continue
        runs.append(sorted(items, key=lambda r: r["seq"]))
    return runs, excluded


def matrix(rows) -> dict:
    runs, excluded = ordered_sessions(rows)
    nodes = list(NODES)
    if any(node_of(r["kind"]) == "other" for run in runs for r in run):
        nodes.append("other")
    at = {n: i for i, n in enumerate(nodes)}
    counts = [[0] * len(nodes) for _ in nodes]
    triples: Counter = Counter()
    support: dict[tuple, set] = defaultdict(set)
    pair_next: Counter = Counter()
    for run in runs:
        kinds = [node_of(r["kind"]) for r in run]
        for a, b in zip(kinds, kinds[1:], strict=False):
            counts[at[a]][at[b]] += 1
        for a, b, c in zip(kinds, kinds[1:], kinds[2:], strict=False):
            triples[(a, b, c)] += 1
            pair_next[(a, b)] += 1
            support[(a, b, c)].add(run[0]["session_uid"])
    row_n = [sum(r) for r in counts]
    prob = [[(v / n if n else 0.0) for v in r] for r, n in zip(counts, row_n, strict=True)]
    chain = None
    eligible = [t for t in triples if len(support[t]) >= MIN_CHAIN_SUPPORT]
    if eligible:
        best = max(eligible, key=lambda t: (len(support[t]), triples[t], tuple(-at[k] for k in t)))
        a, b, c = best
        chain = {"steps": list(best),
                 "probs": [prob[at[a]][at[b]], triples[best] / pair_next[(a, b)]],
                 "support_sessions": len(support[best])}
    return {"nodes": nodes, "counts": counts, "prob": prob, "row_n": row_n,
            "pairs": sum(row_n), "excluded_order_calls": excluded, "top_chain": chain}


def _sequence(items) -> list[dict]:
    return sorted(items, key=lambda r: (r["seq"] is None, r["seq"] or 0,
                                        r["started_at"] or 0, r["call_uid"]))


def retries(rows, conn=None) -> list[dict]:
    """Adjacent failed calls in one session with the same (tool name key, argument digest)."""
    runs: list[tuple[dict, int]] = []
    for items in _session_order(rows).values():
        seq = _sequence(items)
        length = 1
        for prev, cur in zip(seq, seq[1:], strict=False):
            same = (prev["state"] == cur["state"] == "failed" and cur["argument_digest"]
                    and (tool_name_key(prev["name_raw"]), prev["argument_digest"])
                    == (tool_name_key(cur["name_raw"]), cur["argument_digest"]))
            if same:
                length += 1
                continue
            if length > 1:
                runs.append((prev, length))
            length = 1
        if length > 1:
            runs.append((seq[-1], length))
    texts = _texts(conn, [r["call_event_uid"] for r, _ in runs]) if conn is not None else {}
    groups: dict[str, dict] = {}
    for row, length in runs:
        text, attrs = texts.get(row["call_event_uid"], (None, None))
        try:
            parsed = json.loads(attrs) if attrs else {}
        except ValueError:
            parsed = {}
        summary = args_summary(parsed, text) or row["command_head"] or row["name_raw"]
        g = groups.setdefault(summary, {"command": summary, "count": 0, "max_run": 0,
                                        "session_uids": []})
        g["count"] += length - 1
        g["max_run"] = max(g["max_run"], length)
        if row["session_uid"] not in g["session_uids"] and len(g["session_uids"]) < MAX_SESSIONS:
            g["session_uids"].append(row["session_uid"])
    return sorted(groups.values(), key=lambda g: (-g["count"], g["command"]))[:MAX_RETRIES]


def classify(text: str | None) -> tuple[str, str]:
    if text:
        for key, label, pattern in FAILURE_RULES:
            if re.search(pattern, text, re.IGNORECASE):
                return key, label
    return OTHER


def failures(conn, rows) -> dict:
    failed = [r for r in rows if r["state"] == "failed"]
    texts = _texts(conn, [r["result_event_uid"] for r in failed]) if conn is not None else {}
    groups: dict[tuple, dict] = {}
    clean: dict[str, str] = {}  # Failure texts repeat a lot; redact each distinct one once.
    for row in failed:
        raw = (texts.get(row["result_event_uid"]) or (None, None))[0]
        if raw and raw not in clean:
            clean[raw] = redact(raw).strip()
        text = clean[raw] if raw else None
        if row["error_class"]:
            key, label, source = row["error_class"], row["error_class"], "error_class"
        else:
            (key, label), source = classify(text), "text_rule"
        g = groups.setdefault((source, key), {"key": key, "label": label, "n": 0,
                                              "sessions": set(), "texts": Counter(),
                                              "source": source})
        g["n"] += 1
        g["sessions"].add(row["session_uid"])
        if text:
            g["texts"][text] += 1
    total = len(failed)
    out = []
    for g in groups.values():
        typical = g.pop("texts").most_common(1)
        sessions = sorted(g.pop("sessions"))
        out.append({**g, "share": g["n"] / total if total else None,
                    "sessions": len(sessions), "session_uids": sessions[:MAX_SESSIONS],
                    "typical": redact(typical[0][0][:TYPICAL_CHARS])[:TYPICAL_CHARS]
                    if typical else None})
    out.sort(key=lambda g: (-g["n"], g["key"]))
    return {"total": total, "unknown_status": sum(r["state"] == "unknown" for r in rows),
            "rows": out}


def wait_bucket(ms: int) -> str:
    for label, lo, hi in WAIT_BUCKETS:
        if ms >= lo and (hi is None or ms < hi):
            return label
    return WAIT_BUCKETS[0][0]


def approvals(rows) -> dict:
    asked = [r for r in rows if r["approval"] is not None]
    waits = [r["approval_wait_ms"] for r in asked if r["approval_wait_ms"] is not None]
    hist = Counter(wait_bucket(w) for w in waits)
    histogram = [{"bucket": label, "n": hist.get(label, 0)} for label, _, _ in WAIT_BUCKETS]
    half, running = None, 0
    for b in histogram:
        running += b["n"]
        if waits and running * 2 >= len(waits):
            half = b["bucket"]
            break
    heads = Counter()
    for r in asked:
        info = command_info(r["command_head"], r.get("command"))
        if r["command_head"] and info["cls"] == "readonly":
            heads[info["head"]] += 1
    agents = sorted({r["agent"] for r in rows if r["agent"]})
    with_ = sorted({r["agent"] for r in asked if r["agent"]})
    return {"count": len(asked), "timed_n": len(waits),
            "median_wait_ms": common.quantile(waits, 0.5), "sum_wait_ms": sum(waits),
            "histogram": histogram, "half_bucket": half,
            "readonly_prompted": {"n": sum(heads.values()), "heads": [
                {"head": h, "n": n} for h, n in sorted(heads.items(), key=lambda x: (-x[1], x[0]))
            ]},
            "agents_with": with_, "agents_without": [a for a in agents if a not in with_]}


def _norm_name(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _mcp_tools(server: str, rows) -> list[dict]:
    """Tools called under one MCP server: ``[{name, raw, n, failed, known, unknown, err}]``.
    ``name`` drops the ``mcp__<server>__`` prefix agents put in front of the tool name; calls with
    no tool name (empty, or only the server prefix) fold into one item with ``name`` None."""
    by: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by[row["name_raw"] or ""].append(row)
    prefix = re.compile(r"^(?:mcp__" + re.escape(server) + r"__|" + re.escape(server) + r"[./:])",
                        re.IGNORECASE)
    merged: dict[str, dict] = {}
    for raw, items in by.items():
        name = prefix.sub("", raw).strip() or None
        entry = merged.setdefault(name, {"name": name, "raw": [], "rows": []})
        if raw:
            entry["raw"].append(raw)
        entry["rows"].extend(items)
    out = []
    for entry in merged.values():
        c = _counts(entry["rows"])
        out.append({"name": entry["name"], "raw": sorted(entry["raw"]), **c,
                    "err": common.rate(c["failed"], c["known"])})
    return sorted(out, key=lambda t: (-t["n"], t["name"] is None, t["name"] or ""))


def mcp(rows, inventory_items) -> list[dict]:
    servers: dict[str, dict] = {}
    for row in rows:
        if not row["mcp_server"]:
            continue
        s = servers.setdefault(row["mcp_server"], {"rows": []})
        s["rows"].append(row)
    out: dict[str, dict] = {}
    for name, s in servers.items():
        c = _counts(s["rows"])
        dated = [r["started_at"] for r in s["rows"] if r["started_at"] is not None]
        out[_norm_name(name)] = {
            "server": name, "calls": c["n"], "failed": c["failed"],
            "err": common.rate(c["failed"], c["known"]),
            "sessions": len({r["session_uid"] for r in s["rows"]}),
            "last_used_at": max(dated) if dated else None, "status": "unscanned",
            "resident_tokens": None, "resident_basis": "unknown", "inv_id": None,
            "tools": _mcp_tools(name, s["rows"])}
    seen = set()
    for item in inventory_items or []:
        if item.get("type") != "mcp":
            continue
        ident = (item.get("config_path"), item.get("name"))
        if ident in seen:
            continue
        seen.add(ident)
        key = _norm_name(item.get("name"))
        entry = out.setdefault(key, {
            "server": item.get("name"), "calls": 0, "failed": 0, "err": None, "sessions": 0,
            "last_used_at": None, "status": None, "resident_tokens": None,
            "resident_basis": "unknown", "inv_id": None, "tools": []})
        if entry["inv_id"] is not None:
            continue  # Same server configured twice: the first scan wins.
        resident = item.get("resident") or {}
        basis = resident.get("basis") or "unknown"
        entry.update(status=item.get("status"), inv_id=item.get("inv_id"),
                     resident_basis=basis,
                     resident_tokens=resident.get("tokens_est") if basis != "unknown" else None)
    return sorted(out.values(), key=lambda m: (-m["calls"], m["server"] or ""))


def fetch_subagents(conn, scope, *, agents=None, from_ts=None, until_ts=None) -> list[dict]:
    where, params = common.scope_where(scope, "s", agents=agents, time_col="s.started_at",
                                       from_ts=from_ts, until_ts=until_ts)
    sql = ("SELECT s.session_uid, s.parent_uid, s.started_at, s.ended_at, s.status FROM session s "
           f"WHERE s.kind = 'subagent' AND {where}")
    return [dict(r) for r in conn.execute(sql, params)]


def parallel(subs) -> dict:
    """Group sibling sub-agents started within PARALLEL_WINDOW_MS of a batch's first one."""
    by_parent: dict[str, list[dict]] = defaultdict(list)
    for s in subs:
        by_parent[s["parent_uid"] or s["session_uid"]].append(s)
    batches: list[list[dict]] = []
    for items in by_parent.values():
        dated = sorted((s for s in items if s["started_at"] is not None),
                       key=lambda s: s["started_at"])
        batches += [[s] for s in items if s["started_at"] is None]
        current: list[dict] = []
        for s in dated:
            if current and s["started_at"] - current[0]["started_at"] > PARALLEL_WINDOW_MS:
                batches.append(current)
                current = []
            current.append(s)
        if current:
            batches.append(current)
    buckets = {d: {"degree": d, "n": 0, "stopped": 0} for d in PARALLEL_DEGREES}
    for batch in batches:
        b = buckets["4+" if len(batch) >= 4 else str(len(batch))]
        b["n"] += len(batch)
        b["stopped"] += sum(s["status"] == "interrupted" for s in batch)
    ge4 = buckets["4+"]
    lo, hi = common.wilson(ge4["stopped"], ge4["n"])
    return {"buckets": list(buckets.values()), "max": max((len(b) for b in batches), default=0),
            "stopped_share_ge4": {"value": common.rate(ge4["stopped"], ge4["n"]), "lo": lo,
                                  "hi": hi, "n": ge4["n"]}}


def _subagent_kpi(subs) -> dict:
    spans = [s["ended_at"] - s["started_at"] for s in subs
             if s["started_at"] is not None and s["ended_at"] is not None
             and s["ended_at"] >= s["started_at"]]
    return {"dispatches": len(subs), "avg_duration_ms": sum(spans) / len(spans) if spans else None,
            "max_parallel": parallel(subs)["max"]}


def _error(rows) -> dict:
    c = _counts(rows)
    return {"value": common.rate(c["failed"], c["known"]), **c}


def kpis(rows, prev_rows, weekly, *, subs=None, prev_subs=None, asked=None) -> dict:
    """``weekly`` is [(week_start_ms, rows)]; prev values are None without a prev window."""
    c = _counts(rows)
    roots = {r["root_uid"] for r in rows}
    lo, hi = common.wilson(c["failed"], c["known"])
    failed_shell = sum(r["state"] == "failed" and r["kind"] == "shell" for r in rows)
    err = _error(rows)
    prev_err = _error(prev_rows)["value"] if prev_rows is not None else None
    asked = asked or approvals(rows)
    prev_calls = len(prev_rows) if prev_rows is not None else None
    prev_asked = (sum(r["approval"] is not None for r in prev_rows)
                  if prev_rows is not None else None)
    sub = _subagent_kpi(subs or [])
    prev_sub = len(prev_subs) if prev_subs is not None else None

    def trend(fn):
        return [{"week": start, "value": fn(items)} for start, items in weekly]

    return {
        "calls": {"value": c["n"], "per_session": common.rate(c["n"], len(roots)),
                  "prev": prev_calls, "delta": common.delta(c["n"], prev_calls),
                  "trend": trend(len)},
        "error_rate": {"value": err["value"], "lo": lo, "hi": hi, "failed": c["failed"],
                       "known": c["known"], "unknown": c["unknown"],
                       "unknown_share": common.rate(c["unknown"], c["n"]),
                       "shell_share": common.rate(failed_shell, c["failed"]),
                       "prev": prev_err, "delta": common.delta(err["value"], prev_err),
                       "trend": trend(lambda items: _error(items)["value"])},
        "approvals": {"count": asked["count"], "timed_n": asked["timed_n"],
                      "median_wait_ms": asked["median_wait_ms"],
                      "sum_wait_ms": asked["sum_wait_ms"], "prev": prev_asked,
                      "delta": common.delta(asked["count"], prev_asked),
                      "trend": trend(lambda items: sum(r["approval"] is not None
                                                       for r in items))},
        "subagent": {**sub, "prev": prev_sub, "delta": common.delta(sub["dispatches"], prev_sub)},
    }


def automation(approval: dict, retry_rows: list[dict], servers: list[dict]) -> list[dict]:
    out = []
    if approval["readonly_prompted"]["n"]:
        out.append({"kind": "permission_rule", "title": "只读命令自动放行",
                    "count": approval["readonly_prompted"]["n"], "candidate_id": None})
    if retry_rows:
        out.append({"kind": "hook", "title": "重复失败熔断",
                    "count": sum(r["count"] for r in retry_rows), "candidate_id": None})
    unused = [m for m in servers if m["status"] == "unused"]
    if unused:
        out.append({"kind": "removal", "title": "移除闲置 MCP", "count": len(unused),
                    "candidate_id": None})
    return out


# -- assembly ----------------------------------------------------------------------------

def _within(ts, lo, hi) -> bool:
    if ts is None:
        return lo is None and hi is None
    return (lo is None or ts >= lo) and (hi is None or ts < hi)


def build_tools(conn, scope, params: dict | None = None, *, inventory_items=None,
                now_ms: int) -> dict:
    params = params or {}
    s = common.scope_dict(scope)
    agents = params.get("agent") or None
    group_by = params.get("group_by") or "name"
    tz = ZoneInfo(s.get("display_timezone") or "UTC")
    lo, hi = s.get("from_ts"), s.get("until_ts")
    end = hi if hi is not None else now_ms
    weeks = common.week_buckets(end)
    prev = common.prev_window(lo, hi)
    floor = None if lo is None else min(lo, weeks[0][0], prev[0] if prev else lo)
    span = fetch_calls(conn, scope, agents=agents, from_ts=floor, until_ts=hi)
    rows = [r for r in span if _within(r["started_at"], lo, hi)]
    prev_rows = [r for r in span if prev and _within(r["started_at"], *prev)] if prev else None
    weekly = [(a, []) for a, _ in weeks]
    first_week = weeks[0][0]
    for r in span:
        ts = r["started_at"]
        if ts is not None and first_week <= ts < end:
            weekly[(ts - first_week) // common.WEEK_MS][1].append(r)
    sub_span = fetch_subagents(conn, scope, agents=agents, from_ts=floor, until_ts=hi)
    subs = [x for x in sub_span if _within(x["started_at"], lo, hi)]
    prev_subs = [x for x in sub_span if _within(x["started_at"], *prev)] if prev else None

    tools = table(rows, group_by, tz)
    approval = approvals(rows)
    retry_rows = retries(rows, conn)
    servers = mcp(rows, inventory_items)
    c = _counts(rows)
    durations = Counter(r["duration_quality"] for r in rows)
    coverage = {"status_known_share": common.rate(c["known"], c["n"]),
                "approval_agents_with": approval["agents_with"],
                "approval_agents_without": approval["agents_without"],
                "duration_quality": {k: durations.get(k, 0)
                                     for k in ("reported", "estimated", "missing")},
                "inventory": "available" if inventory_items is not None else "unavailable",
                "ignored_scope": [k for k in ("model_ids", "effort_raw", "scene",
                                              "legacy_project_ids") if s.get(k)]}
    return {
        "coverage": coverage,
        "header": {"calls": c["n"], "tool_kinds": len(tools), "mcp_servers": len(servers),
                   "sessions": len({r["root_uid"] for r in rows})},
        "kpis": kpis(rows, prev_rows, weekly, subs=subs, prev_subs=prev_subs, asked=approval),
        "tools": tools,
        "matrix": matrix(rows),
        "retries": retry_rows,
        "failures": failures(conn, rows),
        "approval": {"histogram": approval["histogram"], "half_bucket": approval["half_bucket"],
                     "readonly_prompted": approval["readonly_prompted"], "candidate_id": None},
        "mcp": servers,
        "parallel": parallel(subs),
        "automation": automation(approval, retry_rows, servers),
    }


# -- route -------------------------------------------------------------------------------

def _inventory(scope, agents) -> list[dict] | None:
    from .. import features

    try:
        s = common.scope_dict(scope)
        agent_ids = [*(s.get("agent_ids") or []), *(agents or [])] or None
        return features.linked_inventory({"project_ids": s.get("project_ids"),
                                          "agent_ids": agent_ids}).get("items", [])
    except Exception:  # noqa: BLE001 - inventory is optional; the page shows 未扫描.
        return None


def _candidates(gw, scope) -> dict[str, str]:
    """kind → candidate_id from the latest recommendation run of this scope (best effort)."""
    from ..recommend import store

    try:
        with gw.appdb.read() as conn:
            run = store.latest_run(conn, common.scope_hash(scope))
            if run is None:
                return {}
            out: dict[str, str] = {}
            for card in store.candidates(conn, run["run_id"], limit=50):
                kind = card.get("kind") or card.get("type")
                if kind in ("permission_rule", "hook", "removal") and kind not in out:
                    out[kind] = card["candidate_id"]
            return out
    except Exception:  # noqa: BLE001 - a missing run never blocks the page.
        return {}


def _with_candidates(body: dict, ids: dict[str, str]) -> dict:
    if not ids:
        return body
    return {**body,
            "automation": [{**a, "candidate_id": ids.get(a["kind"])} for a in body["automation"]],
            "approval": {**body["approval"], "candidate_id": ids.get("permission_rule")}}


def register(api, gw) -> None:
    from ..services.routes_analytics import analytics_scope

    scope_dependency = Depends(analytics_scope)

    @api.get("/v1/uiview/tools")
    def uiview_tools(scope=scope_dependency,
                     group_by: Literal["name", "kind"] = "name",
                     agent: Annotated[list[str] | None, Query()] = None,
                     agents: str | None = None, topic: str | None = None,
                     outcome: str | None = None, fric: str | None = None,
                     hour: int | None = Query(None, ge=0, le=23),
                     wait_ms: int = Query(0, ge=0, le=3000)):
        facets = {"topic": topic, "outcome": outcome, "fric": fric, "hour": hour}
        params = {"group_by": group_by, "agent": common.agent_list(agent, agents) or [],
                  **{k: v for k, v in facets.items() if v not in (None, "")}}
        ids, early = common.facet_sessions(gw, facets, scope.display_timezone, wait_ms)
        if early is not None:
            return early
        if ids is not None:
            current = scope.root_session_uids
            scope = replace(scope, root_session_uids=ids if current is None
                            else sorted(set(ids) & set(current)))
        rev = gw.revisions.snapshot()
        if rev.get("data_rev") is None:
            return {"meta": common.ui_meta(scope, rev, {}, params=params, freshness="none",
                                           reason="no_projection")}
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        # Without until_ts the weekly trend ends today: the day joins the cache key.
        day = None if common.scope_dict(scope).get("until_ts") is not None \
            else now_ms // common.DAY_MS
        key = common.cache_key(NAME, scope, {**params, "day": day}, rev, home=gw.home)
        cached = common.CACHE.get(key)
        if cached is None:
            inventory = _inventory(scope, params["agent"])
            with gw.reads.read() as conn:
                cached = build_tools(conn, scope, params, inventory_items=inventory,
                                     now_ms=now_ms)
            common.CACHE.put(key, cached)
            source = "computed"
        else:
            source = "cache"
        body = dict(_with_candidates(cached, _candidates(gw, scope)))
        coverage = body.pop("coverage")
        return {"meta": common.ui_meta(scope, rev, coverage, params=params, freshness="fresh",
                                       source=source), **body}
