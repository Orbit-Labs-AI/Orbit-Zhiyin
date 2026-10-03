"""Route ①: knowledge-base rules matched to problems, ordered by the RC-06 table.

Also hosts the RawCand builders shared by the other new routes, so every
candidate has the same shape whatever route produced it.
"""

import json
import os
import re

from .. import mechanism
from ..kb import Rule
from ..narrate import audience_default
from ..ranking.hygiene import GENERIC

# Where a remedy lands, per the Agent the user runs most (user scope; project scope swaps
# the home prefix for the project's directory name). Only agents with a known config layout are
# listed: any other top agent (hermes, kimi, opencode, dsh, pi, …) gets path_hint=None and the card
# is a manual / needs_context action — never a Claude path.
PATHS = {"claude_code": {"permission_rule": "~/.claude/settings.json", "hook": "~/.claude/settings.json",
                         "skill": "~/.claude/skills/{id}/SKILL.md", "subagent": "~/.claude/agents/{id}.md",
                         "rule": "AGENTS.md", "prompt": "AGENTS.md"},
         "codex": {"permission_rule": "~/.codex/config.toml", "hook": "~/.codex/config.toml",
                   "skill": "~/.codex/skills/{id}/SKILL.md", "rule": "AGENTS.md", "prompt": "AGENTS.md"}}


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


def top_agent(inputs: dict) -> str | None:
    used = sorted(((a, n) for a, n in (inputs.get("agents") or {}).items() if n), key=lambda kv: (-kv[1], kv[0]))
    return used[0][0] if used else None


def target_agents(support: dict, inputs: dict) -> list[str]:
    """Agents the user runs that the remedy can reach; the support matrix only without usage."""
    used = sorted(((a, n) for a, n in (inputs.get("agents") or {}).items() if n), key=lambda kv: (-kv[1], kv[0]))
    if used:
        return [agent for agent, _ in used if support.get(agent, support.get("*", "unknown")) != "unsupported"]
    return sorted(agent for agent, value in support.items() if value != "unsupported")


def project_name(project_id: str | None, inputs: dict) -> str | None:
    """Directory name of a project (``inputs.projects``); never the opaque project id."""
    info = (inputs.get("projects") or {}).get(project_id) or {}
    root = info.get("root")
    return (os.path.basename(str(root).rstrip("/")) if root else None) or info.get("name")


AGENT_HOME = {"claude_code": "~/.claude/", "codex": "~/.codex/"}


def agent_owns_path(path: str, agent: str | None) -> bool:
    """False when ``path`` lives in another agent's home directory than ``agent``'s."""
    owner = next((a for a, home in AGENT_HOME.items() if path.startswith(home)), None)
    return owner is None or owner == agent


def path_hint(kind: str, rule_id: str, inputs: dict, project: str | None) -> str | None:
    """Landing path for the top Agent; project scope → ``<project name>/...``; None for other agents."""
    path = PATHS.get(top_agent(inputs) or "", {}).get(kind)
    if not path:
        return None
    path = path.format(id=rule_id)
    if project is None:
        return path
    name = project_name(project, inputs)
    local = path[2:] if path.startswith("~/") else path
    return f"{name}/{local}" if name else local


def _toml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def allow_file(heads: list[str], agent: str | None) -> list[list[str]]:
    """Read-only allowlist snippet for the measured command heads ('+' = added line)."""
    if agent == "codex":
        lines = [["# ~/.codex/config.toml", " "]]
        for head in heads:
            lines += [["[[permissions.allow]]", "+"], [f"command = {_toml(head)}", "+"]]
        return lines
    body = [[f"      {_toml(f'Bash({head}:*)')},", "+"] for head in heads]
    return [["{", " "], ['  "permissions": {', " "], ['    "allow": [', " "], *body, ["    ]", " "], ["  }", " "],
            ["}", " "]]


