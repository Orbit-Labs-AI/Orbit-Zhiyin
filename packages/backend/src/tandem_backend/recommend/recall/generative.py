"""Route ⑧: generation placeholders handed to the AI module (recommend never imports ai).

Emitted when an active problem has no ready-made remedy, or when a KB rule
needs a slot only the user's own sessions can fill (e.g. the instruction text).
"""

from .. import mechanism
from .kb_route import evidence_of, from_rule, missing_slots, target_agents

TASKS = {"rule": "generate.rule", "hook": "generate.hook", "skill": "generate.skill"}
LABELS = {"rule": "规则", "hook": "Hook", "skill": "Skill"}
NO_AI = "AI 生成未开启：使用模板默认值，未个性化"


def _target_kind(problem: dict, memory: dict) -> str:
    for kind in mechanism.choose(problem, memory)["kinds"]:
        if kind in TASKS:
            return kind
    return "rule"


def _matches(rule, problem: dict, memory: dict) -> bool:
    """KB rules of kind 'generate' are templates for this route (kb_route skips them)."""
    prefix = rule.problem.key_prefix
    return (problem["type"] in rule.problem.types and rule.id not in set(memory.get("muted_kb_rules") or ())
            and (not prefix or problem["key"].startswith(prefix)))


def _placeholder(problem: dict, kind: str, inputs: dict, memory: dict, rule=None) -> dict:
    key = f"generate:{kind}:{problem['key']}"
    slots = {name: value for name, value in problem["vars"].items() if isinstance(value, (str, int, float))}
    if rule is not None:
        cand = from_rule(rule, problem, inputs, rec_key=key, match_basis="generated", origin="generated")
        template = rule.remedy.template or "blank@1"
    else:
        cand = {
            "rec_key": key, "problem": problem, "kind": "generate", "dim": "skill" if kind == "skill" else kind,
            "level": 2, "audience_min": 1, "title": f"按你的会话生成一个{LABELS[kind]}",
            "summary": f"知识库里没有现成方案，基于 {problem['sessions']} 个会话的证据定制生成。",
            "match_basis": "generated", "routes": {}, "fusion": 0., "evidence": evidence_of(problem),
            "source": {"origin": "generated", "item_id": None, "url": None, "license": None, "version": None,
                       "verified": False},
            "target": {"agents": target_agents({}, inputs), "scope": "user", "project_id": None, "path_hint": None},
            "track": {"triggered": problem["type"], "mechanical": "生成产物调用次数", "guardrail": "会话摩擦率",
                      "follow_days": 7, "extend_days": 28},
            "trial": {"steps": ["交给生成工坊生成草稿", "审阅并安装", "7 天后看问题是否减少"], "metric": problem["type"],
                      "follow_days": 7},
            "alternatives": [], "kb": None, "item": None, "agents": {}, "prior": {"alpha": 1., "beta": 1.},
            "cost": {"setup_minutes": 10., "context_tokens": 300, "reversible": True},
            "risk": {"level": "medium", "flags": ["generated_content"]}, "requirements": {"tools": [], "software": []},
            "gates_hint": {"scenes": None, "language": None}, "unit_minutes": None, "tags": [problem["type"], kind],
            "file": None,
            "explain_hints": {"reason_template": problem["reason"], "mechanism": "没有现成方案时按证据生成。",
                              "trial": "生成后先预览再安装。", "limitation": "生成内容需要人工审阅。",
                              "vars": dict(problem["vars"])},
        }
        template = "blank@1"
    cand["kind"], cand["level"], cand["match_basis"] = "generate", 2, "generated"
    cand["generate"] = {"task_id": TASKS[kind], "template_id": template, "slots": slots,
                        "evidence_ids": list(problem["evidence"]["event_ids"])}
    if not (memory.get("settings") or {}).get("ai_generate"):
        cand["explain_hints"]["limitation"] = NO_AI
    return cand


def recall(problems: list[dict], rules, inputs: dict, memory: dict, covered: dict[str, dict]) -> tuple[list, dict]:
    """``covered`` maps problem_id -> any non-generic candidate already produced for it."""
    rows, payload = [], {}
    by_problem: dict[str, list[dict]] = {}
    for cand in covered.values():
        if cand.get("problem"):
            by_problem.setdefault(cand["problem"]["problem_id"], []).append(cand)
    for problem in problems:
        if problem["status"] != "active":
            continue
        if not any(kind in TASKS for kind in mechanism.choose(problem, memory)["kinds"]) and \
                problem["type"] in mechanism.REMEDY_PRIORITY:
            continue  # subtraction-only problems: nothing to generate
        own = by_problem.get(problem["problem_id"], [])
        slotted = [rule for cand in own if cand.get("kb") and cand["kb"]["remedy"]["slots"]
                   for rule in rules if rule.id == cand["kb"]["id"] and missing_slots(rule, problem)]
        generators = [rule for rule in rules if rule.remedy.kind == "generate" and _matches(rule, problem, memory)]
        if own and not slotted and not generators:
            continue
        rule = slotted[0] if slotted else generators[0] if generators else None
        kind = (rule.remedy.kind if rule is not None and rule.remedy.kind in TASKS
                else rule.remedy.dim if rule is not None and rule.remedy.dim in TASKS else _target_kind(problem, memory))
        cand = _placeholder(problem, kind, inputs, memory, rule)
        payload[cand["rec_key"]] = cand
        rows.append((cand["rec_key"], round(.5 + .5 * problem["wilson_lo"], 6)))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows, payload
