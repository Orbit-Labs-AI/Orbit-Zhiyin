import statistics
import time

import pytest

from tandem_backend.recommend.recall import catalog_route, generative, hashed, models
from tandem_backend.recommend.recall.multi import recall_all


def signal(rule_id, root, value=2):
    return {"signal_id": f"{rule_id}-{root}", "rule_id": rule_id, "reason": f"{rule_id} 在会话中反复出现",
            "metrics": [{"path": "x", "value": value}], "scope": {"root_session_uid": root, "project_id": "p1"},
            "evidence": [{"kind": "event", "session_uid": root, "id": f"ev-{rule_id}-{root}"}]}


def make(signals=(), facts=None, inventory=None, main=30, **over):
    return {"version": "rec-inputs-v1", "scope": "all", "scope_hash": "h", "agents": {"claude_code": main, "codex": 2},
            "sessions": {"main": main, "weeks": 4, "first_ts": "2026-06-01T00:00:00Z", "last_ts": "2026-09-30T00:00:00Z"},
            "signals": list(signals), "assessments": [], "tasks": [{"domain": ["web"], "task_type": ["deploy"]}],
            "facts": facts or {"usage": {"skill": {}, "mcp": {}}}, "inventory": inventory, "profile": None,
            "legacy_cards": [], **over}


def many(rule_id, n=6):
    return [signal(rule_id, f"{rule_id}-r{i}") for i in range(n)]


READONLY = {"readonly_prompts": [{"command_head": "git status", "count": 90, "sessions": 12, "session_uids": ["a"]}],
            "readonly_prompt_sessions": 12}
WRANGLER = {"failures_by_software": [{"software": "wrangler", "error_class": "auth", "count": 9, "sessions": 5,
                                      "session_uids": ["w1", "w2", "w3", "w4", "w5"]}]}
RULES_FILE = [{"inv_id": "i1", "type": "rule", "name": "AGENTS.md", "config_path": "~/AGENTS.md", "lines": 320,
               "resident_tokens": 3500}]
UNUSED = [{"inv_id": "i2", "type": "mcp", "name": "figma", "enabled": True, "resident_tokens": 900}]

CASES = [
    ("readonly", make(facts=READONLY), {}, "kb:readonly-allowlist"),
    ("retry", make(many("identical_retries")), {}, "kb:retry-breaker"),
    ("software", make(facts=WRANGLER), {}, "kb:env-quirks-rule@tool_env_failure:wrangler"),
    ("verify", make(many("acceptance_evidence_gap")), {}, "kb:verify-checklist"),
    ("verify-escalate", make(many("acceptance_evidence_gap")),
     {"state": {"kb:verify-checklist": {"status": "installed"}}}, "kb:stop-verify-hook"),
    ("correction", make(many("correction_density")), {}, "kb:completion-contract"),
    ("spiral", make(many("correction_density")), {}, "template:clear-and-restate"),
    ("repeat", make(many("repeated_requirements")), {}, "kb:repeated-instruction-rule"),
    ("communication", make(legacy_cards=[{"rule_id": "unexplained_terms", "root_session_uid": f"c{i}"} for i in range(5)],
                           profile={"languages": ["zh"]}), {}, "kb:humanizer-zh"),
    ("rules-file", make(inventory=RULES_FILE), {}, "removal:i1"),
    ("unused", make(inventory=UNUSED), {}, "removal:i2"),
    ("context", make(many("context_pressure")), {}, "kb:context-handoff"),
]


@pytest.mark.parametrize(("name", "inputs", "memory", "expected"), CASES, ids=[c[0] for c in CASES])
def test_expected_remedy_is_recalled_in_top10(name, inputs, memory, expected):
    result = recall_all(inputs, memory)
    top = [cand["rec_key"] for cand in result["candidates"][:10]]
    assert expected in top, (name, top)
    cand = next(c for c in result["candidates"] if c["rec_key"] == expected)
    assert cand["routes"] and cand["fusion"] > 0 and cand["title"] and "{" not in cand["title"]
    assert result["kb_version"].startswith("kb-v1@")


def test_recall_at_10_over_all_cases_is_one():
    hits = sum(expected in [c["rec_key"] for c in recall_all(i, m)["candidates"][:10]] for _, i, m, expected in CASES)
    assert hits / len(CASES) == 1.0


def test_escalation_ranks_hook_above_rule_once_rule_installed():
    memory = {"state": {"kb:verify-checklist": {"status": "installed"}}}
    keys = [c["rec_key"] for c in recall_all(make(many("acceptance_evidence_gap")), memory)["candidates"]]
    assert keys.index("kb:stop-verify-hook") < keys.index("kb:verify-checklist")


