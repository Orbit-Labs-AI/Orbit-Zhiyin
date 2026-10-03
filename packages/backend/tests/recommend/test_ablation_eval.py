"""EV-05 / EV-05.1 / EV-05.2: time-split replay, AI rerank, ablations and exposure rates."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tandem_backend.ai.engines import FakeEngine
from tandem_backend.appdb import AppDB
from tandem_backend.evalrun import cli, runner
from tandem_backend.recommend import evaluation as ev
from tandem_backend.recommend.engine import build_slate
from tandem_backend.recommend.ranking import gates as gate_mod
from tandem_backend.recommend.ranking import rank as rank_mod

FIXTURES = Path(__file__).resolve().parents[4] / "evals" / "recommendation" / "fixtures"
T = "2026-09-28T00:00:00Z"


@pytest.fixture(scope="module")
def data():
    cases = json.loads((FIXTURES / "replay-cases.json").read_text())["cases"]
    users = json.loads((FIXTURES / "timeline-cases.json").read_text())["users"]
    return cases, ev.link_cases(users, cases)


def _slate(keys):
    return {"candidates": [{"rec_key": k, "kind": "rule", "rank": i, "problem": {"type": "p", "key": "p:x"}}
                           for i, k in enumerate(keys, 1)], "problems": [], "diagnostics": []}


def fake_build(inputs, memory):
    installed = {k for k, s in memory["state"].items() if s.get("status") == "installed"}
    return _slate([k for k in ("a", "b", "c", "d") if k not in installed])


def user(**kw):
    return {"id": "u", "cutoffs": [{"t": T, "inputs": {"sessions": {"last_ts": "2026-09-26T00:00:00Z"}}}], **kw}


def test_time_split_labels_horizon_and_history():
    users = [user(adoptions=[{"ts": "2026-09-20T00:00:00Z", "target": "a"},       # before t → installed
                             {"ts": "2026-10-01T00:00:00Z", "target": "d", "grade": 2}]),
             user(id="late", adoptions=[{"ts": "2026-12-01T00:00:00Z", "target": "b"}])]
    result = ev.time_split(users, build=fake_build)
    assert result["cutoffs"] == 1  # the late user has no label inside 14 days
    row = result["per_cutoff"][0]
    assert row["top"] == ["b", "c", "d"] and row["hit"] and result["ndcg@3"] == 0.5


def test_time_split_rejects_leaked_inputs():
    leaky = {"id": "x", "cutoffs": [{"t": T, "inputs": {"sessions": {"last_ts": "2026-09-29T00:00:00Z"}}}],
             "adoptions": [{"ts": "2026-10-01T00:00:00Z", "target": "a"}]}
    with pytest.raises(ValueError, match="include data from"):
        ev.time_split([leaky], build=fake_build)


def test_rerank_via_fake_engine_changes_display_order():
    def judge(req):
        return {"items": [{"candidate_id": "a", "fit": "unfit", "reasons": [], "explain": "p:x 不适用",
                           "pair_with": []}]}

    engine = FakeEngine({"rerank.fit": judge})
    users = [user(adoptions=[{"ts": "2026-10-01T00:00:00Z", "target": "a"}])]
    base = ev.time_split(users, build=fake_build)
    reranked = ev.time_split(users, build=fake_build, rerank=ev.engine_rerank(engine))
    assert base["ndcg@3"] == 1.0 and engine.requests[0].task_id == "rerank.fit"
    assert reranked["per_cutoff"][0]["top"] == ["b", "c", "d"] and reranked["hit_rate@3"] == 0.0


def test_rerank_falls_back_when_engine_output_invalid():
    engine = FakeEngine({"rerank.fit": {"items": [{"candidate_id": "zz", "fit": "unfit", "reasons": [],
                                                   "explain": "p:x", "pair_with": []}]}})
    slate = _slate(["a", "b"])
    ev.engine_rerank(engine)(slate)
    assert [c["display_rank"] for c in slate["candidates"]] == [1, 2]


def test_ablated_patches_are_scoped(data):
    cases, _ = data
    case = next(c for c in cases if c["id"] == "identical-retries")
    memory = ev.EMPTY_MEMORY | {"state": {"kb:systematic-debugging": {"status": "muted"}}}
    original_score, original_checks = rank_mod.score, dict(gate_mod.CHECKS)
    with ev.ablated(gates=("not_dismissed",)) as build:
        assert "kb:systematic-debugging" in [c["rec_key"] for c in ev.top_k(build(case["inputs"], memory))]
    assert rank_mod.score is original_score and gate_mod.CHECKS == original_checks
    assert "kb:systematic-debugging" not in [c["rec_key"] for c in ev.top_k(build_slate(case["inputs"], memory))]
    with pytest.raises(ValueError, match="unknown ablation"):
        with ev.ablated(terms=("nope",)):
            pass


def test_neutral_score_formula_tracks_rank_score(data, monkeypatch):
    """Guard: the ablation recompute must match rank.score; update both if RC-05 changes."""
    cases, _ = data
    original, pairs = rank_mod.score, []
    recompute = ev._neutral_score(original, ())

    def spy(raw, gates, inputs, memory, *, max_fusion=None):
        score = original(raw, gates, inputs, memory, max_fusion=max_fusion)
        again = recompute(raw, gates, inputs, memory, max_fusion=max_fusion)
        pairs.append((score["priority"], again["priority"]))
        return score

    monkeypatch.setattr(rank_mod, "score", spy)
    for case in cases:
        build_slate(case["inputs"], ev.EMPTY_MEMORY)
    assert pairs and all(abs(a - b) <= .05 for a, b in pairs)


def test_ablation_report_covers_gates_terms_and_bundles(data):
    cases, users = data
    report = ev.ablation_report(cases, users)
    names = {(r["kind"], r["name"]): r for r in report["rows"]}
    assert {n for k, n in names if k == "gate"} == set(gate_mod.CHECKS)
    assert {n for k, n in names if k == "term"} == set(ev.TERMS)
    rc17 = names[("bundle", "RC-17")]
    assert rc17["verdict"] == "keep" and rc17["delta"]["split.repeat_na@3"] > 0
    # regression floor at the measured synthetic baseline (2026-10-03), not a loose sanity bound
    base = report["baseline"]
    assert base["replay.hit_rate@3"] == 1.0 and base["replay.ndcg@3"] >= .765
    assert base["split.hit_rate@3"] == 1.0 and base["split.ndcg@3"] >= .881 and base["split.repeat_na@3"] == 0


NOW = int(time.time() * 1000)


def _exposure_db(path: Path) -> None:
    db = AppDB(path)
    with db.write() as conn:
        rows = [(i, "kb:noisy", "A7", "view") for i in range(12)]
        rows += [(100 + i, "kb:good", "lite", "view") for i in range(10)]
        rows += [(200 + i, "kb:good", "lite", "install") for i in range(4)]
        rows += [(300 + i, "kb:rare", "A7", "view") for i in range(3)]
        conn.executemany("INSERT INTO rec_exposure (ts, rec_key, surface, action) VALUES (?,?,?,?)",
                         [(NOW - 86_400_000 + ts, k, s, a) for ts, k, s, a in rows])
        conn.executemany("INSERT INTO label (label_id, target_kind, target_id, rec_key, label, ts) "
                         "VALUES (?, 'candidate', ?, ?, 'not_applicable', ?)",
                         [(f"l{i}", f"c{i}", "kb:noisy", NOW - 1000) for i in range(7)]
                         + [("r0", "c9", "kb:rare", NOW - 1000)])
    db.close()


def test_exposure_report_rates_by_rule_and_surface(tmp_path):
    _exposure_db(tmp_path / "app.db")
    db = AppDB(tmp_path / "app.db")
    with db.read() as conn:
        report = ev.exposure_report(conn, now=NOW)
    db.close()
    by_rule = {r["remedy_rule"]: r for r in report["rows"]}
    assert by_rule["kb:noisy"]["na_rate"] == round(7 / 12, 4) and by_rule["kb:noisy"]["surface"] == "A7"
    assert by_rule["kb:good"]["adoption_rate"] == .4 and by_rule["kb:good"]["na_rate"] == 0
    assert by_rule["kb:rare"]["n"] == 3 and by_rule["kb:rare"]["na_rate"] is None  # n < 10: only n
    assert report["downweight"] == ["kb:noisy"] and report["na_rate_ok"] is False


def test_suite_registered_and_fails_on_bad_exposure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    clean = runner.run_suite("recommend", params={"ablation": False})
    assert clean.skipped is None and clean.score == 1.0
    assert {c.id for c in clean.checks} >= {"recommend.split.hit_rate@3", "recommend.rerank.no_regression",
                                            "recommend.rc17.repeat_na"}
    _exposure_db(tmp_path / "app.db")
    bad = runner.run_suite("recommend", params={"appdb": str(tmp_path / "app.db"), "ablation": False})
    check = next(c for c in bad.checks if c.id == "recommend.exposure.na_rate")
    assert not check.passed and "kb:noisy" in check.detail


def test_cli_fail_under(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    code = cli.main(["eval", "run", "--suite", "recommend", "--fail-under", "0.9", "--no-store",
                     "--home", str(tmp_path / "tandem")])
    assert code == 0 and "PASS" in capsys.readouterr().out


def test_suite_skips_without_fixtures(tmp_path):
    result = runner.run_suite("recommend", params={"fixtures_dir": str(tmp_path / "none")})
    assert result.skipped == "evals/recommendation/fixtures not found"


def test_suite_reports_replay_negatives_and_disclaimer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    clean = runner.run_suite("recommend", params={"ablation": False})
    cases = json.loads((FIXTURES / "replay-cases.json").read_text())["cases"]
    n_negative = sum("expect" in case for case in cases)
    check = next(c for c in clean.checks if c.id == "recommend.replay.negative_pass_rate")
    assert check.passed and check.value == 1.0 and f"{n_negative} negative cases" in check.detail
    assert clean.metrics["replay"]["n_negative"] == n_negative > 0
    assert clean.metrics["disclaimer"].startswith("合成集，仅回归")


def test_suite_fails_when_a_negative_case_recommends(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    fixtures = tmp_path / "recommendation" / "fixtures"
    fixtures.mkdir(parents=True)
    cases = json.loads((FIXTURES / "replay-cases.json").read_text())["cases"]
    positive = next(c for c in cases if c["id"] == "permission-readonly")
    # the same evidence that should produce a permission card, declared as "must recommend nothing"
    wrong = {"id": "neg-wrong", "inputs": positive["inputs"], "relevant": {}, "expect": {"ranked": 0}}
    (fixtures / "replay-cases.json").write_text(json.dumps({"cases": [*cases, wrong]}), encoding="utf-8")
    (fixtures / "timeline-cases.json").write_text((FIXTURES / "timeline-cases.json").read_text(), encoding="utf-8")
    (fixtures.parent / "replay.py").write_text((FIXTURES.parent / "replay.py").read_text(), encoding="utf-8")
    result = runner.run_suite("recommend", params={"ablation": False, "fixtures_dir": str(fixtures)})
    check = next(c for c in result.checks if c.id == "recommend.replay.negative_pass_rate")
    n_negative = sum("expect" in case for case in cases) + 1
    assert not check.passed and check.value == round((n_negative - 1) / n_negative, 4)
    assert "neg-wrong: ranked" in check.detail
