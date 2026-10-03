import copy
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from orbit_backend.analytics.inputs import AnalysisInputBundle, Scope
from orbit_backend.analytics.outcome_subjective import (
    aggregate_subjective_outcomes,
    analyze_subjective_outcomes,
)
from orbit_backend.analytics.outcome_subjective.extraction import (
    classify_feedback,
    collect_deliveries,
    extract_subjective_feedback,
)
from orbit_backend.analytics.outcome_subjective.linking import link_feedback_targets
from orbit_backend.analytics.outcome_subjective.summary import summarize_subjective_outcomes
from orbit_backend.analytics.service import analyze_bundle
from orbit_backend.api import create_app
from orbit_backend.cli import main


def event(uid, seq, text, *, sid="s", delivery=False, ts="auto", **attrs):
    return {"event_uid": uid, "session_uid": sid, "seq": seq, "ts": seq * 100 if ts == "auto" else ts,
            "kind": "message.assistant" if delivery else "message.user", "turn_uid": "turn",
            "actor": "assistant" if delivery else "human", "text": text,
            "attrs": {"origin": "assistant" if delivery else "human", "task_id": "task", "task_id_source": "native",
                      **({"phase": "final"} if delivery else {}), **attrs}}


def delivery(uid="d", seq=1, **attrs):
    return event(uid, seq, "已交付一个版本。", delivery=True, **attrs)


def bundle(events, sessions=None):
    return AnalysisInputBundle(
        sessions or [{"session_uid": "s", "kind": "main", "root_uid": "s", "project_id": "p"}],
        events, [], [], {k: {"status": "available"} for k in ("events", "sessions", "projects", "tool_calls", "model_calls")},
        projects=[{"project_id": "p", "name": "synthetic"}])


@pytest.mark.parametrize("text,acceptance,completion,rework", [
    ("这个可以了", "accepted", None, False), ("这样可以，谢谢！", "accepted", None, False),
    ("还是不行", "rejected", None, False), ("不对。", "rejected", None, False),
    ("任务已经完成了", None, True, False), ("我确认整个任务完成了", None, True, False),
    ("问题还没解决", None, False, False), ("解决了", None, True, False),
    ("请重写这份报告", None, None, True), ("请重新修改这一版", None, None, True),
    ("Looks good!", "accepted", None, False), ("It doesn't work.", "rejected", None, False),
    ("The issue is resolved.", None, True, False), ("Please rewrite the report.", None, None, True),
    ("可以了，但不能接受", "mixed", None, False),
    ("这个可以了，不过请重写结论", "accepted", None, True),
    ("可以了，另外新增导出功能", "accepted", None, False),
])
def test_classification_dimensions_are_independent(text, acceptance, completion, rework):
    label = classify_feedback(text)
    assert label is not None
    assert (label["user_acceptance"], label["user_confirmed_completion"], bool(label["rework_feedback"])) == (acceptance, completion, rework)


@pytest.mark.parametrize("text", [
    "", "好的", "谢谢", "算了", "继续", "再增加导出功能", "请使用 Markdown", "不要重写报告",
    "不需要返工", "没有说可以了", "这个不是可以了", "不是不对", "可以了吗", "可以了？", "不对吗？",
    "如果可以了，就不用继续", "如果修好，可以了", "例如，可以了", "请回答，可以了",
    "用户说：可以了", "他认为可以了", "请确认任务完成了", "任务完成后再通知我",
    '“可以了”', "'可以了'", '"可以了"', "`可以了`", "> 可以了", "```text\n可以了\n```",
    "# AGENTS.md\n可以了", "<INSTRUCTIONS>\n可以了\n</INSTRUCTIONS>",
    "<external_codex_apps_open_page>可以了</external_codex_apps_open_page>",
    "If it works, looks good", "It does not look good", "Is the task completed?", "Not accepted",
])
def test_not_every_positive_or_negative_word_is_feedback(text):
    assert classify_feedback(text) is None


def test_conflicting_completion_and_reason_evidence():
    label = classify_feedback("任务完成了。任务没有完成。")
    assert label["user_confirmed_completion"] is None and label["completion_conflict"]
    label = classify_feedback("请重写这份报告，因为缺少测试结果")
    assert label["rework_feedback"][0]["reason"] == "缺少测试结果"


