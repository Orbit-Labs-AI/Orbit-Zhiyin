import copy

import pytest

from orbit_backend.analytics.respond import (
    analyze_execution_sequence,
    analyze_respond,
    build_execution_relations,
    execution_intervals,
    normalize_tool_calls,
    pair_tool_calls,
    result_status,
)


def test_pairing_uses_source_session_and_id_not_neighbor_or_timestamp(make_event):
    c = make_event("c", 1, "tool.call", ts=900, call_id="native", name="shell")
    r = make_event("r", 2, "tool.result", ts=100, call_id="native", status="failed", exit_code=1)
    other = make_event("other", 2, "tool.result", sid="other", call_id="native", status="success")
    out = pair_tool_calls([r, other, c])
    assert len(out["calls"]) == 1
    assert out["calls"][0]["result_event_uid"] == "r"
    assert out["calls"][0]["status"] == "failed"
    assert out["calls"][0]["ended_at"] is None
    assert out["orphan_result_event_uids"] == ["other"]
    r["source_id"] = "different-provider"
    assert pair_tool_calls([c, r])["calls"][0]["result_event_uid"] is None


def test_mirror_dedup_and_conflicting_returns_abstain(make_event):
    c = make_event("c", 0, "tool.call", call_id="x")
    r = make_event("r", 1, "tool.result", call_id="x", status="success")
    paired = pair_tool_calls([c, copy.deepcopy(c), r])
    assert len(paired["calls"]) == 1
    assert paired["duplicate_event_uids"] == ["c"]
    conflict = pair_tool_calls([c, r, make_event("r2", 2, "tool.result", call_id="x", status="failed")])
    assert conflict["calls"][0]["pairing_status"] == "conflict"
    assert result_status(conflict["calls"][0]) == "unknown"
    assert len(conflict["pairing_conflicts"]) == 1


def test_result_before_call_and_missing_call_identity_not_guessed(make_event):
    es = [make_event("r", 0, "tool.result", call_id="x", status="success"),
          make_event("c", 1, "tool.call", call_id="x"),
          make_event("missing", 2, "tool.call")]
    paired = pair_tool_calls(es)
    assert all(c["result_event_uid"] is None for c in paired["calls"])
    assert paired["orphan_result_event_uids"] == ["r"]


def test_conflicting_canonical_calls_have_no_trusted_result_and_preserve_input(make_call):
    calls = [make_call(), make_call(status="failed")]
    before = copy.deepcopy(calls)
    out = normalize_tool_calls(calls)
    assert len(out["calls"]) == 1
    assert out["calls"][0]["status"] is None
    assert out["calls"][0]["result_event_uid"] is None
    assert len(out["call_conflicts"]) == 1
    assert calls == before


@pytest.mark.parametrize("values,expected", [
    ({"status": "success", "failed_command_results": 1}, "failed"),
    ({"status": "success", "unknown_return_values": 1}, "unknown"),
    ({"status": "completed"}, "success"), ({"status": None}, "unknown"),
    ({"status": "rejected"}, "rejected"), ({"status": "interrupted"}, "interrupted")])
def test_status_keeps_wrapper_and_protocol_boundaries(make_call, values, expected):
    assert result_status(make_call(**values)) == expected


def test_retry_confirmation_requires_task_tool_digest_and_scope(make_call):
    first = make_call("a", status="failed", seq=1, argument_digest="x", argument_digest_kind="literal")
    second = make_call("b", seq=2, argument_digest="x", argument_digest_kind="literal")
    assert analyze_execution_sequence([first, second])["retry_links"][0]["state"] == "confirmed"
    second.pop("argument_digest")
    assert analyze_execution_sequence([first, second])["retry_links"][0]["state"] == "candidate"
    second["task_uid"] = "another-task"
    assert analyze_execution_sequence([first, second])["retry_links"] == []


def test_explicit_retry_can_change_arguments_but_not_cross_sessions(make_call):
    first = make_call("a", status="failed", seq=1)
    second = make_call("b", seq=2, retry_of_call_uid="a")
    assert analyze_execution_sequence([first, second])["retry_links"][0]["basis"] == "explicit_link"
    second["session_uid"] = "child"
    assert analyze_execution_sequence([first, second])["retry_links"] == []


def test_native_parallel_intervals_exclude_log_differences_and_touching_endpoints(make_call):
    calls = [make_call("a", started_at=0, ended_at=10000, interval_reliable=True),
             make_call("b", started_at=5000, ended_at=15000, duration_source="native_bounds"),
             make_call("log", started_at=0, ended_at=10000, duration_source="event_difference"),
             make_call("touch", started_at=15000, ended_at=20000, interval_reliable=True)]
    r = execution_intervals(calls)
    assert len(r["parallel_intervals"]) == 1
    assert r["parallel_intervals"][0]["started_at"] == 5000
    assert r["parallel_intervals"][0]["ended_at"] == 10000
    assert r["interval_unknown_calls"] == [{"session_uid": "s", "call_uid": "log"}]


def test_subagent_relations_need_ids_and_fork_is_not_spawn(make_event, make_session):
    sessions = [make_session(), make_session("child", kind="subagent", parent_uid="s"),
                make_session("fork", forked_from="s")]
    es = [make_event("spawn", 1, "subagent.spawn", child_session_uid="child"),
          make_event("join", 2, "subagent.result", child_session_uid="child"),
          make_event("unknown", 3, "subagent.spawn")]
    r = build_execution_relations(es, sessions)
    assert len(r["subagent_relations"]) == 1
    assert r["subagent_relations"][0]["join_event_uids"] == ["join"]
    assert r["unresolved_subagent_events"] == ["unknown"]
    assert r["fork_relations"] == [{"session_uid": "fork", "forked_from": "s"}]


