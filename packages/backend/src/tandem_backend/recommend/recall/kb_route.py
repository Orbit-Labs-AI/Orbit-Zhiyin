"""Route ①: knowledge-base rules matched to problems, ordered by the RC-06 table.

Also hosts the RawCand builders shared by the other new routes, so every
candidate has the same shape whatever route produced it.
"""

from .. import mechanism
from ..kb import Rule

PATHS = {"permission_rule": "~/.claude/settings.json", "hook": "~/.claude/settings.json",
         "skill": "~/.claude/skills/{id}/SKILL.md", "subagent": "~/.claude/agents/{id}.md",
         "rule": "AGENTS.md", "prompt": "AGENTS.md"}


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill(text: str, values: dict) -> str:
    """Format ``{var}`` placeholders, leaving unknown ones visible for the explainer."""
    try:
        return text.format_map(_Keep({k: v for k, v in values.items() if isinstance(v, (str, int, float))}))
    except (ValueError, IndexError):
        return text


def evidence_of(problem: dict | None) -> dict:
    if not problem:
        return {"session_uids": [], "signal_ids": [], "counts": {"sessions": 0, "events": 0}}
    ev = problem["evidence"]
    return {"session_uids": list(ev["session_uids"]), "signal_ids": list(ev["signal_ids"]),
            "counts": {"sessions": problem["sessions"], "events": len(ev["event_ids"])}}


def target_agents(support: dict, inputs: dict) -> list[str]:
    used = sorted((inputs.get("agents") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    agents = [agent for agent, _ in used if support.get(agent, "unknown") != "unsupported"]
    return agents or sorted(agent for agent, value in support.items() if value != "unsupported")


def project_of(problem: dict | None) -> str | None:
    projects = (problem or {}).get("project_ids") or []
    return projects[0] if len(projects) == 1 else None


def rule_key(rule: Rule, problem: dict | None, prefix: str = "kb") -> str:
    """'kb:<id>'; keyed rules on per-instance problems (e.g. per software) get '@<problem key>'."""
    if problem and rule.problem.key_prefix and problem["key"].startswith(problem["type"] + ":"):
        return f"{prefix}:{rule.id}@{problem['key']}"
    return f"{prefix}:{rule.id}"


def from_rule(rule: Rule, problem: dict | None, inputs: dict, *, rec_key: str, match_basis: str,
              origin: str = "kb") -> dict:
    values = {**((problem or {}).get("vars") or {})}
    # Unfilled required slots show as "…" in display text; the generative route asks AI to fill them.
    shown = {**values, **{name: "…" for name in rule.remedy.slots if name not in values}}
    project = project_of(problem)
    scope = "project" if rule.remedy.scope == "project" or project else "user"
    path = PATHS.get(rule.remedy.kind)
    if path and scope == "project" and project and path.startswith("~/.claude"):
        path = path.replace("~/.claude", f"{project}/.claude")
    return {
        "rec_key": rec_key, "problem": problem, "kind": rule.remedy.kind, "dim": rule.remedy.dim,
        "level": rule.remedy.level, "audience_min": rule.audience_min,
        "title": fill(rule.title, shown), "summary": fill(rule.summary, shown), "match_basis": match_basis,
        "routes": {}, "fusion": 0., "evidence": evidence_of(problem),
        "source": {"origin": origin, "item_id": rule.id, "url": None, "license": None,
                   "version": str(rule.version), "verified": True},
        "target": {"agents": target_agents(rule.remedy.agents, inputs), "scope": scope, "project_id": project,
                   "path_hint": path.format(id=rule.id) if path else None},
        "track": {**rule.track.model_dump(), "extend_days": 28},
        "trial": {"steps": [fill(step, shown) for step in rule.steps], "metric": rule.track.triggered,
                  "follow_days": rule.track.follow_days},
        "alternatives": [f"kb:{ref}" for ref in rule.remedy.alternatives], "generate": None,
        "kb": rule.model_dump(mode="json"), "item": None, "agents": dict(rule.remedy.agents),
        "prior": rule.benefit.prior.model_dump(), "cost": rule.cost.model_dump(), "risk": rule.risk.model_dump(),
        "requirements": {"tools": [], "software": [values["software"]] if "software" in values else []},
        "gates_hint": rule.gates.model_dump(), "unit_minutes": rule.benefit.unit_minutes, "tags": list(rule.tags),
        "file": [[fill(line, shown), mark] for line, mark in rule.file] or None,
        "explain_hints": {**rule.explain.model_dump(), "vars": values},
    }


def missing_slots(rule: Rule, problem: dict | None) -> list[str]:
    values = (problem or {}).get("vars") or {}
    return [name for name, slot in rule.remedy.slots.items()
            if slot.required and slot.default is None and not values.get(name)]


def recall(problems: list[dict], rules: list[Rule], memory: dict, inputs: dict | None = None,
           inventory=None) -> tuple[list[tuple[str, float]], dict[str, dict]]:
    """Match problem-bound rules; removal and predicate rules belong to their own routes."""
    inputs = inputs or {}
    muted = set(memory.get("muted_kb_rules") or ())
    rows, payload = [], {}
    for problem in problems:
        if problem["status"] not in ("active", "below_threshold"):
            continue
        choice = mechanism.choose(problem, memory, inventory, rules)
        for rule in rules:
            if (rule.id in muted or rule.predicate or rule.remedy.kind == "removal"
                    or problem["type"] not in rule.problem.types):
                continue
            prefix = rule.problem.key_prefix
            if prefix and not problem["key"].startswith(prefix):
                continue
            raw = (1. if prefix else .8) * mechanism.weight(rule.remedy.kind, choice)
            if problem["status"] != "active":
                raw *= .5
            key = rule_key(rule, problem)
            if key in payload and payload[key]["routes"].get("_raw", 0) >= raw:
                continue
            cand = from_rule(rule, problem, inputs, rec_key=key, match_basis="problem_rule")
            cand["explain_hints"]["mechanism_row"] = choice["row"]
            cand["explain_hints"]["mechanism_note"] = choice["note"]
            cand["routes"]["_raw"] = raw
            payload[key] = cand
    for key, cand in payload.items():
        rows.append((key, cand["routes"].pop("_raw")))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows, payload
