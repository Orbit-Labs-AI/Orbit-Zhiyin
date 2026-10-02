"""app.db recommendation store: DDL, runs, pruning, exposures, labels and memory."""

from __future__ import annotations

import json

import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.recommend import store

NOW = 1_800_000_000_000


def cand(key, *, kind="hook", dim="hook", rank=1, passed=True, priority=50.0, problem=None):
    return {"rec_key": key, "kind": kind, "dim": dim, "level": 1, "audience_min": 0,
            "title": key.upper(), "rank": rank if passed else None, "problem": problem,
            "gates": {"passed": passed, "checks": {}, "reasons": [] if passed else ["x"]},
            "score": {"priority": priority}, "ui": {"title": key}, "explain": {"reason": "r"},
            "trial": {}, "track": {}}


def run_row(run_id, digest, created, scope_hash="s1"):
    return {"run_id": run_id, "scope_hash": scope_hash, "scope": {"a": 1},
            "inputs_digest": digest, "data_rev": "1", "inventory_rev": 1,
            "engine_version": "test", "status": "ready", "created_at": created}


@pytest.fixture
def db(tmp_path):
    appdb = AppDB(tmp_path / "app.db")
    yield appdb
    appdb.close()


def test_ddl_is_idempotent(tmp_path):
    AppDB(tmp_path / "app.db").close()
    again = AppDB(tmp_path / "app.db")
    tables = {r[0] for r in again.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"rec_run", "rec_candidate", "rec_state", "rec_exposure", "label", "rec_top",
            "tracking", "rec_outcome"} <= tables
    again.close()


def test_insert_find_candidates_and_compact_gated(db):
    with db.write() as conn:
        ids = store.insert_run(conn, run_row("r1", "d1", NOW), [
            cand("kb:a", rank=1), cand("kb:b", dim="skill", kind="skill", rank=2),
            cand("kb:c", passed=False, priority=10)])
    assert ids[0] == store.candidate_id("r1", "kb:a")
    with db.read() as conn:
        assert store.find_run(conn, "s1", "d1")["run_id"] == "r1"
        assert store.latest_run(conn, "s1")["scope"] == {"a": 1}
        assert [c["rec_key"] for c in store.candidates(conn, "r1")] == ["kb:a", "kb:b"]
        assert [c["rec_key"] for c in store.candidates(conn, "r1", dim="skill")] == ["kb:b"]
        gated = store.candidates(conn, "r1", passed=False)
        assert gated[0]["rec_key"] == "kb:c" and "ui" not in gated[0]
        assert store.dim_counts(conn, "r1") == {"hook": 1, "skill": 1}
        row = conn.execute("SELECT card FROM rec_candidate WHERE rec_key='kb:a'").fetchone()
        assert ", " not in row[0]  # compact JSON


def test_prune_keeps_pinned_and_force_replace(db):
    with db.write() as conn:
        for i in range(5):
            store.insert_run(conn, run_row(f"r{i}", f"d{i}", NOW + i), [cand("kb:a")])
        store.pin_run(conn, "r0")
        assert store.prune(conn, "s1", keep=2) == 2
        kept = {r["run_id"] for r in store.list_runs(conn, "s1")}
        assert kept == {"r0", "r3", "r4"}
        assert conn.execute("SELECT count(*) FROM rec_candidate").fetchone()[0] == 3
        # Same digest again (forced) replaces the unpinned run, keeps the pinned one.
        store.insert_run(conn, run_row("r5", "d4", NOW + 5), [cand("kb:a")])
        store.insert_run(conn, run_row("r6", "d0", NOW + 6), [cand("kb:a")])
        kept = {r["run_id"] for r in store.list_runs(conn, "s1")}
    assert kept == {"r0", "r3", "r5", "r6"}


def test_exposure_view_dedupe_and_actions(db):
    with db.write() as conn:
        store.insert_run(conn, run_row("r1", "d1", NOW), [
            cand("kb:a", problem={"key": "p", "wilson_lo": 0.2, "sessions": 8}), cand("kb:b")])
        cid = store.candidate_id("r1", "kb:a")
        state = store.record_exposure(conn, cid, "A7", 0, "view", NOW)
        assert state["shown_count"] == 1 and state["status"] == "shown"
        assert state["last_evidence"] == 8
        state = store.record_exposure(conn, cid, "A7", 0, "view", NOW + store.HOUR)
        assert state["shown_count"] == 1  # within 6 h
        state = store.record_exposure(conn, cid, "lite", 0, "view", NOW + store.HOUR)
        assert state["shown_count"] == 2  # other surface
        state = store.record_exposure(conn, cid, "A7", 0, "view", NOW + 7 * store.HOUR)
        assert state["shown_count"] == 3
        state = store.record_exposure(conn, store.candidate_id("r1", "kb:b"), "A7", 1,
                                      "snooze", NOW)
        assert state["status"] == "snoozed" and state["snooze_until"] == NOW + store.SNOOZE_MS
        assert not store.visible(state, NOW + store.DAY)
        assert store.visible(state, NOW + 15 * store.DAY)
        with pytest.raises(KeyError):
            store.record_exposure(conn, "missing", "A7", 0, "view", NOW)