def test_delivery_collection_excludes_nonfinals_replays_and_children():
    events = [delivery(), delivery("comment", 2, phase="commentary"), delivery("missing", 3, phase=None),
              delivery("child", 4, sid="child"), delivery("replay", 5, replayed_from="d")]
    assert [d["delivery_event_uid"] for d in collect_deliveries(events, {"s"})] == ["d"]


@pytest.mark.parametrize("origin", ["unknown", "injected", "system", "peer", "automation", "queued"])
def test_extraction_requires_confirmed_human(origin):
    ds = collect_deliveries([delivery()], {"s"})
    assert extract_subjective_feedback([event("f", 2, "可以了", origin=origin)], ds, {"s"}) == []


def test_extraction_actor_and_main_session_guards():
    f = event("f", 2, "可以了")
    f["actor"] = "assistant"
    assert extract_subjective_feedback([f], [], {"s"}) == []
    assert extract_subjective_feedback([event("f", 2, "可以了", sid="child")], [], {"s"}) == []


def test_extraction_keeps_unlinked_candidates_and_unknowns():
    r = analyze_subjective_outcomes([event("f", 2, "可以了")], {"s"})
    assert r["feedback"][0]["link_status"] == "unlinked"
    assert r["counts"]["accepted_feedback_count"] == 0
    assert r["unknown_n"] == 1
    assert r["unknown_reasons"]["no_prior_same_task_delivery"] == 1


def test_target_indexes_support_explicit_older_version_without_mutating_inputs():
    events = [delivery("v1", 1, artifact_id="report", artifact_version="1"),
              delivery("v2", 3, artifact_id="report", artifact_version="2"),
              event("f", 4, "请重写结论", feedback_target={"artifact_id": "report", "artifact_version": "1"})]
    before = copy.deepcopy(events)
    r = analyze_subjective_outcomes(list(reversed(events)), {"s"})
    assert events == before
    assert r["feedback"][0]["delivery_event_uid"] == "v1"
    assert r["feedback"][0]["feedback_target"]["artifact_version"] == "1"
    assert r["feedback"][0]["completion_scope"] == "artifact"
    assert r["counts"]["deliveries_without_feedback"] == 1


@pytest.mark.parametrize("target,reason", [
    ({"delivery_event_uid": "missing"}, "target_not_in_selected_history"),
    ({"artifact_id": "missing"}, "target_not_in_selected_history"),
    ({"artifact_version": "1"}, "version_without_object"),
    ({"delivery_event_uid": "d", "artifact_version": "2"}, "artifact_mismatch"),
    ({"task_id": "other"}, "target_not_in_selected_history"),
    ({"delivery_event_uid": "d", "task_id": "other"}, "task_mismatch"),
    ({"delivery_event_uid": "future"}, "delivery_not_prior"),
    ({"delivery_event_uid": ["d"]}, "invalid_explicit_target"),
    ({}, "invalid_explicit_target"),
    ({"typo": "d"}, "invalid_explicit_target"), ("d", "invalid_explicit_target"),
])
def test_broken_explicit_target_never_falls_back(target, reason):
    r = analyze_subjective_outcomes([delivery(), delivery("future", 5), event("f", 3, "可以了", feedback_target=target)], {"s"})
    assert r["feedback"][0]["link_reason"] == reason
    assert r["effective_n"] == 0


def test_linking_sequence_is_authoritative_and_ties_are_unknown():
    ds = collect_deliveries([delivery("a", 1), delivery("b", 1)], {"s"})
    f = {"session_uid": "s", "event_uid": "f", "seq": 2, "ts": 200, "task_id": "task"}
    assert link_feedback_targets([f], ds)[0]["link_reason"] == "ambiguous_delivery_order"
    assert link_feedback_targets([{**f, "requested_target": {"delivery_event_uid": "a"}}], ds)[0]["link_status"] == "linked"


def test_no_cross_session_task_link_or_forward_delivery():
    ds = collect_deliveries([delivery()], {"s"})
    for f in (event("early", 0, "可以了"), event("other", 3, "可以了", sid="other"), event("new", 3, "可以了", task_id="other")):
        assert extract_subjective_feedback([f], ds, {"s", "other"})[0]["link_status"] == "unlinked"


def test_heuristic_task_identity_remains_candidate_and_explicit_reference_can_link():
    es = [delivery(task_id_source="legacy_derived"), event("f", 2, "可以了", task_id_source="legacy_derived")]
    r = analyze_subjective_outcomes(es, {"s"})
    assert r["feedback"][0]["link_status"] == "candidate" and r["effective_n"] == 0
    es[1]["attrs"]["feedback_target"] = {"delivery_event_uid": "d"}
    assert analyze_subjective_outcomes(es, {"s"})["effective_n"] == 1


