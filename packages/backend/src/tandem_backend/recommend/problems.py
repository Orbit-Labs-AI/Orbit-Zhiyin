"""Problem layer: lift per-session signals and SQL facts into cross-session problems.

A problem is promoted to ``active`` only when it recurs: k sessions out of n
with a Wilson lower bound clear of noise. Everything stays deterministic and
cheap (no model calls), so the gateway can rebuild it on every engine run.
"""

import hashlib
import math
from datetime import datetime

RULE_TO_PROBLEM = {
    "correction_density": "wrong_approach",
    "repeated_requirements": "repeated_instruction",
    "identical_retries": "tool_env_failure",
    "tool_failures": "tool_env_failure",
    "validation_failures": "buggy_output",
    "acceptance_evidence_gap": "missing_verification",
    "context_pressure": "context_loss",
}
COMMUNICATION_RULES = {"explanation_revision", "long_response", "unexplained_terms"}
DIMENSIONS = {"missing_verification": "verification", "buggy_output": "verification",
              "wrong_approach": "actionability", "context_loss": "grounding"}
# Problem types lifted from SQL facts by ``_kb_problems`` (see section._kb_facts).
FACT_TYPES = ("review_loop", "parallel_conflict", "readonly_review", "repeated_workflow",
              "late_build_failure", "polling", "deploy_platform_mix")
TYPES = (*dict.fromkeys(RULE_TO_PROBLEM.values()), "permission_friction", "communication_gap",
         "resident_cost", "installed_unused", *FACT_TYPES)
MIN_SESSIONS, MIN_WILSON_LO, MIN_DENOMINATOR = 3, .05, 5
MAX_IDS = 50


