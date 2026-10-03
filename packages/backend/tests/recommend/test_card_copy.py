"""recs-B7: card numbers and copy on real-data shapes (synthetic): ev / evq agree, no
「0 个会话出现」/「−0 常驻 token」, Chinese catalog copy, no internal ids, no「…」titles."""

from test_engine import INPUTS, MEMORY, fake_recall, problem, raw

from orbit_backend.recommend import engine, kb, narrate, problems
from orbit_backend.recommend.recall import catalog_route, kb_route, models

ITEM = {"item_id": "skill:vendor/pack/protein-design", "kind": "skill", "name": "protein-design",
        "summary": "Design proteins with diffusion models and validate folds.", "url": "https://example.test/x",
        "agents": ["claude_code"], "license": "MIT", "difficulty": 2, "risk": [], "content_hash": "h",
        "verified": True, "tags": ["python", "typescript"]}


def _card(cand, inputs=INPUTS):
    gates = {"passed": True, "checks": {}, "reasons": [], "notes": [], "level": cand.get("level") or 1}
    cand = {**cand, "explain": narrate.explain(cand, cand.get("problem"), gates)}
    cand["ui"] = narrate.ui(cand, inputs, cand)
    return cand


def test_profile_catalog_card_reads_in_chinese_without_fake_numbers():
    card = _card(catalog_route.from_item(dict(ITEM), None, INPUTS, match_basis="profile"))
    ui, explain = card["ui"], card["explain"]
    assert "资源库" in ui["why"] and "Design proteins" not in ui["why"]
    assert explain["mechanism"] and explain["trial"] and "公开资源库" in explain["limitation"]
    assert ui["steps"] and ui["primary"] == "查看方案"
    assert "0 个会话" not in ui["gain"] and ui["ev"] == "" and ui["evq"] == {}


def test_problem_catalog_card_counts_agree_with_evidence():
    prob = problem(sessions=6, evidence={"session_uids": [f"s{i}" for i in range(6)], "signal_ids": [],
                                         "event_ids": []})
    card = _card(catalog_route.from_item(dict(ITEM), prob, INPUTS, match_basis="catalog_feature"))
    assert card["ui"]["ev"] == "6 个会话" and len(card["ui"]["evq"]["session_uids"]) == 6


def test_model_card_ev_matches_its_resolvable_sessions():
    mix = [{"model_id": "m", "effort": "high", "agent": "claude_code", "sessions": 90, "readonly_sessions": 70,
            "tokens": 10, "readonly_session_uids": [f"r{i}" for i in range(20)]}]
    rows, payload = models.recall({**INPUTS, "facts": {"model_mix": mix}})
    card = _card(payload[rows[0][0]])
    assert card["ui"]["ev"] == "70 个会话" and len(card["ui"]["evq"]["session_uids"]) == 20


def test_removal_gain_is_never_minus_zero_and_estimates_say_so():
    inv = problems.build({"sessions": {"main": 40, "weeks": 6, "first_ts": "2026-05-01T00:00:00Z",
                                       "last_ts": "2026-09-01T00:00:00Z"},
                          "facts": {"usage": {"skill": {}, "mcp": {}}},
                          "inventory": [{"inv_id": "m1", "type": "mcp", "name": "figma", "enabled": True}]})
    unused = next(p for p in inv if p["type"] == "installed_unused")
    assert _card(raw("removal:m1", kind="removal", dim="mcp", prob=unused))["ui"]["gain"] == ""  # no ledger yet
    ledger = {"tokens": 100_000_000, "active_ms": 3_600_000, "turns": 10, "requests": 2000, "ops": {}}
    card = _card(raw("removal:m1", kind="removal", dim="mcp", prob=unused), {**INPUTS, "facts": {"trajectory": ledger}})
    # 500 estimated tokens × 2 000 requests = 1 % of all tokens × .9
    assert card["ui"]["gain"] == "省 token 0.9%" and "约 500 tokens（估计）" in card["ui"]["save"]["basis"]
    zero = _card(raw("removal:z", kind="removal", dim="mcp", prob=problem(ptype="installed_unused", vars={}),
                     cost={"context_tokens": 0}))
    assert zero["ui"]["gain"] == ""


