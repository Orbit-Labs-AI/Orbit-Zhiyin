"""Human callback answers must be recoverable without importing the questions."""

import json

import pytest

from tandem_backend.analysis import analyze
from tandem_backend.feedback import signals
from tandem_backend.importers.codex import parse_rollout
from tandem_backend.models import Event
from tandem_backend.privacy import direct_user_text
from tandem_backend.store import Store, import_codex


def callback(answer: str, question: str = "你希望回答简洁、说人话并注明来源吗？") -> str:
    return "<send_user_message_question_reply>\n" + json.dumps([
        {"questionItemId": "assistant-generated-id", "question": question, "answer": answer},
    ], ensure_ascii=False) + "\n</send_user_message_question_reply>"


def write_log(path, messages):
    rows = [{"type": "session_meta", "payload": {"id": path.stem, "source": "cli", "cwd": "/fictional/replies"}}]
    rows.extend({"type": kind, "payload": payload} for kind, payload in messages)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({**row, "timestamp": "2026-01-01T00:00:01Z"}, ensure_ascii=False) + "\n" for row in rows))


def user(text):
    return "response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def test_only_answers_can_contribute_preferences():
    assert direct_user_text(callback("继续实现")) == "继续实现"
    event = Event("e", "s", 1, "user_message", None, text=direct_user_text(callback("我选第二项")))
    assert signals([event]) == []
    event.text = direct_user_text(callback("请解释得易懂，读者是大一学生。", "已经完成了吗？"))
    assert any(s.dimension == "clarity" and "大一学生" in s.quote for s in signals([event]))


@pytest.mark.parametrize("text", [
    '<send_user_message_question_reply>{"answer":"说人话"}</send_user_message_question_reply>',
    '<send_user_message_question_reply>["说人话"]</send_user_message_question_reply>',
    '<send_user_message_question_reply>not json</send_user_message_question_reply>',
    '<send_user_message_question_reply>[]',
    '<send_user_message_question_reply>[{"question":"说人话","answer":false}]</send_user_message_question_reply>',
])
def test_malformed_or_non_text_callbacks_supply_no_preferences(text):
    assert direct_user_text(text) == ""


def test_distinct_mirror_only_message_survives_same_turn(tmp_path):
    path = tmp_path / "source.jsonl"
    write_log(path, [
        ("event_msg", {"type": "task_started", "turn_id": "one"}),
        user("请解释概念。"),
        ("event_msg", {"type": "user_message", "message": "请解释概念。"}),
        ("event_msg", {"type": "user_message", "message": callback("请用一个容易理解的例子。")}),
    ])
    events = [e for e in parse_rollout(path).events if e.kind == "user_message"]
    assert [e.text for e in events] == ["请解释概念。", "请用一个容易理解的例子。"]
    assert events[1].details["input_format"] == "question_reply"
    assert events[1].details["mirror"] is True


def test_fixed_snapshot_and_session_exclusion_still_apply_to_answers(tmp_path):
    path = tmp_path / "codex" / "sessions" / "evaluation.jsonl"
    write_log(path, [user(callback("请说人话，简洁些。"))])
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, path.parents[1])
    assert analyze(store)["counts"]["user_messages"] == 1
    import_codex(store, path.parents[1], exclude_sessions={"evaluation"})
    assert store.counts()["events"] == 0
    import_codex(store, path.parents[1], before="2025-12-31T00:00:00Z")
    assert store.counts()["sessions"] == 0


def test_long_message_dedup_uses_full_content_not_retained_prefix(tmp_path):
    path = tmp_path / "long.jsonl"
    prefix = "说明" * 6500
    write_log(path, [user(prefix + "版本一"),
                     ("event_msg", {"type": "user_message", "message": prefix + "版本二"})])
    events = [e for e in parse_rollout(path).events if e.kind == "user_message"]
    assert len(events) == 2
    assert events[0].text == events[1].text
    assert events[0].details["message_digest"] != events[1].details["message_digest"]
