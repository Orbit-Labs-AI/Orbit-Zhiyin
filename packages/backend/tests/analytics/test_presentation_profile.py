"""Projection regressions use actual feature extraction, not invented schemas."""

from copy import deepcopy
from datetime import datetime

import pytest

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.presentation.profile import build_profile
from tandem_backend.analytics.service import analyze_bundle


def _ts(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def _event(text, uid="e", sid="s", seq=0, ts=100, task_id="native-task", **extra):
    return {"event_uid": uid, "session_uid": sid, "seq": seq, "ts": ts,
            "kind": "message.user", "actor": "human", "turn_uid": f"turn-{uid}",
            "text": text, "attrs": {"origin": "human", "task_id": task_id,
                                     "task_id_source": "native"}, **extra}


def _analysis(events, scope=None):
    sessions = [{"session_uid": sid, "root_uid": sid, "kind": "main",
                 "project_id": "p", "source_id": "synthetic", "started_at": 0}
                for sid in sorted({e["session_uid"] for e in events})]
    bundle = AnalysisInputBundle(sessions, events, [], [],
                                {k: {"status": "available"} for k in
                                 ("sessions", "events", "tool_calls", "model_calls", "projects")})
    return analyze_bundle(bundle, scope or Scope(), with_text=False)


def test_actual_feature_ids_are_joined_and_single_pole_axes_abstain():
    analysis = _analysis([_event("直接执行。先给方案。请运行测试。")])
    native_id = analysis["instruction"]["records"][0]["task_id"]
    assert native_id == analysis["tasks"]["records"][0]["task_id"]  # shared canonical identity
    profile = build_profile(analysis)
    assert profile["coverage"]["unmapped_instruction_n"] == 0
    # One task is below the 5-task / 2-session minimum: the vote is kept, the score is not.
    assert profile["axes"]["delegation"]["observed_mean"] == 1
    assert profile["axes"]["delegation"]["score"] is None
    assert profile["axes"]["delegation"]["status"] == "insufficient"
    # Plan and execute_first conflict, so the task gives no planning vote.
    assert profile["axes"]["planning"]["observed_score"] is None
    assert profile["axes"]["verification"]["observed_mean"] == 1
    assert profile["axes"]["verification"]["observed_score"] is None
    assert profile["axes"]["verification"]["score"] is None
    assert profile["axes"]["verification"]["direction"] is None
    assert profile["axes"]["orchestration"]["score"] is None
    assert profile["code"] is None


def test_monthly_view_caps_long_histories_without_changing_overall_observations():
    old = _event("直接完成报告", uid="old", ts=_ts("2000-01-01T00:00:00+00:00"))
    new = _event("直接完成报告", uid="new", sid="new-session", task_id="new-task",
                 ts=_ts("2026-10-02T00:00:00+00:00"))
    profile = build_profile(_analysis([old, new]))
    trend = profile["monthly_trend"]
    assert len(trend["rows"]) == trend["max_months"] == 12
    assert trend["rows"][0]["month"] == "2025-11"
    assert trend["rows"][-1]["month"] == "2026-10"
    assert trend["earlier_observed_months_omitted"] == 1
    assert profile["axes"]["delegation"]["effective_task_n"] == 2


def test_long_tasks_duplicates_and_cross_session_tasks_do_not_get_more_votes():
    events = [_event("直接完成报告", uid=f"long-{i}", seq=i, task_id="long") for i in range(10)]
    events += [_event("先询问我。编写报告", uid="other", sid="s2", task_id="short")]
    # Same trusted native task identity in another session remains one task vote.
    events += [_event("直接完成报告", uid="continued", sid="s2", seq=1, task_id="long")]
    analysis = _analysis(events)
    analysis["instruction"]["records"].append(deepcopy(analysis["instruction"]["records"][0]))
    analysis["tasks"]["records"].append(deepcopy(analysis["tasks"]["records"][0]))
    axis = build_profile(analysis)["axes"]["delegation"]
    assert axis["effective_task_n"] == 2
    assert axis["observed_mean"] == 0.5
    assert axis["score"] is None  # two tasks are below the minimum


def test_conflicting_authorizations_abstain_and_preserve_evidence():
    profile = build_profile(_analysis([
        _event("先询问我。编写报告", uid="ask"),
        _event("直接完成报告", uid="direct", seq=1),
    ]))
    axis = profile["axes"]["delegation"]
    assert axis["score"] is None
    assert axis["conflicting_task_n"] == 1
    assert {e["event_uid"] for e in axis["conflict_evidence"]} == {"ask", "direct"}


def test_explicit_supersession_is_resolved_but_does_not_rewrite_prior_month():
    jan = _ts("2026-01-15T12:00:00+00:00")
    feb = _ts("2026-02-15T12:00:00+00:00")
    first = _event("先询问我。编写报告", uid="ask", ts=jan)
    initial = _analysis([first])
    constraint_id = initial["instruction"]["records"][0]["features"]["requested_autonomy"][0]["constraint_uid"]
    second = _event("直接完成报告", uid="direct", seq=1, ts=feb)
    second["attrs"]["supersedes_instruction_ids"] = [constraint_id]
    profile = build_profile(_analysis([first, second]))
    assert profile["axes"]["delegation"]["observed_mean"] == 1
    months = {r["month"]: r for r in profile["monthly_trend"]["rows"]}
    assert months["2026-01"]["axes"]["delegation"]["observed_mean"] == 0
    # The replacement references prior context, which a monthly-only sample does
    # not contain: conservative unknown is preferable to inventing active policy.
    assert months["2026-02"]["axes"]["delegation"]["score"] is None


def test_conditional_and_truncated_instructions_do_not_score():
    conditional = _event("如果测试通过，直接完成报告", uid="condition")
    truncated = _event("直接完成报告", uid="truncated", sid="s2", task_id="t2", text_truncated=True)
    profile = build_profile(_analysis([conditional, truncated]))
    assert profile["axes"]["delegation"]["score"] is None
    assert profile["code"] is None


def test_partial_replacement_does_not_resurrect_previously_complete_instruction():
    first = _event("先询问我。编写报告", uid="first")
    initial = _analysis([first])
    old_id = initial["instruction"]["records"][0]["features"]["requested_autonomy"][0]["constraint_uid"]
    replacement = _event("直接完成报告", uid="partial", seq=1, text_truncated=True)
    replacement["attrs"]["supersedes_instruction_ids"] = [old_id]
    axis = build_profile(_analysis([first, replacement]))["axes"]["delegation"]
    assert axis["score"] is None
    assert axis["signal_rate"] is None
    assert axis["conflicting_task_n"] == 0
    assert axis["unresolved_task_n"] == 1
    assert "replacement_text_not_observable" in axis["missing_reasons"]
    assert axis["unresolved_evidence"][0]["event_uid"] == "partial"


def test_type_needs_support_and_does_not_impute_other_poles():
    events = [_event("直接完成报告", uid=f"t{i}", task_id=f"native-{i}",
                     sid=f"s{i % 2}", seq=i) for i in range(5)]
    profile = build_profile(_analysis(events))
    assert profile["axes"]["delegation"]["direction"] == "D"
    assert profile["axes"]["planning"]["direction"] is None
    assert profile["axes"]["verification"]["direction"] is None
    assert profile["code"] is None
    # No checks observed is not evidence for acceleration.
    assert profile["axes"]["verification"]["observed_score"] is None


def test_axis_session_support_counts_axis_evidence_not_unrelated_task_messages():
    events = [_event("直接完成报告", uid=f"choice-{i}", sid="s1", seq=i,
                     task_id=f"t{i}") for i in range(5)]
    events += [_event("继续编写报告", uid=f"followup-{i}", sid="s2", seq=i,
                      task_id=f"t{i}") for i in range(5)]
    axis = build_profile(_analysis(events))["axes"]["delegation"]
    assert axis["effective_task_n"] == 5
    assert axis["session_n"] == 1
    assert axis["direction"] is None


def test_shared_task_cross_session_verification_conflict_is_not_a_positive_vote():
    profile = build_profile(_analysis([
        _event("请运行测试", uid="check", sid="s1"),
        _event("不要运行测试。编写报告", uid="prohibition", sid="s2"),
    ]))
    axis = profile["axes"]["verification"]
    assert axis["conflicting_task_n"] == 1
    assert axis["observed_score"] is None
    assert {r["event_uid"] for r in axis["conflict_evidence"]} == {"check", "prohibition"}


def test_candidate_task_boundaries_do_not_produce_typed_personality():
    events = [_event("直接完成报告", uid=f"e{i}", sid=f"s{i}") for i in range(5)]
    for event in events:
        event["attrs"].pop("task_id_source")
    axis = build_profile(_analysis(events))["axes"]["delegation"]
    assert axis["score"] == 1
    assert axis["direction"] is None
    assert "candidate_task_boundaries" in axis["missing_reasons"]


def test_months_use_display_timezone_and_zero_filled_gaps_are_forbidden():
    # January UTC, February in Asia/Shanghai.
    first = _event("直接完成报告", uid="first", ts=_ts("2026-01-31T20:00:00+00:00"))
    last = _event("先询问我。编写报告", uid="last", seq=1, task_id="other",
                  ts=_ts("2026-04-10T00:00:00+00:00"))
    missing = _event("直接完成报告", uid="unclocked", sid="s2", ts=None, task_id="unclocked")
    profile = build_profile(_analysis([first, last, missing], Scope(display_timezone="Asia/Shanghai")))
    trend = profile["monthly_trend"]
    assert [r["month"] for r in trend["rows"]] == ["2026-02", "2026-03", "2026-04"]
    assert trend["rows"][1]["axes"]["delegation"]["score"] is None
    assert trend["unknown_time_instruction_n"] == 1


def test_scatter_is_fixed_observable_metric_mapping_with_valid_zero_rule_hits():
    events = [_event("你可以自主完成报告。先给方案", uid="planned", task_id="t1"),
              _event("你可以自主完成报告", uid="plain", seq=1, task_id="t2"),
              _event("你可以自主完成报告", uid="other", sid="s2", task_id="t3")]
    analysis = _analysis(events)
    scatter = build_profile(analysis)["scatter"]
    points = {p["session_uid"]: p for p in scatter["points"]}
    assert (points["s"]["x"], points["s"]["y"]) == (1, 0.5)
    assert (points["s2"]["x"], points["s2"]["y"]) == (1, 0)
    assert scatter["y_axis"]["label"] == "明确规划要求命中率"
    subset = _analysis([e for e in events if e["session_uid"] == "s"])
    assert build_profile(subset)["scatter"]["points"][0]["y"] == 0.5


def test_scatter_excludes_unknown_text_from_hit_denominator():
    events = [_event("你可以自主完成报告。先给方案", uid="planned", task_id="t1"),
              _event("请编写报告", uid="unknown", seq=1, task_id="t2", text_truncated=True)]
    point = build_profile(_analysis(events))["scatter"]["points"][0]
    assert point["y"] == 1
    assert point["planning_observable_task_n"] == 1


def test_task_distribution_and_explicit_preferences_preserve_semantics_without_mutation():
    analysis = _analysis([
        _event("请修复代码并编写报告", uid="task"),
        _event("以后这个项目用中文", uid="preference", seq=1),
        _event("这个项目改用英文", uid="revision", seq=2),
    ])
    before = deepcopy(analysis)
    profile = build_profile(analysis)
    assert analysis == before
    assert profile["task_distribution"]["task_count"] == 1
    assert profile["task_distribution"]["domain"]["rates"]["software"] == 1
    assert profile["task_distribution"]["domain"]["rates"]["writing"] == 1
    preferences = profile["preferences"]
    assert preferences["summary"]["record_count"] == 2
    assert preferences["records"][1]["operation"] == "revise"
    assert preferences["records"][1]["preference_history"]
    assert "history" in preferences["basis"]
    # Output references do not alias nested input metadata.
    profile["scope"]["display_timezone"] = "altered"
    assert analysis == before


def test_unavailable_sources_have_null_values_and_no_invented_type():
    profile = build_profile({"scope": {"display_timezone": "UTC"},
                             "tasks": {"records": None}, "instruction": {"records": None},
                             "preferences": {"records": None}})
    assert profile["code"] is None
    assert profile["coverage"]["task_n"] is None
    assert profile["task_distribution"]["task_count"] is None
    assert profile["preferences"]["summary"]["record_count"] is None
    assert all(a["score"] is None for a in profile["axes"].values())
    assert profile["scatter"]["points"] == []


@pytest.mark.parametrize("value", [True, "2026-01-01", float("nan")])
def test_bad_times_do_not_enter_calendar_buckets(value):
    analysis = _analysis([_event("直接完成报告")])
    analysis["instruction"]["records"][0]["ts"] = value
    analysis["tasks"]["records"][0]["task_boundaries"][0]["start"]["ts"] = value
    analysis["tasks"]["records"][0]["label_evidence"] = {}
    assert build_profile(analysis)["monthly_trend"]["rows"] == []


def test_single_explicit_task_among_many_does_not_score_an_axis():
    """a1a3-B18: one delegation phrase out of many tasks is 'insufficient', never 1.0."""
    events = [_event("直接完成报告", uid="only", sid="s0", task_id="t0")]
    events += [_event(f"整理第 {i} 节文档", uid=f"plain-{i}", sid=f"s{i % 3}", seq=i,
                      task_id=f"t{i}") for i in range(1, 30)]
    profile = build_profile(_analysis(events))
    axis = profile["axes"]["delegation"]
    assert axis["effective_task_n"] == 1
    assert axis["score"] is None and axis["observed_score"] is None
    assert axis["status"] == "insufficient"
    assert axis["evidence"] and axis["evidence"][0]["event_uid"] == "only"
    low, high = axis["signal_rate_ci"]
    assert low < axis["signal_rate"] < high


def test_chinese_planning_and_verification_requests_are_observed():
    events = [_event(text, uid=f"u{i}", sid=f"s{i % 2}", seq=i, task_id=f"t{i}") for i, text in
              enumerate(["先出一个方案给我看", "请你先调研一下再动手", "请你再次确认，没有问题后提交",
                         "确保所有图表数据一致", "please make a plan"])]
    axes = build_profile(_analysis(events))["axes"]
    # discuss_first is observed but only plan_first votes on the planning pole.
    assert axes["planning"]["effective_task_n"] == 2
    assert axes["verification"]["effective_task_n"] == 2
    assert axes["planning"]["observed_score"] is None  # single-pole: signal_rate only
