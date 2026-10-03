from orbit_backend.features import sessfeat


def rows(svc, uid):
    with svc.hub.read() as db:
        return dict(db.execute("SELECT v.name, f.n FROM sess_feat f JOIN feat_vocab v "
                               "ON v.fid = f.fid WHERE f.session_uid = ?", (uid,)).fetchall())


def states(svc):
    with svc.hub.read() as db:
        return dict(db.execute("SELECT session_uid, updated_at FROM sess_feat_state").fetchall())


def test_materialize_maps_and_derives(seeded, make_service):
    svc = make_service()
    result = sessfeat.materialize(svc)
    assert result["changed"] == 3 and result["removed"] == 0
    s1 = rows(svc, "s1")
    assert s1["tool:shell"] == 3
    assert s1["cmd:git status"] == 2 and s1["cmdcls:readonly"] == 2
    assert s1["ftype:.py"] == 4 and s1["lang:python"] == 5  # 4 from extension + marker
    assert s1["mcp:playwright"] == 1 and s1["tool:browser"] == 1
    assert s1["err:permission-denied"] == 1
    assert s1["friction:tool_error"] == 2
    assert s1["friction:retry_same_call"] == 1
    assert s1["friction:destructive_cmd"] == 2
    assert s1["friction:approval_wait"] == 1 and s1["friction:readonly_prompted"] == 1
    assert s1["friction:long_tool_wait"] == 1
    assert rows(svc, "s3") == {"tool:file.edit": 5, "skill:pdf": 2}
    assert not sessfeat.stale(svc)


def test_incremental_touches_only_changed(seeded, make_service, revs):
    svc = make_service()
    sessfeat.materialize(svc)
    before = states(svc)
    seeded.session("s4", project="p2", day=3, features=[("skill", "docx", 1)])
    seeded.call("s2", head="git push")
    seeded.delete("s3")
    result = sessfeat.materialize(svc)
    assert result["changed"] == 2 and result["removed"] == 1
    after = states(svc)
    assert after["s1"] == before["s1"]
    assert "s3" not in after and rows(svc, "s3") == {}
    assert rows(svc, "s2")["friction:destructive_cmd"] == 1
    assert rows(svc, "s4") == {"skill:docx": 1}
    assert sessfeat.materialize(svc)["changed"] == 0
    revs.value["data_rev"] = 2
    assert sessfeat.stale(svc)


def test_single_flight_and_no_orbit(home, make_service):
    svc = make_service()
    assert sessfeat.materialize(svc)["status"] == "no_data"
    svc.materialize_lock.acquire()
    try:
        assert sessfeat.materialize(svc) == {"skipped": True}
    finally:
        svc.materialize_lock.release()