def test_mechanism_never_leaks_internal_plan_ids():
    hints = {"mechanism": "常驻成本只能做减法（RC-06 第 12 行）", "reason_template": "", "vars": {}}
    card = _card(raw("kb:x", explain_hints=hints))
    assert "RC-" not in card["explain"]["mechanism"] and card["explain"]["mechanism"]


def test_keyed_rule_without_its_slot_is_not_offered():
    rules, _ = kb.load()
    env = next(r for r in rules if r.id == "env-quirks-rule")
    bare = problem(ptype="tool_env_failure", key="tool_env_failure:something", vars={},
                   evidence={"session_uids": ["s1"], "signal_ids": [], "event_ids": []})
    assert not kb_route.prefix_ok(env, bare)
    named = {**bare, "vars": {"software": "wrangler"}}
    assert kb_route.prefix_ok(env, named)
    title = kb_route.from_rule(env, named, INPUTS, rec_key="k", match_basis="problem_rule")["title"]
    assert "wrangler" in title and "…" not in title


def test_slate_cards_never_show_placeholder_numbers():
    cands = [catalog_route.from_item(dict(ITEM), None, INPUTS, match_basis="profile") | {"fusion": .01}]
    slate = engine.build_slate(INPUTS, MEMORY, recall=fake_recall(cands, []))
    for cand in slate["candidates"]:
        ui = cand.get("ui") or {}
        assert "0 个会话出现" not in str(ui.get("gain")) and "−0 " not in str(ui.get("gain"))


def test_plugin_cache_removals_disable_the_plugin_without_absolute_paths():
    import os

    from orbit_backend.recommend.recall import subtract

    home = os.path.expanduser("~")
    cache = f"{home}/.claude/plugins/cache/vendor/bio-pack/1.2.0/skills/fold/SKILL.md"
    inv = [{"inv_id": "s1", "type": "skill", "name": "fold", "resident_tokens": 2400, "config_path": cache,
            "agent": "claude_code"},
           {"inv_id": "s2", "type": "skill", "name": "dock", "resident_tokens": 2100,
            "config_path": cache.replace("fold", "dock"), "agent": "claude_code"},
           {"inv_id": "r1", "type": "rule", "name": "AGENTS.md", "lines": 300, "resident_tokens": 900,
            "config_path": f"{home}/work/AGENTS.md"}]
    probs = problems.build({"sessions": {"main": 30, "weeks": 4}, "facts": {}, "inventory": inv})
    rules, _ = kb.load()
    rows, payload = subtract.recall(probs, rules, {"facts": {}}, {})
    plugin = payload["removal:plugin:bio-pack@vendor"]
    assert len([k for k in payload if k.startswith("removal:plugin:")]) == 1
    assert plugin["title"].startswith("停用插件 bio-pack") and plugin["rec_key"] == "removal:plugin:bio-pack@vendor"
    assert plugin["target"]["path_hint"] == "~/.claude/settings.json · enabledPlugins"
    rule = next(c for k, c in payload.items() if not k.startswith("removal:plugin:"))
    assert rule["target"]["path_hint"] == "~/work/AGENTS.md"
    for cand in payload.values():
        assert home not in str(_card(cand)["ui"])
    assert subtract.tilde("/Users/someone/x") == "~/x" and subtract.tilde("AGENTS.md") == "AGENTS.md"


def test_session_claiming_card_without_uids_is_gated():
    from orbit_backend.recommend.ranking import gates

    mix = [{"model_id": "m", "effort": "high", "agent": "claude_code", "sessions": 90, "readonly_sessions": 70,
            "tokens": 10}]
    rows, payload = models.recall({**INPUTS, "facts": {"model_mix": mix}})
    value, reason = gates._bottleneck_evidence(payload[rows[0][0]], INPUTS, MEMORY)
    assert value is False and reason == "没有可回看的会话证据"
