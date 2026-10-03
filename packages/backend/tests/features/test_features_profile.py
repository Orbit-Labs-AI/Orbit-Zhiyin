import math

from orbit_backend.features.profile import hash_vector


def test_profile_weights_and_scope(seeded, make_service):
    svc = make_service()
    body = svc.profile()
    assert body["cache"] == "miss" and body["n_sessions"] == 3
    assert body["coverage"]["with_features"] == 3
    assert body["revs"] == {"data": 1, "inventory": 1, "catalog": "0", "vocab": "vocab-1"}
    vector = body["vector"]
    assert max(vector.values()) == 1.0
    # tool:shell in 2 of 3 sessions with n=4: (1+ln4)*ln(4/2.5) relative to the max
    raw = {name: max(0.05, (1 + math.log(n)) * math.log(4 / (s + 0.5)))
           for name, n, s in [("tool:shell", 4, 2), ("tool:file.edit", 5, 1)]}
    assert abs(vector["tool:file.edit"] / vector["tool:shell"]
               - raw["tool:file.edit"] / raw["tool:shell"]) < 1e-3
    per_ns = {}
    for tag in body["tags"]:
        per_ns[tag["ns"]] = per_ns.get(tag["ns"], 0) + 1
    assert max(per_ns.values()) <= 6 and len(body["tags"]) <= 24
    assert len(body["centroid"]) == 128

    p2 = svc.profile({"project_ids": ["p2"]})
    assert p2["n_sessions"] == 1 and set(p2["vector"]) == {"tool:file.edit", "skill:pdf"}
    codex = svc.profile({"agent_ids": ["codex"]})
    assert codex["n_sessions"] == 1 and "ftype:.ts" in codex["vector"]
    later = svc.profile({"from_ts": 1_760_000_000_000 + 86_400_000})
    assert later["n_sessions"] == 2


def test_profile_cache_and_stale_rebuild(seeded, make_service, revs):
    svc = make_service()
    first = svc.profile()
    assert svc.profile()["cache"] == "hit"
    svc.lru.clear()
    assert svc.profile()["cache"] == "hit"  # from app.db
    seeded.session("s9", project="p2", day=5, features=[("skill", "docx", 3)])
    revs.value["data_rev"] = 2
    stale = svc.profile()
    assert stale["cache"] == "stale" and stale["revs"]["data"] == 1
    assert stale["stale"] is True and stale["current_revs"]["data"] == 2
    assert stale["n_sessions"] == first["n_sessions"]
    svc.wait_idle(10)
    fresh = svc.profile()
    assert fresh["cache"] == "hit" and fresh["n_sessions"] == 4
    assert fresh["stale"] is False and fresh["rebuilding"] is False and "current_revs" not in fresh
    assert "skill:docx" in fresh["vector"]
    with svc.hub.read() as db:
        assert db.execute("SELECT COUNT(*) FROM feat_profile").fetchone()[0] == 1
    assert svc.profile(refresh=True)["cache"] == "miss"


def test_signals_and_evidence(seeded, make_service):
    svc = make_service()
    body = svc.profile(signals=[{"id": "friction:problem.retry", "weight": 0.9, "n": 4}],
                       include=("evidence",))
    assert body["vector"]["friction:problem.retry"] == 0.9
    assert body["scope_hash"] != svc.profile()["scope_hash"]
    top = body["tags"][0]["id"]
    assert body["evidence"][top]
    shell = body["evidence"].get("tool:shell")
    if shell:
        assert shell == ["s2", "s1"]  # newest first


def test_centroid_deterministic(seeded, make_service):
    a = hash_vector([("tool:shell", 1.0), ("lang:python", 0.5)])
    b = hash_vector([("lang:python", 0.5), ("tool:shell", 1.0)])
    assert a == b and abs(sum(v * v for v in a) - 1) < 1e-9
    svc = make_service()
    first = svc.profile()["centroid"]
    svc.lru.clear()
    again = svc.profile()["centroid"]
    assert max(abs(x - y) for x, y in zip(first, again, strict=True)) < 1e-6


def test_profile_without_orbit(home, make_service):
    body = make_service().profile()
    assert body["n_sessions"] == 0 and body["tags"] == [] and body["centroid"] is None


def test_stale_profile_says_it_is_rebuilding(seeded, make_service, revs):
    """While the background rebuild runs, the old body is labelled stale + rebuilding."""
    import threading

    svc = make_service()
    svc.profile()
    seeded.session("s9", project="p2", day=5, features=[("skill", "docx", 3)])
    revs.value["data_rev"] = 2
    gate = threading.Event()
    build = svc._build

    def slow_build(*args):
        gate.wait(10)
        return build(*args)

    svc._build = slow_build
    try:
        stale = svc.profile()
        assert stale["stale"] is True and stale["rebuilding"] is True
        assert stale["revs"]["data"] == 1 and stale["current_revs"]["data"] == 2
    finally:
        gate.set()
        svc.wait_idle(10)
    done = svc.profile()
    assert done["stale"] is False and done["revs"]["data"] == 2
