import builtins
import time

import pytest

from orbit_backend.recommend import engine, narrate

UI_KEYS = {"dim", "type", "icon", "lvl", "aud", "title", "gain", "why", "ev", "evq", "compat", "primary", "target",
           "file", "steps", "commands", "track", "save", "tok", "tok_pct", "n"}


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
    assert slate["engine_version"] == "rec-engine-v2.4" and slate["status"] == "ready"
    assert slate["kb_version"] == "kb-1" and slate["catalog_generation"] == 7 and slate["routes"] == {"kb": 2}
    top, low = slate["candidates"]
    assert top["rank"] == 1 and top["gates"]["passed"] and set(top["ui"]) == UI_KEYS
    assert not {"kb", "item", "prior", "cost", "requirements", "gates_hint", "explain_hints"} & set(top)
    assert set(top["gates"]) == {"passed", "checks", "reasons"}
    ui = top["ui"]
    assert ui["why"] == "你手动批准了 212 次 git status、ls 这类只读命令。"
    assert ui["gain"] == "8 个会话出现" and ui["ev"] == "8 个会话" and ui["compat"] == "Claude Code · Codex"
    # INPUTS carries no trajectory ledger → no share is computed, and never an hours figure
    assert ui["save"]["time_pct"] is None and ui["save"]["label"] == "未估算" and ui["tok"] == 0
    assert ui["tok_pct"] is None
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


# 36 000 000 ms (10 h) of active time, 1M tokens, 100 user turns, 2 000 requests; per class n / tokens / ms
LEDGER = {"tokens": 1_000_000, "active_ms": 36_000_000, "turns": 100, "requests": 2000,
          "requests_by_agent": {"claude_code": 1500, "codex": 500},
          "ops": {"call": {"n": 1000, "tokens": 400_000, "ms": 18_000_000},
                  "failed": {"n": 20, "tokens": 200_000, "ms": 1_200_000},
                  "readonly": {"n": 50, "tokens": 0, "ms": 1_500_000}}}
LEDGER_INPUTS = {**INPUTS, "facts": {"trajectory": LEDGER}}


def ui_of(r, inputs=LEDGER_INPUTS):
    return engine.build_slate(inputs, MEMORY, recall=fake_recall([r]))["candidates"][0]["ui"]


def test_approval_share_is_time_only():
    save = ui_of(raw("kb:ro-allow"))["save"]
    # 13.25 approvals × 1 500 000 / 50 ms = 397 500 ms → 1.104167 % of 36 000 000 ms; tokens: the calls still run
    # × Beta(9, 1) mean .9 = .99375 ; range × [.751205, 1] = [.82946, 1.104167]
    assert save["share"] == {"time": 1.1042, "token": 0.} and save["effect"] == .9 and save["op"] == "readonly"
    assert save["time_pct"] == .9938 and save["token_pct"] == 0. and save["time_range"] == [.8295, 1.1042]
    assert save["label"] == "省时 1.0% · 省 token 0%" and save["key"] == "permission_friction"
    assert "只读审批等待" in save["basis"] and "在全部轨迹里占时间 1.1%、token 0%" in save["basis"]
    assert not any(unit in save["basis"] + save["label"] for unit in ("小时", " h", "/ 月"))


def test_failure_share_uses_measured_failed_calls():
    prob = problem(ptype="tool_env_failure", key="tool_env_failure:git", weekly_count=10)
    ui = ui_of(raw("kb:retry-breaker", kind="hook", prob=prob, prior={"alpha": 8, "beta": 2}))
    save = ui["save"]
    # 10 failures × (200 000 / 20) tokens = 100 000 → 10 % ; × (1 200 000 / 20) ms = 600 000 → 1.6667 % ; × .8
    assert save["share"] == {"time": 1.6667, "token": 10.} and save["op"] == "failed"
    assert save["time_pct"] == 1.3333 and save["token_pct"] == 8. and ui["gain"] == save["label"] == "省时 1.3% · 省 token 8.0%"


