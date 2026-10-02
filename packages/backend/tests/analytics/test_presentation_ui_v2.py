from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.presentation import build_presentation
from tandem_backend.analytics.service import analyze_bundle


def sample():
    sessions = [{"session_uid": sid, "root_uid": sid, "kind": "main", "source_id": "test",
                 "agent": agent, "project_id": sid}
                for sid, agent in (("a", "codex"), ("b", "claude_code"))]
    # 2026-01-01 15:30 UTC = 23:30 in Shanghai; crosses local midnight.
    base = 1767281400000
    events = []
    for sid, offset, text in (("a", 0, "请开发前端组件并编写单元测试"),
                              ("b", 86_400_000, "请翻译这篇文章")):
        for seq, kind, delta in ((1, "message.user", 0), (2, "message.assistant", 3_600_000)):
            events.append({"session_uid": sid, "event_uid": f"{sid}{seq}", "seq": seq,
                           "turn_uid": f"{sid}-turn", "kind": kind, "ts": base + offset + delta,
                           "actor": "human" if seq == 1 else "assistant",
                           "text": text if seq == 1 else "完成了。",
                           "attrs": {"origin": "human" if seq == 1 else "agent"}})
    coverage = {key: {"status": "available"} for key in
                ("sessions", "events", "tool_calls", "model_calls", "projects")}
    return AnalysisInputBundle(sessions, events, [], [], coverage)


def test_original_ui_project_inventory_and_distinct_time_units():
    features = analyze_bundle(sample(), Scope(display_timezone="Asia/Shanghai"), with_text=False)
    view = build_presentation(features)
    assert view["statistics"]["counts"]["projects"]["value"] == 2
    assert view["overview"]["collaboration_duration"]["value"] == 7_200_000
    assert view["overview"]["human_work_duration"]["value"] is None
    assert features["sessions"][0]["features"]["observed_event_dates"] == ["2026-01-01", "2026-01-02"]
    hours = view["statistics"]["activity"]["observed_span_by_hour"]
    assert hours["unit"] == "minute"
    assert sum(row["minutes"] for row in hours["rows"]) == 120
    rhythm = features["overview"]["activity_rhythm"]["human_messages"]
    assert rhythm["by_weekday_hour"] == {"4:23": 1, "5:23": 1}
    assert {r["agent"]: r["human_messages"]["effective_n"] for r in
            view["overview"]["agent_activity"]} == {"codex": 1, "claude_code": 1}
    a = next(p for p in view["projects"] if p["project_id"] == "a")
    assert a["statistics"]["time"]["observed_session_span_sum_ms"]["value"] == 3_600_000
    assert a["statistics"]["counts"]["human_messages"]["value"] == 1


def test_ui_scoped_subdomains_and_recent_task_order():
    view = build_presentation(analyze_bundle(sample(), Scope(display_timezone="Asia/Shanghai"), with_text=False))
    a = next(p for p in view["projects"] if p["project_id"] == "a")
    b = next(p for p in view["projects"] if p["project_id"] == "b")
    assert {r["id"] for r in a["domain_details"]["rows"]} == {
        "software.frontend", "software.testing_debugging"}
    assert {r["id"] for r in b["domain_details"]["rows"]} == {"writing.translation", "writing.content"}
    assert all(r["session_uids"] == ["a"] for r in a["domain_details"]["rows"])
    assert view["timeline_recent"][0]["session_uid"] == "b"
    assert view["timeline"][0]["session_uid"] == "a"
    selected = build_presentation(analyze_bundle(sample(), Scope(agent_ids=["codex"]), with_text=False))
    assert selected["statistics"]["counts"]["projects"]["value"] == 1
    assert {r["id"] for r in selected["semantics"]["domain_details"]["rows"]} == {
        "software.frontend", "software.testing_debugging"}


def test_missing_and_unrepresentable_timestamps_do_not_become_epoch_dates():
    bundle = sample()
    bundle.events[1]["ts"] = None
    bundle.events[3]["ts"] = 10**30
    features = analyze_bundle(bundle, Scope(display_timezone="Asia/Shanghai"), with_text=False)
    view = build_presentation(features)
    assert all(s["features"]["time_unknown_event_count"] == 1 for s in features["sessions"])
    assert view["statistics"]["time"]["unclocked_events"]["value"] == 2
    assert view["overview"]["collaboration_duration"]["status"] == "partial"
    assert view["overview"]["collaboration_duration"]["value"] == 0


def test_shared_native_task_keeps_each_project_and_timeline_label_evidence_local():
    bundle = sample()
    for session in bundle.sessions:
        session["legacy_project_id"] = session.pop("project_id")
    for event in bundle.events:
        event["attrs"].update(task_id="shared-native-task", task_id_source="native")
    features = analyze_bundle(bundle, Scope(display_timezone="Asia/Shanghai"), with_text=False)
    view = build_presentation(features)
    assert len(features["tasks"]["records"]) == 1
    assert len(view["timeline"]) == 2
    a = next(p for p in view["projects"] if p["legacy_project_id"] == "a")
    assert {r["id"] for r in a["domain_details"]["rows"]} == {
        "software.frontend", "software.testing_debugging"}
    assert {d["id"] for d in view["timeline"][0]["domain_details"]} == {
        "software.frontend", "software.testing_debugging"}
    assert {d["id"] for d in view["timeline"][1]["domain_details"]} == {
        "writing.translation", "writing.content"}
