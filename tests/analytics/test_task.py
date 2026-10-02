import copy

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