def test_candidate_shape_matches_contract():
    result = recall_all(make(many("identical_retries"), facts=READONLY, inventory=RULES_FILE))
    required = {"rec_key", "problem", "kind", "dim", "level", "audience_min", "title", "summary", "match_basis",
                "routes", "fusion", "evidence", "source", "target", "track", "trial", "alternatives", "generate",
                "kb", "item", "agents", "prior", "cost", "risk", "requirements", "gates_hint", "unit_minutes",
                "tags", "file", "explain_hints"}
    fusions = [c["fusion"] for c in result["candidates"]]
    assert fusions == sorted(fusions, reverse=True) and len(fusions) <= 200
    for cand in result["candidates"]:
        assert required <= cand.keys(), cand["rec_key"]
        assert 1 <= cand["level"] <= 4 and cand["track"]["extend_days"] == 28
    retry = next(c for c in result["candidates"] if c["rec_key"] == "kb:retry-breaker")
    assert retry["evidence"]["counts"]["sessions"] == 6 and retry["problem"]["status"] == "active"
    assert retry["target"]["agents"][0] == "claude_code" and retry["explain_hints"]["mechanism_row"] == 0
    assert set(result["routes"]) >= {"kb", "subtract", "catalog", "hashed_lexical"}


class FakeCatalog:
    """10k-item catalog stand-in: answers by friction feature, records every request."""

    def __init__(self, n=10_000, vector="not_indexed", delay=0.):
        self.requests, self.vector, self.delay = [], vector, delay
        types = ["tool_env_failure", "missing_verification", "permission_friction"]
        self.by_type = {t: [] for t in types}
        for i in range(n):
            self.by_type[types[i % 3]].append(i)

    def match(self, request):
        self.requests.append(request)
        if self.delay:
            time.sleep(self.delay)
        response = {"generation": 7, "vector": {"status": self.vector}, "items": []}
        if request.problem_type is None:
            response["items"] = [self._item("profile-py", [], .4)]
            return response
        ids = self.by_type.get(request.problem_type, [])[:request.limit]
        response["items"] = [self._item(f"cat-{i}", [{"feature": "friction", "value": request.problem_type},
                                                     {"feature": "topic", "value": "bash"}], 1 - j / 100)
                             for j, i in enumerate(ids)]
        response["items"].append(self._item("lexical-only", [], .99))  # no problem evidence: must be dropped
        return response

    @staticmethod
    def _item(item_id, features, score):
        return {"item_id": item_id, "type": "skill", "name": item_id, "summary": "s", "url": "https://example.test",
                "agents": ["claude_code"], "license": "MIT", "difficulty": 2, "risk": [], "content_hash": item_id,
                "version_id": "v1", "score": score, "score_parts": {"routes": {"lexical": {}}},
                "matched_features": features}


def test_catalog_route_keeps_only_problem_evidence_and_gates_profile():
    catalog = FakeCatalog()
    profile = {"tags": {"python": 2.0, "rare": 1.0}, "languages": [], "frameworks": [], "tools": [],
               "evidence_sessions": {"python": 5, "rare": 1}}
    result = recall_all(make(many("identical_retries"), profile=profile), {}, catalog=catalog)
    keys = {c["rec_key"]: c for c in result["candidates"]}
    assert keys["catalog:cat-0"]["match_basis"] == "catalog_feature" and keys["catalog:cat-0"]["source"]["license"] == "MIT"
    assert "catalog:lexical-only" not in keys
    assert keys["catalog:profile-py"]["match_basis"] == "profile"
    profile_queries = [r for r in catalog.requests if r.problem_type is None]
    assert len(profile_queries) == 1 and profile_queries[0].text == "python"
    assert result["catalog_generation"] == 7
    assert any(d["source"] == "catalog.vector" and d["status"] == "not_indexed" for d in result["diagnostics"])

    weak = {**profile, "evidence_sessions": {"python": 2}}
    catalog2 = FakeCatalog()
    recall_all(make(many("identical_retries"), profile=weak), {}, catalog=catalog2)
    assert all(r.problem_type for r in catalog2.requests)


def test_catalog_timeout_is_a_diagnostic(monkeypatch):
    monkeypatch.setattr(catalog_route, "TIMEOUT_S", .05)
    result = recall_all(make(many("identical_retries")), {}, catalog=FakeCatalog(n=30, delay=.5))
    assert any(d["status"] == "timeout" for d in result["diagnostics"])
    assert any(c["rec_key"] == "kb:retry-breaker" for c in result["candidates"])


def test_catalog_none_falls_back_to_legacy_bm25():
    result = recall_all(make(many("identical_retries")), {}, catalog=None)
    assert {"source": "catalog", "status": "fallback", "reason": "catalog_not_configured"} in result["diagnostics"]
    legacy = [c for c in result["candidates"] if "catalog" in c["routes"]]
    assert legacy and all(c["rec_key"].startswith("catalog:") for c in legacy)
    assert "catalog:tandem-diagnose-retry" in {c["rec_key"] for c in legacy}


