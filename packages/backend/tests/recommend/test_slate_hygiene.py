"""Slate hygiene: catalog-only bucket, cross-route dedupe, no leaked ``{var}`` placeholders."""

from __future__ import annotations

import json
import re

from tandem_backend.recommend import engine
from tandem_backend.recommend.recall.catalog_route import from_item

INPUTS = {"agents": {"codex": 30}, "sessions": {"main": 30, "weeks": 4},
          "facts": {"failures_by_software": [{"software": "wrangler", "sessions": 3}]}, "profile": None}
MEMORY = {"now": 0, "state": {}, "labels": {}, "weights": {}, "posteriors": {}}
PROBLEM = {"problem_id": "p1", "type": "missing_verification", "key": "k1", "sessions": 12,
           "denominator": 36, "wilson_lo": .2, "weekly_count": 3., "unit": "次", "status": "active",
           "reason": "{k} 个会话", "vars": {"k": 12, "n": 36},
           "evidence": {"session_uids": [f"s{i}" for i in range(12)], "signal_ids": [], "event_ids": []}}


def item(item_id, name, kind="skill"):
    return {"item_id": item_id, "kind": kind, "name": name, "summary": f"{name} 摘要",
            "agents": ["codex"], "license": "MIT", "verified": True, "difficulty": 2}


def raw(item_id, name, *, problem=None, overlap=True, kind="skill", fusion=.01):
    cand = from_item(item(item_id, name, kind), problem, INPUTS,
                     match_basis="catalog_feature" if problem else "profile")
    cand["fusion"] = fusion
    cand["routes"] = {"feature": {"rank": 1, "raw": .1}} if overlap else {"catalog": {"rank": 1, "raw": .1}}
    if overlap:
        cand["feature_overlap"] = {"score": .1, "matched": ["cmd:git status"]}
    return cand


def slate(raws):
    out = engine.build_slate(INPUTS, MEMORY, recall=lambda *a, **k: {"candidates": raws, "problems": [PROBLEM]})
    passing = [c for c in out["candidates"] if c["gates"]["passed"]]
    return passing, [c for c in out["candidates"] if not c["gates"]["passed"]]


def test_catalog_only_bucket_capped_below_evidence():
    raws = [raw("kb:verify", "完成前自检清单", problem=PROBLEM, fusion=.001)]
    raws += [raw(f"skill:filler{i}", f"Filler {i}", fusion=.05) for i in range(6)]
    raws.append(raw("skill:orphan", "README", overlap=False, fusion=.09))
    passing, gated = slate(raws)
    assert passing[0]["rec_key"] == "catalog:kb:verify" and passing[0]["basis"] == "problem"
    library = [c for c in passing if c["basis"] == "catalog_only"]
    assert len(library) == 3 and all(c["bucket"] == "资料库推荐" for c in library)
    assert all(c["rank"] > passing[0]["rank"] for c in library)
    reasons = {c["rec_key"]: c["excluded"] for c in gated}
    assert reasons["catalog:skill:orphan"] == "catalog_no_overlap"
    assert sum(r == "cap:catalog_only" for r in reasons.values()) == 3


def test_duplicates_across_routes_keep_evidence_card():
    kb_card = raw("kb:split-mixed-session", "一个会话只做一件事", fusion=.05)  # catalog_only copy
    tmpl = raw("template-split", "一个会话 只做一件事！", problem=PROBLEM, fusion=.01)  # same title, normalized
    other = raw("kb:verify", "完成前自检清单", problem=PROBLEM)
    passing, gated = slate([kb_card, tmpl, other])
    titles = [c["title"] for c in passing]
    assert len(titles) == 2 and "完成前自检清单" in titles
    assert next(c for c in passing if c["title"] != "完成前自检清单")["rec_key"] == "catalog:template-split"
    assert [c["excluded"] for c in gated] == ["duplicate:catalog:template-split"]


def test_no_placeholders_in_card_text():
    env = raw("kb:env-quirks-rule", "AGENTS.md：写明 {software} 的环境约定", problem=PROBLEM)
    build = raw("kb:project-build-hook", "编辑后自动运行 {build_command}", kind="hook")
    build["summary"] = "下次用到 {instruction} 时"
    passing, _ = slate([env, build])
    assert {c["title"] for c in passing} == {"AGENTS.md：写明 wrangler 的环境约定", "编辑后自动运行 构建命令"}
    slot = re.compile(r"\{[a-z_]+\}")
    for card in passing:
        text = json.dumps({k: card.get(k) for k in ("title", "summary", "explain", "ui", "trial", "track")},
                          ensure_ascii=False)
        assert not slot.search(text), slot.findall(text)
