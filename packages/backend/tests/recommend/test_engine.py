import builtins
import time

import pytest

from tandem_backend.recommend import engine, narrate

UI_KEYS = {"dim", "type", "icon", "lvl", "aud", "title", "gain", "why", "ev", "evq", "compat", "primary", "target",
           "file", "steps", "commands", "track", "save", "tok", "n"}


def problem(pid="p1", ptype="permission_friction", sessions=8, **kw):
    return {"problem_id": pid, "type": ptype, "key": ptype, "dimension": None, "sessions": sessions,
            "denominator": 20, "wilson_lo": .3, "weekly_count": 13.25, "unit": "次", "status": "active",
            "evidence": {"session_uids": ["s1", "s2"]}, "scene": None, "language": None,
            "vars": {"count": 212, "examples": "git status、ls"}} | kw


def raw(key, kind="permission_rule", dim="hook", prob="default", **kw):
    base = {
        "rec_key": key, "problem": problem() if prob == "default" else prob, "kind": kind, "dim": dim, "level": 1,
        "audience_min": 0, "title": "只读命令自动放行", "summary": "把只读命令加入白名单",
        "match_basis": "problem", "routes": {"kb": {"rank": 1, "raw": 1}}, "fusion": .03,
        "evidence": {"session_uids": ["s1", "s2"], "signal_ids": [], "counts": {}},
        "source": {"origin": "kb", "item_id": None, "verified": True},
        "target": {"agents": ["claude_code"], "scope": "user", "path_hint": "~/.claude/settings.json"},
        "track": {"triggered": "approvals_per_week", "mechanical": "approvals_per_week", "guardrail": "friction_rate"},
        "trial": {"steps": ["预览", "确认写入"]}, "alternatives": [], "generate": None,
        "kb": {"id": key.split(":")[-1], "remedy": {"pairs_with": [], "conflicts_with": []}}, "item": None,
        "agents": {"claude_code": "native", "codex": "manual"}, "prior": {"alpha": 9, "beta": 1},
        "cost": {"setup_minutes": 1, "context_tokens": 0, "reversible": True}, "risk": {"level": "low", "flags": []},
        "requirements": {}, "gates_hint": {}, "unit_minutes": .5, "tags": ["permissions"],
        "file": [['"Bash(git status:*)",', "+"]],
        "explain_hints": {"reason_template": "你手动批准了 {count} 次 {examples} 这类只读命令。",
                          "mechanism": "permissions.allow 在调用前放行", "trial": "新开会话运行 git status",
                          "limitation": "只覆盖只读命令", "vars": {}},
    }
    return base | kw


INPUTS = {"version": "rec-inputs-v1", "agents": {"claude_code": 40, "codex": 3}, "sessions": {"main": 43},
          "inventory": [], "profile": None}
MEMORY = {"now": 0, "state": {}, "labels": {}, "muted_kb_rules": [], "muted_problem_types": [], "weights": {},
          "posteriors": {}, "level": None, "settings": {}}


def fake_recall(cands, problems=None):
    def recall(inputs, memory, catalog=None):
        return {"problems": problems if problems is not None else [problem()], "candidates": cands,
                "routes": {"kb": len(cands)}, "diagnostics": [{"source": "catalog", "status": "ok"}],
                "kb_version": "kb-1", "catalog_generation": 7}
    return recall


