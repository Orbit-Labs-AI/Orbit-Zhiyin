import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from orbit_backend.appdata import sources_scope
from orbit_backend.features import sessfeat
from orbit_backend.services.routes_features import scope_from
from orbit_backend.sessionops import exclusion

def rows(svc, uid):
    with svc.hub.read() as db:
        return dict(db.execute("SELECT v.name,f.n FROM sess_feat f JOIN feat_vocab v "
                               "ON v.fid=f.fid WHERE session_uid=?", (uid,)).fetchall())


def test_profile_applies_privacy_to_cached_results_and_etag(seeded, make_service, monkeypatch):
    svc = make_service()
    sources = [{"id": "src-claude_code", "enabled": True},
               {"id": "src-codex", "enabled": True}]
    monkeypatch.setattr(sources_scope, "_provider", lambda: sources)
    first = svc.profile()
    tag = svc.etag()
    exclusion.add(svc.appdb, "s1", reason="private")
    sources[1]["enabled"] = False
    private = svc.profile(include=("evidence",))
    assert first["n_sessions"] == 3 and private["n_sessions"] == 1
    assert private["scope_hash"] != first["scope_hash"] and svc.etag() != tag
    assert {uid for ids in private["evidence"].values() for uid in ids} == {"s3"}
    assert svc.profile({"source_ids": []})["n_sessions"] == 0
    assert svc.profile(scope_from(None, None, [""]))["n_sessions"] == 0
    # Explicit selection can include a disabled source, but cannot undo an exclusion.
    assert svc.profile({"source_ids": ["src-codex"]})["n_sessions"] == 1
    assert svc.profile({"root_session_uids": ["s1"]})["n_sessions"] == 0


def test_materialization_detects_equal_size_corrections(seeded, make_service, revs):
    svc = make_service()
    sessfeat.materialize(svc)
    seeded.db.execute("UPDATE tool_call SET status='failed', exit_code=1, "
                      "error_class='audit_error' WHERE session_uid='s2'")
    seeded.db.execute("UPDATE session_feature SET n=99 WHERE session_uid='s2' "
                      "AND feature='tool_category'")
    revs.value["data_rev"] += 1
    result = sessfeat.materialize(svc)
    assert result["changed"] == 1
    current = rows(svc, "s2")
    assert current["tool:shell"] == 99 and current["friction:tool_error"] == 1
    assert current["err:audit_error"] == 1 and not sessfeat.stale(svc)


def test_profile_waits_for_inflight_materialization(seeded, make_service, monkeypatch):
    svc = make_service()
    entered = threading.Event()
    materialize = sessfeat.materialize

    def observed(*args, **kwargs):
        entered.set()
        return materialize(*args, **kwargs)

    monkeypatch.setattr(sessfeat, "materialize", observed)
    with ThreadPoolExecutor(1) as pool:
        svc.materialize_lock.acquire()
        try:
            future = pool.submit(svc.profile, {"project_ids": ["p1"]})
            assert entered.wait(5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.05)
        finally:
            svc.materialize_lock.release()
        assert future.result(5)["coverage"]["with_features"] == 2
    cached = svc.profile({"project_ids": ["p1"]})
    assert cached["cache"] == "hit" and cached["coverage"]["with_features"] == 2


def test_old_materialization_marker_is_invalidated(seeded, make_service):
    svc = make_service()
    with svc.appdb.write() as db:
        db.execute("INSERT INTO sess_feat_state VALUES (?, ?, ?)",
                   (sessfeat.DATA_REV_KEY, "1", 0))
    assert sessfeat.stale(svc)
    assert svc.profile()["coverage"]["with_features"] == 3
