"""Bind literal terms, numeric caps and readers to the user's actual instruction."""

import pytest

from tandem_backend.analysis import analyze
from tandem_backend.feedback import reader_context, scene_of, signals, task_contexts
from tandem_backend.models import Event
from tandem_backend.pipeline_eval import _write_case
from tandem_backend.recommend import recommend
from tandem_backend.store import Store, import_codex


def observed(text):
    return signals([Event("u", "s", 1, "user_message", None, text=text)])


@pytest.mark.parametrize("text", ["回答不超过100字。", "回复最多 100 字。", "摘要限制为100字符。", "回答不要超过100字。"])
def test_standalone_numeric_bound_reaches_bottleneck_and_recommendation(tmp_path, text):
    home = tmp_path / "codex"
    _write_case(home, "bound", [{"kind": "user", "text": text},
                                {"kind": "assistant", "text": "说明" * 80}])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    data = analyze(store)
    assert data["bottlenecks"][0]["measurement"]["threshold"] == 100
    assert recommend(data)[0]["resource_id"] == "humanizer-zh"


def test_declarations_and_descriptive_governors_do_not_become_execution_preferences():
    for text in ("实现已经完成，下面是运行日志。", "测试已经通过，下面是报告。", "请确认实现是否已经完成。", "请查看测试日志。"):
        assert not any(s.dimension in ("actionability", "verification") for s in observed(text))
    assert any(s.dimension == "verification" for s in observed("分析原因并运行测试。"))
    assert any(s.dimension == "actionability" for s in observed("先解释方案再实现。"))


def test_quoted_style_terms_survive_but_quoted_examples_do_not():
    assert {s.dimension for s in observed("回答请保持“简洁直接”。")} >= {"clarity", "brevity"}
    assert any(s.dimension == "clarity" for s in observed("请用“通俗易懂”的语言解释。"))
    assert any(s.dimension == "clarity" for s in observed("我希望回答“通俗易懂”。"))
    assert not any(s.dimension in ("clarity", "brevity") for s in observed("请解释“通俗易懂”这个词。"))
    assert not any(s.dimension in ("clarity", "brevity") for s in observed("请用“回答太长”作为翻译例子。"))
    assert not any(s.dimension == "brevity" for s in observed("请用 `精简版.md` 生成目录。"))


def test_negated_readers_are_not_retained_or_reintroduced_by_followup():
    assert {r["id"] for r in reader_context("不要给初学者看，请给开发者解释。", "u")} == {"developer"}
    assert {r["id"] for r in reader_context("别面向大一学生，写给普通读者。", "u")} == {"general_reader"}
    contexts = task_contexts([Event("u", "s", 1, "user_message", None, text="给大一学生解释这个定理。"),
                              Event("v", "s", 2, "user_message", None, text="请再解释，别面向大一学生。")])
    assert contexts["v"]["readers"] == []


def test_implementation_of_math_function_is_coding_but_proof_remains_math():
    assert scene_of("请实现矩阵乘法函数，完成后运行测试。") == "coding"
    assert scene_of("给大一学生直观解释矩阵乘法的数学证明。") == "math_explanation"


def test_new_question_marker_does_not_inherit_earlier_coding_context():
    contexts = task_contexts([Event("u", "s", 1, "user_message", None, text="给开发者说明代码接口，请用英文。"),
                              Event("v", "s", 2, "user_message", None, text="再问一个新问题：请简洁介绍这个餐厅。")])
    assert contexts["v"]["scene"] == "conversation"
    assert contexts["v"]["language"] == "zh" and contexts["v"]["readers"] == []
    assert contexts["v"]["task_id"] == "v"