def test_vector_ready_skips_hashed_lexical_route():
    result = recall_all(make(many("identical_retries")), {}, catalog=FakeCatalog(n=30, vector="ready"))
    assert "hashed_lexical" not in result["routes"]
    assert {"source": "hashed_lexical", "status": "skipped", "reason": "catalog_vector_ready"} in result["diagnostics"]


@pytest.mark.serial
def test_hashed_encoder_is_deterministic_and_fast():
    enc = hashed.HashedEncoder()
    a, b = enc.encode("同一命令连续失败 retry bash"), hashed.HashedEncoder().encode("同一命令连续失败 retry bash")
    assert a == b and abs(sum(v * v for v in a.values()) - 1) < 1e-9
    assert hashed.cosine(a, b) == pytest.approx(1)
    docs = {f"d{i}": f"文档 {i} 关于 重复失败 和 hook 熔断 retry{i % 7}" for i in range(100)}
    first = hashed.rank("重复失败 熔断", docs)
    start = time.perf_counter()
    for _ in range(20):
        assert hashed.rank("重复失败 熔断", docs) == first
    assert (time.perf_counter() - start) / 20 < .005  # well under 1 ms/100 docs locally; CI headroom


def test_generative_placeholder_when_no_route_matches():
    muted = ["verify-checklist", "stop-verify-hook", "verify-ladder"]
    memory = {"muted_kb_rules": muted, "settings": {"ai_generate": False}}
    result = recall_all(make(many("acceptance_evidence_gap")), memory, catalog=FakeCatalog(n=0, vector="ready"))
    cand = next(c for c in result["candidates"] if c["rec_key"].startswith("generate:"))
    assert cand["rec_key"] == "generate:rule:missing_verification" and cand["kind"] == "generate"
    assert cand["generate"]["task_id"] == "generate.rule" and cand["generate"]["template_id"] == "blank@1"
    assert cand["generate"]["evidence_ids"] and cand["explain_hints"]["limitation"] == generative.NO_AI


def test_generative_fills_missing_required_slot():
    result = recall_all(make(many("repeated_requirements")), {"settings": {"ai_generate": True}})
    cand = next(c for c in result["candidates"] if c["rec_key"] == "generate:rule:repeated_instruction")
    assert cand["generate"]["template_id"] == "agents-md-section@1"
    assert cand["explain_hints"]["limitation"] != generative.NO_AI


def test_cold_start_offers_generic_rules():
    result = recall_all(make(main=3), {})
    keys = {c["rec_key"] for c in result["candidates"]}
    assert {"generic:verify-checklist", "generic:completion-contract", "generic:context-handoff"} <= keys
    assert all(c["problem"] is None for c in result["candidates"] if c["rec_key"].startswith("generic:"))
    assert not any(k.startswith("generic:") for k in (c["rec_key"] for c in recall_all(make(main=30))["candidates"]))


def test_model_effort_route():
    facts = {"model_mix": [{"model_id": "opus", "effort": "high", "sessions": 12, "readonly_sessions": 6, "tokens": 9}]}
    keys = {c["rec_key"]: c for c in recall_all(make(facts=facts))["candidates"]}
    cand = keys["model:effort-medium-readonly"]
    assert cand["kind"] == "model" and cand["explain_hints"]["basis"] == "estimated"
    low = {"model_mix": [{"model_id": "opus", "effort": "high", "sessions": 40, "readonly_sessions": 6}]}
    assert "model:effort-medium-readonly" not in {c["rec_key"] for c in recall_all(make(facts=low))["candidates"]}


def test_graph_pairs_with_installed():
    memory = {"state": {"kb:retry-breaker": {"status": "installed"}}}
    result = recall_all(make(main=30), memory)
    keys = {c["rec_key"]: c for c in result["candidates"]}
    assert "graph" in keys["kb:systematic-debugging"]["routes"]
    assert keys["kb:systematic-debugging"]["match_basis"] == "complement"


def test_complement_survives_problem_cards_with_cap():
    from tandem_backend.recommend import engine

    memory = {"state": {"kb:retry-breaker": {"status": "installed"}}}
    inputs = make(facts=READONLY, main=30)  # a permission problem drives its own cards
    slate = engine.build_slate(inputs, memory, recall=lambda i, m, catalog=None: recall_all(i, m))
    ranked = [c for c in slate["candidates"] if c["rank"]]
    assert any(c["basis"] == "problem" for c in ranked)
    complements = [c for c in ranked if c["basis"] == "complement"]
    assert len(complements) == 1, [(c["rec_key"], c["basis"]) for c in ranked]