def test_clocks_and_truncated_feedback_are_not_silently_trusted():
    es = [delivery(ts=200), event("f", 2, "可以了", ts=100)]
    assert analyze_subjective_outcomes(es, {"s"})["feedback"][0]["link_reason"] == "timestamp_conflict"
    es[1]["ts"] = None
    r = analyze_subjective_outcomes(es, {"s"})
    assert r["effective_n"] == 1 and r["feedback"][0]["available_at"] is None
    assert r["feedback"][0]["time_quality"] == "sequence_only"
    es[1]["text_truncated"] = True
    assert analyze_subjective_outcomes(es, {"s"})["feedback"][0]["link_reason"] == "truncated_feedback"


def test_summary_preserves_reversal_and_silent_deliveries():
    r = analyze_subjective_outcomes([delivery(), event("yes", 2, "可以了"),
                                    event("no", 3, "还是不行，请重写结论"), delivery("v2", 4)], {"s"})
    state = r["delivery_states"][0]
    assert state["feedback_event_uids"] == ["yes", "no"]
    assert state["latest_user_acceptance"] == "rejected" and state["available_at"] == 300
    assert r["counts"]["accepted_feedback_count"] == r["counts"]["rejected_feedback_count"] == 1
    assert r["counts"]["rework_feedback_count"] == r["counts"]["deliveries_without_feedback"] == 1
    assert r["delivery_states"][1]["latest_user_acceptance"] is None
    assert r["task_success"] is None


def test_empty_unavailable_and_partial_are_distinct():
    empty = analyze_subjective_outcomes([], {"s"})
    assert empty["counts"]["recognized_feedback_count"] == 0 and empty["status"] == "available"
    assert analyze_subjective_outcomes([], {"s"}, "partial")["status"] == "partial"
    for status in ("unavailable", "excluded"):
        r = analyze_subjective_outcomes([], {"s"}, status)
        assert r["feedback"] is None and r["counts"] is None and r["status"] == status
        assert aggregate_subjective_outcomes([r], status)["counts"] is None
    assert summarize_subjective_outcomes(None, None)["counts"] is None
    r = analyze_subjective_outcomes([event("unknown", 1, "可以了", origin="unknown"), event("missing", 2, None)], {"s"})
    assert r["unknown_n"] == 2 and r["status"] == "partial"


def test_duplicate_replayed_evidence_does_not_change_counts():
    es = [delivery(), event("f", 2, "可以了"), event("copy", 3, "可以了", duplicate_of="f")]
    assert analyze_subjective_outcomes(es, {"s"})["counts"]["human_message_count"] == 1


def test_bundle_time_project_and_child_boundaries():
    es = [delivery(), event("yes", 2, "可以了"), event("no", 3, "还是不行")]
    b = bundle(es)
    historical = analyze_bundle(b, Scope(until_ts=300), with_text=False)
    assert historical["sessions"][0]["subjective_outcomes"]["delivery_states"][0]["latest_user_acceptance"] == "accepted"
    assert analyze_bundle(b, Scope(from_ts=200), with_text=False)["sessions"][0]["subjective_outcomes"]["effective_n"] == 0
    assert analyze_bundle(b, Scope(project_ids=[]), with_text=False)["overview"]["subjective_outcomes"]["effective_n"] == 0
    b.sessions.append({"session_uid": "child", "kind": "subagent", "root_uid": "s", "project_id": "p"})
    b.events.extend([delivery("cd", 1, sid="child"), event("cf", 2, "可以了", sid="child")])
    r = analyze_bundle(b, with_text=False)
    assert r["overview"]["subjective_outcomes"]["counts"]["linked_feedback_count"] == 2
    assert r["projects"][0]["subjective_outcomes"] == r["overview"]["subjective_outcomes"]
    b.events = None
    assert analyze_bundle(b, with_text=False)["overview"]["subjective_outcomes"]["counts"] is None


