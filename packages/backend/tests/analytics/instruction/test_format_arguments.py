"""Format arguments remain task controls, with normalized values for consumers."""

import pytest

from tandem_backend.analytics.instruction import (
    extract_instruction_constraints,
    resolve_instruction_scope,
)


def extract(text):
    event = {"event_uid": "e", "session_uid": "s", "seq": 1, "ts": 10,
             "kind": "message.user", "actor": "human", "text": text,
             "attrs": {"origin": "human", "task_id": "t"}}
    return extract_instruction_constraints([event], main_ids={"s"})


@pytest.mark.parametrize("text,values,relation", [
    ("请用 Markdown 表格", ["markdown", "table"], "combined"),
    ("请用 JSON 或 Markdown 输出", ["json", "markdown"], "alternative"),
    ("请用表格比较 JSON 和 Markdown", ["table"], "single"),
    ("输出为 JSON", ["json"], "single"),
    ("Return JSON", ["json"], "single"),
])
def test_concrete_format_arguments_without_changing_control_value(text, values, relation):
    constraint = extract(text)[0]["features"]["format_requirements"][0]
    assert constraint["value"] == "format"
    assert constraint["format_values"] == values
    assert constraint["format_relation"] == relation
    assert constraint["text"] == text


@pytest.mark.parametrize("text", ["不要使用 JSON", '> 请用 JSON', '请解释这句话：请用 JSON'])
def test_non_request_never_produces_format_arguments(text):
    assert extract(text)[0]["features"]["format_requirements"] is None


def test_condition_remains_a_task_local_execution_gate():
    rows = extract("如果测试通过，请用 JSON")
    item = rows[0]["features"]["format_requirements"][0]
    assert item["format_values"] == ["json"] and item["condition"]
    resolved = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "t"})
    assert resolved["active"] == []
    assert resolved["history"][0]["state"] == "conditional"
