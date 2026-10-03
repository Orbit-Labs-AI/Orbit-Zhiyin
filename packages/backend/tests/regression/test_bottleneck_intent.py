"""Intent and original task context must survive the entire recommendation path."""

import pytest

from orbit_backend.analysis import analyze
from orbit_backend.bottlenecks import _artifact_delivery
from orbit_backend.pipeline_eval import _write_case
from orbit_backend.recommend import recommend
from orbit_backend.store import Store, import_codex


def pipeline(tmp_path, request, response=None):
    home = tmp_path / "codex"
    steps = [{"kind": "user", "text": request}]
    if response is not None:
        steps.append({"kind": "assistant", "text": response})
    else:
        steps.extend({"kind": "tool", "tool": "exec_command", "arguments": '{"cmd":"run-check"}',
                      "output": '{"exit_code":1}'} for _ in range(3))
    _write_case(home, "intent", steps)
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    return store, analyze(store)


@pytest.mark.parametrize("request_text,expected,expected_recommendation", [
    ("请修复解析器，完成后运行三次预期失败测试。", False, False),
    ("请排查解析器，并验证失败路径。", False, False),
    ("请解决问题，再运行三次负例测试。", False, False),
    ("请修复解析器，这三次测试不应该失败。", True, False),
    ("不要运行预期失败测试，请运行正常检查。", True, False),
    ("预期失败测试已经完成；现在请运行正常测试。", True, True),
    ("负例测试已通过；现在请运行测试。", True, True),
    ("之前的预期失败测试记录在这里；现在请运行正常测试。", True, True),
    ("请运行正常测试，然后运行三次预期失败测试。", False, False),
])
def test_expected_negative_tests_do_not_become_debugging_recommendations(tmp_path, request_text, expected, expected_recommendation):
    _, data = pipeline(tmp_path, request_text)
    assert bool(data["bottlenecks"]) is expected
    # A candidate alone cannot bypass the profile join. Explicit current test
    # execution does supply that requirement; descriptive repair clauses do not.
    assert bool(recommend(data)) is expected_recommendation


def test_matrix_implementation_failures_join_coding_profile_and_recommendation(tmp_path):
    _, data = pipeline(tmp_path, "请实现矩阵乘法函数，完成后运行测试。")
    incident = data["bottlenecks"][0]
    assert incident["scene"] == "coding"
    assert incident["task_id"] == incident["evidence_ids"][0]
    assert recommend(data)[0]["resource_id"] == "systematic-debugging"


def test_completed_negative_test_does_not_mask_a_new_normal_test_failure(tmp_path):
    _, data = pipeline(tmp_path, "预期失败测试已经完成；现在请运行正常测试。")
    assert data["bottlenecks"][0]["type"] == "repeated_tool_failure"
    assert recommend(data)[0]["resource_id"] == "systematic-debugging"


@pytest.mark.parametrize("request_text,scene", [
    ("请给开发者写英文项目报告，完成后运行检查。", "developer_report"),
    ("请写这份文档，完成后运行检查。", "document"),
])
def test_failed_tools_keep_the_scene_and_its_evidence_when_filtered(tmp_path, request_text, scene):
    store, data = pipeline(tmp_path, request_text)
    incident = data["bottlenecks"][0]
    assert incident["scene"] == scene
    selected = analyze(store, scene=scene)
    assert selected["bottlenecks"][0]["id"] == incident["id"]
    assert analyze(store, scene="coding")["bottlenecks"] == []
    assert recommend(selected) == []  # The pinned debugging resource only supports coding.
    if scene == "developer_report":
        assert incident["language"] == "en"
        assert {r["id"] for r in incident["readers"]} == {"developer"}


@pytest.mark.parametrize("prefix", ["无法写入", "未保存", "计划保存", "准备写入", "将保存", "已完成代码，接下来保存"])
def test_unconfirmed_file_action_is_not_reported_as_delivery(tmp_path, prefix):
    reply = prefix + " [说明.md](/fictional/说明.md)。"
    assert not _artifact_delivery(reply)
    _, data = pipeline(tmp_path, "请写一份通俗易懂的文档。", reply)
    assert not any(g["code"] == "artifact_body_missing" for g in data["data_gaps"])


def test_completed_delivery_is_still_distinct_from_observing_the_document_body(tmp_path):
    reply = "已完成并保存到 [说明.md](/fictional/说明.md)。"
    _, data = pipeline(tmp_path, "请写一份通俗易懂的文档。", reply)
    assert data["data_gaps"][0]["code"] == "artifact_body_missing"
    assert _artifact_delivery("[说明.md](/fictional/说明.md) 已保存。")
    assert _artifact_delivery("已将 [说明.md](/fictional/说明.md) 重写为英文稿。")
    assert _artifact_delivery("已在 [说明.md](/fictional/说明.md) 中补充实例。")
    assert not _artifact_delivery("已将 [说明.md](/fictional/说明.md) 列入计划，准备重写。")
    assert not _artifact_delivery("请确认是否已将 [说明.md](/fictional/说明.md) 重写为英文稿。")
