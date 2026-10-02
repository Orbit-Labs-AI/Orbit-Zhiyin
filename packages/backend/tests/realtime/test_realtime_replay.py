from __future__ import annotations

from tandem_backend.realtime.replay import DEFAULT_CASES, run_cases


def test_all_replay_cases_pass():
    assert DEFAULT_CASES.is_file()
    report = run_cases()
    failed = [c for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    assert len(report["cases"]) == 8
    assert report["false_alarms"] == 0
    latency = report["detect_latency_s"]
    assert latency["failing"] == 0 and latency["awaiting_approval"] == 0
    assert latency["just_finished"] == 0


def test_false_alarm_is_counted(tmp_path):
    case = {"id": "x", "rows": [{"t": 0, "kind": "message", "actor": "human"}],
            "until": 30, "never": ["running"]}
    path = tmp_path / "cases.json"
    path.write_text('{"cases": [' + __import__("json").dumps(case) + "]}")
    report = run_cases(path)
    assert report["false_alarms"] == 1 and not report["cases"][0]["passed"]
    assert report["detect_latency_s"] == {"failing": None, "just_finished": None,
                                          "awaiting_approval": None}
