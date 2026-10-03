"""Selection aliases and empty filters must never widen a feature profile."""

import pytest

from orbit_backend.features.scope import normalize, scope_hash, session_where


@pytest.mark.parametrize("key", ["project_ids", "source_ids", "agent_ids", "root_session_uids"])
def test_explicit_empty_filter_is_no_rows(key):
    assert normalize({key: []})[key] == []
    where, params = session_where({key: []})
    assert "0" in where and params == []
    assert scope_hash({key: []}) != scope_hash({})


def test_ai_scope_aliases_preserve_the_selected_bounds():
    old = {"project_id": "p", "start_ms": 0, "end_ms": 100, "session_uids": ["s"]}
    native = {"project_ids": ["p"], "from_ts": 0, "until_ts": 100, "root_session_uids": ["s"]}
    assert normalize(old) == normalize(native)
    assert session_where(old) == session_where(native)


def test_profile_empty_sources_and_ai_aliases(seeded, make_service):
    svc = make_service()
    assert svc.profile({"source_ids": []})["n_sessions"] == 0
    assert svc.profile({"project_id": "p2"})["n_sessions"] == 1
