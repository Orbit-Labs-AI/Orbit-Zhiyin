from __future__ import annotations

from fakectx import hook_pack

from orbit_backend.ai.generate import diagnose, rerank
from orbit_backend.ai.generate.util import numbers_ok


def _diag_pack():
    return hook_pack(content={"metrics": {"sessions": 42, "correction_rate": 0.23},
                              "transitions": [{"from": "edit", "to": "debug", "count": 9, "probability": 0.4}]},
                     numbers=[42, 0.23, 9, 0.4])


FINDING = {"step": "debug", "why": "23% 的会话出现纠正，edit→debug 共 9 次", "change": "改完先跑测试",
           "mechanism": "hook", "verify": {"metric": "correction_rate", "direction": "down", "window_days": 14},
           "evidence_session_uids": ["s1"]}


def test_numbers_ok():
    assert numbers_ok("纠正率 23%，共 42 个会话", [0.23, 42])
    assert numbers_ok("纠正率 0.23", [23])
    assert numbers_ok("3 次重试", [])
    assert not numbers_ok("纠正率 35%", [0.23])
    assert numbers_ok("约 0.27", [0.23]) and not numbers_ok("约 0.30", [0.23])


def test_diagnose_validate():
    pack = _diag_pack()
    assert diagnose.validate({"findings": [FINDING], "caveats": []}, pack) == []
    bad_metric = {**FINDING, "verify": {**FINDING["verify"], "metric": "happiness"}}
    assert "metric unknown" in diagnose.validate({"findings": [bad_metric]}, pack)[0]
    foreign = {**FINDING, "evidence_session_uids": ["s9"]}
    assert "not in evidence" in diagnose.validate({"findings": [foreign]}, pack)[0]
    assert diagnose.validate({"findings": [{**FINDING, "step": "dance"}]}, pack)
    assert diagnose.validate({"findings": [{**FINDING, "why": "纠正率高达 61%"}]}, pack)


def test_diagnose_finalize_handoff():
    out = diagnose.finalize({"findings": [FINDING, {**FINDING, "mechanism": "model"}], "caveats": ["样本少"]},
                            _diag_pack(), "ai")
    first, second = out["result"]["findings"]
    assert first["handoff"] == {"task_id": "generate.hook", "goal": "改完先跑测试", "goal_source": "ask", "refs": ["s1"]}
    assert "handoff" not in second and out["artifact"] is None
    assert diagnose.TASK["cache_ttl_s"] == 86400 and diagnose.TASK["fallback"] is None


CANDIDATES = [{"candidate_id": "c1", "title": "A", "kind": "skill", "priority": 0.9, "reason": "测试反复失败", "evidence_counts": {}},
              {"candidate_id": "c2", "title": "B", "kind": "hook", "priority": 0.7, "reason": "缺少验证", "evidence_counts": {}},
              {"candidate_id": "c3", "title": "C", "kind": "rule", "priority": 0.5, "reason": "规则", "evidence_counts": {}}]


def _rerank_pack():
    return hook_pack(content={"candidates": CANDIDATES, "profile": {"dimensions": {"verification": 0.8}}})


def _item(cid, fit, explain="pnpm test 经常失败", pair=()):
    return {"candidate_id": cid, "fit": fit, "reasons": ["good_fit_evidence"], "explain": explain, "pair_with": list(pair)}


def test_rerank_moves_unfit_last_without_touching_priority():
    output = {"items": [_item("c1", "unfit"), _item("c2", "fits", pair=["c3"]), _item("c3", "partial")]}
    assert rerank.validate(output, _rerank_pack()) == []
    out = rerank.finalize(output, _rerank_pack(), "ai")
    assert out["result"]["order"] == ["c2", "c3", "c1"]
    assert [i["candidate_id"] for i in out["result"]["items"]] == ["c1", "c2", "c3"]
    assert all("priority" not in i for i in out["result"]["items"])
    assert [c["priority"] for c in CANDIDATES] == [0.9, 0.7, 0.5]


def test_rerank_validate_rejects_foreign_and_self_pairs():
    pack = _rerank_pack()
    assert "not in input" in rerank.validate({"items": [_item("zz", "fits")]}, pack)[0]
    assert "itself" in rerank.validate({"items": [_item("c1", "fits", pair=["c1"])]}, pack)[0]
    assert "cite" in rerank.validate({"items": [_item("c1", "fits", explain="很好用")]}, pack)[0]
    assert rerank.validate({"items": [_item("c1", "fits", explain="补 verification 维度")]}, pack) == []


def test_rerank_fallback():
    pack = _rerank_pack()
    out = rerank.finalize(rerank.fallback(pack, "engine_error"), pack, "fallback")
    assert out["status"] == "fallback" and out["result"]["source"] == "template"
    assert [i["fit"] for i in out["result"]["items"]] == ["unknown"] * 3
    assert out["result"]["items"][1]["explain"] == "缺少验证" and out["result"]["order"] == ["c1", "c2", "c3"]
