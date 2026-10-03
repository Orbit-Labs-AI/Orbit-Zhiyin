"""Source Agent selection remains distinct from request-level model selection."""

import json

from orbit_data.store import Store as DataStore
from orbit_data.validation.fixtures import create_sources

from orbit_backend.analytics.inputs import (
    AnalysisInputBundle,
    Scope,
    legacy_bundle,
    metadata,
    select,
)
from orbit_backend.data_access.store import CanonicalStore
from orbit_backend.models import Event, ParsedSession, Session
from orbit_backend.store import Store


def test_legacy_agent_requires_parser_provenance_and_empty_filter_means_none(tmp_path):
    store = Store(tmp_path / "legacy.db")
    for sid, policy in (("codex-session", {"parser": 26}), ("unknown-session", {})):
        session = Session(sid, "p", "demo", "/demo", f"{sid}.jsonl", model="codex")
        event = Event(sid + "-user", sid, 0, "user_message", "2026-01-01T00:00:00Z")
        store.save(ParsedSession(session, [event]), "fixture", json.dumps(policy))
    bundle = legacy_bundle(store)
    assert {s["session_uid"]: s["agent"] for s in bundle.sessions} == {
        "codex-session": "codex", "unknown-session": None,
    }
    scope = Scope(agent_ids=["codex"])
    sessions, events, tools, models, diagnostics = select(bundle, scope)
    assert [s["session_uid"] for s in sessions] == ["codex-session"]
    assert [e["session_uid"] for e in events] == ["codex-session"]
    assert metadata(bundle, scope, diagnostics)["scope"]["agent_ids"] == ["codex"]
    assert diagnostics["excluded_sessions"]["agent_filter"] == 1
    assert select(bundle, Scope(agent_ids=[]))[:3] == ([], [], [])


def test_canonical_adapter_enriches_agent_and_preserves_scope(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    home = tmp_path / "data"
    with DataStore(home) as store:
        for agent in ("pi", "claude_code"):
            source = store.add_source(agent, roots[agent])
            for path in roots[agent].rglob("*.jsonl"):
                store.capture_stream(source, path.relative_to(roots[agent]).as_posix(), [path.read_bytes()])
        store.rebuild()
    adapter = CanonicalStore(home)
    scope = Scope(agent_ids=["pi"], model_ids=["fixture-model"])
    raw = adapter.read_bundle(scope)
    assert raw["scope"]["agent_ids"] == ["pi"]
    assert {s["agent"] for s in raw["sessions"]} == {"pi"}
    assert {s["agent"] for s in adapter.session_page()["items"]} == {"pi", "claude_code"}
    bundle = adapter.analysis_bundle(scope)
    selected = select(bundle, scope)
    assert {s["agent"] for s in selected[0]} == {"pi"}
    assert len(selected[3]) == 1
    assert select(adapter.analysis_bundle(Scope(agent_ids=[])), Scope(agent_ids=[]))[:4] == (
        [], [], [], [],
    )


def test_canonical_bundle_source_mapping_filters_roots_and_descendants():
    raw = {
        "input_contract": "analysis-input-v1",
        "sample_boundary": {"sources": [
            {"source_id": "a", "agent": "codex"}, {"source_id": "b", "agent": "pi"},
        ]},
        "sessions": [
            {"session_uid": "root", "source_id": "a", "kind": "main", "root_uid": "root"},
            {"session_uid": "child", "source_id": "b", "kind": "subagent", "root_uid": "root"},
        ],
        "events": [
            {"event_uid": sid, "session_uid": sid, "kind": "message.user", "ts": 1, "attrs": {}}
            for sid in ("root", "child")
        ],
        "tool_calls": [], "model_calls": [], "statistical_members": {"event_uids": ["root", "child"]},
    }
    bundle = AnalysisInputBundle.from_dict(raw)
    for agent, sid in (("codex", "root"), ("pi", "child")):
        sessions, events, *_ = select(bundle, Scope(agent_ids=[agent]))
        assert [s["session_uid"] for s in sessions] == [sid]
        assert [e["session_uid"] for e in events] == [sid]
    assert select(bundle, Scope(agent_ids=[]))[:4] == ([], [], [], [])
