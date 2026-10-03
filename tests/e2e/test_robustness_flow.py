"""The replay oracle must catch broken evidence rather than merely run analysis."""

import copy
import importlib
import json
from pathlib import Path

import pytest

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.service import recommend


@pytest.fixture
def replay(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    oracle = importlib.import_module("evals.analytics.robustness_invariants")
    synthetic = importlib.import_module("benchmarks.analytics.synthetic")
    bundle = AnalysisInputBundle.from_dict(synthetic.generate_bundle(20, 7))
    scope = Scope()
    controlled = importlib.import_module("evals.analytics.robustness")
    bundle = controlled.fixture_seed(bundle, scope)
    seed = next(c for c in bundle.tool_calls if c["call_uid"] == "constructed:seed")
    for i in range(3):
        controlled.add_attempt(
            bundle,
            seed["session_uid"],
            seed["task_uid"],
            seed["turn_uid"],
            f"constructed:retry-{i}",
            2 + i * 2,
            seed["ended_at"] + 10 + i * 20,
            "success",
            retry_of=seed["call_uid"],
        )
    analysis = analyze_bundle(bundle, scope, with_text=False, with_recommendations=False)
    loaded = load_catalog(
        items=json.loads((root / "evals/recommendation/fixtures/reviewed-skills.json").read_text())[
            "items"
        ]
    )
    result = recommend(analysis, context={"agent": "codex"}, catalog=loaded.items, family="skills")
    assert result["recommendations"]
    return oracle, bundle, scope, analysis, result


def test_valid_shared_turn_and_artifact_membership_uses_graph_edges(replay):
    oracle, bundle, scope, analysis, result = replay
    graph = analysis["work_graph"]
    assert any(n["kind"] == "Turn" and n.get("task_uid") is None for n in graph["nodes"])
    assert oracle.validate_result(bundle, scope, analysis, result)["status"] == "passed"


@pytest.mark.parametrize(
    "damage,expected",
    [
        ("membership", "trajectory_member_misattributed"),
        ("card_evidence", "recommendation_event_unselected"),
        ("signal_root", "card_signal_wrong_root"),
        ("pending", "unknown_context_promoted"),
        ("measured", "historical_log_claims_measured_utility"),
        ("human_count", "human_denominator_mismatch"),
        ("dangling", "dangling_graph_edge"),
    ],
)
def test_relational_oracle_rejects_corruption(replay, damage, expected):
    oracle, bundle, scope, analysis, result = replay
    analysis, result = copy.deepcopy(analysis), copy.deepcopy(result)
    graph = analysis["work_graph"]
    card = result["recommendations"][0]
    if damage == "membership":
        removed = next(e for e in graph["edges"] if e["kind"] == "BELONGS_TO_TASK")
        graph["edges"].remove(removed)
    elif damage == "card_evidence":
        card["evidence"] = [
            {"kind": "event", "session_uid": card["scope"]["root_session_uid"], "id": "absent"}
        ]
    elif damage == "signal_root":
        uid = card["candidate_features"]["grounded_signal_ids"][0]
        next(s for s in result["signals"] if s["signal_id"] == uid)["scope"]["root_session_uid"] = (
            "wrong-root"
        )
    elif damage == "pending":
        card["pending_requirements"] = ["unknown environment"]
        card["compatibility"] = "compatible"
        card["recommendation_status"] = "ready"
    elif damage == "measured":
        card["effect_status"] = "measured"
    elif damage == "human_count":
        analysis["bottleneck_features"]["interaction"]["effective_samples"]["human_messages"] += 1
    elif damage == "dangling":
        graph["edges"][0]["to_node_uid"] = "absent"
    checked = oracle.validate_result(bundle, scope, analysis, result)
    assert checked["status"] == "failed" and expected in checked["violation_counts"]


def test_native_comparison_excludes_only_last_scan_time_and_batch_size(monkeypatch):
    runner = importlib.import_module("evals.analytics.robustness_native")
    left = {name: [] for name in runner.CORE_SECTIONS}
    left["sessions"] = [
        {
            "coverage": {
                "source_scans": {
                    "status": "available",
                    "scans": [
                        {
                            "source_id": "a",
                            "scanned_at": 100,
                            "indexed_files": 153,
                            "coverage": "selected_files",
                        }
                    ],
                }
            }
        }
    ]
    right = copy.deepcopy(left)
    scan = right["sessions"][0]["coverage"]["source_scans"]["scans"][0]
    scan.update(scanned_at=200, indexed_files=51)
    assert runner.core(left) == runner.core(right)
    assert runner.scan_metadata(left) != runner.scan_metadata(right)
    scan["coverage"] = "partial"
    assert runner.core(left) != runner.core(right)


def test_failed_replay_records_failure_and_never_overwrites_existing_run(tmp_path, monkeypatch):
    runner = importlib.import_module("evals.analytics.robustness")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    output = tmp_path / ".local/run"

    def broken(*args, **kwargs):
        output.mkdir(parents=True)
        runner.save(output / "summary.json", {"status": "running", "cases": []})
        raise RuntimeError("private source detail must not be copied into the manifest")

    monkeypatch.setattr(runner, "_run", broken)
    with pytest.raises(RuntimeError):
        runner.run(None, Scope(), output)
    manifest = json.loads((output / "summary.json").read_text())
    assert manifest == {"status": "failed", "cases": [], "error_type": "RuntimeError"}
    before = (output / "summary.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.run(None, Scope(), output)
    assert (output / "summary.json").read_bytes() == before
