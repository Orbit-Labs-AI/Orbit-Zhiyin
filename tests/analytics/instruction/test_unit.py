import copy

import pytest

from tandem_backend.analytics.features import structure as legacy_structure
from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.instruction import (
    extract_instruction_constraints,
    instruction_text,
    resolve_instruction_scope,
    structure,
    summarize_control_patterns,
)
from tandem_backend.analytics.instruction.extraction import _clauses


def message(text="先给方案", uid="u", seq=0, sid="s", ts=100, **attrs):
    return {"event_uid": uid, "session_uid": sid, "seq": seq, "ts": ts,
            "kind": "message.user", "actor": "human", "text": text,
            "attrs": {"origin": "human", "task_id": "task", **attrs}}


def extract(*messages):
    return extract_instruction_constraints(list(messages), main_ids={"s"})


def test_normalization_removes_wrappers_quotes_fences_but_keeps_file_identifiers():
    source = ('<environment_context>\n不要测试\n</environment_context>\n'
              '> 不要测试\n\n\x60\x60\x60text\n不要测试\n\x60\x60\x60\n'
              '示例：“不要测试”。只修改 \x60src/a.py\x60。使用 \x60pytest\x60。')
    text = instruction_text(source)
    assert "不要测试" not in text
    assert "src/a.py" in text and "pytest" in text
    assert instruction_text(None) == ""
    assert list(_clauses("1. 只修改 a.py。\n- 请运行 pytest;示例：不要测试")) == [
        "只修改 a.py", "请运行 pytest"]


def test_structure_preserves_alias_validates_measurements_and_filters_quoted_markers():
    assert legacy_structure is structure
    assert structure({"text": None}) is None
    result = structure({"event_uid": "u", "text": '> 必须不要\n\n请用 JSON 输出。\n- a.py\n1. test?',
                        "attrs": {"original_chars": True,
                                  "prompt_structure": {"code_block_count": 2, "constraint_marker_count": -1,
                                                       "url_count": False, "event_uid": "bad", "other": 100}}})
    assert result["event_uid"] == "u" and "other" not in result
    assert result["constraint_marker_count"] == 0
    assert result["code_block_count"] == 2 and result["url_count"] == 0
    assert result["explicit_format_request_count"] == 1
    assert result["bullet_count"] == result["numbered_list_count"] == result["question_mark_count"] == 1
    assert result["file_reference_count"] == 1
    assert result["prompt_char_count"] > 1
    empty = structure({"event_uid": "e", "text": "", "attrs": {}})
    assert empty["constraint_density"] is None and empty["prompt_line_count"] == 0


def test_structure_truncation_and_authoritative_original_length():
    result = structure({"event_uid": "u", "text": "必须修改", "text_truncated": True,
                        "attrs": {"original_chars": 1000}})
    assert result["prompt_char_count"] == 1000 and result["quality"] == "lower_bound"
    assert result["constraint_density"] == 1 / 4


def test_all_core_features_and_evidence_are_stable_without_mutating_input():
    source = message("先给方案，等我确认后再改文件。请运行 pytest 并报告结果。"
                     "只修改 src/a.py。不要推送。验收标准：全部测试通过。")
    before = copy.deepcopy(source)
    row = extract(source)[0]
    assert source == before
    assert row == extract(source)[0]
    assert all(row["features"][name] for name in (
        "requested_autonomy", "execution_order", "verification_requirements",
        "allowed_scope", "prohibited_actions", "acceptance_criteria"))
    assert row["features"]["requested_autonomy"][0]["value"] == "ask_first"
    assert row["features"]["allowed_scope"][0]["targets"] == ["src/a.py"]
    assert all(c["event_uid"] == "u" and c["task_id"] == "task" and c["constraint_uid"]
               for c in row["constraints"])


@pytest.mark.parametrize("change", [
    {"actor": "assistant"}, {"kind": "message.assistant"}, {"session_uid": "child"},
    {"attrs": {"origin": "unknown"}}, {"attrs": {"origin": "peer"}},
    {"attrs": {"origin": "human", "replayed_from": "old"}},
    {"attrs": {"origin": "human", "duplicate_of": "old"}},
])
def test_only_confirmed_nonreplayed_main_humans(change):
    assert extract({**message(), **change}) == []


def test_dedup_order_missing_and_truncated_samples():
    a, b = message(None, uid="a", seq=1), {**message("hello", uid="b"), "text_truncated": True}
    rows = extract(a, b, a)
    assert [r["event_uid"] for r in rows] == ["b", "a"]
    assert rows[0]["status"] == "partial" and "text_truncated" in rows[0]["unknown_reasons"]
    assert rows[1]["features"]["requested_autonomy"] is None
    assert rows[1]["unknown_reasons"] == ["text_unavailable"]