def wilson_lo(k: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for k successes out of n."""
    if n <= 0:
        return 0.
    k = min(max(k, 0), n)
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0., (centre - margin) / (1 + z * z / n))


def _ts(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / (1000 if value > 1e11 else 1)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class _Acc:
    __slots__ = ("type", "key", "roots", "k", "n", "weekly", "sessions", "signals", "events", "reasons",
                 "projects", "unit", "vars")

    def __init__(self, type_, key):
        self.type, self.key = type_, key
        self.roots, self.sessions, self.signals, self.events = set(), [], [], []
        self.k = self.n = None
        self.weekly, self.reasons, self.projects, self.unit, self.vars = 0., [], set(), "次", {}

    def add_ids(self, target, values):
        for value in values:
            if value and value not in target and len(target) < MAX_IDS:
                target.append(value)


def build(inputs: dict, memory: dict | None = None) -> list[dict]:
    """Return problems sorted active-first, then by weekly count."""
    memory = memory or {}
    muted = set(memory.get("muted_problem_types") or ())
    sessions = inputs.get("sessions") or {}
    main = int(sessions.get("main") or 0)
    weeks = max(1., float(sessions.get("weeks") or 1))
    accs: dict[tuple[str, str], _Acc] = {}

    def acc(type_, key):
        return accs.setdefault((type_, key), _Acc(type_, key))

    for signal in inputs.get("signals") or ():
        type_ = RULE_TO_PROBLEM.get(signal.get("rule_id"))
        if not type_:
            continue
        scope = signal.get("scope") or {}
        a = acc(type_, f"{type_}:{scope['group']}" if scope.get("group") else type_)
        if scope.get("root_session_uid"):
            a.roots.add(scope["root_session_uid"])
        if scope.get("project_id"):
            a.projects.add(scope["project_id"])
        metrics = signal.get("metrics") or []
        value = metrics[0].get("value") if metrics else None
        a.weekly += float(value) if isinstance(value, (int, float)) and value > 0 else 1.
        if metrics and metrics[0].get("unit"):
            a.unit = metrics[0]["unit"]
        evidence = signal.get("evidence") or []
        a.add_ids(a.sessions, [scope.get("root_session_uid"), *(e.get("session_uid") for e in evidence)])
        a.add_ids(a.events, [e.get("id") for e in evidence])
        a.add_ids(a.signals, [signal.get("signal_id")])
        if signal.get("reason"):
            a.reasons.append(signal["reason"])
    assessed: dict[str, set] = {}
    for assessment in inputs.get("assessments") or ():
        type_ = RULE_TO_PROBLEM.get(assessment.get("rule_id"))
        root = (assessment.get("scope") or {}).get("root_session_uid")
        if type_ and root:
            assessed.setdefault(type_, set()).add(root)
    for a in accs.values():
        a.k = len(a.roots) or len(a.signals)
        a.n = max(main, len(assessed.get(a.type, ())), a.k)

    facts = inputs.get("facts") or {}
    prompts = facts.get("readonly_prompts") or []
    if prompts:
        a = acc("permission_friction", "would_prompt:readonly_shell")
        ranked = sorted(prompts, key=lambda row: (-int(row.get("count") or 0), str(row.get("command_head"))))
        for row in ranked:
            a.add_ids(a.sessions, row.get("session_uids") or ())
        a.k = int(facts.get("readonly_prompt_sessions") or max((row.get("sessions") or 0) for row in prompts))
        a.n = max(main, a.k)
        a.weekly = sum(int(row.get("count") or 0) for row in prompts)
        a.unit = "次审批"
        heads = [str(row.get("command_head")) for row in ranked[:5]]
        a.vars = {"heads": "、".join(heads), "head_list": heads, "n_heads": len(prompts)}
        a.reasons.append(f"{a.k} 个会话里出现只读命令审批（{a.vars['heads']}）")
    by_software: dict[str, list[dict]] = {}
    for row in facts.get("failures_by_software") or ():
        if int(row.get("sessions") or 0) >= 2 and row.get("software"):
            by_software.setdefault(str(row["software"]), []).append(row)
    for software, rows in sorted(by_software.items()):
        a = acc("tool_env_failure", f"tool_env_failure:{software}")
        uids = {uid for row in rows for uid in row.get("session_uids") or ()}
        a.add_ids(a.sessions, sorted(uids))
        a.k = max(a.k or 0, len(uids) or max(int(row.get("sessions") or 0) for row in rows))
        a.n = max(main, a.k, a.n or 0)
        a.weekly += sum(int(row.get("count") or 0) for row in rows)
        a.vars = {**a.vars, "software": software, "error_classes": sorted({str(r.get("error_class")) for r in rows})}
        a.reasons.append(f"{software} 在 {a.k} 个会话里失败")

    _kb_problems(acc, facts, main)

    inventory = inputs.get("inventory")
    if inventory is not None:
        usage = facts.get("usage") or {}
        first, last = _ts(sessions.get("first_ts")), _ts(sessions.get("last_ts"))
        window_days = (last - first) / 86400 if first is not None and last is not None else 0.
        for item in inventory:
            inv_id, name, kind = item.get("inv_id"), item.get("name") or item.get("inv_id"), item.get("type")
            lines, tokens = int(item.get("lines") or 0), int(item.get("resident_tokens") or 0)
            base = {"inv_id": inv_id, "name": name, "inv_type": kind, "lines": lines, "tokens": tokens,
                    "config_path": item.get("config_path")}
            hits = []
            if kind == "rule" and lines > 200:
                hits.append(("resident_cost", f"resident_cost:rules_file:{name}", f"{name} 有 {lines} 行，每个会话都会加载"))
            elif tokens >= 2000:
                hits.append(("resident_cost", f"resident_cost:{inv_id}", f"{name} 每个会话常驻约 {tokens} tokens"))
            bucket = usage.get("skill" if kind == "skill" else "mcp", {}) if kind in ("skill", "mcp") else None
            if (bucket is not None and item.get("enabled", True) and main >= 10 and window_days >= 14
                    and int((bucket.get(name) or {}).get("calls") or 0) == 0):
                hits.append(("installed_unused", f"installed_unused:{inv_id}",
                             f"{name} 在 {main} 个会话、{int(window_days)} 天里从未被调用"))
            for type_, key, reason in hits:
                a = acc(type_, key)
                a.k = a.n = main
                a.weekly = main / weeks
                a.unit = "会话"
                a.vars = {**base, "days": int(window_days)}
                a.reasons.append(reason)
    comm = [card for card in inputs.get("legacy_cards") or () if card.get("rule_id") in COMMUNICATION_RULES]
    if comm:
        a = acc("communication_gap", "communication_gap")
        roots = {card.get("root_session_uid") or (card.get("scope") or {}).get("root_session_uid") for card in comm}
        roots.discard(None)
        a.add_ids(a.sessions, sorted(roots))
        a.k = len(roots) or len(comm)
        a.n = max(main, a.k)
        a.weekly = len(comm)
        a.reasons.append(f"{a.k} 个会话里出现改写或解释请求")

    profile = inputs.get("profile") or {}
    languages = profile.get("languages") or []
    scope_hash = str(inputs.get("scope_hash") or "")
    output = []
    for (type_, key), a in sorted(accs.items()):
        if type_ in muted:
            continue
        k, n = int(a.k or 0), int(a.n or 0)
        lo = wilson_lo(k, n)
        status = ("insufficient" if n < MIN_DENOMINATOR
                  else "active" if k >= MIN_SESSIONS and lo >= MIN_WILSON_LO else "below_threshold")
        weekly = round(a.weekly / weeks, 2)
        output.append({
            "problem_id": hashlib.sha256(f"{scope_hash}|{type_}|{key}".encode()).hexdigest()[:16],
            "type": type_, "key": key, "dimension": DIMENSIONS.get(type_), "sessions": k, "denominator": n,
            "wilson_lo": round(lo, 4), "weekly_count": weekly, "unit": a.unit, "status": status,
            "evidence": {"session_uids": a.sessions, "signal_ids": a.signals, "event_ids": a.events},
            "reason": a.reasons[0] if a.reasons else f"{k}/{n} 个会话出现 {type_}",
            "scene": None, "language": languages[0] if type_ == "communication_gap" and languages else None,
            "project_ids": sorted(a.projects),
            "vars": {"k": k, "n": n, "weekly": round(weekly, 1), **a.vars},
        })
    order = {"active": 0, "below_threshold": 1, "insufficient": 2}
    output.sort(key=lambda p: (order[p["status"]], -p["weekly_count"], p["key"]))
    return output


def _median(values) -> int:
    ordered = sorted(int(v) for v in values)
    return ordered[len(ordered) // 2] if ordered else 0


def _top(values) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return max(sorted(counts), key=lambda v: counts[v]) if counts else None


def _kb_problems(acc, facts: dict, main: int) -> None:
    """Lift the per-session KB coverage facts into problems (k sessions out of ``main``)."""

    def lift(type_, key, uids, count, unit, vars_, reason, projects=()):
        uids = sorted({uid for uid in uids if uid})
        if not uids:
            return
        a = acc(type_, key)
        a.add_ids(a.sessions, uids)
        a.k = len(uids)
        a.n = max(main, a.k)
        a.weekly = float(count)
        a.unit = unit
        a.projects.update(p for p in projects if p)
        a.vars = {**a.vars, **vars_}
        a.reasons.append(reason)

    rows = facts.get("review_loops") or []
    if rows:
        rounds = [int(r.get("rounds") or 0) for r in rows]
        lift("review_loop", "review_loop", [r.get("session_uid") for r in rows], sum(rounds), "轮 review",
             {"rounds_median": _median(rounds), "rounds_max": max(rounds)},
             f"{len(rows)} 个会话里 review 和修改来回了 {_median(rounds)} 轮以上")
    rows = facts.get("parallel_conflicts") or []
    if rows:
        files = sorted({f for r in rows for f in r.get("files") or ()})
        uids = [u for r in rows for u in (r.get("a"), r.get("b"))]
        lift("parallel_conflict", "parallel_conflict", uids, len(rows), "对会话",
             {"pairs": len(rows), "files_examples": "、".join(files[:3])},
             f"{len(rows)} 对同时进行的会话改到了同一批文件",
             projects=[r.get("project_id") for r in rows])
    rows = facts.get("readonly_reviews") or []
    if rows:
        lift("readonly_review", "readonly_review", [r.get("session_uid") for r in rows], len(rows), "会话",
             {"reads_median": _median(r.get("reads") or 0 for r in rows),
              "minutes_median": _median(r.get("minutes") or 0 for r in rows)},
             f"{len(rows)} 个会话只读不改，平均读了 {_median(r.get('reads') or 0 for r in rows)} 次")
    for row in facts.get("repeated_workflows") or ():
        sequence = [str(step) for step in row.get("sequence") or ()]
        if not sequence:
            continue
        text = " → ".join(sequence)
        lift("repeated_workflow", f"repeated_workflow:{text}", row.get("session_uids") or (),
             int(row.get("sessions") or 0), "次流程",
             {"sequence": text, "steps_list": sequence, "n_steps": len(sequence),
              "sessions": int(row.get("sessions") or 0)},
             f"{row.get('sessions')} 个会话重复同一串步骤：{text}")
    rows = facts.get("late_build_failures") or []
    if rows:
        command = _top(r.get("build_command") for r in rows) or "build"
        lift("late_build_failure", "late_build_failure", [r.get("session_uid") for r in rows], len(rows),
             "次构建失败", {"build_command": command, "edits_median": _median(r.get("edits") or 0 for r in rows)},
             f"{len(rows)} 个会话连续改了多处才跑 {command}，结果构建失败",
             projects=[r.get("project_id") for r in rows])
    rows = facts.get("polling") or []
    if rows:
        checks = [int(r.get("checks") or 0) for r in rows]
        lift("polling", "polling", [r.get("session_uid") for r in rows], sum(checks), "次检查",
             {"checks_median": _median(checks), "targets": "、".join(sorted({str(r.get("target")) for r in rows})[:3])},
             f"{len(rows)} 个会话反复手动查看进度")
    for row in facts.get("deploy_platforms") or ():
        platforms = [str(p) for p in row.get("platforms") or ()]
        project = row.get("project") or row.get("project_id") or ""
        lift("deploy_platform_mix", f"deploy_platform_mix:{row.get('project_id')}", row.get("session_uids") or (),
             int(row.get("sessions") or 0), "会话",
             {"platforms": "、".join(platforms), "project": project, "n_platforms": len(platforms)},
             f"{project} 里同时出现 {'、'.join(platforms)} 的部署命令", projects=[row.get("project_id")])
