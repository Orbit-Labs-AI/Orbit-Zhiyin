"""Evaluation labels and reader criteria must remain separate from the user's ledger."""

import json

from tandem_backend.analysis import analyze
from tandem_backend.cli import demo_home, main
from tandem_backend.pipeline_eval import _metrics, _write_case, evidence_checks, pipeline_benchmark
from tandem_backend.recommend import recommend
from tandem_backend.store import Store, import_codex


def test_full_pipeline_contrasts_match_labeled_decisions():
    result = pipeline_benchmark()
    assert result["cases"] == 34
    assert result["correct"] == result["cases"]
    assert result["human_acceptance"] == "pending"
    assert result["history_updated"] is False
    assert result["split"] == "development_contrasts"
    assert all(m["false_positive"] == 0 and m["false_negative"] == 0 for m in result["metrics"].values())
    assert all(all(case["checks"].values()) for case in result["results"])


def test_set_metrics_do_not_reward_empty_predictions_as_precision_one():
    assert _metrics([(set(), set())])["precision"] is None
    metric = _metrics([({"a", "b"}, {"b", "c"}), (set(), {"d"})])
    assert metric["true_positive"] == 1
    assert metric["false_positive"] == 1
    assert metric["false_negative"] == 2
    assert metric["precision"] == 0.5
    assert metric["recall"] == 0.3333


def test_benchmark_cannot_modify_selected_normal_database(tmp_path):
    store = Store(tmp_path / "normal.sqlite")
    import_codex(store, demo_home(tmp_path / "codex"))
    counts = store.counts()
    events = [e.to_dict() for e in store.events()]
    output = tmp_path / "evaluation.json"
    main(["--db", str(store.path), "evaluate", "--suite", "pipeline", "--output", str(output)])
    assert store.counts() == counts
    assert [e.to_dict() for e in store.events()] == events
    assert json.loads(output.read_text())["history_updated"] is False


def test_evidence_checks_reject_fabricated_reference_context_and_source(tmp_path):
    store = Store(tmp_path / "normal.sqlite")
    import_codex(store, demo_home(tmp_path / "codex"))
    data = analyze(store)
    recs = recommend(data)
    assert all(evidence_checks(store, data, recs).values())
    rec = recs[0]
    bad = {**rec, "profile_evidence_ids": ["invented"]}
    assert not evidence_checks(store, data, [bad])["references_valid"]
    bad = {**rec, "scene": "math_explanation"}
    assert not evidence_checks(store, data, [bad])["original_context_preserved"]
    bad = {**rec, "source_url": "https://example.com/unknown"}
    assert not evidence_checks(store, data, [bad])["versioned_source_reference_valid"]
    bad = {**rec, "effect_status": "proven"}
    assert not evidence_checks(store, data, [bad])["original_context_preserved"]


def test_case_writer_does_not_receive_or_copy_expected_labels(tmp_path):
    path = _write_case(tmp_path / "codex", "sample", [{"kind": "user", "text": "你好。"}])
    text = path.read_text()
    assert "expected" not in text and "evaluation_only" not in text
    parsed = [json.loads(line) for line in text.splitlines()]
    assert sum(r["payload"].get("role") == "user" for r in parsed) == 1