def test_rework_problems_cost_one_turn_and_cap_at_the_class_total():
    rework = problem(ptype="wrong_approach", key="wrong_approach", weekly_count=5)
    save = ui_of(raw("kb:completion-contract", kind="prompt", prob=rework, prior={"alpha": 1, "beta": 1}))["save"]
    # 5 corrections × one turn (10 000 tokens, 360 000 ms) = 5 % of each total ; × .5
    assert save["op"] == "turn" and save["share"] == {"time": 5., "token": 5.} and save["time_pct"] == 2.5
    flood = problem(ptype="tool_env_failure", key="tool_env_failure", weekly_count=500)
    save = ui_of(raw("kb:retry-breaker", kind="hook", prob=flood))["save"]
    assert save["share"] == {"time": 3.3333, "token": 20.}  # never more than all failed calls cost


def test_unmeasured_class_falls_back_to_an_average_call():
    tests = problem(ptype="buggy_output", key="buggy_output", weekly_count=4)
    untimed = {**LEDGER_INPUTS, "facts": {"trajectory": {**LEDGER, "ops": {**LEDGER["ops"], "failed": {"n": 0, "tokens": 0, "ms": 0}}}}}
    save = ui_of(raw("kb:verify-ladder", kind="workflow", prob=tests), untimed)["save"]
    # no failed call was timed → 4 × (400 000 / 1000) tokens = 1 600 → .16 % ; 4 × 18 000 ms → .2 %
    assert save["op"] == "failed" and save["share"] == {"time": .2, "token": .16} and "按平均工具调用近似" in save["basis"]


def test_removal_frees_resident_tokens_of_its_agent():
    unused = problem(ptype="installed_unused", key="installed_unused:figma", weekly_count=40,
                     vars={"tokens": 300, "agent": "claude_code", "tokens_basis": "measured"})
    ui = ui_of(raw("kb:disable-unused", kind="removal", dim="mcp", prob=unused, prior={"alpha": 6, "beta": 1}))
    save = ui["save"]
    # 300 tokens × 1 500 Claude Code requests = 450 000 → 45 % ; time not measured ; × 6/7
    assert save["op"] == "resident" and save["share"] == {"time": None, "token": 45.} and save["time_range"] is None
    assert save["token_pct"] == 38.5714 and save["label"] == "省 token 39%" and "时间代价未实测" in save["basis"]
    assert ui["tok"] == -300 and ui["tok_pct"] == -45.


def test_added_context_is_priced_as_a_share():
    ui = ui_of(raw("kb:ro-allow", cost={"setup_minutes": 1, "context_tokens": 200, "reversible": True}))
    assert ui["tok"] == 200 and ui["tok_pct"] == 30.  # 200 × 1 500 requests / 1M (target agent claude_code)
    big = {**LEDGER_INPUTS, "facts": {"trajectory": {**LEDGER, "tokens": 10 ** 9}}}
    tiny = ui_of(raw("kb:ro-allow", cost={"setup_minutes": 1, "context_tokens": 2, "reversible": True}), big)
    assert tiny["tok_pct"] == .0003  # 2 × 1 500 / 1e9: a real cost, never rounded to「不占常驻」
    # Requests without recorded tokens still count: 200 × 1 500 > 100 000 tokens is at most all of them.
    small = {**LEDGER_INPUTS, "facts": {"trajectory": {**LEDGER, "tokens": 100_000}}}
    assert ui_of(raw("kb:ro-allow", cost={"setup_minutes": 1, "context_tokens": 200, "reversible": True}),
                 small)["tok_pct"] == 100.


def test_catalog_entries_share_the_problem_not_invented_numbers():
    from orbit_backend.recommend.recall.catalog_route import from_item

    prob = problem(evidence={"session_uids": ["s1"], "signal_ids": [], "event_ids": []})
    cards = []
    for item_id in ("a", "b"):
        r = from_item({"item_id": item_id, "kind": "skill", "name": f"Skill {item_id}", "agents": [],
                       "license": "MIT", "verified": True}, prob, INPUTS, match_basis="catalog_feature")
        assert r["unit_minutes"] is None
        cards.append((narrate._save({"kind": "skill", "problem": prob}, r, INPUTS),
                      narrate._save({"kind": "skill", "problem": prob}, r, LEDGER_INPUTS)))
    assert all(old["time_pct"] is None and old["label"] == "未估算" for old, _ in cards)
    assert cards[0][1] == cards[1][1] and cards[0][1]["share"] == {"time": 1.1042, "token": 0.}


