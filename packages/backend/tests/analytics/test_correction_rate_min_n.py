"""a1a3-B19: a single correction message must not make a session's correction rate 1.0."""

from tandem_backend.analytics.inputs import AnalysisInputBundle
from tandem_backend.analytics.service import analyze_bundle


def build(texts):
    cov = {k: {"status": "available"} for k in
           ("events", "sessions", "tool_calls", "turns", "projects", "model_calls")}
    events = [{"event_uid": f"u{i}", "session_uid": "s", "seq": i, "ts": 100 + i,
               "kind": "message.user", "turn_uid": f"t{i}", "actor": "human", "text": text,
               "attrs": {"origin": "human"}} for i, text in enumerate(texts)]
    return AnalysisInputBundle(
        [{"session_uid": "s", "kind": "main", "root_uid": "s", "project_id": "p", "started_at": 0}],
        events, [], [], cov, projects=[{"project_id": "p", "name": "fixture"}])


def features(texts):
    return analyze_bundle(build(texts), with_text=False)["sessions"][0]["features"]


def test_single_correction_message_has_no_rate():
    f = features(["不对，请重新来"])
    assert f["correction_signal_count"] == 1
    assert f["correction_signal_rate"] is None
    assert f["correction_signal_rate_n"] == 1
    assert f["correction_signal_rate_ci"] is None


def test_rate_with_enough_messages_carries_n_and_interval():
    f = features(["请修复测试", "不对，请重新来", "好的继续"])
    assert f["correction_signal_rate"] == 1 / 3
    assert f["correction_signal_rate_n"] == 3
    low, high = f["correction_signal_rate_ci"]
    assert 0 < low < 1 / 3 < high < 1
