"""Problem→remedy knowledge base (RC-01): reviewed Tandem templates, not scraped content.

Each rule says which problem types it addresses, what kind of change it is,
how to try it and what to track. The file is small (tens of rules), so it is
validated as a whole and cached by mtime; a broken file fails loudly.
"""

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["rule", "prompt", "skill", "hook", "permission_rule", "mcp", "plugin", "subagent", "model",
               "workflow", "removal", "builtin", "generate"]
Dim = Literal["rule", "skill", "hook", "mcp", "agent", "model", "flow"]
Support = Literal["native", "manual", "adaptation_required", "unsupported"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProblemMatch(_M):
    types: list[str] = Field(min_length=1)
    key_prefix: str | None = None
    min_sessions: int = Field(default=3, ge=1)
    min_wilson_lo: float = Field(default=.05, ge=0, le=1)


class Slot(_M):
    required: bool = False
    default: str | None = None


class Remedy(_M):
    kind: Kind
    dim: Dim
    agents: dict[str, Support] = Field(default_factory=lambda: {"claude_code": "native", "codex": "manual"})
    level: int = Field(ge=1, le=4)
    scope: Literal["user", "project"] = "user"
    template: str | None = None
    path: str | None = None  # overrides the default target path for this kind
    alternatives: list[str] = Field(default_factory=list)
    pairs_with: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    slots: dict[str, Slot] = Field(default_factory=dict)


class Prior(_M):
    alpha: float = Field(default=1, gt=0)
    beta: float = Field(default=1, gt=0)


class Benefit(_M):
    unit: str
    unit_minutes: float = Field(ge=0)
    # Where unit_minutes comes from (measurement or cited estimate). Without it the minutes only order
    # candidates internally and the card shows「未估算」instead of a minutes figure.
    unit_minutes_source: str | None = None
    # Why there is no source yet (what measurement would supply it); shown instead of minutes.
    unit_minutes_note: str | None = None
    prior: Prior = Prior()


class Cost(_M):
    setup_minutes: float = Field(default=2, ge=0)
    context_tokens: int = Field(default=0, ge=0)
    reversible: bool = True


class Risk(_M):
    level: Literal["low", "medium", "high"] = "low"
    flags: list[str] = Field(default_factory=list)


class Track(_M):
    triggered: str
    mechanical: str
    guardrail: str
    follow_days: int = Field(default=7, ge=1)


class Explain(_M):
    reason_template: str
    mechanism: str
    trial: str
    limitation: str


class Gates(_M):
    scenes: list[str] | None = None
    language: list[str] | None = None


class Rule(_M):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: int = Field(default=1, ge=1)
    title: str
    summary: str
    problem: ProblemMatch
    remedy: Remedy
    benefit: Benefit
    cost: Cost = Cost()
    risk: Risk = Risk()
    track: Track
    explain: Explain
    gates: Gates = Gates()
    audience_min: int = Field(default=0, ge=0, le=2)
    generic: bool = False
    predicate: Literal["verification_gap", "correction_spiral", "mixed_sessions"] | None = None
    tags: list[str] = Field(default_factory=list)
    file: list[tuple[str, str]] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    commands: list[str | None] = Field(default_factory=list)
    catalog_ref: str | None = None


class KnowledgeBase(_M):
    schema_version: Literal["remedies-v1"]
    origin: str
    # How remedy.agents beyond the hand-reviewed claude_code/codex were derived (capability matrix).
    agent_support_basis: str | None = None
    rules: list[Rule] = Field(min_length=1)


DEFAULT_PATH = files("tandem_backend").joinpath("data/recommend/remedies.v1.json")
_cache: dict[str, tuple[int, int, list[Rule], str]] = {}


def parse(raw: bytes) -> tuple[list[Rule], str]:
    kb = KnowledgeBase.model_validate(json.loads(raw.decode("utf-8")))
    ids = [rule.id for rule in kb.rules]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate kb rule id")
    known = set(ids)
    for rule in kb.rules:
        refs = (*rule.remedy.alternatives, *rule.remedy.pairs_with, *rule.remedy.conflicts_with)
        if missing := [ref for ref in refs if ref not in known or ref == rule.id]:
            raise ValueError(f"kb rule {rule.id} references unknown ids {missing}")
        if len(rule.commands) > len(rule.steps):
            raise ValueError(f"kb rule {rule.id}: commands ({len(rule.commands)}) outnumber steps")
        for name, slot in rule.remedy.slots.items():
            if slot.required and slot.default is not None:
                raise ValueError(f"kb rule {rule.id} slot {name}: required slots take no default")
    return list(kb.rules), "kb-v1@" + hashlib.sha256(raw).hexdigest()[:8]


def load(path: str | Path | None = None) -> tuple[list[Rule], str]:
    """Return (rules, version); reloads only when the file's mtime or size changes."""
    target = Path(str(path or DEFAULT_PATH))
    stat = target.stat()
    key = str(target)
    hit = _cache.get(key)
    if hit and hit[:2] == (stat.st_mtime_ns, stat.st_size):
        return hit[2], hit[3]
    rules, version = parse(target.read_bytes())
    _cache[key] = (stat.st_mtime_ns, stat.st_size, rules, version)
    return rules, version


def by_id(rules: list[Rule]) -> dict[str, Rule]:
    return {rule.id: rule for rule in rules}
