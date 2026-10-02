import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.evalrun import runner
from tandem_backend.evalrun import store as eval_store


def test_pass_skip_and_scores(fake_suites):
    report = runner.run(["ok", "skip"])
    assert report["passed"] and report["score"] == 1.0 and report["status"] == "done"
    skipped = report["suites"][1]
    assert skipped == {"suite": "skip", "skipped": "no data", "score": None, "checks": [], "metrics": {}}


def test_failed_check_fails_and_score_is_unweighted_mean(fake_suites):
    report = runner.run(["ok", "half"])
    assert not report["passed"] and report["score"] == 0.75
    assert report["suites"][1]["checks"][1] == {"id": "half.b", "passed": False, "value": 0.2,
                                                "threshold": 0.5, "detail": "low"}


def test_crash_is_a_failed_check(fake_suites):
    report = runner.run(["boom"])
    (check,) = report["suites"][0]["checks"]
    assert check["id"] == "boom.crashed" and not check["passed"] and "kaput" in check["detail"]
    assert not report["passed"] and report["score"] == 0.0


@pytest.mark.parametrize(("fail_under", "passed"), [(None, True), (1.0, True), (0.0, True)])
def test_fail_under_boundaries_on_perfect_run(fake_suites, fail_under, passed):
    assert runner.run(["ok"], fail_under=fail_under)["passed"] is passed


def test_fail_under_alone_can_fail():
    # A suite whose checks all pass but whose score sits below the bar cannot exist, so
    # check the rule on summarize() directly with a hand-built suite row.
    rows = [{"suite": "a", "skipped": None, "score": 0.5, "checks": [], "metrics": {}}]
    assert not runner.summarize("r", 0, rows, 0.5001)["passed"]
    assert runner.summarize("r", 0, rows, 0.5)["passed"]


def test_all_skipped_has_no_score_and_passes(fake_suites):
    report = runner.run(["skip"], fail_under=0.9)
    assert report["score"] is None and report["passed"]


def test_all_and_unknown_and_params(fake_suites, tmp_path):
    assert [s["suite"] for s in runner.run("all")["suites"]] == sorted(fake_suites)
    with pytest.raises(ValueError):
        runner.run(["nope"])
    with pytest.raises(ValueError):
        runner.run(["ok"], fail_under=1.5)
    report = runner.run(["params"], params={"x": 1}, home=tmp_path)
    assert report["passed"] and report["suites"][0]["metrics"]["home"] == str(tmp_path)


def test_store_round_trip(fake_suites, tmp_path):
    db = AppDB(tmp_path / "app.db")
    seen = []
    report = runner.run(["ok", "half", "skip"], fail_under=0.5, params={"x": 1}, store=db,
                        progress=lambda sid, row: seen.append((sid, row is None)))
    assert seen == [("ok", True), ("ok", False), ("half", True), ("half", False),
                    ("skip", True), ("skip", False)]
    stored = eval_store.get_run(db, report["run_id"])
    assert stored["suites"] == report["suites"]
    assert stored["passed"] is False and stored["score"] == report["score"]
    assert stored["fail_under"] == 0.5 and stored["params"] == {"x": 1}
    (brief,) = eval_store.list_runs(db)
    assert brief["suites"] == ["ok", "half", "skip"] and brief["status"] == "done"
    assert eval_store.get_run(db, "missing") is None
    db.close()


def test_prune_keeps_latest_runs(fake_suites, tmp_path, monkeypatch):
    db = AppDB(tmp_path / "app.db")
    monkeypatch.setattr(eval_store, "KEEP_RUNS", 3)
    clock = iter(range(1000, 100000, 10))
    monkeypatch.setattr(runner, "_now", lambda: next(clock))
    ids = [runner.run(["ok"], store=db)["run_id"] for _ in range(5)]
    assert [r["run_id"] for r in eval_store.list_runs(db)] == ids[::-1][:3]
    with db.read() as conn:
        assert conn.execute("SELECT count(DISTINCT run_id) FROM eval_check").fetchone()[0] == 3
    db.close()