def test_slate_shape_and_ui_keys():
    gated = raw("kb:risky", risk={"level": "high"})
    slate = engine.build_slate(INPUTS, MEMORY, recall=fake_recall([raw("kb:ro-allow"), gated]))
    assert slate["engine_version"] == "rec-engine-v2" and slate["status"] == "ready"
    assert slate["kb_version"] == "kb-1" and slate["catalog_generation"] == 7 and slate["routes"] == {"kb": 2}
    top, low = slate["candidates"]
    assert top["rank"] == 1 and top["gates"]["passed"] and set(top["ui"]) == UI_KEYS
    assert not {"kb", "item", "prior", "cost", "requirements", "gates_hint", "explain_hints"} & set(top)
    assert set(top["gates"]) == {"passed", "checks", "reasons"}
    ui = top["ui"]
    assert ui["why"] == "你手动批准了 212 次 git status、ls 这类只读命令。"
    assert ui["gain"] == "−52 次 / 月" and ui["ev"] == "8 个会话" and ui["compat"] == "Claude Code · Codex"
    # the fixture's .5 min/event has no source → no minutes figure on the card
    assert ui["save"]["min_month"] is None and ui["save"]["label"] == "未估算" and ui["tok"] == 0
    assert ui["n"] == [20, None]
    assert ui["primary"] == "一键应用" and ui["type"] == "Hook" and ui["icon"] == "bolt"
    assert ui["evq"] == {"session_uids": ["s1", "s2"]} and ui["steps"] == ["预览", "确认写入"]
    assert ui["track"][0] == ["每周审批次数", 13.25, None, "次/周"] and len(ui["track"]) == 3
    assert ui["file"] == [['"Bash(git status:*)",', "+"]]
    assert top["explain"]["mechanism"] and top["explain"]["source"] == "template"
    assert low["rank"] is None and "ui" not in low and low["gates"]["checks"]["risk_ok"] is False
    assert low["problem_type"] == "permission_friction"


def test_reason_falls_back_when_template_cannot_fill():
    r = raw("kb:x", explain_hints={"reason_template": "共 {missing} 次", "mechanism": "m"})
    cand = engine.build_slate(INPUTS, MEMORY, recall=fake_recall([r]))["candidates"][0]
    assert cand["ui"]["why"] == "8 个会话出现「只读命令反复弹审批」"
    certain = raw("kb:y", explain_hints={"reason_template": "安装后一定会提升效率"})
    assert narrate.explain(certain, certain["problem"], {})["reason"] == "8 个会话出现「只读命令反复弹审批」"


def test_statuses():
    weak = problem(status="insufficient", sessions=2, denominator=3)
    few = INPUTS | {"sessions": {"main": 3}}
    assert engine.build_slate(few, MEMORY, recall=fake_recall([raw("kb:a", prob=weak)]))["status"] == \
        "insufficient_evidence"
    assert engine.build_slate(INPUTS, MEMORY, recall=fake_recall([raw("kb:a", prob=weak)]))["status"] == "no_matching"
    generic = raw("gen:acceptance", kind="prompt", dim="rule", prob=None, match_basis="generic")
    slate = engine.build_slate(INPUTS, MEMORY, recall=fake_recall([generic], problems=[]))
    assert slate["status"] == "cold_start" and slate["candidates"][0]["ui"]["primary"] == "复制片段"


def test_risk_downgrade_reaches_ui_level():
    r = raw("kb:hook", kind="hook", risk={"level": "medium", "flags": []})
    cand = engine.build_slate(INPUTS, MEMORY, recall=fake_recall([r]))["candidates"][0]
    assert cand["level"] == 3 and cand["ui"]["lvl"] == 3 and cand["ui"]["primary"] == "预览并安装"
    assert "降为 L3，需逐行预览" in cand["explain"]["limitation"]


def test_recall_import_failure(monkeypatch):
    real_import = builtins.__import__

    def deny(name, *args, **kw):
        if name.endswith("recall.multi"):
            raise ImportError(name)
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", deny)
    slate = engine.build_slate(INPUTS, MEMORY)
    assert slate["status"] == "no_matching" and slate["candidates"] == []
    assert slate["diagnostics"] == [{"source": "recall", "status": "unavailable"}]


@pytest.mark.serial
def test_perf_200_candidates():
    cands = []
    kinds = [("permission_rule", "hook"), ("skill", "skill"), ("rule", "rule"), ("hook", "hook"), ("mcp", "mcp")]
    for i in range(200):
        kind, dim = kinds[i % 5]
        cands.append(raw(f"kb:r{i}", kind=kind, dim=dim, fusion=1 / (60 + i), tags=[f"t{i % 7}", f"u{i % 11}"],
                         prob=problem(pid=f"p{i % 12}", ptype="tool_env_failure")))
    recall = fake_recall(cands)
    engine.build_slate(INPUTS, MEMORY, recall=recall)
    start = time.perf_counter()
    slate = engine.build_slate(INPUTS, MEMORY, recall=recall)
    elapsed = time.perf_counter() - start
    assert len(slate["candidates"]) == 200
    assert elapsed < .15, elapsed  # target < 30 ms; loose bound for CI noise


