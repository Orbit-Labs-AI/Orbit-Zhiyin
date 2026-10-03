import copy

import pytest

from tandem_backend.analytics.common import semantic_messages
from tandem_backend.analytics.task import (
    extract_task_features,
    segment_tasks,
    summarize_task_distribution,
)
from tandem_backend.analytics.task.features import request_clauses


def test_labels_goals_artifacts_and_evidence(fixtures):
    s, e, _ = fixtures
    events = semantic_messages([e("请修复 Python 代码，并编写报告 report.md")], [s()])
    result = extract_task_features(events)
    assert result["domain"] == ["software", "writing"]
    assert result["task_type"] == ["create", "debug"]
    assert {a["name"] for a in result["expected_artifacts"]} == {"报告", "report.md"}
    assert result["task_goal"] == "请修复 Python 代码"
    assert result["label_evidence"]["task_type"]["debug"][0]["event_uid"] == "e"
    assert result["semantic_status"] == "candidate"


def test_negative_actions_quotes_reading_are_not_deliverables(fixtures):
    s, e, _ = fixtures
    assert request_clauses("不要修复代码，请总结文档") == ["请总结文档"]
    result = extract_task_features(semantic_messages([e("不要修复代码，请总结文档")], [s()]))
    assert result["task_type"] == ["summarize"] and result["domain"] == ["writing"]
    assert result["expected_artifacts"] is None
    result = extract_task_features(semantic_messages([e("请解释 README.md")], [s()]))
    assert result["expected_artifacts"] is None
    assert not segment_tasks([e('> 请修复代码')], [s()])["records"]


def test_vague_request_has_unknown_features(fixtures):
    s, e, _ = fixtures
    record = segment_tasks([e("帮我处理一下")], [s()])["records"][0]
    assert record["domain"] is record["task_type"] is record["task_goal"] is record["expected_artifacts"] is None
    assert record["task_boundaries"][0]["end"] is None


def test_multiple_tasks_goal_revision_and_open_end(fixtures):
    s, e, _ = fixtures
    es = [e("调研后端接口", "a", 0), e("现在实现后端接口", "b", 1),
          e("目标改为编写脚本", "c", 2), e("新任务：解释数学定理", "d", 3)]
    result = segment_tasks(es, [s()])
    assert len(result["records"]) == 3
    first, second, third = result["records"]
    assert first["task_boundaries"][0]["end"]["event_uid"] == "b"
    assert first["task_boundaries"][0]["end_inclusive"] is False
    assert len(second["task_goal_history"]) == 2 and second["task_goal"] == "目标改为编写脚本"
    assert third["task_boundaries"][0]["end"] is None
    assert result["task_by_event"]["b"] == result["task_by_event"]["c"]


def test_only_user_close_ends_a_task_not_turn_or_assistant(fixtures):
    s, e, _ = fixtures
    es = [e("请编写报告", "a", 0), {**e("任务完成", "b", 1), "kind": "message.assistant", "actor": "assistant"}]
    assert segment_tasks(es, [s()])["records"][0]["task_boundaries"][0]["end"] is None
    es.append(e("任务完成", "c", 2))
    record = segment_tasks(es, [s()])["records"][0]
    assert record["task_boundaries"][0]["end_reason"] == "user_explicit_close"
    assert "task_success" not in record


def test_cross_session_requires_explicit_identity(fixtures):
    s, e, _ = fixtures
    es = [e("请编写报告", "a", sid="a", task_id="same"), e("继续编写报告", "b", sid="b", task_id="same")]
    sessions = [s("a"), s("b")]
    assert len(segment_tasks(es, sessions)["records"]) == 2
    for event in es:
        event["attrs"]["task_id_source"] = "human_confirmed"
    result = segment_tasks(es, sessions)
    assert len(result["records"]) == 1 and result["records"][0]["related_session_ids"] == ["a", "b"]
    assert summarize_task_distribution(result["records"] * 2)["task_count"] == 1
    sessions[1]["project_id"] = "different"
    assert len(segment_tasks(es, sessions)["records"]) == 2


def test_distribution_unknown_multilabel_and_no_input_mutation(fixtures):
    s, e, _ = fixtures
    es = [e("请修复代码，并编写报告", "a", 0), e("新任务：帮我处理一下", "b", 1)]
    original = copy.deepcopy(es)
    tasks = segment_tasks(es, [s()])["records"]
    summary = summarize_task_distribution(tasks)
    assert summary["task_count"] == 2
    assert summary["task_type"]["effective_n"] == 1 and summary["task_type"]["unknown_n"] == 1
    assert summary["task_type"]["rates"] == {"create": 1, "debug": 1}
    assert es == original
    assert summarize_task_distribution(None)["task_count"] is None
    assert summarize_task_distribution([])["domain"]["rates"] is None


def test_cross_session_goal_order_uses_time_and_preserves_native_seq(fixtures):
    from tandem_backend.analytics.common import chronological_messages
    s, e, _ = fixtures
    initial = e("请编写报告", "first", 0, sid="z", ts=10, task_id="t", task_id_source="native")
    revision = e("目标改为编写脚本", "later", 0, sid="a", ts=20, task_id="t", task_id_source="native")
    record = segment_tasks([revision, initial], [s("a"), s("z")])["records"][0]
    assert [g["goal"] for g in record["task_goal_history"]] == ["请编写报告", "目标改为编写脚本"]
    assert record["task_goal"] == "目标改为编写脚本"
    skewed = [e("a", "second", 1, ts=0), e("b", "first", 0, ts=200)]
    assert [m["event_uid"] for m in chronological_messages(skewed)] == ["first", "second"]


@pytest.mark.parametrize("text,kind", [
    ("请给初学者写一份程序教程", "create"),
    ("帮我为同事写一封邮件", "create"),
    ("请用两段话介绍项目报告的结构", "explain"),
    ("Please describe the report structure", "explain"),
])
def test_named_recipient_and_introductory_requests_keep_goal_evidence(text, kind, fixtures):
    s, e, _ = fixtures
    record = segment_tasks([e(text)], [s()])["records"][0]
    assert record["task_goal"] == text and record["task_type"] == [kind]
    assert record["semantic_status"] == "candidate"
    assert record["label_evidence"]["task_type"][kind][0]["event_uid"] == "e"


@pytest.mark.parametrize("text", [
    "不要给初学者写教程", "历史记录：请给初学者写教程", "他刚刚介绍了项目结构",
    '“请给初学者写教程”', "请用表格", "请把回答简短一点", "这封介绍信", "默认回答简短一点",
])
def test_goal_coverage_does_not_turn_quoted_status_or_format_controls_into_goals(text, fixtures):
    s, e, _ = fixtures
    result = extract_task_features(semantic_messages([e(text)], [s()]))
    assert result["task_goal"] is None


def test_analyzing_a_writing_request_does_not_become_a_writing_action(fixtures):
    s, e, _ = fixtures
    result = extract_task_features(semantic_messages([e("请分析给初学者写教程的需求")], [s()]))
    assert result["task_type"] == ["analyze"]


def test_english_sentences_split_on_full_stop_without_breaking_files_or_versions():
    from tandem_backend.analytics.common import clauses
    from tandem_backend.analytics.task.features import request_clauses

    assert request_clauses("Don't touch the config. Please add tests for the parser") == [
        "Please add tests for the parser"]
    assert clauses("Update parser.py to v1.2. Then run it") == ["Update parser.py to v1.2", "Then run it"]
    assert clauses("pi is 3.14... ok") == ["pi is 3.14", "ok"]
