"""One child run can produce many lifecycle events; none are human messages."""

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.contract import canonical
from tandem_data.store import Store

from tandem_backend.analytics.respond import analyze_respond


def test_activity_is_not_spawn_and_child_identity_is_never_ui_item_identity(tmp_path):
    records = [{"type": "session_meta", "payload": {"id": "parent"}}]
    for index, (phase, child) in enumerate([
        ("started", "child1"), ("interacted", "child1"), ("interacted", "child1"),
        ("completed", "child1"), ("interacted", "child2"), ("interacted", None),
    ]):
        item = {"type": "SubAgentActivity", "id": f"item{index}", "kind": phase}
        if child:
            item["agent_thread_id"] = child
        records.append({"type": "event_msg", "timestamp": f"2026-10-02T00:00:0{index}Z",
                        "payload": {"type": "item_completed", "item": item}})
    for phase in ("collab_waiting_begin", "collab_agent_interaction_begin", "collab_close_end"):
        records.append({"type": "event_msg", "payload": {"type": phase, "receiver_thread_id": "child1"}})
    with Store(tmp_path / "data") as store:
        source = store.add_source("codex", tmp_path / "source")
        store.capture_stream(source, "sessions/parent.jsonl", [(canonical(r) + "\n").encode() for r in records])
        store.rebuild()
        bundle = read_analysis(store.home, AnalysisScope("UTC"))
        result = analyze_respond(bundle["events"], bundle["tool_calls"], bundle["sessions"], {bundle["sessions"][0]["session_uid"]})
        assert result["workflow"]["subagent_spawn_count"] == 1
        assert result["subagent_instance_count"] == 2
        assert result["subagent_activity_event_count"] == 9
        assert len(result["unresolved_subagent_events"]) == 1
        assert len(result["subagent_runs"]) == 2
        first = next(r for r in result["subagent_runs"] if r["status"] == "completed")
        assert first["started_at"] < first["completed_at"]
        assert all(e["actor"] == "subagent" for e in bundle["events"] if e["kind"].startswith("subagent."))
