"""A discussion topic must not supply the profile half of a recommendation."""

import pytest

from orbit_backend.analysis import analyze
from orbit_backend.feedback import explicit_language, signals
from orbit_backend.models import Event
from orbit_backend.pipeline_eval import _write_case
from orbit_backend.recommend import recommend
from orbit_backend.store import Store, import_codex


@pytest.mark.parametrize("text", [
    "介绍可运行程序的定义。", "分析可运行性的含义。",
    "请解释跑通的意思。", "可运行程序是什么？",
])
def test_execution_topics_do_not_supply_a_workflow_preference(text):
    observed = signals([Event("u", "s", 1, "user_message", None, text=text)])
    assert not any(s.dimension == "actionability" for s in observed)


@pytest.mark.parametrize("text", [
    "请做可运行原型。", "先做最小可运行版本。", "请实现这个函数，保持可运行。",
    "先解释方案再实现。",
])
def test_actual_execution_requests_keep_their_preference(text):
    observed = signals([Event("u", "s", 1, "user_message", None, text=text)])
    assert any(s.dimension == "actionability" for s in observed)


@pytest.mark.parametrize("text", [
    "英文版本是什么意思？请简洁解释。", "比较中文和英文版本，简洁说明区别。",
    "介绍英文报告的定义。", "请解释如何写英文报告。",
])
def test_language_subject_is_not_a_deliverable_language(text):
    assert explicit_language(text) is None


@pytest.mark.parametrize("text", [
    "给我英文版本。", "请写英文报告。", "请用英文解释英文版本是什么意思。",
])
def test_actual_english_output_request_survives(text):
    assert explicit_language(text) == "en"


@pytest.mark.parametrize("text", ["介绍可运行程序的定义。", "分析可运行性的含义。"])
def test_descriptive_topic_cannot_enable_debugging_recommendation(tmp_path, text):
    home = tmp_path / "codex"
    _write_case(home, "topic", [{"kind": "user", "text": text}] + [
        {"kind": "tool", "tool": "exec_command", "arguments": '{"cmd":"check"}',
         "output": '{"exit_code":1}'} for _ in range(3)])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    data = analyze(store)
    assert data["bottlenecks"][0]["type"] == "repeated_tool_failure"
    assert data["profile"]["workflow"] == []
    assert recommend(data) == []


@pytest.mark.parametrize("text", [
    "英文版本是什么意思？请简洁解释。", "比较中文和英文版本，简洁说明区别。",
])
def test_topic_discussion_preserves_chinese_recommendation(tmp_path, text):
    home = tmp_path / "codex"
    _write_case(home, "language", [{"kind": "user", "text": text},
                                    {"kind": "assistant", "text": "这是一段中文说明。" * 400}])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    data = analyze(store)
    assert data["bottlenecks"][0]["language"] == "zh"
    assert {r["resource_id"] for r in recommend(data)} == {"humanizer-zh"}
