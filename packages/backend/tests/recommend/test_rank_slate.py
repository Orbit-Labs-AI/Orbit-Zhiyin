import pytest

from tandem_backend.recommend.ranking.rank import prior, score
from tandem_backend.recommend.ranking.slate import select

INPUTS = {"agents": {"claude_code": 40}, "profile": None}
MEMORY = {"now": 0, "state": {}, "labels": {}, "weights": {}, "posteriors": {}}


def permission_raw(**kw):
    base = {"rec_key": "kb:ro-allow", "kind": "permission_rule", "dim": "hook", "fusion": .05,
            "problem": {"problem_id": "p1", "type": "permission_friction", "sessions": 8, "weekly_count": 13.25,
                        "wilson_lo": .31},
            "unit_minutes": .5, "prior": {"alpha": 9, "beta": 1}, "agents": {"claude_code": "native"},
            "cost": {"setup_minutes": 0, "context_tokens": 0}, "risk": {"level": "low"}, "tags": []}
    return base | kw


def test_priority_formula_hand_computed():
    s = score(permission_raw(), {}, INPUTS, MEMORY, max_fusion=.05)
    # B = 1-exp(-13.25*.5/30) = .19815; c = .31; p = .9; f = .5*1 + .3*1 + .2*0 = .8
    assert s["benefit"] == pytest.approx(.1981, abs=1e-4)
    assert s["p_effective"] == .9 and s["fit"] == .8 and s["risk"] == .05
    assert s["priority"] == 3.92
    costly = score(permission_raw(cost={"setup_minutes": 2, "context_tokens": 500}), {}, INPUTS, MEMORY,
                   max_fusion=.05)
    assert costly["priority"] == 2.86


def test_default_prior_and_posterior_update():
    assert prior({"kind": "hook"}) == (8, pytest.approx(2))
    raw = permission_raw(prior=None)
    s = score(raw, {}, INPUTS, MEMORY | {"posteriors": {"kb:ro-allow": {"alpha": 0, "beta": 10}}})
    assert s["p_effective"] == pytest.approx(9 / 20, abs=1e-4)


def test_decay_curve_and_reset():
    def decay(state, labels=None, sessions=8):
        raw = permission_raw()
        raw["problem"]["sessions"] = sessions
        memory = MEMORY | {"state": {"kb:ro-allow": state}, "labels": {"kb:ro-allow": labels or []}}
        return score(raw, {}, INPUTS, memory)["decay"]

    assert decay({"shown_count": 1, "last_evidence": 8}) == 1
    assert decay({"shown_count": 2, "last_evidence": 8}) == .85
    assert decay({"shown_count": 3, "last_evidence": 8}) == pytest.approx(.7225)
    assert decay({"shown_count": 9, "last_evidence": 8}) == .5
    assert decay({"shown_count": 9, "last_evidence": 5}) == 1  # evidence +60 %
    assert decay({"shown_count": 9, "last_evidence": 8}, [{"label": "open"}]) == 1
    assert score(permission_raw(), {}, INPUTS, MEMORY)["decay"] == 1


def test_personalization_clip():
    memory = MEMORY | {"weights": {"kind": {"permission_rule": 3}, "dim": {"hook": 2}}}
    assert score(permission_raw(), {}, INPUTS, memory)["personal"] == 1.5
    memory = MEMORY | {"weights": {"kind": {"permission_rule": .1}}}
    assert score(permission_raw(), {}, INPUTS, memory)["personal"] == .5


def test_gated_and_generic_bases_still_score():
    s = score({"rec_key": "g", "kind": "prompt", "problem": None}, {}, INPUTS, MEMORY)
    assert s["benefit"] == .1 and s["confidence"] == .1
    s = score({"rec_key": "m", "kind": "model", "problem": None, "confidence": .6}, {}, INPUTS, MEMORY)
    assert s["benefit"] == .3 and s["confidence"] == .6
    profile = INPUTS | {"profile": {"evidence_sessions": 10}}
    s = score({"rec_key": "pr", "kind": "skill", "problem": None, "match_basis": "profile"}, {}, profile, MEMORY)
    assert s["benefit"] == .15 and s["confidence"] == .25


def cand(key, priority, kind="skill", dim="skill", pid="p1", tags=()):
    problem = {"problem_id": pid, "type": "t" + str(pid)} if pid else None
    return {"rec_key": key, "kind": kind, "dim": dim, "problem": problem, "tags": list(tags),
            "score": {"priority": priority}}


def test_mmr_caps_and_alternatives_folding():
    pool = [cand("a", 10, "hook", "hook"), cand("b", 9, "hook", "hook"),  # b folds into a (same problem+dim)
            cand("c", 8, "rule", "rule"), cand("d", 7, "skill", "skill"),  # d: problem p1 already has 2
            cand("e", 6, "skill", "skill", "p2"), cand("f", 5, "skill", "skill", "p3"),
            cand("g", 4, "skill", "skill", "p4"),  # third skill → cap
            cand("h", 3, "builtin", "rule", "p5"), cand("i", 2, "builtin", "rule", "p6")]
    ranked = select(pool)
    keys = [c["rec_key"] for c in ranked]
    assert keys[:2] == ["a", "c"]
    assert set(keys) == {"a", "c", "e", "f", "h"}
    assert [c["rank"] for c in ranked] == [1, 2, 3, 4, 5]
    a = next(c for c in ranked if c["rec_key"] == "a")
    assert [alt["rec_key"] for alt in a["alternatives"]] == ["b"]
    excluded = {c["rec_key"]: c["excluded"] for c in pool if c.get("rank") is None}
    assert excluded == {"b": "folded:a", "d": "cap:problem", "g": "cap:skill", "i": "cap:builtin"}


def test_mmr_prefers_variety_on_near_ties():
    pool = [cand("x1", 10, pid="p1", tags=["git"]), cand("x2", 9.9, "rule", "rule", "p1", tags=["git"]),
            cand("y", 9.8, "hook", "hook", "p2", tags=["deploy"])]
    assert [c["rec_key"] for c in select(pool)][:2] == ["x1", "y"]


def test_generic_only_when_nothing_else_passes():
    generic = [cand(f"g{i}", 5 - i, "prompt", "rule", None) for i in range(5)]
    mixed = select([*generic, cand("p", 1, "hook", "hook")])
    assert [c["rec_key"] for c in mixed] == ["p"]
    ranked = select([cand(f"g{i}", 5 - i, "prompt", "rule", None) for i in range(5)])
    assert len(ranked) == 3 and ranked[0]["rec_key"] == "g0"


def test_tie_break_by_rec_key():
    ranked = select([cand("b", 1, pid="p1"), cand("a", 1, "hook", "hook", pid="p2")])
    assert ranked[0]["rec_key"] == "a"


def test_utility_orders_clipped_priorities():
    low = cand("a-low", 0, "hook", "hook", "p1")
    high = cand("z-high", 0, "skill", "skill", "p2")
    low["score"]["utility"], high["score"]["utility"] = -.002, .001
    assert [c["rec_key"] for c in select([low, high])] == ["z-high", "a-low"]
    weak = score(permission_raw(problem={"problem_id": "p", "weekly_count": .1, "wilson_lo": .05}), {}, INPUTS, MEMORY)
    assert weak["priority"] == 0 and weak["utility"] < 0
