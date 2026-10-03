"""Agent support matrix (compat.py), match-row provenance fields and rule admission (admission.py)."""

import sqlite3

import pytest

from orbit_catalog import admission, index
from orbit_catalog.compat import install_targets, resource_format, support_matrix, supported_agents
from orbit_catalog.contracts import Feature, MatchRequest, Record, Resource, SourceSpec
from orbit_catalog.search import eligibility, search
from orbit_catalog.store import CatalogStore

from .test_storage import publish

SHA = "a" * 40
READ = {"verification": "repository_and_source_read"}


def test_skill_format_adds_vendored_readers_and_marks_unvendored_unknown():
    matrix = support_matrix("skill", ["claude_code"])
    assert matrix["claude_code"]["basis"] == "source_declared"
    for agent in ("codex", "opencode", "hermes", "dsh", "pi"):
        assert matrix[agent]["support"] == "native" and matrix[agent]["basis"] == "format:agent_skill"
        assert matrix[agent]["evidence"].startswith("third_party/")
    for agent in ("kimi", "cursor", "gemini", "copilot"):
        assert matrix[agent] == {"support": "unknown", "basis": "unverified", "evidence": "agent_skill reader not vendored"}
    # A source that declares kimi keeps it native: the declaration, not our table, is the evidence.
    assert support_matrix("skill", ["kimi"])["kimi"]["support"] == "native"
    assert supported_agents("skill", ["claude_code"]) == ["claude_code", "codex", "dsh", "hermes", "opencode", "pi"]


def test_rule_format_comes_from_the_file_name():
    agents_md = f"https://github.com/o/r/blob/{SHA}/docs/AGENTS.md"
    assert resource_format("rule", agents_md) == "agents_md"
    assert supported_agents("rule", [], agents_md) == ["codex", "dsh", "hermes", "opencode", "pi"]
    cursor = f"https://github.com/o/r/blob/{SHA}/rules/python.mdc"
    assert resource_format("rule", cursor) is None
    assert support_matrix("rule", ["cursor"], cursor) == {
        "cursor": {"support": "native", "basis": "source_declared", "evidence": "source agents"}}
    claude_md = support_matrix("rule", [], repo_path="CLAUDE.md")
    assert sorted(claude_md) == ["dsh", "hermes", "pi"]


def test_claude_hooks_run_in_dsh_and_need_adaptation_for_codex():
    matrix = support_matrix("hook", ["claude_code"], f"https://github.com/o/r/blob/{SHA}/hooks/hooks.json")
    assert matrix["dsh"]["support"] == "native"
    assert matrix["codex"]["support"] == "adaptation_required"
    assert "hermes" not in matrix  # Hermes hooks are Python plugins, not hooks.json: unknown.
    assert support_matrix("hook", ["copilot"]) == {
        "copilot": {"support": "native", "basis": "source_declared", "evidence": "source agents"}}
    assert support_matrix("subagent", ["claude_code"]) == {
        "claude_code": {"support": "native", "basis": "source_declared", "evidence": "source agents"}}


def test_install_targets_per_agent():
    matrix = support_matrix("skill", ["claude_code"])
    targets = {t["agent"]: t for t in install_targets("skill", "PDF Tools", matrix)}
    assert targets["claude_code"]["user_path"] == "~/.claude/skills/pdf-tools/SKILL.md"
    assert targets["hermes"] == {"agent": "hermes", "mode": "copy_dir", "user_path": "~/.hermes/skills/pdf-tools/SKILL.md",
                                 "project_path": None}
    assert targets["pi"]["project_path"] == ".pi/skills/pdf-tools/SKILL.md"
    assert "kimi" not in targets  # unknown support -> no guessed path
    rule = install_targets("rule", "x", support_matrix("rule", ["copilot"]))
    assert rule == [{"agent": "copilot", "mode": "append_section", "user_path": None,
                     "project_path": ".github/copilot-instructions.md"}]
    assert install_targets("plugin", "x", matrix) == []


def _store(tmp_path, rows):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    publish(store, rows)
    return store


def _item(item_id, *, summary, body="", licensed=True, metadata=READ, type="skill", agents=("claude_code",), **extra):
    return Record(native_id=item_id, resource=Resource(
        item_id=item_id, type=type, name=item_id, summary=summary, body=body, url=f"https://github.com/o/r/blob/{SHA}/{item_id}/SKILL.md",
        body_policy="licensed" if licensed else "metadata", license="MIT" if licensed else None,
        agents=list(agents), metadata=dict(metadata), **extra))


