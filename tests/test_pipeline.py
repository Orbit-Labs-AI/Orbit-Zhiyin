import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tandem_backend.analysis import analyze, union_duration, wilson_interval
from tandem_backend.api import create_app
from tandem_backend.cli import demo_home
from tandem_backend.evaluation import benchmark, evaluate_text
from tandem_backend.feedback import language_of, signals
from tandem_backend.importers.codex import _status, parse_rollout
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


@pytest.mark.parametrize("marker", ["guardian_review", "subagent"])
def test_rollout_source_marker_excludes_automatic_prompts_without_metadata_db(tmp_path, marker):
    kind, data = meta()
    p = rollout(tmp_path / "automatic.jsonl", [(kind, {**data, "thread_source": marker}), message("请简洁解释")])
    result = parse_rollout(p, metadata={"sample": {"thread_source": "user"}})
    assert result.skipped_reason == "non_user_session"
    assert result.events == []


@pytest.mark.parametrize("output,status", [
    ('{"exit_code":1}', "failed"),
    ('{"exit_code":0}', "success"),
    ('{"exit_code":true}', None),
    ('{"isError":true}', "failed"),
    ('Chunk ID: test\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\n{"exit_code":1}', "success"),
    ('Chunk ID: test\nWall time: 0.1 seconds\nProcess exited with code 2\nFinal output:\nfixture succeeded', "failed"),
    ('Chunk ID: test\nWall time: 0.1 seconds\nOutput:\nProcess exited with code 1', None),
    ('stdout fixture: {"exit_code":1}\nProcess exited with code 1', None),
])
def test_tool_status_uses_transport_metadata_and_ignores_stdout(output, status):
    assert _status(output) == status


def test_successful_fixture_reads_do_not_create_repair_recommendations(tmp_path):
    rows = [meta(), message("先实现再测试，交付可运行版本。")]
    for i in range(3):
        rows.extend([
            ("response_item", {"type": "function_call", "name": "exec_command", "call_id": str(i), "arguments": '{"cmd":"cat fixture.json"}'}),
            ("response_item", {"type": "function_call_output", "call_id": str(i), "output": 'Chunk ID: test\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\n{"exit_code":1}'}),
        ])
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    rollout(home / "sessions" / "fixture.jsonl", rows)
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    data = analyze(store)
    assert data["counts"]["explicit_tool_failures"] == 0
    assert data["bottlenecks"] == []
    assert recommend(data) == []


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


def test_fixed_snapshot_drops_unclocked_events(tmp_path):
    p = rollout(tmp_path / "clock.jsonl", [meta(), message("请讲清楚")])
    with p.open("a") as file:
        file.write(json.dumps({"type": "response_item", "payload": message("没看懂")[1]}) + "\n")
    result = parse_rollout(p, before="2026-02-01T00:00:00Z")
    assert [e.text for e in result.events] == ["请讲清楚"]
    assert result.warnings[-1]["code"] == "unclocked_at_snapshot"


def test_language_mentions_are_not_language_instructions():
    assert language_of("不要用英文，请用中文解释。") == "zh"
    assert language_of("请用中文讲清楚这个 English API。") == "zh"
    assert language_of("请介绍 English API 的用法。") == "zh"
    assert language_of("请提供英文版本。") == "en"
    assert language_of("翻译成英语，保持事实。") == "en"
    assert language_of("不要翻译成英文，保留中文原文。") == "zh"
    assert language_of("别生成英语版本，请用中文。") == "zh"
    assert language_of("不要输出中文，请提供英文版本。") == "en"


def test_later_correction_in_same_dimension_is_not_hidden_by_first_request():
    event = Event("e", "s", 1, "user_message", None, text="请简洁些；你这次还是太长，请再精简。")
    result = [s for s in signals([event]) if s.dimension == "brevity"]
    assert len(result) == 1
    assert result[0].category == "correction"
    assert "你这次还是太长" in result[0].quote


def test_source_field_is_not_a_grounding_preference():
    event = Event("e", "s", 1, "user_message", None, text="请把 source 字段重命名为来源。")
    assert not any(s.dimension == "grounding" for s in signals([event]))
    event.text = "写报告时请注明来源，不要想当然。"
    assert any(s.dimension == "grounding" for s in signals([event]))


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


def test_tightening_import_policy_removes_old_evidence(tmp_path):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    import_codex(store, home, exclude_sessions={"demo-0"})
    assert {s["id"] for s in store.sessions()} == {"demo-1", "demo-2"}
    assert not store.events(session_id="demo-0")
    import_codex(store, home, before="2000-01-01T00:00:00Z")
    assert store.counts()["sessions"] == 0


def test_acknowledgement_does_not_override_clause_specific_correction():
    event = Event("e", "s", 1, "user_message", None, text="很好，但还是太长，请精简；没看懂，请先给方案，然后直接实现。")
    observed = {s.dimension: s.category for s in signals([event])}
    assert observed["brevity"] == "correction"
    assert observed["clarity"] == "correction"
    assert observed["planning"] == "request"
    assert observed["actionability"] == "request"


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


def test_code_and_chart_readability_do_not_become_writing_preferences():
    for text in ("代码保持简洁，MPI 教程单独成文。", "函数写得简单易读一点。", "图表坐标太长了，改成科学计数法。",
                 "我已经修改完相关c语言代码，使之简洁且仅包含必需内容。", "每小节精简至8道题，去掉重复题。",
                 "讲义中简短公式的换行太多，调整居中排版。"):
        event = Event("e", "s", 1, "user_message", None, text=text)
        assert not any(s.dimension in ("clarity", "brevity") for s in signals([event]))
    event = Event("e", "s", 1, "user_message", None, text="请解释这个函数，语言简洁易读。")
    assert {s.dimension for s in signals([event])} >= {"clarity", "brevity"}


def test_recommendation_requires_profile_and_bottleneck_and_traceable_evidence(tmp_path):
    store = Store(tmp_path / "demo.sqlite")
    import_codex(store, demo_home(tmp_path / "codex"))
    analysis = analyze(store)
    recommendations = recommend(analysis)
    assert {r["resource_id"] for r in recommendations} == {"humanizer-zh", "systematic-debugging"}
    ids = {e.id for e in store.events()}
    for rec in recommendations:
        assert rec["profile_evidence_ids"] and rec["bottleneck_evidence_ids"]
        assert set(rec["evidence_ids"]) <= ids
        assert rec["match_basis"] == "profile_and_bottleneck"
    assert recommend({**analysis, "bottlenecks": []}) == []
    assert recommend({**analysis, "preferences": []}) == []
    assert recommend(analysis, scene="unrelated-scene") == []


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
