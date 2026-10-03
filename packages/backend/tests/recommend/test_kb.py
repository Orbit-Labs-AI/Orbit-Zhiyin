import json

import pytest

from orbit_backend.recommend import kb, mechanism

MVP_TYPES = {"permission_friction", "tool_env_failure", "missing_verification", "communication_gap",
             "repeated_instruction", "resident_cost", "wrong_approach", "installed_unused", "context_loss",
             "buggy_output"}


def test_bundled_kb_validates_and_covers_mvp_problem_types():
    rules, version = kb.load()
    assert version.startswith("kb-v1@") and len(version) == 14
    ids = [rule.id for rule in rules]
    assert len(ids) == len(set(ids)) >= 16
    covered = {type_ for rule in rules for type_ in rule.problem.types}
    assert MVP_TYPES <= covered
    assert sum(rule.generic for rule in rules) >= 3
    for rule in rules:
        # Every mechanism-table kind of a rule is a known RC-06 kind for one of its problem types.
        kind = rule.remedy.dim if rule.remedy.kind == "generate" else rule.remedy.kind
        assert any(kind in mechanism.REMEDY_PRIORITY.get(t, []) or kind == "workflow"
                   for t in rule.problem.types), rule.id
        assert rule.explain.reason_template and rule.track.triggered and rule.steps


def test_load_is_cached_by_mtime(tmp_path):
    raw = kb.DEFAULT_PATH.read_bytes()
    path = tmp_path / "kb.json"
    path.write_bytes(raw)
    first = kb.load(path)
    assert kb.load(path) is not None and kb.load(path)[0] is first[0]
    data = json.loads(raw)
    data["rules"] = data["rules"][:1]
    data["rules"][0]["remedy"]["alternatives"] = []
    path.write_text(json.dumps(data))
    rules, version = kb.load(path)
    assert len(rules) == 1 and version != first[1]


@pytest.mark.parametrize("mutate", [
    lambda d: d["rules"].append(dict(d["rules"][0])),                                # duplicate id
    lambda d: d["rules"][0]["remedy"].update(pairs_with=["no-such-rule"]),           # dangling reference
    lambda d: d["rules"][0].update(surprise=1),                                      # extra field
    lambda d: d["rules"][0]["remedy"].update(slots={"x": {"required": True, "default": "a"}}),
])
def test_invalid_kb_is_rejected(mutate):
    data = json.loads(kb.DEFAULT_PATH.read_bytes())
    mutate(data)
    with pytest.raises(ValueError):
        kb.parse(json.dumps(data).encode())


def test_mechanism_rows_and_hook_escalation():
    rules, _ = kb.load()
    problem = {"type": "missing_verification", "key": "missing_verification", "status": "active"}
    plain = mechanism.choose(problem, {}, None, rules)
    assert plain["kinds"][0] == "rule" and plain["row"] == 0
    memory = {"state": {"kb:verify-checklist": {"status": "installed"}}}
    escalated = mechanism.choose(problem, memory, None, rules)
    assert escalated["kinds"][0] == "hook" and escalated["row"] == 2
    assert mechanism.choose({**problem, "type": "wrong_approach"}, {}, None, rules)["row"] == 11
    assert mechanism.choose({**problem, "type": "permission_friction"}, {})["row"] == 13
    assert mechanism.weight("hook", escalated) == 1 and mechanism.weight("removal", escalated) == .5


# -- per-event minutes and agent support (round-2 audit) ----------------------------------------

def test_every_rule_states_a_minutes_source_or_why_not():
    rules, _ = kb.load()
    for rule in rules:
        b = rule.benefit
        assert bool(b.unit_minutes_source) != bool(b.unit_minutes_note), rule.id
        if b.unit_minutes_note:
            assert "未估算原因：" in b.unit_minutes_note and "未校准" in b.unit_minutes_note, rule.id


def test_unsourced_rule_card_shows_the_reason_not_minutes():
    from orbit_backend.recommend.narrate import _save
    rule = kb.by_id(kb.load()[0])["readonly-allowlist"]
    raw = {"unit_minutes": rule.benefit.unit_minutes, "unit_minutes_source": rule.benefit.unit_minutes_source,
           "unit_minutes_note": rule.benefit.unit_minutes_note, "prior": rule.benefit.prior.model_dump()}
    cand = {"kind": "permission_rule", "problem": {"weekly_count": 10}}
    save = _save(cand, raw, {"sessions": {"weeks": 4}})
    assert save["min_month"] is None and save["label"] == "未估算"
    assert "approval_wait_ms" in save["basis"]


# Independent restatement of the mapping documented in remedies.v1.json ``agent_support_basis``:
# which capability a remedy needs, and how a matrix value turns into a support level.
_NEEDS = {"skill": "skills", "generate": "skills", "hook": "hooks", "subagent": "subagents"}
_BY_ID = {"headless-poll": "headless", "disable-unused": "mcp",
          "split-rules-file": "instructions", "trim-resident": "instructions"}
_COPYABLE = {"skills", "mcp"}  # same file format across agents: the user copies it by hand
_READS_AGENTS_MD = {"opencode", "pi", "hermes", "dsh"}  # upstream source paths in the KB file


def _expected(rule, agent, matrix):
    need = _BY_ID.get(rule.id) or _NEEDS.get(rule.remedy.kind) or (
        "instructions" if rule.remedy.kind in ("rule", "prompt") else None)
    if need is None:
        return None
    if need == "instructions":
        return "manual" if agent in _READS_AGENTS_MD else None
    value = matrix[agent][need]
    if value == "unknown":
        return None
    if value == "unsupported":
        return "unsupported"
    return "manual" if value == "supported" and need in _COPYABLE else "adaptation_required"


def test_remedy_agents_follow_the_capability_matrix():
    from orbit_data.capabilities import MATRIX
    rules, _ = kb.load()
    assert set(MATRIX) == {"claude_code", "codex", "opencode", "pi", "hermes", "dsh", "kimi"}
    for rule in rules:
        assert {"claude_code", "codex"} & set(rule.remedy.agents), rule.id  # hand-reviewed pair kept
        for agent in ("opencode", "pi", "hermes", "dsh", "kimi"):
            assert rule.remedy.agents.get(agent) == _expected(rule, agent, MATRIX), (rule.id, agent)
    by = kb.by_id(rules)
    # spot checks against the matrix by hand: pi hooks are partial, hermes skills supported, kimi unknown
    assert by["retry-breaker"].remedy.agents["pi"] == "adaptation_required"
    assert by["systematic-debugging"].remedy.agents["hermes"] == "manual"
    assert by["disable-unused"].remedy.agents["pi"] == "adaptation_required"
    assert "kimi" not in by["verify-checklist"].remedy.agents
    assert set(by["readonly-allowlist"].remedy.agents) == {"claude_code", "codex"}  # no matrix basis