def test_mock_store_api_and_cli_share_the_family(tmp_path, capsys):
    b = bundle([delivery(), event("f", 2, "可以了，问题解决了")])
    output = tmp_path / "analytics.json"
    with patch("orbit_backend.analytics.service.legacy_bundle", return_value=b) as loader:
        main(["--db", str(tmp_path / "mock.sqlite"), "analytics", "--no-text", "--output", str(output)])
        capsys.readouterr()
        cli = json.loads(output.read_text())
        with TestClient(create_app(tmp_path / "mock.sqlite")) as client:
            overview = client.get("/v1/analytics/overview").json()["overview"]
            detail = client.get("/v1/analytics/sessions/s").json()["session"]
            projects = client.get("/v1/analytics/projects").json()["projects"]
            old = client.get("/v1/analytics/sessions/s?until_ts=200").json()["session"]
        assert loader.call_count == 5
    assert overview["subjective_outcomes"] == cli["overview"]["subjective_outcomes"]
    assert detail["subjective_outcomes"] == cli["sessions"][0]["subjective_outcomes"]
    assert projects == cli["projects"]
    assert old["subjective_outcomes"]["effective_n"] == 0
    assert detail["subjective_outcome_candidates"][0]["signal"] == "positive"
    assert detail["task_success"] is None


def test_text_references_to_older_versions_require_an_explicit_link():
    es = [delivery("v1", 1), delivery("v2", 3), event("f", 4, "请重写上一版报告")]
    r = analyze_subjective_outcomes(es, {"s"})
    assert r["feedback"][0]["link_reason"] == "text_target_requires_explicit_reference"
    es[-1]["attrs"]["feedback_target"] = {"delivery_event_uid": "v1"}
    assert analyze_subjective_outcomes(es, {"s"})["feedback"][0]["delivery_event_uid"] == "v1"


def test_optional_identity_metadata_does_not_crash_or_become_a_known_task():
    es = [delivery(task_id={"bad": "id"}, artifact_id=[]), event("f", 2, "可以了", task_id={"bad": "id"})]
    assert analyze_subjective_outcomes(es, {"s"})["effective_n"] == 0
    es = [delivery(task_id_source="unknown"), event("f", 2, "可以了")]
    assert analyze_subjective_outcomes(es, {"s"})["effective_n"] == 0


def test_public_summary_and_aggregate_share_evidence_and_effective_counts():
    r = analyze_subjective_outcomes([delivery(), event("f", 2, "可以了")], {"s"})
    s = summarize_subjective_outcomes(r["feedback"], r["deliveries"])
    assert s["counts"]["unclassified_message_count"] == 0
    assert s["counts"] == r["counts"]
    assert aggregate_subjective_outcomes([r])["counts"] == r["counts"]
    assert r["feedback"][0]["feedback_evidence"]["event_uid"] == "f"


def test_legacy_final_answer_phase_is_an_observed_delivery():
    r = analyze_subjective_outcomes([delivery(phase="final_answer"), event("f", 2, "可以了")], {"s"})
    assert r["effective_n"] == 1


def test_rework_reason_does_not_borrow_another_sentences_cause():
    f = classify_feedback("请重写报告。这个可以了，因为很清楚。")
    assert f["rework_feedback"][0]["reason"] is None


def test_legacy_candidates_keep_the_original_shape_and_polarities():
    r = analyze_bundle(bundle([delivery(), event("f", 2, "可以了")]), with_text=False)
    assert r["sessions"][0]["subjective_outcome_candidates"] == [
        {"event_uid": "f", "delivery_event_uid": "d", "signal": "positive"}]
    r = analyze_bundle(bundle([delivery(), event("f", 2, "可以了，但不能接受")]), with_text=False)
    assert r["sessions"][0]["subjective_outcome_candidates"] == []
    assert r["sessions"][0]["subjective_outcomes"]["feedback"][0]["signal"] == "mixed"


@pytest.mark.parametrize("target,scope", [
    ({"delivery_event_uid": "v1"}, "delivery"),
    ({"artifact_id": "doc", "artifact_version": "1"}, "artifact"),
    (None, "task"),
])
def test_completion_scope_uses_the_explicit_target_before_ambient_task(target, scope):
    events = [delivery("v1", 1, artifact_id="doc", artifact_version="1"),
              delivery("v2", 2, artifact_id="doc", artifact_version="2"),
              event("f", 3, "任务完成了", feedback_target=target)]
    result = analyze_subjective_outcomes(events, {"s"})
    assert result["feedback"][0]["completion_scope"] == scope
    target_uid = "v2" if target is None else "v1"
    assert result["feedback"][0]["delivery_event_uid"] == target_uid
    untouched = next(s for s in result["delivery_states"] if s["delivery_event_uid"] != target_uid)
    assert untouched["latest_user_confirmed_completion"] is None
