import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("replay", ROOT / "evals/recommendation/replay.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)


def test_fixtures_are_synthetic_and_large_enough():
    cases = replay.load_cases()
    positives = [c for c in cases if "expect" not in c]
    assert len(positives) >= 12 and len({c["id"] for c in cases}) == len(cases)
    for case in positives:
        assert case["relevant"] and all(1 <= g <= 3 for g in case["relevant"].values())
        assert case["label_rationale"]  # each label set states why, independent of the engine
    for case in cases:
        assert "/Users/" not in str(case["inputs"])
    negatives = [c for c in cases if "expect" in c]
    assert len(negatives) >= 5 and all(c["relevant"] == {} for c in negatives)
    catalog = [c for c in positives if any("origin=catalog" in k for k in c["relevant"])]
    assert len(catalog) >= 2


def test_labels_do_not_come_from_engine_priority_table():
    note = json.loads(replay.FIXTURES.read_text(encoding="utf-8"))["note"]
    assert "未参考 mechanism.REMEDY_PRIORITY" in note and "优先序给出" not in note


def test_metrics_with_fake_build():
    case = {"id": "x", "inputs": {}, "relevant": {"type=t&kind=hook": 3, "r2": 1}}

    def build(inputs, memory):
        cands = [{"rec_key": "r1", "rank": 1, "kind": "rule", "problem": {"type": "t"}},
                 {"rec_key": "r2", "rank": 2, "kind": "rule"},
                 {"rec_key": "r3", "rank": 3, "kind": "hook", "problem": {"type": "t"}},
                 {"rec_key": "gated", "rank": None, "kind": "hook", "problem": {"type": "t"}}]
        return {"status": "ready", "candidates": cands}

    result = replay.run_replay([case], build)
    row = result["per_case"][0]
    assert row["top3"] == ["r1", "r2", "r3"] and row["hit"] and result["hit_rate@3"] == 1
    # gains [0, 1, 7]; ideal [7, 1]
    expected = (1 / replay.math.log2(3) + 7 / 2) / (7 + 1 / replay.math.log2(3))
    assert row["ndcg"] == pytest.approx(expected, abs=1e-4)


def test_replay_regression_thresholds():
    """Regression floor at the measured 2026-10-03 values (14 positives: hit 1.0, ndcg .7652);
    a drop means a ranking change made the synthetic set worse — not that real users are served."""
    result = replay.run_replay(replay.load_cases())
    assert result["n_positive"] == 14 and result["n_negative"] == 5
    assert result["disclaimer"].startswith("合成集，仅回归")
    assert result["hit_rate@3"] == 1.0, result["per_case"]
    assert result["ndcg@3"] >= .765, result["per_case"]
    assert result["negative_pass_rate"] == 1.0, result["negatives"]
    by_id = {c["id"]: c for c in result["per_case"]}
    assert any(k.startswith("catalog:") for k in by_id["repeat-kb-muted-catalog"]["top3"])


@pytest.mark.parametrize("case_id", ["neg-no-history", "neg-four-sessions", "neg-clean-history",
                                     "neg-muted-type", "neg-all-muted"])
def test_negative_cases_produce_no_problem_cards(case_id):
    case = next(c for c in replay.load_cases() if c["id"] == case_id)
    slate = replay._default_build()(case["inputs"], replay.EMPTY_MEMORY | (case.get("memory") or {}))
    assert replay.check_negative(slate, case["expect"]) == []
    assert not [c for c in slate["candidates"] if c.get("rank") and c.get("problem")]
