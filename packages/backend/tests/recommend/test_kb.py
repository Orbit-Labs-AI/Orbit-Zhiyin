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