def test_net_non_positive_never_ranks():
    # weekly .1 × .5 min: B = 1-exp(-.05/30) = .0016653 ; c = .3 ; p = .9 ; f = .5 + .3 + 0 = .8
    # value = (.0016653*.3*.9*.8)**.25 = (3.5970e-4)**.25 = .13772 ; cost = 1/30
    # net = .13772/1.03333 - .25 (medium risk) = -.11672 < 0
    weak = raw("kb:weak", prob=problem(weekly_count=.1), risk={"level": "medium", "flags": []})
    slate = engine.build_slate(INPUTS, MEMORY, recall=fake_recall([raw("kb:ro-allow"), weak]))
    ranked = [c for c in slate["candidates"] if c["rank"]]
    assert [c["rec_key"] for c in ranked] == ["kb:ro-allow"]
    assert all(c["score"]["utility"] > 0 for c in ranked)
    gated = next(c for c in slate["candidates"] if c["rec_key"] == "kb:weak")
    assert gated["excluded"] == engine.NET_NON_POSITIVE and engine.NET_NON_POSITIVE in gated["gates"]["reasons"]
    assert gated["score"]["utility"] == pytest.approx(.13772 / (1 + 1 / 30) - .25, abs=1e-4)


def test_sourced_unit_minutes_use_benefit_scenario_bounds():
    r = raw("kb:ro-allow", unit_minutes_source="实测：审批对话框平均停留 30 秒")
    ui = engine.build_slate(INPUTS, MEMORY, recall=fake_recall([r]))["candidates"][0]["ui"]
    # point: 13.25 × 4.345 × .5 × .9 = 25.906 ; Beta(9,1) ±1.645·sd: sd = √(9/(100·11)) = .090453
    # reduction = [.9 − .148795, min(1, .9 + .148795)] = [.751205, 1] → low 21.62, high 28.785
    assert ui["save"]["min_month"] == 26 and ui["save"]["label"] == "≈ 26 min"
    assert ui["save"]["low"] == 22 and ui["save"]["high"] == 29
    assert "实测：审批对话框平均停留 30 秒" in ui["save"]["basis"]


def test_catalog_entries_never_share_invented_minutes():
    from tandem_backend.recommend.recall.catalog_route import from_item

    prob = problem(evidence={"session_uids": ["s1"], "signal_ids": [], "event_ids": []})
    cards = []
    for item_id in ("a", "b"):
        r = from_item({"item_id": item_id, "kind": "skill", "name": f"Skill {item_id}", "agents": [],
                       "license": "MIT", "verified": True}, prob, INPUTS, match_basis="catalog_feature")
        assert r["unit_minutes"] is None
        cards.append(narrate._save({"kind": "skill", "problem": prob}, r, INPUTS))
    assert all(c["min_month"] is None and c["label"] == "未估算" for c in cards)


def test_token_pricing_is_symmetric():
    from tandem_backend.recommend.ranking.rank import score
    from tandem_backend.recommend.units import CONTEXT_TOKENS_PER_UNIT

    removal = raw("removal:x", kind="removal", unit_minutes=None, resident_tokens=3000,
                  cost={"setup_minutes": 0, "context_tokens": 0})
    adding = raw("kb:y", cost={"setup_minutes": 0, "context_tokens": 3000})
    s_rm, s_add = score(removal, {}, INPUTS, MEMORY), score(adding, {}, INPUTS, MEMORY)
    # both use 3000 / 2000 = 1.5 units: removal benefit 1 − e^−1.5 = .77687, addition cost 1.5
    assert CONTEXT_TOKENS_PER_UNIT == 2000
    assert s_rm["benefit_basis"] == "resident_tokens" and s_rm["benefit"] == pytest.approx(.7769, abs=1e-4)
    assert s_add["cost"] == pytest.approx(1.5)
    assert not hasattr(narrate, "TOKEN_MINUTES")
