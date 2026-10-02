from tandem_backend.bottlenecks import diagnose
from tandem_backend.feedback import scene_of, signals
from tandem_backend.models import Event


def dimensions(text):
    return {s.dimension for s in signals([Event("e", "s", 1, "user_message", None, text=text)])}


def test_descriptive_implementation_questions_are_not_execution_requirements():
    for text in ("这个函数是怎么实现的？", "分析现有实现的复杂度。", "请解释哈希表的实现原理。"):
        assert "actionability" not in dimensions(text)
    assert "actionability" in dimensions("请实现这个函数，保持可运行。")


def test_descriptive_test_questions_are_not_verification_requirements():
    for text in ("这个测试为什么失败？请解释原因。", "分析现有测试的覆盖范围。", "请介绍测试驱动开发的概念。"):
        assert "verification" not in dimensions(text)
    assert "verification" in dimensions("完成后请运行测试。")
    assert "verification" in dimensions("为函数编写单元测试。")


def test_backend_subject_does_not_make_a_code_question_a_report():
    assert scene_of("请解释这个后端函数，语言易读。") == "coding"
    assert scene_of("请实现后端函数，再测试。") == "coding"
    assert scene_of("请写后端报告，解释接口变化。") == "developer_report"


def test_code_revision_clause_does_not_relabel_unrelated_explanation_request():
    events = [Event("a", "s", 1, "assistant_message", None, text="上一份回复。"),
              Event("u", "s", 2, "user_message", None, text="请简洁说明新接口；上一版代码继续修改。")]
    observed = signals(events)
    assert next(s for s in observed if s.dimension == "brevity").category == "request"
    findings, _ = diagnose(events, observed)
    assert not any(f["type"] == "explanation_revision" for f in findings)