def _title(rule: Rule, values: dict) -> str:
    """Filled title; a slot without a value drops the part after the colon."""
    title = fill(rule.title, values)
    if "{" in title:
        title = re.split(r"[：:]", rule.title)[0].strip()
    return title


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
    # Unfilled slots read as a generic phrase (never "…" or a raw {slot}); the generative route
    # asks AI to fill them.
    shown = {**values, **{name: GENERIC.get(name, "相关项") for name in rule.remedy.slots if name not in values}}
    project = project_of(problem)
    scope = "project" if rule.remedy.scope == "project" or project else "user"
    path = rule.remedy.path.format(id=rule.id) if rule.remedy.path else path_hint(
        rule.remedy.kind, rule.id, inputs, project if scope == "project" else None)
    if path and not agent_owns_path(path, top_agent(inputs)):
        path = None  # e.g. a fixed ~/.claude/... path while the user runs another agent
    file = [[fill(line, shown), mark] for line, mark in rule.file]
    if rule.remedy.kind == "permission_rule" and values.get("head_list"):
        file = allow_file([str(h) for h in values["head_list"]], top_agent(inputs))
    audience = (rule.audience_min if "audience_min" in rule.model_fields_set
                else audience_default(rule.remedy.kind, rule.remedy.level))
    return {
        "rec_key": rec_key, "problem": problem, "kind": rule.remedy.kind, "dim": rule.remedy.dim,
        "level": rule.remedy.level, "audience_min": audience,
        "title": _title(rule, values), "summary": fill(rule.summary, shown), "match_basis": match_basis,
        "routes": {}, "fusion": 0., "evidence": evidence_of(problem),
        "source": {"origin": origin, "item_id": rule.id, "url": None, "license": None,
                   "version": str(rule.version), "verified": True, "catalog_ref": rule.catalog_ref},
        "target": {"agents": target_agents(rule.remedy.agents, inputs), "scope": scope, "project_id": project,
                   "path_hint": path},
        "track": {**rule.track.model_dump(), "extend_days": 28},
        "trial": {"steps": [fill(step, shown) for step in rule.steps],
                  "commands": [fill(c, shown) if c else None for c in rule.commands], "metric": rule.track.triggered,
                  "follow_days": rule.track.follow_days},
        "alternatives": [f"kb:{ref}" for ref in rule.remedy.alternatives], "generate": None,
        "kb": rule.model_dump(mode="json"), "item": None, "agents": dict(rule.remedy.agents),
        "prior": rule.benefit.prior.model_dump(), "cost": rule.cost.model_dump(), "risk": rule.risk.model_dump(),
        "requirements": {"tools": [], "software": [values["software"]] if "software" in values else []},
        "gates_hint": rule.gates.model_dump(), "unit_minutes": rule.benefit.unit_minutes,
        "unit_minutes_source": rule.benefit.unit_minutes_source, "tags": list(rule.tags),
        "file": file or None,
        "explain_hints": {**rule.explain.model_dump(), "vars": values},
        "unfilled_slots": [name for name in rule.remedy.slots if name not in values],
    }


def prefix_ok(rule: Rule, problem: dict) -> bool:
    """Keyed rules need a matching key and their required slots known (e.g. env-quirks on a
    problem without a software to name would title itself「写明 … 的环境约定」)."""
    prefix = rule.problem.key_prefix
    if prefix and not problem["key"].startswith(prefix):
        return False
    return not (prefix and missing_slots(rule, problem))


def missing_slots(rule: Rule, problem: dict | None) -> list[str]:
    values = (problem or {}).get("vars") or {}
    return [name for name, slot in rule.remedy.slots.items()
            if slot.required and slot.default is None and not values.get(name)]


def recall(problems: list[dict], rules: list[Rule], memory: dict, inputs: dict | None = None,
           inventory=None) -> tuple[list[tuple[str, float]], dict[str, dict]]:
    """Match problem-bound rules; removal, generate and predicate rules belong to their own routes."""
    inputs = inputs or {}
    muted = set(memory.get("muted_kb_rules") or ())
    rows, payload = [], {}
    for problem in problems:
        if problem["status"] not in ("active", "below_threshold"):
            continue
        choice = mechanism.choose(problem, memory, inventory, rules)
        for rule in rules:
            if (rule.id in muted or rule.predicate or rule.remedy.kind in ("removal", "generate")
                    or problem["type"] not in rule.problem.types):
                continue
            prefix = rule.problem.key_prefix
            if not prefix_ok(rule, problem):
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
