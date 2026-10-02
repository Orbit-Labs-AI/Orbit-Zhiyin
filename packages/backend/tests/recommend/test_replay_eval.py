import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("replay", ROOT / "evals/recommendation/replay.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)


def test_fixtures_are_synthetic_and_large_enough():
    cases = replay.load_cases()
    assert len(cases) >= 12 and len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case["relevant"] and all(1 <= g <= 3 for g in case["relevant"].values())
        assert "/Users/" not in str(case["inputs"])


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


def test_replay_meets_quality_bar():
    if importlib.util.find_spec("tandem_backend.recommend.recall.multi") is None:
        pytest.skip("requires rec-recall-kb")
    result = replay.run_replay(replay.load_cases())
    assert result["hit_rate@3"] >= .9, result["per_case"]
    assert result["ndcg@3"] >= .75, result["per_case"]