def test_label_effects_and_undo(db):
    with db.write() as conn:
        store.insert_run(conn, run_row("r1", "d1", NOW), [cand("kb:a"), cand("kb:b")])
        cid = store.candidate_id("r1", "kb:a")
        store.record_exposure(conn, cid, "A7", 0, "view", NOW)
        label_id, effect = store.add_label(conn, "candidate", cid, "not_applicable",
                                           "has_equivalent", now=NOW + 1)
        assert effect == {"hidden_until": None, "status": "not_applicable"}
        assert store.states(conn, ["kb:a"])["kb:a"]["status"] == "not_applicable"
        rev = store.memory_rev(conn)
        assert store.undo_label(conn, label_id, NOW + 2)
        assert store.states(conn, ["kb:a"])["kb:a"]["status"] == "shown"
        assert store.memory_rev(conn) != rev
        _, effect = store.add_label(conn, "candidate", store.candidate_id("r1", "kb:b"),
                                    "snooze", now=NOW)
        assert effect["hidden_until"] == NOW + store.SNOOZE_MS
        store.add_label(conn, "candidate", cid, "mute", now=NOW + 3)
        store.add_label(conn, "problem", "permission_friction:x", "mute", now=NOW + 3)
        assert not store.undo_label(conn, "nope", NOW)
        memory = store.memory(conn, NOW + 15 * store.DAY)
    assert memory["muted_kb_rules"] == ["a"]
    assert memory["muted_problem_types"] == ["permission_friction"]
    assert memory["state"]["kb:b"]["status"] == "candidate"  # snooze expired
    assert [entry["label"] for entry in memory["labels"]["kb:a"]] == ["mute"]


def test_memory_weights_and_posteriors(db):
    with db.write() as conn:
        store.insert_run(conn, run_row("r1", "d1", NOW), [
            cand("kb:a", kind="skill", dim="skill"), cand("kb:b", kind="hook", dim="hook")])
        a, b = store.candidate_id("r1", "kb:a"), store.candidate_id("r1", "kb:b")
        for i in range(3):
            store.add_label(conn, "candidate", a, "useful", now=NOW + i)
        store.add_label(conn, "candidate", b, "not_useful", now=NOW)
        store.add_label(conn, "candidate", b, "not_useful", "reverted", labeler="system",
                        now=NOW + 1)
        conn.execute("INSERT INTO tracking (tracking_id, install_id, candidate_id, rec_key, kind,"
                     " registered_at, baseline_from, baseline_to, metrics, effect_status) VALUES"
                     " ('t','i',?, 'kb:a','skill',0,0,0,'[]','positive')", (a,))
        memory = store.memory(conn, NOW, {"ai_generate": True, "level": 1})
    # skill: 1 + 0.5*3/8 = 1.1875 ; hook: 1 + 0.5*(-2)/7 = 0.857
    assert memory["weights"]["kind"]["skill"] == pytest.approx(1.1875)
    assert memory["weights"]["dim"]["hook"] == pytest.approx(1 - 1 / 7, abs=1e-4)
    assert memory["posteriors"]["kb:a"] == {"alpha": 4.0, "beta": 0.0}
    assert memory["posteriors"]["kb:b"] == {"alpha": 0.0, "beta": 3.0}
    assert memory["settings"] == {"ai_generate": True} and memory["level"] == 1
    json.dumps(memory)


def test_weight_is_clipped():
    assert store._weight(100, 0, 0) == 1.4
    assert store._weight(0, 0, 100) == 0.6


def test_views_stay_out_of_memory_rev_and_decay_at_read(db):
    with db.write() as conn:
        store.insert_run(conn, run_row("r1", "d1", NOW), [
            cand("kb:a", problem={"key": "p", "sessions": 8}), cand("kb:b", rank=2)])
        cid = store.candidate_id("r1", "kb:a")
        rev = store.memory_rev(conn)
        for hours in (0, 7, 14):
            store.record_exposure(conn, cid, "A7", 0, "view", NOW + hours * store.HOUR)
        assert store.memory_rev(conn) == rev
        assert "shown_count" not in store.memory(conn, NOW)["state"]["kb:a"]
        states = store.states(conn)
        cards = store.candidates(conn, "r1")
    a = next(c for c in cards if c["rec_key"] == "kb:a")
    assert store.read_decay(states["kb:a"], a) == pytest.approx(.7225)
    assert store.read_decay(states["kb:a"], {"problem": {"sessions": 12}}) == 1.0  # +50 %
    assert store.read_decay({**states["kb:a"], "install_id": "i1"}, a) == 1.0
    ordered = store.apply_decay(cards, states)
    assert [c["rec_key"] for c in ordered] == ["kb:a", "kb:b"]  # 1/.7225 < 2: stays first
    states["kb:a"]["shown_count"] = 9
    states["kb:b"] = {**states["kb:a"], "rec_key": "kb:b", "shown_count": 0}
    cards.append({**a, "rec_key": "kb:c", "score": {}})  # rank 3 slot, never shown
    ordered = store.apply_decay(cards, states)
    assert ordered[0]["score"]["decay"] == .5  # floor: position 1 → 2, ties keep slate order
    assert [c["rec_key"] for c in ordered] == ["kb:a", "kb:b", "kb:c"]
