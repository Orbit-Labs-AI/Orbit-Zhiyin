"""Problem layer: lift per-session signals and SQL facts into cross-session problems.

A problem is promoted to ``active`` only when it recurs: k sessions out of n
with a Wilson lower bound clear of noise. Everything stays deterministic and
cheap (no model calls), so the gateway can rebuild it on every engine run.
"""

import hashlib
import math
import re
from datetime import datetime

from orbit_backend.features.linked import UNUSED_WINDOW_DAYS

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
# The Wilson bar relaxes with the population size: ``MIN_WILSON_LO`` holds up to ``REF_N``
# sessions and shrinks by sqrt(REF_N / n) above it (never under ``FLOOR_WILSON_LO``), so a
# heterogeneous heavy user (390 sessions over many projects) is not held to a 5 % share.
# Basis: a design heuristic, not a fitted or FDR-controlled threshold. The √ scaling keeps the
# bar ∝ the Wilson half-width (which shrinks ∝ 1/√n), i.e. "a problem must stand out by the same
# number of standard errors" rather than by a fixed share. Its effect is pinned by the minimum-k
# table in tests/recommend/test_problem_calibration.py (n=60 → k≥7, n=200 → k≥11, n=400 → k≥14).
REF_N, FLOOR_WILSON_LO = 60, .01
# Shortest observation window used to turn counts into weekly rates (one day): shorter windows
# would extrapolate a few minutes of history into a weekly figure.
MIN_WEEKS = 1 / 7
MAX_IDS = 50
MIN_READONLY_PROMPTS = 2
UNIT_ZH = {"count": "次", "ratio": "次", "events": "次", "calls": "次", "sessions": "会话", "minutes": "分钟"}
# Inventory facts (unused / resident) are measurements, not k-of-n recurrences: a fixed
# confidence instead of a Wilson bound whose numerator equals its denominator.
INVENTORY_CONFIDENCE = {"resident_cost": .8, "installed_unused": .5}
# "Unused" means no call over the whole window features.linked uses for the same claim
# (UNUSED_WINDOW_DAYS = 90): with a shorter history zero calls is "insufficient_history" there,
# so the problem layer must not call it unused either. Confidence then grows from .5 at 90 days to
# .9 at 2× the window (product default, not calibrated).
UNUSED_FULL_CONFIDENCE_DAYS = 2 * UNUSED_WINDOW_DAYS
# MCP servers load their tool schemas each session; without a measurement use this estimate.
MCP_RESIDENT_EST = 500
# Generic tool names never stand for a "software" (they wrap every shell / agent call).
GENERIC_TOOLS = {"exec_command", "bash", "shell", "local_shell", "terminal", "commandexecution", "pwsh",
                 "agent", "task", "js", "node_repl", "write_stdin", "spawn_agent", "subagent"}
# SQL facts that stand in for analytics signals on unlabelled logs:
# fact name -> (problem type, key, weekly count field, reason template).
FACT_PROBLEMS = {
    "retry_runs": ("tool_env_failure", "tool_env_failure:retry", "segments",
                   "{k} 个会话里出现失败后原样重试，最长连续 {max_len} 次"),
    "compactions": ("context_loss", "context_loss:compaction", "count",
                    "{k} 个会话发生自动压缩，其中 {m} 个压缩后你还在继续说明"),
    "unverified_edits": ("missing_verification", "missing_verification:unverified", "sessions",
                         "{k} 个会话改了 ≥5 处却没有在最后运行测试或构建"),
    "test_failures": ("buggy_output", "buggy_output:test", "count",
                      "{k} 个会话里同一测试反复失败（{commands}）"),
}

MAX_INSTRUCTION = 24
_REPEATED = re.compile(r"重复(?:要求|说明|提出)[：:]\s*(.+)")


def instruction_of(signal: dict) -> str | None:
    """The repeated requirement, for「写进规则：{instruction}」: the signal's own wording
    (after「重复要求：」) when present, else its group; cut to 24 characters."""
    match = _REPEATED.search(str(signal.get("reason") or ""))
    text = (match.group(1) if match else (signal.get("scope") or {}).get("group")) or ""
    text = text.strip().rstrip("。.")
    return text[:MAX_INSTRUCTION] or None


