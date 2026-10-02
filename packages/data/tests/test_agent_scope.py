"""Agent filters use source provenance, independently of request model names."""

import pytest

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.store import Store
from tandem_data.validation.fixtures import create_sources


@pytest.fixture
def multi_agent_home(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    home = tmp_path / "data"
    with Store(home) as store:
        for agent in ("claude_code", "pi"):
            source = store.add_source(agent, roots[agent])
            for path in roots[agent].rglob("*.jsonl"):
                store.capture_stream(
                    source, path.relative_to(roots[agent]).as_posix(), [path.read_bytes()]
                )
        store.rebuild()
    return home


def test_agent_and_model_are_independent_intersecting_filters(multi_agent_home):
    all_agents = read_analysis(multi_agent_home, AnalysisScope("UTC", model_ids=("fixture-model",)))
    assert {s["agent"] for s in all_agents["sessions"]} == {"claude_code", "pi"}
    one_agent = read_analysis(
        multi_agent_home,
        AnalysisScope("UTC", agent_ids=("pi",), model_ids=("fixture-model",)),
    )
    assert {s["agent"] for s in one_agent["sessions"]} == {"pi"}
    assert len(one_agent["model_calls"]) == 1
    assert one_agent["scope"]["agent_ids"] == ("pi",)
    assert one_agent["scope"]["model_ids"] == ("fixture-model",)
    source_ids = {s["source_id"] for s in one_agent["sessions"]}
    assert {s["source_id"] for s in one_agent["sample_boundary"]["sources"]} == source_ids
    assert {f["source_id"] for f in one_agent["sample_boundary"]["files"]} == source_ids
    assert not read_analysis(multi_agent_home, AnalysisScope("UTC", agent_ids=("fixture-model",)))[
        "events"
    ]
    assert not read_analysis(
        multi_agent_home, AnalysisScope("UTC", agent_ids=("pi",), model_ids=("claude_code",))
    )["events"]


@pytest.mark.parametrize("agents", [(), ("missing-agent",)])
def test_empty_or_unknown_agent_selection_is_empty(multi_agent_home, agents):
    result = read_analysis(multi_agent_home, AnalysisScope("UTC", agent_ids=agents), max_events=0)
    for key in ("events", "sessions", "tool_calls", "model_calls", "turns", "projects"):
        assert result[key] == []
    assert result["statistical_members"]["event_uids"] == []
    assert result["sample_boundary"]["sources"] == []
    assert result["sample_boundary"]["files"] == []
    assert result["scope"]["agent_ids"] == agents


def test_agent_predicate_applies_before_event_memory_budget(multi_agent_home):
    selected = read_analysis(multi_agent_home, AnalysisScope("UTC", agent_ids=("pi",)))
    budget = len(selected["events"])
    assert budget > 0
    with pytest.raises(ValueError, match="event limit exceeded"):
        read_analysis(multi_agent_home, AnalysisScope("UTC"), max_events=budget)
    filtered = read_analysis(
        multi_agent_home, AnalysisScope("UTC", agent_ids=("pi",)), max_events=budget
    )
    assert filtered["events"] == selected["events"]
    combined = read_analysis(
        multi_agent_home, AnalysisScope("UTC", agent_ids=("pi", "claude_code"))
    )
    assert {s["agent"] for s in combined["sessions"]} == {"pi", "claude_code"}


def test_selected_descendant_does_not_restore_unselected_agent_root(multi_agent_home):
    with Store(multi_agent_home) as store:
        sessions = {
            row["agent"]: row["session_uid"]
            for row in store.db.execute(
                "SELECT s.session_uid,src.agent FROM session s JOIN source src USING(source_id)"
            )
        }
        child, root = sessions["pi"], sessions["claude_code"]
        store.db.execute(
            "UPDATE session SET kind='subagent',parent_uid=?,root_uid=? WHERE session_uid=?",
            (root, root, child),
        )
    result = read_analysis(
        multi_agent_home, AnalysisScope("UTC", agent_ids=("pi",), root_session_uids=(root,))
    )
    assert {s["session_uid"] for s in result["sessions"]} == {child}
    assert {e["session_uid"] for e in result["events"]} == {child}
    for options in ({"include_children": False}, {"excluded_session_uids": (root,)}):
        assert not read_analysis(
            multi_agent_home, AnalysisScope("UTC", agent_ids=("pi",), **options)
        )["events"]
    assert not read_analysis(
        multi_agent_home, AnalysisScope("UTC", agent_ids=("pi",), from_ts=2000000000000)
    )["events"]