def test_match_rows_carry_verification_and_support(tmp_path):
    store = _store(tmp_path, [_item("read", summary="pdf form filler"),
                              _item("tree-only", summary="pdf merger", metadata={"verification": "tree_metadata_only"}),
                              _item("bare", summary="pdf splitter", metadata={})])
    rows = {r["item_id"]: r for r in search(store, MatchRequest(text="pdf"))["items"]}
    assert rows["read"]["verification"] == "repository_and_source_read"
    assert rows["tree-only"]["verification"] == "tree_metadata_only"
    assert rows["bare"]["verification"] is None  # never defaulted to a verified value
    assert rows["read"]["support"]["hermes"] == "native"
    assert rows["read"]["support"]["kimi"] == "unknown"
    assert rows["read"]["support_basis"]["hermes"]["basis"] == "format:agent_skill"
    assert rows["read"]["admission"] == {"tier": "none", "review": None}  # no problem_type asked
    # A claude_code-declared skill is eligible for a Hermes user; a subagent is not.
    publish(store, [_item("read", summary="pdf form filler"),
                    _item("sub", summary="pdf reviewer", type="subagent")], revision="r2")
    hermes = search(store, MatchRequest(text="pdf", agents=["hermes"]))["items"]
    assert [r["item_id"] for r in hermes] == ["read"]


RETRY = "retry_same_call"


def _recommend(store, friction=RETRY):
    return MatchRequest(purpose="recommendation", text="stop retry storms", problem_id="p1", problem_type=friction,
                        scene="coding", evidence_ids=["e1"], profile_evidence_ids=["pe1"], agents=["hermes"],
                        language="en", features=[Feature(feature="dimension", value="loop")])


def _admission_rows():
    filler = "Formats source files consistently. " * 3
    return [
        # "retry" once in the summary: head mass 3 -> weight 3/4 * 0.6 = 0.45 = threshold -> admitted.
        _item("guard", summary="Stops a retry storm", body=filler),
        # Same text, body not licensed: the friction evidence is unread -> not admitted.
        _item("unlicensed", summary="Stops a retry storm", licensed=False),
        # Same text, source tree only: not verified -> not admitted.
        _item("unverified", summary="Stops a retry storm", body=filler, metadata={"verification": "tree_metadata_only"}),
        # One early body mention only: mass 1 -> 1/2 * 0.6 = 0.30 < 0.45 -> not admitted.
        _item("passing", summary="Formatter", body="Never retry formatting. " + filler),
    ]


def test_rule_admission_makes_fetched_items_recommendable(tmp_path):
    assert admission.ADMIT_FRICTION_WEIGHT == pytest.approx(0.45)
    store = _store(tmp_path, _admission_rows())
    result = search(store, _recommend(store))
    assert result["gates"] == []
    assert [r["item_id"] for r in result["items"]] == ["guard"]
    assert result["items"][0]["admission"] == {"tier": "rule_admitted", "review": None}
    assert search(store, _recommend(store, "approval_wait"))["items"] == []
    # The SQL form used by evals agrees with the in-memory mask.
    where, args = eligibility(_recommend(store))
    with sqlite3.connect(store.path) as conn:
        ids = [r[0] for r in conn.execute(f"SELECT i.item_id FROM catalog_item i WHERE {where} ORDER BY 1", args)]
    assert ids == ["guard"]


def test_reviewed_reject_removes_rule_admitted_item(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "review_decisions", lambda: {"guard": "reviewed_reject"})
    store = _store(tmp_path, _admission_rows())
    assert search(store, _recommend(store))["items"] == []


def test_rule_admits_boundaries():
    ok = {"verified": True, "body_policy": "licensed", "risk_level": 1, "kind": "skill", "friction_weight": 0.45}
    assert admission.rule_admits(**ok)
    for change in ({"verified": False}, {"body_policy": "metadata"}, {"risk_level": 2}, {"kind": "plugin"},
                   {"friction_weight": 0.449}):
        assert not admission.rule_admits(**{**ok, **change})
    assert admission.review_decisions() == {}  # bundled review file starts empty


def test_detail_install_paths_follow_the_support_matrix(tmp_path):
    from orbit_catalog import query
    store = _store(tmp_path, [_item("Pdf Tools", summary="pdf form filler", body="# Use\nfill forms")])
    detail = query.get_item(store, "Pdf Tools")
    paths = {p["agent"]: p for p in detail["install"]["paths"]}
    assert paths["hermes"]["user_path"] == "~/.hermes/skills/pdf-tools/SKILL.md"
    assert paths["claude_code"]["project_path"] == ".claude/skills/pdf-tools/SKILL.md"
    assert set(paths) == {"claude_code", "codex", "opencode", "hermes", "dsh", "pi"}
    assert detail["support"]["kimi"]["support"] == "unknown"


def test_declared_levels_win_and_agent_support_omits_unknown(tmp_path):
    matrix = support_matrix("rule", ["claude_code", "codex"], declared={"claude_code": "native", "codex": "manual",
                                                                       "generic": "native", "x": "bogus"})
    assert matrix["codex"] == {"support": "manual", "basis": "declared_level", "evidence": "metadata.agent_support"}
    assert "generic" not in matrix and "x" not in matrix
    store = _store(tmp_path, [_item("kbish", summary="pdf helper",
                                    metadata={**READ, "agent_support": {"claude_code": "native", "codex": "manual"}})])
    row = search(store, MatchRequest(text="pdf"))["items"][0]
    assert row["agent_support"]["codex"] == "manual" and row["agent_support"]["hermes"] == "native"
    assert "kimi" not in row["agent_support"] and row["support"]["kimi"] == "unknown"
