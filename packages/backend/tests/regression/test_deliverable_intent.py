"""Classify requested deliverables, never manufacture verification from background."""

import pytest

from orbit_backend.evaluation.pipeline import _write_case
from orbit_backend.models import Event
from orbit_backend.profiling.analysis import analyze
from orbit_backend.profiling.feedback import scene_of, signals
from orbit_backend.recommend import recommend
from orbit_backend.store import Store, import_codex


def test_report_intent_precedes_math_subject_while_math_and_implementation_remain_distinct(tmp_path):
    text = "请写一份矩阵乘法项目进度报告，简洁说明。"
    assert scene_of(text) == "developer_report"
    assert scene_of("请写项目报告，说明如何运行后端。") == "developer_report"
    assert scene_of("请实现后端接口，并写项目报告。") == "coding"
    assert scene_of("给大一学生解释矩阵乘法的数学证明。") == "math_explanation"
    home = tmp_path / "codex"
    _write_case(home, "report", [{"kind": "user", "text": text},
                                  {"kind": "assistant", "text": "报告中不必要的重复说明。" * 350}])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    selected = analyze(store, scene="developer_report")
    assert selected["bottlenecks"][0]["type"] == "long_response"
    assert recommend(selected)[0]["scene"] == "developer_report"
    assert analyze(store, scene="math_explanation")["counts"]["user_messages"] == 0


@pytest.mark.parametrize("text", ["测试工具是 pytest。", "测试日志如下。", "测试用例是一个负例。", "测试计划需要讨论。"])
def test_clause_initial_test_background_does_not_create_a_debugging_profile(tmp_path, text):
    home = tmp_path / "codex"
    _write_case(home, "background", [{"kind": "user", "text": text}] + [
        {"kind": "tool", "tool": "exec_command", "arguments": '{"cmd":"test-run"}', "output": '{"exit_code":1}'} for _ in range(3)])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    data = analyze(store)
    assert not any(p["dimension"] == "verification" for p in data["preferences"])
    assert recommend(data) == []


def test_real_verification_commands_still_support_profile_evidence():
    for text in ("测试这段代码。", "请运行测试用例。", "完成后运行测试。", "检查代码运行结果。", "先做原型，再测试。"):
        assert any(s.dimension == "verification" for s in signals([Event("u", "s", 1, "user_message", None, text=text)]))
