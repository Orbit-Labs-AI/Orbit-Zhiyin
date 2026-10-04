"""AI enrichment is optional, bounded, evidence-linked, and cannot fabricate a candidate."""

from types import SimpleNamespace

from orbit_backend import ai
from orbit_backend.recommend import expert, runs
from orbit_backend.recommend.funnel import Funnel
from orbit_backend.recommend.recall.catalog_route import _normalise_catalog, from_item


def slate():
    return {"problems": [{"problem_id": "p", "type": "tool_retry", "status": "active", "sessions": 6}],
            "candidates": [{"rec_key": "one", "rank": 1, "kind": "skill", "gates": {"passed": True},
                            "problem": {"problem_id": "p"}},
                           {"rec_key": "two", "rank": 2, "kind": "hook", "gates": {"passed": True}}],
            "diagnostics": [], "routes": {}}


def test_expert_attaches_evidence_linked_draft_without_reading_sessions(monkeypatch):
    calls = []
    def run(task, **kwargs):
        calls.append((task, kwargs))
        return {"status": "ok", "job_id": "j", "result": {"queries": [], "suggestions": [
            {"kind": "workflow", "problem_id": "p", "title": "Review one retry", "summary": "A bounded experiment",
             "steps": ["Inspect the exit code"], "evidence_ids": ["p"], "limitations": ["Not measured"]},
            {"kind": "skill", "problem_id": "foreign", "evidence_ids": ["foreign"]}]}}
    monkeypatch.setattr(ai, "service", lambda gw: SimpleNamespace(run=run))
    result = slate()
    result["funnel"] = Funnel({}, [], {}).export()
    expert.enrich(object(), result, {"sessions": {"raw": "must not be sent"}}, {}, None, {})
    advice = result["candidates"][0]["expert_advice"]
    assert len(advice) == 1 and advice[0]["draft"] and advice[0]["effect_status"] == "unmeasured"
    assert calls[0][0] == "recommend.expert" and "sessions" not in calls[0][1]["slots"]
    assert [c["rank"] for c in result["candidates"]] == [1, 2]
    observed = result["funnel"]["upstream"]["expert"]["suggestions"]
    assert observed[0]["reason"] == "draft_advice_not_installed"
    assert observed[1]["reason"] == "unknown_problem" and not observed[1]["kept"]


def test_expert_and_rerank_failures_leave_deterministic_cards(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("model is unavailable")
    monkeypatch.setattr(ai, "service", lambda gw: SimpleNamespace(run=broken))
    result = slate()
    expert.enrich(object(), result, {}, {}, None, {})
    runs.ai_rerank(object(), result, {})
    assert len(result["candidates"]) == 2 and not any("display_rank" in c for c in result["candidates"])
    assert {d["source"] for d in result["diagnostics"]} == {"recommend.expert", "rerank.fit"}


def test_rerank_rejects_unknown_duplicates_and_preserves_omitted_ids(monkeypatch):
    def run(*a, **kw):
        return {"result": {"order": ["unknown", "two", "two"], "items": [None, {"candidate_id": "unknown"}]}}
    monkeypatch.setattr(ai, "service", lambda gw: SimpleNamespace(run=run))
    result = slate()
    runs.ai_rerank(object(), result, {})
    assert [c["display_rank"] for c in result["candidates"]] == [2, 1]
    assert [c["rank"] for c in result["candidates"]] == [1, 2]


def test_catalog_adapter_keeps_verified_source_and_high_risk():
    item = _normalise_catalog({"type": "skill", "item_id": "x", "verification": "repository_and_source_read",
                               "support": {"codex": "native"}, "risk_level": 3, "risk": ["runs_command"]})
    candidate = from_item(item, None, {"agents": {"codex": 3}}, match_basis="profile")
    assert candidate["source"]["verified"] and candidate["risk"]["level"] == "high"
    assert candidate["agents"] == {"codex": "native"}


def test_ai_query_expansion_has_a_fixed_budget_and_requires_curated_remedy(monkeypatch):
    result = slate()
    result["problems"][0]["evidence"] = {"session_uids": ["s"], "signal_ids": ["sig"], "event_ids": ["e"]}
    monkeypatch.setattr(ai, "service", lambda gw: SimpleNamespace(run=lambda *a, **kw: {
        "result": {"suggestions": [], "queries": [{"problem_id": "p", "text": "retry diagnosis"}] * 7}}))
    calls, accepted = [], []
    def match(request):
        calls.append(request)
        return {"items": [{"item_id": origin, "type": "skill", "score": .9,
                           "matched_features": [{"feature": "friction", "value": "tool_retry", "origin": origin}]}
                          for origin in ("curated", "extracted")]}
    def rank(raw, *a, **kw):
        accepted.extend(raw)
        return [], [], []
    monkeypatch.setattr(expert, "rank_candidates", rank)
    expert.enrich(object(), result, {}, {}, SimpleNamespace(match=match), {})
    assert len(calls) == 3 and [c["rec_key"] for c in accepted] == ["catalog:curated"]
    assert result["routes"]["expert_query"] == 1


def test_expansion_candidate_keeps_evidence_when_existing_slots_drop_it(monkeypatch):
    result = slate()
    result["problems"][0]["evidence"] = {"session_uids": ["s1", "s2"], "signal_ids": [], "event_ids": []}
    result["funnel"] = Funnel({}, [], {}).export()
    for index, card in enumerate(result["candidates"]):
        card.update(problem={"problem_id": "p"}, dim=f"dim-{index}", title=f"Existing {index}")
    monkeypatch.setattr(ai, "service", lambda gw: SimpleNamespace(run=lambda *a, **kw: {
        "result": {"suggestions": [], "queries": [{"problem_id": "p", "text": "remedy"}]}}))
    def match(request):
        assert request.audit
        return {"items": [{"item_id": "extra", "type": "skill", "score": .8,
                           "matched_features": [{"feature": "friction", "value": "tool_retry", "origin": "curated"}]}]}
    def rank(raw, *args, audit, **kwargs):
        card = {**raw[0], "rank": 1, "title": "Extra skill", "dim": "third",
                "evidence": {"session_uids": ["s1", "s2"]}, "score": {"priority": 31},
                "gates": {"passed": True}}
        audit.record("raw_candidates", [(card, True, [])])
        return [card], [], []
    monkeypatch.setattr(expert, "rank_candidates", rank)
    expert.enrich(object(), result, {}, {}, SimpleNamespace(match=match), {})
    assert [c["rec_key"] for c in result["candidates"]] == ["one", "two"]
    audit = result["funnel"]
    decision = audit["stages"][-1]["decisions"][0]
    assert audit["stages"][-1]["stage"] == "expert_spare_slot_selection"
    assert not decision["kept"] and "cap:problem" in decision["reasons"]
    assert audit["candidates"]["catalog:extra"]["evidence"]["session_uids"] == ["s1", "s2"]
