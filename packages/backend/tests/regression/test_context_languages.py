"""A Chinese follow-up must not turn an English deliverable into Chinese."""

from orbit_backend.evaluation.pipeline import _write_case
from orbit_backend.models import Event
from orbit_backend.profiling.analysis import analyze
from orbit_backend.profiling.feedback import explicit_language, signals, task_contexts
from orbit_backend.recommend import recommend
from orbit_backend.store import Store, import_codex


def test_same_scene_followup_inherits_readers_and_output_language():
    events = [Event("request", "s", 1, "user_message", None,
                    text="给初学者写一份英文教程，语言通俗。"),
              Event("followup", "s", 2, "user_message", None,
                    text="请再把教程简短些。"),
              Event("switch", "s", 3, "user_message", None,
                    text="请改成中文教程，保持易读。"),
              Event("new_task", "s", 4, "user_message", None,
                    text="给开发者写项目报告，说明结果。")]
    contexts = task_contexts(events)
    assert contexts["followup"]["language"] == "en"
    assert contexts["followup"]["language_basis"] == "explicit_request"
    assert contexts["followup"]["language_evidence_id"] == "request"
    assert contexts["followup"]["scene"] == "document"
    assert contexts["followup"]["readers"][0]["id"] == "beginner"
    assert contexts["switch"]["language"] == "zh"
    assert contexts["new_task"]["language"] == "zh"
    assert [r["id"] for r in contexts["new_task"]["readers"]] == ["developer"]
    assert {s.language for s in signals(events) if s.event_id == "followup"} == {"en"}


def test_topic_mentions_and_negated_instructions_are_not_language_choices():
    assert explicit_language("请介绍 English API。") is None
    assert explicit_language("别输出英语版本。") is None
    assert explicit_language("不要写一份英文教程。") is None
    assert explicit_language("不用中文，请提供英文教程。") == "en"
    assert explicit_language("把说明改为中文，英文单词保留。") == "zh"


def test_recommendation_uses_deliverable_language_from_context(tmp_path):
    home = tmp_path / "codex"
    _write_case(home, "english_followup", [
        {"kind": "user", "text": "请给初学者写一份英文教程，语言通俗。"},
        {"kind": "assistant", "text": "A clear example."},
        {"kind": "user", "text": "请再精简些。"},
        {"kind": "assistant", "text": "Excess detail. " * 240},
    ])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    data = analyze(store)
    recs = recommend(data)
    assert {r["resource_id"] for r in recs} == {"humanizer"}
    assert data["bottlenecks"][0]["language"] == "en"
    assert {r["id"] for r in recs[0]["readers"]} == {"beginner"}
    assert data["contexts"][0]["languages"] == {"en": 2}
    assert recs[0]["language_evidence_id"] in recs[0]["evidence_ids"]
    assert recommend(data, language="zh") == []


def test_new_task_does_not_inherit_previous_language_or_reader(tmp_path):
    contexts = task_contexts([
        Event("old", "s", 1, "user_message", None, text="给初学者写英文教程。"),
        Event("new", "s", 2, "user_message", None, text="现在说明后端接口怎么用，读者是开发者。"),
        Event("other_session", "other", 1, "user_message", None, text="请再简短些。"),
    ])
    assert contexts["new"]["scene"] == "coding"
    assert contexts["new"]["language"] == "zh"
    assert {r["id"] for r in contexts["new"]["readers"]} == {"developer"}
    assert contexts["other_session"]["readers"] == []
    assert contexts["other_session"]["language"] == "zh"