def test_pct_text_and_tiny_shares():
    assert [narrate.pct_text(v) for v in (None, 0, .04, 3.21, 12.6)] == ["—", "0%", "<0.1%", "3.2%", "13%"]
    rare = problem(ptype="tool_env_failure", key="tool_env_failure", weekly_count=.01)
    save = ui_of(raw("kb:retry-breaker", kind="hook", prob=rare))["save"]
    # .01 × 10 000 tokens = 100 → .01 % × .9 = .009 %: still a positive share, printed「<0.1%」not「0%」
    assert save["token_pct"] == .009 and save["label"] == "省时 <0.1% · 省 token <0.1%"


def test_model_cards_say_why_they_are_not_estimated():
    save = narrate._save({"kind": "model", "problem": None}, {}, LEDGER_INPUTS)
    assert save["time_pct"] is None and "推理 token" in save["basis"]


def test_token_pricing_is_symmetric():
    from orbit_backend.recommend.ranking.rank import score
    from orbit_backend.recommend.units import CONTEXT_TOKENS_PER_UNIT

    removal = raw("removal:x", kind="removal", unit_minutes=None, resident_tokens=3000,
                  cost={"setup_minutes": 0, "context_tokens": 0})
    adding = raw("kb:y", cost={"setup_minutes": 0, "context_tokens": 3000})
    s_rm, s_add = score(removal, {}, INPUTS, MEMORY), score(adding, {}, INPUTS, MEMORY)
    # both use 3000 / 2000 = 1.5 units: removal benefit 1 − e^−1.5 = .77687, addition cost 1.5
    assert CONTEXT_TOKENS_PER_UNIT == 2000
    assert s_rm["benefit_basis"] == "resident_tokens" and s_rm["benefit"] == pytest.approx(.7769, abs=1e-4)
    assert s_add["cost"] == pytest.approx(1.5)
    assert not hasattr(narrate, "TOKEN_MINUTES")


def test_class_cap_and_group_ride_on_the_save():
    save = ui_of(raw("kb:retry-breaker", kind="hook",
                     prob=problem(ptype="tool_env_failure", key="tool_env_failure:git", weekly_count=10)))["save"]
    # failed calls draw on the tool-call pool: 18 000 000 / 36 000 000 ms = 50 %, 400 000 / 1M tokens = 40 %
    assert save["group"] == "call" and save["cap"] == {"time": 50., "token": 40.}
    approval = ui_of(raw("kb:ro-allow"))["save"]
    assert approval["group"] == "readonly" and approval["cap"] == {"time": 4.1667, "token": 0.}


def _s(key, group, st, sk, p, cap=(100., 100.)):
    return {"key": key, "group": group, "effect": p, "share": {"time": st, "token": sk},
            "time_pct": None if st is None else st * p, "token_pct": None if sk is None else sk * p,
            "cap": {"time": cap[0], "token": cap[1]}}


def test_total_saving_never_exceeds_the_trajectory():
    """F10: three rework cards whose problems each claimed the whole trajectory summed to「100%」
    after the old Math.min(100, Σ) clamp; the total now stays within the operations' real share."""
    flood = [_s(f"p{i}", "turn", 100., 100., .6) for i in range(3)]
    total = narrate.total_saving(flood)
    assert total == {"time": 60., "token": 60.}  # 3 × 100 % shares scaled to the 100 % pool, × .6
    # alternatives on one problem count once (the best), distinct problems add
    alt = [_s("a", "turn", 10., 8., .5), _s("a", "turn", 10., 8., .8), _s("b", "turn", 5., None, .6)]
    assert narrate.total_saving(alt) == {"time": 11., "token": 6.4}
    # two failure problems on one tool-call pool of 30 % time: 25 + 25 → scaled to 15 + 15
    pool = [_s("f1", "call", 25., 10., .8, (30., 40.)), _s("f2", "call", 25., 10., .6, (30., 40.))]
    assert narrate.total_saving(pool) == {"time": pytest.approx(21.), "token": pytest.approx(14.)}
    assert narrate.total_saving([]) is None and narrate.total_saving([narrate._unestimated("x")]) is None