def wilson_lo(k: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for k successes out of n."""
    if n <= 0:
        return 0.
    k = min(max(k, 0), n)
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0., (centre - margin) / (1 + z * z / n))


def observed_weeks(sessions: dict) -> float:
    """Length of the observed window in weeks: ``sessions.weeks`` when given, else the span between
    ``first_ts`` and ``last_ts``; never below one day (MIN_WEEKS). Without either, 1 week."""
    weeks = sessions.get("weeks")
    if isinstance(weeks, (int, float)) and not isinstance(weeks, bool) and weeks > 0:
        return max(MIN_WEEKS, float(weeks))
    try:
        first = datetime.fromisoformat(str(sessions["first_ts"]).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(sessions["last_ts"]).replace("Z", "+00:00"))
        return max(MIN_WEEKS, (last - first).total_seconds() / (7 * 86400))
    except (KeyError, TypeError, ValueError):
        return 1.


def min_wilson_lo(n: int) -> float:
    """The calibrated Wilson lower-bound bar for a population of ``n`` sessions."""
    if n <= REF_N:
        return MIN_WILSON_LO
    return max(FLOOR_WILSON_LO, MIN_WILSON_LO * math.sqrt(REF_N / n))


def passes(problem: dict) -> bool:
    """Shared evidence bar for problems.build and ranking.gates (one configurable value)."""
    return (int(problem.get("sessions") or 0) >= MIN_SESSIONS
            and float(problem.get("wilson_lo") or 0) >= float(problem.get("threshold", MIN_WILSON_LO)))


def group_label(group) -> str | None:
    """A signal's ``scope.group`` as a key part: a tool dict names its tool; generic tools
    (exec_command, Agent, …) name nothing so they fold into the bare problem type."""
    if isinstance(group, dict):
        group = group.get("tool") or group.get("name") or group.get("software")
    text = str(group).strip() if group else ""
    return None if not text or text.lower() in GENERIC_TOOLS else text


class _Scopes:
    """Reference populations a problem can be measured against (project, task family, software)."""

    def __init__(self, facts: dict):
        days = [d for d in facts.get("session_days") or () if isinstance(d, dict) and d.get("session_uid")]
        given = facts.get("scope_sessions") or {}
        self.project_of = {d["session_uid"]: d.get("project_id") for d in days}
        self.types_of = {d["session_uid"]: list(d.get("task_types") or ()) for d in days}
        self.projects = dict(given.get("projects") or {}) or _count(self.project_of.values())
        self.task_types = dict(given.get("task_types") or {}) or _count(
            t for types in self.types_of.values() for t in types)
        self.software = dict(given.get("software") or {})

    def candidates(self, uids, k: int, software) -> list[tuple[str, int]]:
        out = []
        if software and self.software.get(str(software)):
            out.append(("software", int(self.software[str(software)])))
        uids = [u for u in uids if u]
        if uids and len(uids) >= k:
            projects = {self.project_of.get(u) for u in uids}
            if projects and None not in projects and all(p in self.projects for p in projects):
                out.append(("project", sum(int(self.projects[p]) for p in projects)))
            types = [self.types_of.get(u) for u in uids]
            if all(types):
                family = {t for ts in types for t in ts}
                if all(t in self.task_types for t in family):
                    out.append(("task_family", sum(int(self.task_types[t]) for t in family)))
        return out


def _count(values) -> dict:
    out: dict = {}
    for value in values:
        if value:
            out[value] = out.get(value, 0) + 1
    return out


def _measure(k: int, n: int, uids, software, scopes: _Scopes) -> dict:
    """Pick the narrowest reference population that holds all k sessions and gives the best
    calibrated margin; ``all`` (every main session) is the fallback."""
    best = {"basis": "all", "n": n, "lo": wilson_lo(k, n), "threshold": min_wilson_lo(n)}
    for basis, m in scopes.candidates(uids, k, software):
        m = max(m, k)
        if m >= n or m < MIN_DENOMINATOR:
            continue
        lo, bar = wilson_lo(k, m), min_wilson_lo(m)
        if lo - bar > best["lo"] - best["threshold"]:
            best = {"basis": basis, "n": m, "lo": lo, "threshold": bar}
    return best


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
                 "projects", "unit", "vars", "basis")

    def __init__(self, type_, key):
        self.type, self.key = type_, key
        self.roots, self.sessions, self.signals, self.events = set(), [], [], []
        self.k = self.n = None
        self.weekly, self.reasons, self.projects, self.unit, self.vars = 0., [], set(), "次", {}
        self.basis = None

    def add_ids(self, target, values):
        for value in values:
            if value and value not in target and len(target) < MAX_IDS:
                target.append(value)


def _lift_facts(acc, accs: dict, facts: dict, main: int) -> None:
    """Promote sequence/compaction facts; roots already covered by a signal of the same type
    stay with the signal (analytics first, facts only fill the gaps)."""
    signal_roots: dict[str, set] = {}
    for (type_, _key), a in accs.items():
        if a.signals:
            signal_roots.setdefault(type_, set()).update(a.roots)
    for name, (type_, key, count_field, template) in FACT_PROBLEMS.items():
        fact = facts.get(name) or {}
        uids = list(fact.get("session_uids") or ())
        covered = signal_roots.get(type_, set())
        overlap = sum(uid in covered for uid in uids)
        k = int(fact.get("sessions") or 0) - overlap
        if k <= 0:
            continue
        a = acc(type_, key)
        a.basis = "sql_fact"
        a.add_ids(a.sessions, [uid for uid in uids if uid not in covered])
        a.roots.update(uid for uid in uids if uid not in covered)
        a.k = k
        a.n = max(main, k)
        total = int(fact.get(count_field) or 0)
        a.weekly += max(total - (overlap if count_field == "sessions" else 0), k)
        examples = list(fact.get("examples") or fact.get("commands") or ())[:5]
        extra = {"examples": examples, "max_len": fact.get("max_len"),
                 "m": fact.get("followed_by_user"), "commands": "、".join(examples) or "测试命令",
                 "edits_median": fact.get("edits_median")}
        a.vars = {**a.vars, **{key_: value for key_, value in extra.items() if value is not None}}
        a.reasons.append(template.format(k=k, **{key_: a.vars.get(key_, "") for key_ in
                                                  ("max_len", "m", "commands")}))


def build(inputs: dict, memory: dict | None = None) -> list[dict]:
    """Return problems sorted active-first, then by weekly count."""
    memory = memory or {}
    muted = set(memory.get("muted_problem_types") or ())
    sessions = inputs.get("sessions") or {}
    main = int(sessions.get("main") or 0)
    weeks = observed_weeks(sessions)
    accs: dict[tuple[str, str], _Acc] = {}

    def acc(type_, key):
        return accs.setdefault((type_, key), _Acc(type_, key))

    for signal in inputs.get("signals") or ():
        type_ = RULE_TO_PROBLEM.get(signal.get("rule_id"))
        if not type_:
            continue
        scope = signal.get("scope") or {}
        label = group_label(scope.get("group"))
        a = acc(type_, f"{type_}:{label}" if label else type_)
        if label and type_ == "tool_env_failure":
            a.vars = {**a.vars, "software": label}
        if scope.get("root_session_uid"):
            a.roots.add(scope["root_session_uid"])
        if scope.get("project_id"):
            a.projects.add(scope["project_id"])
        metrics = signal.get("metrics") or []
        value = metrics[0].get("value") if metrics else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            a.weekly += float(value)
        else:  # no metric value: count the evidence events the signal cites, and say so
            a.weekly += len([e for e in signal.get("evidence") or () if e.get("id")])
            a.vars = {**a.vars, "count_basis": "evidence"}
        if metrics and metrics[0].get("unit"):
            a.unit = UNIT_ZH.get(metrics[0]["unit"], metrics[0]["unit"])
        evidence = signal.get("evidence") or []
        a.add_ids(a.sessions, [scope.get("root_session_uid"), *(e.get("session_uid") for e in evidence)])
        a.add_ids(a.events, [e.get("id") for e in evidence])
        a.add_ids(a.signals, [signal.get("signal_id")])
        if signal.get("reason"):
            a.reasons.append(signal["reason"])
        if type_ == "repeated_instruction" and "instruction" not in a.vars and (text := instruction_of(signal)):
            a.vars = {**a.vars, "instruction": text}
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
    every = facts.get("readonly_prompts") or []
    # Allowed prompts only; a head the user ever denied is no allow-list candidate (a4a6-B8).
    denied = facts.get("readonly_denied") or {}
    prompts = [row for row in every if not row.get("denied") and not denied.get(row.get("command_head"))
               and int(row.get("count") or 0) >= MIN_READONLY_PROMPTS]
    if prompts:
        a = acc("permission_friction", "would_prompt:readonly_shell")
        ranked = sorted(prompts, key=lambda row: (-int(row.get("count") or 0), str(row.get("command_head"))))
        for row in ranked:
            a.add_ids(a.sessions, row.get("session_uids") or ())
        widest = max(int(row.get("sessions") or 0) for row in prompts)
        a.k = (int(facts.get("readonly_prompt_sessions") or widest) if len(prompts) == len(every)
               else max(widest, len({u for row in prompts for u in row.get("session_uids") or ()})))
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

    _lift_facts(acc, accs, facts, main)
    _kb_problems(acc, facts, main)

    inventory = inputs.get("inventory")
    if inventory is not None:
        usage = facts.get("usage") or {}
        first, last = _ts(sessions.get("first_ts")), _ts(sessions.get("last_ts"))
        window_days = (last - first) / 86400 if first is not None and last is not None else 0.
        for item in inventory:
            inv_id, name, kind = item.get("inv_id"), item.get("name") or item.get("inv_id"), item.get("type")
            lines, tokens = int(item.get("lines") or 0), int(item.get("resident_tokens") or 0)
            estimated = kind == "mcp" and item.get("resident_tokens") is None
            if estimated:
                tokens = MCP_RESIDENT_EST
            base = {"inv_id": inv_id, "name": name, "inv_type": kind, "lines": lines, "tokens": tokens,
                    "config_path": item.get("config_path"), "tokens_basis": "estimate" if estimated else "measured"}
            for extra in ("agent", "scope", "plugin"):
                if item.get(extra):
                    base[extra] = item[extra]
            hits = []
            if kind == "rule" and lines > 200:
                hits.append(("resident_cost", f"resident_cost:rules_file:{name}", f"{name} 有 {lines} 行，每个会话都会加载"))
            elif not estimated and tokens >= 2000:
                hits.append(("resident_cost", f"resident_cost:{inv_id}", f"{name} 每个会话常驻约 {tokens} tokens"))
            bucket = usage.get("skill" if kind == "skill" else "mcp", {}) if kind in ("skill", "mcp") else None
            if (item.get("usage") or {}).get("attributable") is False:
                bucket = None  # the agent records no skill/MCP attribution: unknown, not unused
            # linked inventory marks agents whose logs never attribute calls (Codex skills) as
            # unknown_usage: no calls there is no evidence of disuse
            if (bucket is not None and item.get("enabled") is not False and main >= 10
                    and window_days >= UNUSED_WINDOW_DAYS
                    and item.get("status") not in ("unknown_usage", "active", "insufficient_history")
                    and int((bucket.get(name) or {}).get("calls") or 0) == 0):
                hits.append(("installed_unused", f"installed_unused:{inv_id}",
                             f"{name} 在 {main} 个会话、{int(window_days)} 天里从未被调用"))
            for type_, key, reason in hits:
                a = acc(type_, key)
                a.k = a.n = main
                a.weekly = main / weeks
                a.unit = "会话"
                a.basis = "inventory"
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
    scopes = _Scopes(facts)
    span_days = 0.
    first_ts, last_ts = _ts(sessions.get("first_ts")), _ts(sessions.get("last_ts"))
    if first_ts is not None and last_ts is not None:
        span_days = (last_ts - first_ts) / 86400
    output = []
    for (type_, key), a in sorted(accs.items()):
        if type_ in muted:
            continue
        k, n = int(a.k or 0), int(a.n or 0)
        if a.basis == "inventory":
            # A measured fact: fixed confidence (unused grows with the observed window), no k/n bound.
            confidence = INVENTORY_CONFIDENCE.get(type_, .5)
            if type_ == "installed_unused":
                ramp = UNUSED_FULL_CONFIDENCE_DAYS - UNUSED_WINDOW_DAYS
                confidence = min(.9, confidence + .4 * min(1., max(0., span_days - UNUSED_WINDOW_DAYS) / ramp))
            scope = {"basis": "inventory", "n": n, "lo": confidence, "threshold": 0.}
            status = "insufficient" if n < MIN_DENOMINATOR else "active"
        else:
            # Signals and SQL facts count sessions independently of ``sessions.main``; a k above
            # the main-session total (subagent or out-of-scope sessions counted in, or no total at
            # all) would make k/n = 1 and promote a spurious active problem. Truncate k to the
            # total, record the mismatch, and hold the problem at "insufficient": its share of
            # sessions is not known.
            mismatch = k > main
            if mismatch:
                a.vars = {**a.vars, "count_mismatch": {"k_reported": k, "main": main}}
                k, n = main, main
            scope = _measure(k, n, a.roots or a.sessions, a.vars.get("software"), scopes)
            status = ("insufficient" if mismatch or n < MIN_DENOMINATOR
                      else "active" if k >= MIN_SESSIONS and scope["lo"] >= scope["threshold"]
                      else "below_threshold")
        lo = scope["lo"]
        weekly = round(a.weekly / weeks, 2)
        output.append({
            "problem_id": hashlib.sha256(f"{scope_hash}|{type_}|{key}".encode()).hexdigest()[:16],
            "type": type_, "key": key, "dimension": DIMENSIONS.get(type_), "sessions": k,
            "denominator": scope["n"], "denominator_all": n, "scope": {"basis": scope["basis"], "n": scope["n"]},
            "wilson_lo": round(lo, 4), "threshold": round(scope["threshold"], 4), "weekly_count": weekly, "unit": a.unit, "status": status,
            "evidence": {"session_uids": a.sessions, "signal_ids": a.signals, "event_ids": a.events},
            "reason": a.reasons[0] if a.reasons else f"{k}/{n} 个会话出现 {type_}",
            "scene": None, "language": languages[0] if type_ == "communication_gap" and languages else None,
            "project_ids": sorted(a.projects),
            "vars": {"k": k, "n": scope["n"], "weekly": round(weekly, 1), **a.vars},
            **({"basis": a.basis} if a.basis else {}),
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
