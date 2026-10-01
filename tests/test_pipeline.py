import json
from pathlib import Path

from fastapi.testclient import TestClient

from tandem_backend.analysis import analyze, union_duration, wilson_interval
from tandem_backend.api import create_app
from tandem_backend.cli import demo_home
from tandem_backend.evaluation import benchmark, evaluate_text
from tandem_backend.feedback import signals
from tandem_backend.importers.codex import parse_rollout
from tandem_backend.models import Event
from tandem_backend.privacy import direct_user_text, redact
from tandem_backend.recommend import recommend
from tandem_backend.store import Store, import_codex


def rollout(path: Path, rows: list[tuple[str, dict]], tail: bytes = b"") -> Path:
    payload = b"".join(json.dumps({"type": kind, "payload": data, "timestamp": "2026-01-01T00:00:01Z"}).encode() + b"\n"
                       for kind, data in rows)
    path.write_bytes(payload + tail)
    return path


def meta(sid="sample", source="cli"):
    return ("session_meta", {"id": sid, "cwd": "/fictional/project", "source": source})


def message(text, role="user"):
    return ("response_item", {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]})


def test_guardian_and_heldout_sessions_never_become_preference_data(tmp_path):
    p = rollout(tmp_path / "guardian.jsonl", [meta(source={"subagent": {"other": "guardian"}}), message("说人话")])
    assert parse_rollout(p).skipped_reason == "non_user_session"
    p = rollout(tmp_path / "heldout.jsonl", [meta("heldout"), message("说人话")])
    assert parse_rollout(p, exclude_sessions={"heldout"}).events == []


def test_attachment_instructions_and_quotes_do_not_become_direct_feedback():
    assert direct_user_text("# AGENTS.md instructions\n<INSTRUCTIONS>说人话</INSTRUCTIONS>") == ""
    assert direct_user_text("# Files pasted\n看不懂\n## My request:\n请导入。") == "请导入。"
    assert direct_user_text("> 看不懂\n```text\n说人话\n```\n请继续") == "请继续"


def test_canonical_messages_are_not_counted_twice_and_models_follow_turn(tmp_path):
    p = rollout(tmp_path / "a.jsonl", [meta(), ("event_msg", {"type": "task_started", "turn_id": "t1"}),
                ("event_msg", {"type": "user_message", "message": "请说人话"}), message("请说人话"),
                ("turn_context", {"turn_id": "t1", "model": "test-model"})])
    events = parse_rollout(p).events
    users = [e for e in events if e.kind == "user_message"]
    assert len(users) == 1
    assert users[0].model == "test-model"


def test_incomplete_tail_preserves_valid_prefix_and_source_file(tmp_path):
    p = rollout(tmp_path / "a.jsonl", [meta(), message("请继续")], b'{"type":"response_item"')
    original = p.read_bytes()
    result = parse_rollout(p)
    assert len(result.events) == 1
    assert result.warnings == [{"line": 3, "code": "incomplete_tail"}]
    assert p.read_bytes() == original


def test_repeated_import_is_idempotent_and_evaluation_does_not_update_profile(tmp_path):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    before = store.counts()
    second = import_codex(store, home)
    assert second.unchanged == 3
    assert store.counts() == before
    with TestClient(create_app(store.path)) as client:
        response = client.post("/v1/evaluation", json={"text": "看不懂，需要说人话", "scene": "profile"})
    assert response.status_code == 200
    assert store.counts() == before


def test_model_filter_keeps_only_matching_events(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, demo_home(tmp_path / "codex"))
    assert analyze(store, model="not-present")["counts"]["sessions"] == 0
    assert analyze(store, model="demo-model")["counts"]["user_messages"] == 3


def test_not_understanding_is_not_a_claim_of_not_understanding():
    event = Event("e", "s", 1, "user_message", None, text="不是看不懂，请直接继续实现。")
    assert all(s.category != "correction" for s in signals([event]))


def test_interval_union_matches_independent_discrete_oracle():
    intervals = [(0, 9), (1, 2), (3, 4), (8, 12), (20, 22), (0, 9)]
    oracle = len({t for start, end in intervals for t in range(start, end)})
    assert union_duration(intervals) == oracle
    assert union_duration(list(reversed(intervals))) == oracle
    assert union_duration([]) == 0
    assert wilson_interval(0, 0) is None
    assert wilson_interval(5, 10) == [0.2366, 0.7634]


def test_readability_contrasts_and_required_facts():
    assert benchmark()["correct"] == benchmark()["cases"]
    assert not evaluate_text("很好。", "profile")["checks_passed"]
    assert not evaluate_text("报告很简短。", "developer_report", ["验证失败"])["checks_passed"]
    assert evaluate_text("这是一条技术参考：使用 KL 散度比较两个分布。", "math_explanation")["checks_passed"]


def test_no_evidence_means_no_skill_recommendation(tmp_path):
    assert recommend(analyze(Store(tmp_path / "empty.sqlite"))) == []


def test_api_reports_and_error_boundaries(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, demo_home(tmp_path / "codex"))
    with TestClient(create_app(store.path)) as client:
        assert client.get("/health").json()["counts"]["sessions"] == 3
        report = client.get("/v1/analysis").json()
        assert "明确要求" in report["summary"]
        assert report["recommendations"][0]["effect_status"] == "unmeasured"
        assert client.get("/v1/analysis?before=yesterday").status_code == 422
        assert client.get("/v1/sessions/missing/events").status_code == 404
        assert client.get("/v1/sessions?limit=0").status_code == 422
        assert client.post("/v1/evaluation", json={"text": "x", "scene": "unknown"}).status_code == 422


def test_common_secret_patterns_are_redacted():
    text = "sk-abcdefghijklmnopqrstuvwxyz123456 bearer ABCDEFGHIJKLMNOP123456 password=example_secret"
    redacted = redact(text)
    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "ABCDEFGHIJKLMNOP" not in redacted
    assert "example_secret" not in redacted