def test_observers_do_not_create_extra_subagent_runs_or_parent_relations(make_event, make_session):
    sessions = [make_session(), make_session("child", kind="subagent", parent_uid="s")]
    es = [make_event("spawn", 1, "subagent.spawn", child_session_uid="child"),
          make_event("view", 900, "subagent.activity", sid="viewer", child_session_uid="child",
                     parent_session_uid="viewer"),
          make_event("view2", 1, "subagent.result", ts=300, sid="viewer2", child_session_uid="child",
                     parent_session_uid="viewer2", status="completed"),
          make_event("orphan", 1, "subagent.wait", sid="viewer", child_session_uid="orphan")]
    out = build_execution_relations(es, sessions)
    assert len(out["subagent_relations"]) == 1
    assert out["subagent_instance_count"] == len(out["subagent_runs"]) == 2
    assert out["subagent_parent_unknown_n"] == 1
    child = next(r for r in out["subagent_runs"] if r["child_session_uid"] == "child")
    assert child["parent_session_uid"] == "s"
    assert child["evidence_uids"] == ["spawn", "view", "view2"]
    assert child["completed_at"] == 300
    assert child["observing_session_uids"] == ["s", "viewer", "viewer2"]
    assert build_execution_relations(list(reversed(es)), sessions) == out


def test_conflicting_creators_abstain_and_run_identity_does_not_depend_on_observer(make_event, make_session):
    activity = make_event("view", 1, "subagent.activity", sid="viewer", child_session_uid="child")
    initially = build_execution_relations([activity], [])
    metadata = [make_session("child", kind="subagent", parent_uid="s")]
    resolved = build_execution_relations([activity], metadata)
    assert initially["subagent_runs"][0]["subagent_run_uid"] == resolved["subagent_runs"][0]["subagent_run_uid"]
    spawn = make_event("conflict", 1, "subagent.spawn", sid="other", child_session_uid="child")
    conflict = build_execution_relations([activity, spawn], metadata)
    assert conflict["subagent_relations"] == []
    assert conflict["subagent_parent_unknown_n"] == 1
    assert conflict["subagent_parent_conflicts"][0]["parent_session_uids"] == ["other", "s"]


def test_failure_reason_is_not_inferred_from_plain_text(make_call):
    c = make_call(status="failed", text="all tests passed")
    r = analyze_respond([], [c], [], {"s"})
    assert r["failure_reasons"][0]["failure_reason"] is None
    assert r["failure_reason_unknown_n"] == 1
    c["error_class"] = "permission_denied"
    assert analyze_execution_sequence([c])["failure_reasons"][0]["failure_reason"] == "permission_denied"


def test_workflow_unsupported_branch_abstains_even_with_observed_rewind(make_event):
    from orbit_backend.analytics.respond.sequence import workflow

    events = [make_event("rewind", 1, "branch", action="rewind")]
    unsupported = workflow(events, [], {"s"}, supported_kinds=set())
    assert unsupported["branch_count"] is None
    assert unsupported["rollback_rewind_count"] is None
    supported = workflow(events, [], {"s"}, supported_kinds={"branch"})
    assert supported["branch_count"] == supported["rollback_rewind_count"] == 1


def test_l2_only_input_can_pair_without_inventing_turns(make_event):
    c = make_event("c", 1, "tool.call", call_id="x")
    r = make_event("r", 2, "tool.result", call_id="x", status="success")
    c["turn_uid"] = r["turn_uid"] = None
    out = analyze_respond([c, r], None, [], {"s"})
    assert out["call_source"] == "paired_L2"
    assert out["tools"]["totals"]["call_count"] == 1
    assert out["turn_count"] is None
    assert out["turn_boundary_unknown_n"] == 2


def test_declined_and_denied_count_as_rejected_not_unknown():
    from orbit_backend.analytics.respond.features import tool_summary

    calls = [{"name_raw": "Bash", "kind": "shell", "status": s, "result_event_uid": f"r{i}"}
             for i, s in enumerate(["declined", "denied", "completed", "failed"])]
    totals = tool_summary(calls)["totals"]
    assert totals["rejected_count"] == 2 and totals["unknown_status_count"] == 0
    assert totals["failure_rate"] == 0.5


def test_status_biased_subset_withholds_rates():
    """a1a3-B8: only errors carry a status -> no 100% failure rate."""
    from orbit_backend.analytics.products.tools import tool_shares
    from orbit_backend.analytics.respond.features import tool_summary

    calls = [{"name_raw": "Edit", "kind": "edit", "status": "unknown", "result_event_uid": f"r{i}",
              "call_uid": f"c{i}", "session_uid": "s1"} for i in range(300)]
    calls += [{"name_raw": "Edit", "kind": "edit", "status": "failed", "result_event_uid": f"f{i}",
               "call_uid": f"f{i}", "session_uid": "s1"} for i in range(5)]
    totals = tool_summary(calls)["totals"]
    assert totals["known_failure_count"] == 5 and totals["eligible_status_count"] == 5
    assert totals["failure_rate"] is None and totals["success_rate"] is None
    assert totals["rate_reason"] == "status_coverage_below_min"
    assert round(totals["status_coverage"], 3) == round(5 / 305, 3)
    share = tool_shares(calls, "name_raw", "available")[0]
    assert share["success_rate"]["value"] is None
    covered = calls[:100] + [dict(c, status="completed") for c in calls[100:300]] + calls[300:]
    totals = tool_summary(covered)["totals"]
    assert totals["rate_reason"] is None and totals["failure_rate"] == 5 / 205
