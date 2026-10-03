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
    assert ui["save"]["min_month"] == 26 and ui["save"]["label"] == "≈ 26 min" and ui["tok"] == 0
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
