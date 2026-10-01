"""Changing the reading order must preserve facts and evidence contracts."""

from tandem_backend.analysis import analyze
from tandem_backend.cli import demo_home
from tandem_backend.content import visible_text
from tandem_backend.narrative import explain, markdown
from tandem_backend.recommend import recommend
from tandem_backend.store import Store, import_codex


def test_empty_report_has_same_public_fields_and_no_unearned_findings(tmp_path):
    store = Store(tmp_path / "empty.sqlite")
    empty = explain(analyze(store))
    import_codex(store, demo_home(tmp_path / "codex"))
    populated = explain(analyze(store))
    assert set(empty) == set(populated)
    assert empty["findings"] == empty["bottlenecks"] == empty["recommendations"] == []
    assert empty["main_evidence_ids"] == []


def test_new_reading_order_retains_decision_and_real_sample_counts(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, demo_home(tmp_path / "codex"))
    data = analyze(store)
    recs = recommend(data)
    result = explain(data, recs)
    text = markdown(result)
    assert result["main_evidence_ids"] == result["bottlenecks"][0]["evidence_ids"]
    assert all(eid in text for eid in result["main_evidence_ids"])
    assert result["recommendations"] == recs
    assert "3 个会话" in result["sample_summary"] and "1 个项目" in result["sample_summary"]
    assert text.index(result["summary"]) < text.index(result["sample_summary"])
    assert len(visible_text(text)) < 1100


def test_developer_output_exposes_counting_basis_without_changing_facts(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, demo_home(tmp_path / "codex"))
    data = analyze(store)
    recs = recommend(data)
    user = explain(data, recs)
    developer = explain(data, recs, "developer")
    assert user["details"] == developer["details"]
    assert user["recommendations"] == developer["recommendations"]
    assert user["main_evidence_ids"] == developer["main_evidence_ids"]
    assert "同一会话重复提出只计一次" in markdown(developer)
    assert "同一会话重复提出只计一次" not in markdown(user)