def test_volume_metrics_are_not_occurrence_counts():
    """context_pressure's first metric is millions of input tokens; it must not become millions of
    rework turns (which pinned the card at the whole trajectory, F10)."""
    from test_recommend_problems import inputs

    from orbit_backend.recommend import problems

    sig = {"signal_id": "c1", "rule_id": "context_pressure", "reason": "r", "scope": {"root_session_uid": "r1"},
           "metrics": [{"path": "cost_time.usage.token_buckets.input_tokens", "value": 3_200_000,
                        "denominator": 4_000_000, "unit": "token"},
                       {"path": "cost_time.usage.request_count", "value": 900, "unit": "count"}],
           "evidence": [{"kind": "model_call", "session_uid": "r1", "id": f"m{i}"} for i in range(900)]
           + [{"kind": "event", "session_uid": "r1", "id": "compaction1"},
              {"kind": "call", "session_uid": "r1", "id": "retry1"}]}
    out = problems.build(inputs(signals=[sig], sessions={"main": 10, "weeks": 1}))[0]
    assert out["type"] == "context_loss" and out["weekly_count"] == 2.0  # 1 compaction + 1 retry
    assert out["vars"]["count_basis"] == "evidence" and out["unit"] != "token"
    save = narrate._save({"kind": "skill", "problem": out}, {"prior": {"alpha": 3, "beta": 2}}, LEDGER_INPUTS)
    assert save["share"] == {"time": 2., "token": 2.} and save["time_pct"] == 1.2  # 2 turns of 100, × .6


def test_unmeasured_approvals_are_not_estimated():
    """R8: no read-only wait was recorded (e.g. Codex without request→decision events): the card
    says so instead of pricing approvals with the call's run time or the average tool call."""
    ops = {"call": {"n": 200, "tokens": 400_000, "ms": 18_000_000},
           "readonly": {"n": 0, "tokens": 0, "ms": 0, "unmeasured": 12}}
    untimed = {**LEDGER_INPUTS, "facts": {"trajectory": {**LEDGER, "ops": ops}}}
    prob = problem(ptype="permission_friction", key="permission_friction", weekly_count=10)
    save = ui_of(raw("kb:ro-allow", prob=prob), untimed)["save"]
    assert save["time_pct"] is None and save["token_pct"] is None and "approval_wait_ms" in save["basis"]
    assert narrate.total_saving([save]) is None or narrate.total_saving([save]) == {"time": 0., "token": 0.}


def test_partly_measured_approvals_use_the_measured_mean_and_say_so():
    ops = {"call": {"n": 200, "tokens": 400_000, "ms": 18_000_000},
           "readonly": {"n": 4, "tokens": 0, "ms": 40_000, "unmeasured": 6}}
    timed = {**LEDGER_INPUTS, "facts": {"trajectory": {**LEDGER, "ops": ops}}}
    prob = problem(ptype="permission_friction", key="permission_friction", weekly_count=2)
    save = ui_of(raw("kb:ro-allow", prob=prob), timed)["save"]
    assert save["op"] == "readonly" and save["group"] == "readonly"
    assert "按 4 次实测审批等待的均值，另 6 次未记录等待" in save["basis"]


def test_total_saving_matches_the_shared_cases():
    """The same cases drive the App's recTotal (live-lite-recs.spec.mjs), so both totals agree."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "prototypes" / "shared" / "fixtures" / "recs" / "total-cases.json"
    cases = json.loads(path.read_text())["cases"]
    assert len(cases) >= 6
    for case in cases:
        total = narrate.total_saving(case["saves"])
        assert total == pytest.approx(case["total"]), case["name"]


def test_rework_turns_are_priced_by_their_own_measured_turns():
    """R10: a correction cited on the cheap turn costs that turn, not all tokens ÷ all turns."""
    turn_cost = {"by_session": {"a": [2, 1000, 20000], "b": [8, 9000, 180000]},
                 "by_event": {"u1": [100, 2000], "u2": [900, 18000]}}
    ledger = {**LEDGER, "turn_cost": turn_cost}
    inp = {**LEDGER_INPUTS, "facts": {"trajectory": ledger}}
    exact = problem(ptype="user_correction", key="user_correction", weekly_count=1)
    exact["evidence"] = {"event_ids": ["u1"], "session_uids": ["a"]}
    op, tokens, ms, note, _ = narrate._op_cost({"kind": "skill"}, {}, exact, ledger, 1.)
    assert (op, tokens, ms) == ("turn", 100, 2000) and "证据里 1 轮" in note
    by_session = {**exact, "evidence": {"event_ids": ["zz"], "session_uids": ["b"]}}
    assert narrate._op_cost({"kind": "skill"}, {}, by_session, ledger, 2.)[1:3] == (2 * 9000 / 8, 2 * 180000 / 8)
    assert "证据里 1 轮的实测成本" in ui_of(raw("kb:ro-allow", prob=exact), inp)["save"]["basis"]
