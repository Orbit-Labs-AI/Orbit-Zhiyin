"""A5 项目习惯 + Lite 项目页 adapter: ``GET /v1/uiview/projects[/{project_id}]``.

Read-only over tandem.db (+ app.db recommendation runs). Durations are observed spans including idle
time; friction is a lexical correction candidate rate; nothing is fitted or regressed.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..ai.pack import VERIFY_RE
from ..analytics.features import LANG
from ..analytics.outcome_subjective.extraction import classify_feedback
from ..install.env import AGENTS, capabilities
from ..privacy import redact
from ..recommend.outcomes import newcombe, welch, wilson
from . import metrics
from .a4a6_common import ManyQuery
from .a4a6_sentiment import (
    FAILED,
    _appdb_rows,
    corrections,
    fetch_calls,
    fetch_humans,
    fetch_sessions,
)

HOUR_MS = 3_600_000
DAY_MS = 86_400_000
# hours = 活跃时长 (uiview.metrics.active_ms, same as A1/A3 ``dur``); the old wall-clock
# span union (idle included) is kept as ``span`` and never presented as working time.
HOURS_BASIS = "active_estimate"
SPAN_BASIS = "observed_span_union_incl_idle"
SCATTER_MIN_SESSIONS = 5
COMPARE_MIN_N = 5
SCATTER_NOTE = "相关不等于因果"
WORKFLOW_MIN_SUPPORT = 3
WORKFLOW_LENGTHS = (3, 4, 5)
COVERAGE_TYPES = ("rule", "hook", "skill", "mcp", "subagent")
CAPABILITY_OF = {"rule": "rules", "hook": "hooks", "skill": "skills", "mcp": "mcp",
                 "subagent": "subagents"}
METRICS = (
    ("avg_session_minutes", "平均会话分钟", "mean"),
    ("messages_per_session", "每会话消息", "mean"),
    ("autonomy", "自主比（工具调用 / (工具调用 + 人类消息)）", "prop"),
    ("verify_rate", "要求验证的会话占比", "prop"),
    ("friction_rate", "纠偏候选率", "prop"),
    ("daily_sessions", "日均会话（活跃日）", "mean"),
)


# ------------------------------------------------------------------ helpers

def _round(value, digits=3):
    return None if value is None else round(value, digits)


def union_ms(intervals) -> int:
    total, cur_start, cur_end = 0, None, None
    for start, end in sorted(i for i in intervals if i[0] is not None and i[1] is not None):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def hours_of(sessions) -> float | None:
    """Summed active time (hours); ``None`` when no session has a timestamped event."""
    known = [s["active_ms"] for s in sessions if s.get("active_ms") is not None]
    return round(sum(known) / HOUR_MS, 2) if known else None


def span_hours_of(sessions) -> float:
    """Wall-clock union of session spans, idle time included (``SPAN_BASIS``)."""
    return round(union_ms((s["started_at"], s["end"]) for s in sessions) / HOUR_MS, 2)


def _active(conn, session_ids) -> dict[str, int | None]:
    stamps: dict[str, list[int]] = {uid: [] for uid in session_ids}
    ids = list(session_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for root, ts in conn.execute(
                f"SELECT s.root_uid, e.ts FROM event e JOIN session s ON s.session_uid = "
                f"e.session_uid WHERE e.ts IS NOT NULL AND s.root_uid IN "
                f"({','.join('?' * len(chunk))})", chunk):
            stamps[root].append(ts)
    return {uid: metrics.active_ms(values) for uid, values in stamps.items()}


def _ext(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else None


def _day(ts) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts / 1000, timezone.utc).date().isoformat()


def load(conn, scope) -> dict:
    """Sessions with per-session stats: humans, corrections, calls, feedback and tags."""
    sessions = fetch_sessions(conn, scope)
    humans = fetch_humans(conn, sessions)
    calls = fetch_calls(conn, sessions)
    active = _active(conn, sessions)
    for s in sessions.values():
        s.update(active_ms=active.get(s["session_uid"]), msgs=0, corr=0, calls=0, verify=False, accepted=False, reworked=False,
                 feedback=False, exts=Counter(), heads=[], human_events=[])
    for m in humans:
        s = sessions[m["session_uid"]]
        s["msgs"] += 1
        s["human_events"].append(m)
        if corrections(m["raw"]):
            s["corr"] += 1
        fb = classify_feedback(m["raw"])
        if fb:
            s["feedback"] = True
            s["accepted"] |= fb.get("user_acceptance") == "accepted"
            s["reworked"] |= bool(fb.get("rework_feedback")) or fb.get("user_acceptance") == "rejected"
    for c in calls:
        s = sessions.get(c["root_uid"])
        if s is None:
            continue
        s["calls"] += 1
        head = (c["command_head"] or "").strip()
        if head and VERIFY_RE.search(head):
            s["verify"] = True
        try:
            files = json.loads(c["files"] or "[]")
        except ValueError:
            files = []
        for f in files:
            ext = _ext(str(f))
            if ext in LANG:
                s["exts"][LANG[ext]] += 1
        if c["session_uid"] == c["root_uid"]:
            s["heads"].append({"name": c["name_raw"] or c["name"], "head": head or None,
                               "key": head or c["kind"] or c["name"], "failed": c["status"] in FAILED})
    projects = {r["project_id"]: dict(r) for r in conn.execute(
        "SELECT project_id, key_type, key, name, git_remote, paths FROM project")}
    return {"sessions": sessions, "projects": projects, "calls": calls}


def friction_of(rows) -> dict:
    corr, msgs = sum(s["corr"] for s in rows), sum(s["msgs"] for s in rows)
    lo, hi = wilson(corr, msgs) if msgs else (None, None)
    return {"value": _round(corr / msgs) if msgs else None, "lo": _round(lo), "hi": _round(hi),
            "corr": corr, "msgs": msgs, "basis": "lexical_candidate"}


def agents_of(rows) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in rows:
        groups[s["agent"]].append(s)
    total = len(rows)
    return [{"agent": agent, "sessions": len(g), "share": _round(len(g) / total) if total else None,
             "hours": hours_of(g), "accepted": sum(s["accepted"] for s in g),
             "reworked": sum(s["reworked"] for s in g), "n": sum(s["feedback"] for s in g)}
            for agent, g in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


def _most_common(values):
    values = [v for v in values if v]
    return Counter(values).most_common(1)[0][0] if values else None


def _persona(pid, persona_lookup) -> dict:
    found = None
    if persona_lookup is not None:
        try:
            found = persona_lookup(pid)
        except Exception:  # noqa: BLE001 - optional adapter must never break the page
            found = None
    if not found:
        return {"code": None, "status": "persona_pending", "n_tasks": None,
                "reason": "persona_pending"}
    return {"code": found.get("code"), "status": found.get("status", "available"),
            "n_tasks": found.get("n_tasks")}


def project_row(pid, rows, project, persona_lookup) -> dict:
    project = project or {}
    exts = Counter()
    for s in rows:
        exts.update(s["exts"])
    msgs, calls = sum(s["msgs"] for s in rows), sum(s["calls"] for s in rows)
    return {"project_id": pid, "name": project.get("name") or pid,
            "path": _most_common(s["cwd"] for s in rows) or project.get("key"),
            "git": project.get("git_remote") or _most_common(s["git_remote"] for s in rows),
            "identity_quality": project.get("key_type"),
            "sessions": len(rows), "hours": {"value": hours_of(rows), "basis": HOURS_BASIS,
                                             "span": span_hours_of(rows),
                                             "span_basis": SPAN_BASIS},
            "agents": agents_of(rows), "friction": friction_of(rows),
            "tools_per_human_message": _round(calls / msgs, 2) if msgs else None,
            "tags": [name for name, _ in exts.most_common(2)],
            "persona": _persona(pid, persona_lookup)}


# ------------------------------------------------------------------ list

def build_projects(conn, scope, params, *, inventory_items=None, persona_lookup=None) -> dict:
    data = load(conn, scope)
    by_project: dict[str, list[dict]] = defaultdict(list)
    for s in data["sessions"].values():
        if s["project_id"]:
            by_project[s["project_id"]].append(s)
    rows = [project_row(pid, g, data["projects"].get(pid), persona_lookup)
            for pid, g in by_project.items()]
    rows.sort(key=lambda r: (-r["sessions"], r["project_id"]))
    points = [{"id": r["project_id"], "label": r["name"], "x": r["tools_per_human_message"],
               "y": r["friction"]["value"], "r": r["hours"]["value"], "n": r["sessions"]}
              for r in rows if r["sessions"] >= SCATTER_MIN_SESSIONS
              and r["tools_per_human_message"] is not None and r["friction"]["value"] is not None]
    body = {"meta": {"contract": "tandem-uiview-a4a6-v1", "hours_basis": HOURS_BASIS,
                     "span_basis": SPAN_BASIS,
                     "friction_basis": "lexical_candidate",
                     "n_sessions": len(data["sessions"])},
            "projects": rows, "scatter": {"points": points, "note": SCATTER_NOTE}}
    if (params or {}).get("group") == "folder":
        folders: dict[tuple, list[dict]] = defaultdict(list)
        for s in data["sessions"].values():
            folders[(s["cwd"], s["project_id"])].append(s)
        body["folders"] = sorted(
            ({"cwd": cwd, "belongs_to": pid, "sessions": len(g), "hours": hours_of(g)}
             for (cwd, pid), g in folders.items()),
            key=lambda f: (-f["sessions"], f["cwd"] or ""))
    else:
        body["folders"] = []
    return body


# ------------------------------------------------------------------ detail

def _metric_values(rows):
    days = Counter(_day(s["started_at"]) for s in rows if s["started_at"] is not None)
    return {
        "avg_session_minutes": [s["active_ms"] / 60_000 for s in rows
                                if s.get("active_ms") is not None],
        "messages_per_session": [s["msgs"] for s in rows],
        "autonomy": (sum(s["calls"] for s in rows), sum(s["calls"] + s["msgs"] for s in rows)),
        "verify_rate": (sum(s["verify"] for s in rows), len(rows)),
        "friction_rate": (sum(s["corr"] for s in rows), sum(s["msgs"] for s in rows)),
        "daily_sessions": list(days.values()),
    }


def compare(a_rows, b_rows, against) -> dict:
    va, vb = _metric_values(a_rows), _metric_values(b_rows)
    enough = len(a_rows) >= COMPARE_MIN_N and len(b_rows) >= COMPARE_MIN_N
    metrics = []
    for key, label, kind in METRICS:
        if kind == "prop":
            (ka, na), (kb, nb) = va[key], vb[key]
            a = ka / na if na else None
            b = kb / nb if nb else None
            n = [na, nb]
            stats = newcombe(ka, na, kb, nb) if enough and na and nb else None
        else:
            xa, xb = va[key], vb[key]
            a = sum(xa) / len(xa) if xa else None
            b = sum(xb) / len(xb) if xb else None
            n = [len(xa), len(xb)]
            stats = welch(xa, xb) if enough and xa and xb else None
        row = {"key": key, "label": label, "a": _round(a), "b": _round(b), "n": n,
               "delta": None, "lo": None, "hi": None, "flat": None}
        if stats is None:
            row["note"] = "无可比"
        else:
            delta, lo, hi = stats
            row.update(delta=_round(delta), lo=_round(lo), hi=_round(hi), flat=lo <= 0 <= hi)
        metrics.append(row)
    return {"against": against, "n_a": len(a_rows), "n_b": len(b_rows), "metrics": metrics}


def workflows(rows, limit=5) -> list[dict]:
    support: dict[tuple, set] = defaultdict(set)
    steps_of: dict[tuple, list[dict]] = {}
    eligible = 0
    for s in rows:
        seq: list[dict] = []
        for step in s["heads"]:
            if not seq or seq[-1]["key"] != step["key"]:
                seq.append(step)
        if len(seq) < min(WORKFLOW_LENGTHS):
            continue
        eligible += 1
        for n in WORKFLOW_LENGTHS:
            for i in range(len(seq) - n + 1):
                gram = tuple(x["key"] for x in seq[i:i + n])
                support[gram].add(s["session_uid"])
                steps_of.setdefault(gram, [{"name": x["name"], "head": x["head"]}
                                           for x in seq[i:i + n]])
    ranked = sorted(((g, u) for g, u in support.items() if len(u) >= WORKFLOW_MIN_SUPPORT),
                    key=lambda gu: (-len(gu[1]), -len(gu[0]), gu[0]))
    picked: list[tuple] = []
    for gram, uids in ranked:
        # A shorter chain fully inside an already chosen one with the same support adds nothing.
        if any(len(uids) == len(pu) and _contains(pg, gram) for pg, pu in picked):
            continue
        picked.append((gram, uids))
        if len(picked) >= limit:
            break
    return [{"steps": steps_of[g], "support_sessions": len(u), "eligible_sessions": eligible,
             "support_rate": _round(len(u) / eligible) if eligible else None,
             "session_uids": sorted(u)[:20]} for g, u in picked]


def _contains(longer, shorter) -> bool:
    n = len(shorter)
    return len(longer) > n and any(longer[i:i + n] == shorter for i in range(len(longer) - n + 1))


def default_allowed_roots(project, rows) -> list[Path]:
    roots = {s["cwd"] for s in rows if s["cwd"]}
    if project:
        roots.update(json.loads(project.get("paths") or "[]"))
        if project.get("key_type") in ("path", "git_root"):
            roots.add(project["key"])
    home = Path.home()
    roots.update(str(home / rel) for _, _, rel in AGENTS.values())
    return [Path(r) for r in roots if r]


def _inside(path: Path, roots) -> bool:
    for root in roots:
        try:
            path.relative_to(Path(os.path.realpath(root)))
            return True
        except ValueError:
            continue
    return False


def rule_files(items, roots) -> tuple[list[dict], int]:
    out, rejected, seen = [], 0, set()
    for item in items:
        if item.get("type") != "rule" or not item.get("config_path"):
            continue
        path = Path(os.path.realpath(item["config_path"]))
        if path in seen:
            continue
        seen.add(path)
        if not _inside(path, roots):
            rejected += 1
            continue
        try:
            st = path.stat()
            with path.open("rb") as fh:
                lines = sum(1 for _ in fh)
        except OSError:
            continue
        out.append({"path": str(path), "bytes": st.st_size, "lines": lines,
                    "mtime": int(st.st_mtime * 1000), "agent": item.get("agent")})
    return out, rejected


def coverage(items, pid, agents) -> list[dict]:
    out = []
    for kind in COVERAGE_TYPES:
        cap = CAPABILITY_OF[kind]
        agents_read = sorted(a for a in agents if capabilities(a, None).get(cap))
        if kind == "subagent" or items is None:
            out.append({"type": kind, "configured": None, "detail": "未扫描",
                        "agents_read": agents_read})
            continue
        mine = [i for i in items if i.get("type") == kind]
        local = sum(1 for i in mine if i.get("scope") == "project" and i.get("project_id") == pid)
        glob = sum(1 for i in mine if i.get("scope") != "project")
        out.append({"type": kind, "configured": bool(local or glob),
                    "detail": f"项目 {local} · 全局 {glob}", "project": local, "global": glob,
                    "agents_read": agents_read})
    return out


def evidence_preview(rows, calls, limit=5) -> list[dict]:
    """Same shape as ``ai.pack._project_evidence`` fallback: corrections, then failing calls."""
    humans = sorted((m for s in rows for m in s["human_events"] if corrections(m["raw"])),
                    key=lambda m: (m["ts"] or 0), reverse=True)[:3]
    out = [{"event_uid": m["event_uid"], "session_uid": m["session_uid"], "kind": "human",
            "text": redact(m["text"])[:300]} for m in humans]
    uids = {s["session_uid"] for s in rows}
    failed = sorted((c for c in calls if c["root_uid"] in uids and c["status"] in FAILED),
                    key=lambda c: (c["started_at"] or 0), reverse=True)[:2]
    out += [{"event_uid": None, "call_uid": c["call_uid"], "session_uid": c["session_uid"],
             "kind": "error",
             "text": redact(" ".join(x for x in (c["name_raw"], c["command_head"]) if x))}
            for c in failed]
    return out[:limit]


def top_recommendation(appdb, pid) -> dict | None:
    rows = _appdb_rows(
        appdb, "SELECT c.candidate_id, c.title, c.card, r.scope FROM rec_candidate c "
               "JOIN rec_run r ON r.run_id=c.run_id WHERE c.passed=1 "
               "ORDER BY r.created_at DESC, COALESCE(c.rank, 1 << 30), c.priority DESC LIMIT 500")
    for row in rows:
        try:
            scope, card = json.loads(row[3] or "{}"), json.loads(row[2] or "{}")
        except ValueError:
            continue
        ids = set((scope or {}).get("project_ids") or [])
        if isinstance(card, dict):
            ids.update(card.get("project_ids") or [])
            if card.get("project_id"):
                ids.add(card["project_id"])
        if pid in ids:
            return {"candidate_id": row[0], "title": row[1]}
    return None


def build_project(conn, scope, project_id, params, *, inventory_items=None, appdb=None,
                  allowed_roots=None, persona_lookup=None) -> dict | None:
    params = params or {}
    data = load(conn, scope)
    sessions = list(data["sessions"].values())
    rows = [s for s in sessions if s["project_id"] == project_id]
    project = data["projects"].get(project_id)
    if project is None and not rows:
        return None
    row = project_row(project_id, rows, project, persona_lookup)
    against = params.get("compare") or "overall"
    other = sessions if against == "overall" else [s for s in sessions
                                                   if s["project_id"] == against]
    roots = allowed_roots if allowed_roots is not None else default_allowed_roots(project, rows)
    files, rejected = rule_files(inventory_items or [], roots)
    agents = sorted({s["agent"] for s in rows})
    return {
        "header": {"project_id": project_id, "name": row["name"], "path": row["path"],
                   "git": row["git"], "identity_quality": row["identity_quality"],
                   "tags": row["tags"], "rule_files": files, "rule_files_rejected": rejected,
                   "sessions": row["sessions"], "hours": row["hours"], "friction": row["friction"],
                   "persona": row["persona"]},
        "vs": compare(rows, other, against),
        "agents": row["agents"],
        "workflows": workflows(rows),
        "coverage": coverage(inventory_items, project_id, agents),
        "evidence_preview": evidence_preview(rows, data["calls"]),
        "top_recommendation": top_recommendation(appdb, project_id),
    }


# ------------------------------------------------------------------ route

def _linked_items(project_ids):
    try:
        from .. import features

        return features.linked_inventory({"project_ids": project_ids}).get("items", [])
    except Exception:  # noqa: BLE001 - inventory unavailable: coverage shows 未扫描
        return None


def register(api, gw) -> None:
    from fastapi import Depends, Query

    from ..services.auth import ApiError
    from ..services.routes_data import mark_empty
    from . import a4a6_common as common

    def scope_of(project_id, agent, since, until):
        if since is not None and until is not None and since >= until:
            raise ApiError(400, "invalid_request", "since 必须早于 until")
        return {"project_ids": project_id or None, "agent_ids": agent or None,
                "from_ts": since, "until_ts": until,
                "excluded_cwd_prefix": str(Path(gw.home) / "agent-cwd")}

    range_dependency = Depends(common.range_scope)

    def lookup():
        return getattr(gw, "persona_lookup", None)

    @api.get("/v1/uiview/projects")
    def projects(project_id: ManyQuery = None, agent: ManyQuery = None, agents: str | None = None,
                 since: int | None = None, until: int | None = None, group: str = "project",
                 topic: str | None = None, outcome: str | None = None,
                 fric: str | None = None, hour: int | None = Query(None, ge=0, le=23),
                 tz: str | None = None, wait_ms: int = Query(0, ge=0, le=3000),
                 ranges: dict = range_dependency):
        if group not in ("project", "folder"):
            raise ApiError(400, "invalid_request", "group 只接受 project|folder")
        ids, early = common.facet_sessions(
            gw, {"topic": topic, "outcome": outcome, "fric": fric, "hour": hour}, tz, wait_ms)
        if early is not None:
            return early
        scope = {**scope_of(project_id, common.agent_list(agent, agents), since, until),
                 **ranges, "session_uids": ids}
        with gw.reads.read(empty=True) as conn:
            body = build_projects(conn, scope, {"group": group}, persona_lookup=lookup())
            return mark_empty(body) if gw.reads.is_empty(conn) else body

    @api.get("/v1/uiview/projects/{project_id}")
    def project(project_id: str, agent: ManyQuery = None, since: int | None = None,
                until: int | None = None, compare: str = "overall",
                ranges: dict = range_dependency):
        scope = {**scope_of(None, agent, since, until), **ranges}
        items = _linked_items([project_id])
        with gw.reads.read(empty=True) as conn:  # nothing imported yet: 404, not 503
            body = build_project(conn, scope, project_id, {"compare": compare},
                                 inventory_items=items, appdb=gw.appdb, persona_lookup=lookup())
        if body is None:
            raise ApiError(404, "not_found", f"项目 {project_id} 不存在")
        return body


__all__ = ["build_project", "build_projects", "register", "union_ms", "workflows"]
