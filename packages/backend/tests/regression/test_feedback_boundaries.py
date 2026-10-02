"""Negating an unwanted outcome can impose a positive requirement."""

from tandem_backend.analysis import analyze
from tandem_backend.feedback import language_of, same_artifact_reference, signals, task_contexts
from tandem_backend.models import Event
from tandem_backend.pipeline_eval import _write_case
from tandem_backend.recommend import recommend
from tandem_backend.store import Store, import_codex


def test_negative_form_brevity_is_kept_without_claiming_a_past_failure(tmp_path):
    home = tmp_path / "codex"
    _write_case(home, "negative_brevity", [
        {"kind": "user", "text": "写项目报告时，说明不必太长。"},
        {"kind": "assistant", "text": "不必要的重复内容。" * 350},
    ])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    data = analyze(store)
    assert {p["dimension"] for p in data["preferences"]} == {"brevity"}
    assert {b["type"] for b in data["bottlenecks"]} == {"long_response"}
    assert recommend(data)[0]["resource_id"] == "humanizer-zh"
    for text in ("回答不要太长。", "说明无需太长。", "回答别太长。", "你这次的报告不要太长。"):
        observed = signals([Event("e", "s", 1, "user_message", None, text=text)])
        assert [s.category for s in observed if s.dimension == "brevity"] == ["request"]
    for text in ("不是太长，请继续。", "不用简短回答，要完整解释。"):
        assert not any(s.dimension == "brevity" for s in signals([Event("e", "s", 1, "user_message", None, text=text)]))


def test_all_supported_negation_forms_remove_the_forbidden_language():
    for prefix in ("无需", "不必", "不需要", "别再", "不用"):
        assert language_of(prefix + "使用英文，请保留中文原文。") == "zh"
    events = [Event("first", "s", 1, "user_message", None, text="写一份英文教程，语言通俗。"),
              Event("followup", "s", 2, "user_message", None, text="请改，不必再使用英文，说明简短些。")]
    assert task_contexts(events)["followup"]["language"] == "zh"


def test_new_math_topic_cannot_attach_to_old_delivery_in_same_session(tmp_path):
    for old in ("介绍今天的天气。", "请写一份代码教程。", "请解释这个数学定理。"):
        home = tmp_path / str(len(old)) / "codex"
        _write_case(home, "topic_switch", [
            {"kind": "user", "text": old},
            {"kind": "assistant", "text": "上一任务已交付。"},
            {"kind": "user", "text": "新的数学定理我没看懂，请直观解释。"},
        ])
        store = Store(home.parent / "evaluation.sqlite")
        import_codex(store, home)
        data = analyze(store)
        assert data["bottlenecks"] == []
        assert recommend(data) == []


def test_short_refinement_and_explicit_long_feedback_keep_the_same_task():
    events = [Event("first", "s", 1, "user_message", None, text="请写这份讲义。"),
              Event("next", "s", 2, "user_message", None, text="数学证明没看懂，再解释一下。"),
              Event("long", "s", 3, "user_message", None,
                    text="我来评价你这次的结果，听完之后修改回复：" + "先说明条件。" * 40 + "语言更加朴素。")]
    contexts = task_contexts(events)
    assert {contexts[e.id]["task_id"] for e in events} == {"first"}
    assert contexts["next"]["scene"] == "math_explanation"


def test_explicit_artifact_feedback_survives_a_scene_label_change():
    events = [Event("u", "s", 1, "user_message", None, text="请完成余下的内容。"),
              Event("a", "s", 2, "assistant_message", None,
                    text="已保存 [作业说明.md](/fictional/course/week2/作业说明.md)。"),
              Event("revision", "s", 3, "user_message", None,
                    text="你这次的 [作业说明.md](week2/作业说明.md) 数学证明没看懂，请直观解释。")]
    contexts = task_contexts(events)
    assert contexts["u"]["task_id"] == contexts["revision"]["task_id"]
    assert contexts["revision"]["scene"] == "math_explanation"
    assert not same_artifact_reference("[说明](week3/README.md)", "[说明](/fictional/week2/README.md)")


def test_callback_answers_extend_context_without_learning_the_question():
    events = [Event("u", "s", 1, "user_message", None, text="给初学者写一份英文教程。"),
              Event("answer", "s", 2, "user_message", None, text="选择第二项。", details={"input_format": "question_reply"})]
    contexts = task_contexts(events)
    assert contexts["answer"]["language"] == "en"
    assert contexts["answer"]["task_id"] == "u"
