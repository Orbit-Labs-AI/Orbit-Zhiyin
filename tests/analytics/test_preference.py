import copy

import pytest

from tandem_backend.analytics.common import clauses, evidence, semantic_coverage, semantic_messages
from tandem_backend.analytics.preference import (
    extract_explicit_preferences,
    resolve_effective_preferences,
    summarize_preferences,
)
from tandem_backend.analytics.preference.rules import preference_values


def test_common_boundary_and_missing_coverage(fixtures):
    s, e, _ = fixtures
    events = [e(), e(uid="copy", replayed_from="e"), e(uid="robot", origin="automation"),
              e(uid="child", sid="c"), e(uid="unknown", origin="unknown"), e(uid="empty", text="")]
    msgs = semantic_messages(events, [s(), s("c", kind="subagent")])
    assert [x["event_uid"] for x in msgs] == ["e", "empty"]
    assert semantic_coverage(events, msgs)["missing_text"] == 1
    assert semantic_coverage(None, [])["human_messages"] is None
    assert evidence(e(ts=None))["time_quality"] == "missing"
    assert clauses("一。二；三\n四") == ["一", "二", "三", "四"]


def test_scope_evidence_and_polarity(fixtures):
    s, e, _ = fixtures
    out = extract_explicit_preferences([e("以后这个项目不要用英文")], [s()])
    p = out["records"][0]
    assert (p["preference_type"], p["value"], p["polarity"]) == ("language", "en", "avoid")
    assert p["preference_scope"] == {"kind": "project", "target_id": "p", "identity_quality": "canonical"}
    assert p["confirmed_by"] is None and p["preference_evidence"][0]["event_uid"] == "e"
    assert preference_values("我喜欢简短代码") == []


@pytest.mark.parametrize("text", [
    '> 以后所有项目都用英文', '```\n以后所有项目都用英文\n```',
    '他说以后所有项目都用英文', '例如我喜欢详细回答', '我喜欢英文吗？',
    '这篇文章包含“我喜欢英文”', '# AGENTS.md\n以后所有项目都用英文',
    'Git 本月调用了 100 次', '我喜欢详细代码', '如果以后所有项目都用英文',
])
def test_negative_evidence_is_not_a_preference(fixtures, text):
    s, e, _ = fixtures
    assert extract_explicit_preferences([e(text)], [s()])["records"] == []


def test_attachment_wrapper_and_truncation(fixtures):
    s, e, _ = fixtures
    text = '# Files pasted\n以后所有项目都用英文\n## My request:\n以后这个项目都用中文'
    out = extract_explicit_preferences([e(text)], [s()])
    assert [p["value"] for p in out["records"]] == ["zh"]
    out = extract_explicit_preferences([{**e("以后所有项目都用英文"), "text_truncated": True}], [s()])
    assert not out["records"] and len(out["candidates"]) == 1


def test_one_off_instruction_and_explicit_task_preference(fixtures):
    s, e, _ = fixtures
    out = extract_explicit_preferences([e("这次请简短一点")], [s()], {"e": "task"})
    assert not out["records"] and out["task_instructions"][0]["preference_scope"]["target_id"] == "task"
    out = extract_explicit_preferences([e("这个任务我喜欢简短回答")], [s()], {"e": "task"})
    assert out["records"][0]["preference_scope"]["kind"] == "task"


def test_unspecified_scope_is_never_global_and_future_schedule_is_pending(fixtures):
    s, e, _ = fixtures
    out = extract_explicit_preferences([e("我喜欢英文")], [s()])
    r = resolve_effective_preferences(out["records"], at=100)
    assert r["applicable"] == [] and r["unresolved"][0]["reason"] == "scope_not_resolved"
    out = extract_explicit_preferences([e("以后所有项目从明天开始都用英文")], [s()])
    assert out["records"] == [] and out["candidates"][0]["effective_at"] is None


def test_revision_reaffirmation_revocation_and_asof(fixtures):
    s, e, _ = fixtures
    es = [e("以后这个项目都用中文", "a", 0, ts=10),
          e("以后这个项目都用中文", "b", 1, ts=20),
          e("这个项目改用英文", "c", 2, ts=30),
          e("撤销这个项目的英文偏好", "d", 3, ts=40)]
    history = extract_explicit_preferences(es, [s()])["records"]
    assert history[1]["preference_history"][0]["relation"] == "reaffirms"
    task = {"project_id": "p"}
    assert [p["value"] for p in resolve_effective_preferences(history, task, 15)["applicable"]] == ["zh"]
    assert [p["value"] for p in resolve_effective_preferences(history, task, 35)["applicable"]] == ["en"]
    assert resolve_effective_preferences(history, task, 45)["applicable"] == []
    assert not resolve_effective_preferences(history, task, 35)["conflicts"]


def test_conflicting_values_and_precedence(fixtures):
    s, e, _ = fixtures
    es = [e("我喜欢所有项目用中文", "a", 0), e("我喜欢这个项目用英文", "b", 1),
          e("我喜欢这个项目用中文", "c", 2)]
    history = extract_explicit_preferences(es, [s()])["records"]
    r = resolve_effective_preferences(history, {"project_id": "p"})
    assert not r["applicable"] and len(r["conflicts"]) == 1
    assert len(resolve_effective_preferences(history, {"project_id": "other"})["applicable"]) == 1


def test_no_project_identity_no_fabricated_scope(fixtures):
    s, e, _ = fixtures
    history = extract_explicit_preferences([e("以后这个项目用中文")], [s(project_id=None)])["records"]
    assert resolve_effective_preferences(history)["unresolved"][0]["reason"] == "scope_not_resolved"
    history = extract_explicit_preferences([e("以后这个项目用中文")], [s(project_id=None, legacy_project_id="path")])["records"]
    assert not resolve_effective_preferences(history, {"project_id": "path"})["applicable"]
    assert resolve_effective_preferences(history, {"legacy_project_id": "path"})["applicable"]


def test_missing_time_clock_skew_and_equal_time_cross_session(fixtures):
    s, e, _ = fixtures
    history = extract_explicit_preferences([e("以后这个项目用中文", "a", 0, ts=None),
        e("这个项目改用英文", "b", 1, ts=None)], [s()])["records"]
    assert resolve_effective_preferences(history, {"project_id": "p"}, 100)["applicable"] == []
    assert [p["value"] for p in resolve_effective_preferences(history, {"project_id": "p"})["applicable"]] == ["en"]
    history = extract_explicit_preferences([e("以后这个项目用中文", "a", 0, ts=200),
        e("这个项目改用英文", "b", 1, ts=100)], [s()])["records"]
    assert [p["value"] for p in resolve_effective_preferences(history, {"project_id": "p"})["applicable"]] == ["en"]
    history = extract_explicit_preferences([e("以后这个项目用中文", "a", 0, sid="a"),
        e("这个项目改用英文", "b", 0, sid="b")], [s("a"), s("b")])["records"]
    assert len(resolve_effective_preferences(history, {"project_id": "p"})["conflicts"]) == 1


def test_determinism_no_mutation_and_summaries(fixtures):
    s, e, _ = fixtures
    events = [e("我喜欢所有项目用中文")]
    original = copy.deepcopy(events)
    a = extract_explicit_preferences(events, [s()])
    assert events == original and a == extract_explicit_preferences(events, [s()])
    assert summarize_preferences(a["records"] * 2)["record_count"] == 1
    assert summarize_preferences(None)["record_count"] is None
    assert resolve_effective_preferences(None)["applicable"] is None
    assert extract_explicit_preferences(None, [s()])["records"] is None