def test_failing_route_is_isolated(monkeypatch):
    def boom(_inputs):
        raise RuntimeError("bad facts")
    monkeypatch.setattr(models, "recall", boom)
    result = recall_all(make(many("identical_retries")))
    assert {"source": "model", "status": "failed", "reason": "RuntimeError: bad facts"} in result["diagnostics"]
    assert any(c["rec_key"] == "kb:retry-breaker" for c in result["candidates"])


@pytest.mark.serial  # wall-clock budget; flaky under the parallel pass
def test_recall_all_latency_budget():
    signals = [s for rule in ("identical_retries", "acceptance_evidence_gap", "correction_density", "context_pressure",
                              "repeated_requirements", "validation_failures") for s in many(rule)]
    inputs = make(signals, facts={**READONLY, **WRANGLER}, inventory=RULES_FILE + UNUSED)
    catalog = FakeCatalog()
    recall_all(inputs, {}, catalog=catalog)
    timings = []
    for _ in range(20):
        start = time.perf_counter()
        result = recall_all(inputs, {}, catalog=catalog)
        timings.append(time.perf_counter() - start)
    assert len(result["problems"]) >= 8
    assert statistics.quantiles(timings, n=20)[-1] < .08


AGENTS7 = ["claude_code", "codex", "hermes", "kimi", "opencode", "dsh", "pi"]
HOMES = {"claude_code": "~/.claude/", "codex": "~/.codex/"}


@pytest.mark.parametrize("agent", AGENTS7)
def test_landing_path_never_falls_back_to_another_agent(agent):
    from tandem_backend.recommend import engine, narrate

    inputs = make(facts=READONLY, agents={agent: 30})
    result = recall_all(inputs, {})
    kb = [c for c in result["candidates"] if c["source"]["origin"] in ("kb", "template")]
    assert kb
    for cand in kb:
        path = cand["target"]["path_hint"] or ""
        for owner, home in HOMES.items():
            if owner != agent:
                assert not path.startswith(home), (agent, cand["rec_key"], path)
    allow = next(c for c in kb if c["rec_key"] == "kb:readonly-allowlist")
    if agent in HOMES:
        assert allow["target"]["path_hint"].startswith(HOMES[agent])
    else:
        assert allow["target"]["path_hint"] is None
        slate = engine.build_slate(inputs, {}, recall=lambda i, m, catalog=None: result)
        card = next(c for c in slate["candidates"] if c["rec_key"] == "kb:readonly-allowlist")
        assert "needs_context" in card["gates"]["reasons"]
        if card.get("ui"):
            assert card["ui"]["primary"] == "查看方案" and card["ui"]["target"] == ""
    assert agent in narrate.AGENT_NAME


def test_catalog_query_covers_every_used_agent():
    catalog = FakeCatalog()
    recall_all(make(many("identical_retries"), agents={"claude_code": 30, "hermes": 4, "kimi": 1, "pi": 0}), {},
               catalog=catalog)
    assert catalog.requests and all(r.agents == ["claude_code", "hermes", "kimi"] for r in catalog.requests)


def test_fuse_weights_change_order():
    from tandem_backend.recommend.recall.fusion import fuse

    routes = {"kb": [("a", 1.), ("b", .9)], "catalog": [("b", 1.), ("a", .9)]}
    # w_kb=1, w_cat=.7: a = 1/61 + .7/62 = .027684, b = 1/62 + .7/61 = .027605 → a first
    default = [f.item_id for f in fuse(routes, k=60, weights={"kb": 1., "catalog": .7})]
    # w_kb=.5, w_cat=1: a = .5/61 + 1/62 = .024326, b = .5/62 + 1/61 = .024458 → b first
    swapped = [f.item_id for f in fuse(routes, k=60, weights={"kb": .5, "catalog": 1.})]
    assert default == ["a", "b"] and swapped == ["b", "a"]


def test_recall_all_weight_override_reaches_fusion():
    inputs = make(many("identical_retries"))
    base = {c["rec_key"]: c["fusion"] for c in recall_all(inputs)["candidates"]}
    boosted = {c["rec_key"]: c["fusion"] for c in recall_all(inputs, weights={"kb": 2.})["candidates"]}
    key = "kb:retry-breaker"
    assert boosted[key] > base[key]
    assert {c["rec_key"] for c in recall_all(inputs, hashed_threshold=1.01)["candidates"]
            if "hashed_lexical" in c["routes"]} == set()


def test_hashed_threshold_boundary():
    docs = {"same": "同一命令连续失败", "other": "完全无关的文本 zebra"}
    score = dict(hashed.rank("同一命令连续失败", docs, threshold=0.))["same"]
    assert score == pytest.approx(1.)  # identical text → cosine 1
    assert "same" in dict(hashed.rank("同一命令连续失败", docs, threshold=score))
    assert "same" not in dict(hashed.rank("同一命令连续失败", docs, threshold=score + 1e-6))