def test_summary_denominators_zero_unknown_and_unavailable():
    rows = extract(message("请运行测试。请运行 pytest"), message("hello", uid="b", seq=1, ts=200))
    summary = summarize_control_patterns(rows)
    assert (summary["message_n"], summary["effective_n"], summary["unknown_n"]) == (2, 1, 1)
    assert summary["features"]["verification_requirements"]["message_rate"] == .5
    assert summary["features"]["verification_requirements"]["values"] == {"requested": 1}
    assert summarize_control_patterns(rows, Scope(until_ts=150))["message_n"] == 1
    assert summarize_control_patterns([])["features"]["requested_autonomy"]["message_rate"] is None
    assert summarize_control_patterns([], source_available=False)["message_n"] is None


def test_scope_as_of_task_session_and_unknown_time():
    rows = extract(message("不要修改 a.py"), message("允许修改 a.py", uid="v", seq=1, ts=200),
                   message("不要推送", uid="other", seq=2, task_id="other"),
                   message("不要提交", uid="unclocked", seq=3, ts=None),
                   message("不要部署", uid="unscoped", seq=4, task_id=None))
    before = copy.deepcopy(rows)
    early = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"}, at=100)
    assert not early["conflicts"]
    assert len(early["active"]) == 1
    late = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"}, at=200)
    assert late["conflicts"] and not late["active"]
    assert {u["reason"] for u in late["unresolved"]} == {"task_unknown", "time_unknown"}
    assert rows == before
    assert not resolve_instruction_scope(rows, {"session_uid": "different", "task_id": "task"})["history"]


def test_scope_no_latest_wins_explicit_replacement_and_invalid_relations():
    old = extract(message("先给方案"))[0]
    new = extract(message("直接执行", uid="new", seq=1, ts=200))[0]
    assert resolve_instruction_scope([old, new], {"session_uid": "s", "task_id": "task"})["conflicts"]
    new["supersedes_instruction_ids"] = [old["constraints"][0]["constraint_uid"], "nonexistent"]
    result = resolve_instruction_scope([old, new], {"session_uid": "s", "task_id": "task"})
    assert result["invalid_replacements"] == ["nonexistent"]
    assert any(c["state"] == "superseded" for c in result["history"])
    assert not result["conflicts"]
    early = resolve_instruction_scope([old, new], {"session_uid": "s", "task_id": "task"}, at=100)
    assert early["active"][0]["event_uid"] == "u"


def test_conditions_and_distinct_files_do_not_become_unconditional_conflicts():
    rows = extract(message("只修改 a.py"), message("不要修改 b.py", uid="b", seq=1),
                   message("如果测试通过，允许修改 c.py", uid="c", seq=2))
    result = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"})
    assert not result["conflicts"]
    assert any(c["state"] == "conditional" for c in result["history"])
    assert all(c["event_uid"] != "c" for c in result["active"])


@pytest.mark.parametrize("task,at", [({}, None), ({"session_uid": "s"}, None),
                                    ({"session_uid": "s", "task_id": "t"}, True)])
def test_scope_requires_explicit_task_and_valid_clock(task, at):
    with pytest.raises(ValueError):
        resolve_instruction_scope([], task, at)


def test_scoped_autonomy_can_coexist_with_explicit_permission_and_empty_is_unknown():
    rows = extract(message("无需确认。只修改 a.py"))
    result = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"})
    assert not result["conflicts"]
    assert len(result["active"]) == 3
    assert resolve_instruction_scope([], {"session_uid": "s", "task_id": "task"})["status"] == "unknown"


@pytest.mark.parametrize("text", [
    "先给方案，等我确认后再改文件",
    "Plan first, wait for my approval before editing",
    "先给方案，如果测试通过，允许修改 a.py",
])
def test_later_condition_does_not_gate_the_prior_plan(text):
    rows = extract(message(text))
    result = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"})
    assert any(c["value"] == "plan_first" and c["condition"] is None for c in result["active"])
    assert any(c["state"] == "conditional" for c in result["history"])


def test_leading_condition_stays_attached_to_its_command():
    rows = extract(message("如果测试通过，请运行 pytest"))
    assert rows[0]["features"]["verification_requirements"][0]["condition"] == "如果测试通过，请运行 pytest"
    result = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"})
    assert not result["active"] and result["unresolved"]


def test_file_named_if_is_not_a_condition():
    rows = extract(message("只修改 if.py"))
    result = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"})
    assert len(result["active"]) == 2 and not result["unresolved"]
    assert all(c["targets"] == ["if.py"] for c in result["active"])
