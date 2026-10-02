"""KB coverage: the UI demo scenarios (PR review, worktree, read-only subagent, repeated
workflow, project build hook, headless polling, deploy target, Codex effort) each have a
fact, an active problem, a KB entry and a card that reaches the slate."""

from __future__ import annotations

import sqlite3
from collections import Counter

import pytest
from fact_db_kb import build as build_db

from tandem_backend.recommend import engine, kb, narrate, problems, section
from tandem_backend.recommend.recall import generative, kb_route, models
from tandem_backend.recommend.recall.multi import recall_all

NEW_RULES = ("pr-review-cap", "worktree-isolation", "readonly-reviewer-subagent", "repeated-workflow-skill",
             "project-build-hook", "headless-poll", "deploy-target-rule", "codex-effort-medium")
BASE_KB_VERSION = "kb-v1@047c4baf"  # remedies.v1.json before these entries
MEMORY = {"now": 0, "state": {}, "labels": {}, "muted_kb_rules": [], "muted_problem_types": [], "weights": {},
          "posteriors": {}, "level": None, "settings": {}}
UIDS = [f"s{i}" for i in range(4)]
# One minimal fact per problem type (the shapes section._kb_facts emits).
FACTS = {
    "review_loop": {"review_loops": [{"session_uid": u, "rounds": 3 + i} for i, u in enumerate(UIDS)]},
    "parallel_conflict": {"parallel_conflicts": [{"project_id": "p1", "a": "s0", "b": "s1", "files": ["a.ts"]},
                                                 {"project_id": "p1", "a": "s2", "b": "s3", "files": ["b.ts"]}]},
    "readonly_review": {"readonly_reviews": [{"session_uid": u, "reads": 25, "minutes": 40} for u in UIDS]},
    "repeated_workflow": {"repeated_workflows": [{"sequence": ["git pull", "npm test", "git add", "git push"],
                                                  "sessions": 4, "session_uids": UIDS}]},
    "late_build_failure": {"late_build_failures": [{"session_uid": u, "project_id": "p1", "edits": 6,
                                                    "build_command": "npm run build"} for u in UIDS]},
    "polling": {"polling": [{"session_uid": u, "target": "train.log", "checks": 6} for u in UIDS]},
    "deploy_platform_mix": {"deploy_platforms": [{"project_id": "p1", "project": "shop", "platforms":
                                                  ["vercel", "wrangler"], "sessions": 4, "session_uids": UIDS}]},
}
RULE_FOR = {"review_loop": "pr-review-cap", "parallel_conflict": "worktree-isolation",
            "readonly_review": "readonly-reviewer-subagent", "repeated_workflow": "repeated-workflow-skill",
            "late_build_failure": "project-build-hook", "polling": "headless-poll",
            "deploy_platform_mix": "deploy-target-rule"}
CODEX_MIX = [{"model_id": "gpt-5-codex", "effort": "xhigh", "agent": "codex", "sessions": 10,
              "readonly_sessions": 6, "tokens": 900_000},
             {"model_id": "opus", "effort": "high", "agent": "claude_code", "sessions": 10,
              "readonly_sessions": 5, "tokens": 500_000}]


def inputs_for(facts: dict, main: int = 30, agents=None) -> dict:
    return {"version": "rec-inputs-v1", "scope": "all", "scope_hash": "h",
            "agents": agents or {"claude_code": main - 5, "codex": 5},
            "sessions": {"main": main, "weeks": 4, "first_ts": None, "last_ts": None},
            "signals": [], "assessments": [], "tasks": [], "facts": {"usage": {"skill": {}, "mcp": {}}, **facts},
            "inventory": None, "profile": None, "legacy_cards": []}


def _clean(text: str) -> bool:
    return "{" not in text and "RC-" not in text


@pytest.mark.parametrize("ptype", sorted(FACTS))
def test_each_new_entry_is_recalled_and_renders_cleanly(ptype):
    inputs = inputs_for(FACTS[ptype])
    built = [p for p in problems.build(inputs) if p["type"] == ptype]
    assert built and all(p["status"] == "active" for p in built), built
    rules, _ = kb.load()
    rule_id = RULE_FOR[ptype]
    if ptype == "repeated_workflow":
        rows, payload = generative.recall(built, rules, inputs, MEMORY, covered={})
        key = f"generate:skill:{built[0]['key']}"
        assert payload[key]["kind"] == "generate" and payload[key]["dim"] == "skill"
        assert payload[key]["generate"]["slots"]["sequence"] == "git pull → npm test → git add → git push"
        assert kb_route.recall(built, rules, MEMORY, inputs)[1] == {}  # generate rules belong to route ⑧
    else:
        rows, payload = kb_route.recall(built, rules, MEMORY, inputs)
        key = next(k for k in payload if k.startswith(f"kb:{rule_id}"))
    cand = payload[key]
    assert cand["source"]["item_id"] == rule_id and _clean(cand["title"])
    explained = narrate.explain(cand, cand["problem"], {"notes": []})
    assert explained["reason"] != narrate.generic_reason(cand["problem"]), explained  # template filled
    assert all(_clean(explained[f]) for f in ("reason", "mechanism", "trial", "limitation")), explained
    assert all(_clean(step) for step in cand["trial"]["steps"])


def test_codex_effort_variant_follows_agents():
    rows, payload = models.recall(inputs_for({"model_mix": CODEX_MIX}))
    assert {"model:codex-effort-medium-readonly", "model:effort-medium-readonly"} <= set(payload)
    codex = payload["model:codex-effort-medium-readonly"]
    assert codex["target"] == {"agents": ["codex"], "scope": "user", "project_id": None,
                               "path_hint": "~/.codex/config.toml model_reasoning_effort"}
    assert _clean(codex["title"]) and codex["trial"]["commands"][1] == "codex --profile readonly"
    reason = narrate.explain(codex, None, {"notes": []})
    assert _clean(reason["mechanism"])
    only_codex = models.recall(inputs_for({"model_mix": CODEX_MIX}, agents={"codex": 30}))[1]
    assert set(only_codex) == {"model:codex-effort-medium-readonly"}
    only_claude = models.recall(inputs_for({"model_mix": CODEX_MIX}, agents={"claude_code": 30}))[1]
    assert set(only_claude) == {"model:effort-medium-readonly"}


def _db_facts(tmp_path) -> tuple[dict, list]:
    path = tmp_path / "kb.db"
    roots = build_db(path)
    root_of = {r["session_uid"]: r["session_uid"] for r in roots}
    diagnostics: list = []
    conn = sqlite3.connect(path)
    try:
        facts = section._kb_facts(conn, root_of, roots, diagnostics)
    finally:
        conn.close()
    assert diagnostics == []
    return facts, roots


def test_sql_facts_make_every_new_problem_active(tmp_path):
    facts, roots = _db_facts(tmp_path)
    assert {r["session_uid"] for r in facts["review_loops"]} == {f"review-{i}" for i in range(4)}
    assert len(facts["parallel_conflicts"]) == 6 and facts["parallel_conflicts"][0]["files"] == ["src/app.ts"]
    assert {r["session_uid"] for r in facts["readonly_reviews"]} == {f"readonly-{i}" for i in range(4)}
    assert facts["repeated_workflows"] == [{"sequence": ["git pull", "npm test", "git add -A", "git commit -m wip",
                                                         "git push"], "sessions": 4,
                                            "session_uids": [f"workflow-{i}" for i in range(4)]}]
    assert facts["late_build_failures"][0]["build_command"] == "latexmk -pdf main.tex"
    assert facts["late_build_failures"][0]["edits"] == 6
    assert facts["polling"][0]["checks"] == 5
    assert facts["deploy_platforms"] == [{"project_id": "proj-d", "project": "deploy-app",
                                          "platforms": ["vercel", "wrangler"], "sessions": 4,
                                          "session_uids": [f"deploy-{i}" for i in range(4)]}]
    built = problems.build(inputs_for(facts, main=len(roots)))
    active = {p["type"] for p in built if p["status"] == "active"}
    assert set(problems.FACT_TYPES) <= active and set(problems.FACT_TYPES) <= set(problems.TYPES)
    assert all(t in narrate.TYPE_ZH for t in problems.FACT_TYPES)
    build = next(p for p in built if p["type"] == "late_build_failure")
    assert build["project_ids"] == ["proj-b"] and build["vars"]["build_command"] == "latexmk -pdf main.tex"


def test_schema_drift_degrades_to_empty_facts():
    conn = sqlite3.connect(":memory:")
    diagnostics: list = []
    facts = section._kb_facts(conn, {"s": "s"}, [], diagnostics)
    assert all(v == [] for v in facts.values()) and diagnostics[0]["source"] == "kb_facts"


def test_slate_covers_every_dimension(tmp_path):
    facts, roots = _db_facts(tmp_path)
    readonly = {"readonly_prompts": [{"command_head": "git status", "count": 40, "sessions": 8,
                                      "session_uids": [r["session_uid"] for r in roots[:8]]}],
                "readonly_prompt_sessions": 8}
    inputs = inputs_for({**facts, **readonly, "model_mix": CODEX_MIX}, main=len(roots),
                        agents={"claude_code": 15, "codex": 6})
    inputs["projects"] = {"proj-b": {"root": "/work/proj-b"}}
    inputs["signals"] = [{"signal_id": f"gap-{r['session_uid']}", "rule_id": "acceptance_evidence_gap",
                          "metrics": [{"value": 1}], "scope": {"root_session_uid": r["session_uid"]},
                          "evidence": [{"session_uid": r["session_uid"], "id": f"ev-{r['session_uid']}"}]}
                         for r in roots[:6]]
    slate = engine.build_slate(inputs, MEMORY, recall=lambda i, m, catalog=None: recall_all(i, m))
    passing = [c for c in slate["candidates"] if c["gates"]["passed"]]
    dims = Counter(c["dim"] for c in passing)
    assert dims["agent"] >= 1 and dims["model"] >= 1 and dims["flow"] >= 2, dims
    assert dims["skill"] >= 2 and dims["hook"] >= 2 and dims["rule"] >= 2, dims
    keys = {c["rec_key"] for c in passing}
    assert any(k.startswith("generate:skill:") for k in keys), keys
    for name in NEW_RULES:
        assert any((c.get("source") or {}).get("item_id") == name for c in passing), name
    worktree = next(c for c in passing if c["source"]["item_id"] == "worktree-isolation")
    assert worktree["ui"]["commands"][0] == "git worktree add ../<repo>-a -b <branch>"
    assert len(worktree["ui"]["commands"]) == len(worktree["ui"]["steps"])
    hook = next(c for c in passing if c["source"]["item_id"] == "project-build-hook")
    assert hook["target"]["path_hint"] == "proj-b/.claude/settings.json"
    assert ["        \"command\": \"latexmk -pdf main.tex\"", "ai"] in hook["ui"]["file"]


def test_kb_validates_new_fields():
    rules, version = kb.load()
    by_id = kb.by_id(rules)
    assert set(NEW_RULES) <= set(by_id) and version != BASE_KB_VERSION
    for name in NEW_RULES:
        rule = by_id[name]
        assert len(rule.commands) <= len(rule.steps)
        assert all(_clean(getattr(rule.explain, f)) for f in ("mechanism", "trial", "limitation")), name
    raw = kb.KnowledgeBase.model_validate({"schema_version": "remedies-v1", "origin": "t", "rules": [
        by_id["worktree-isolation"].model_dump(mode="json")]}).model_dump(mode="json")
    raw["rules"][0]["commands"] = ["a"] * 5
    import json
    with pytest.raises(ValueError, match="commands"):
        kb.parse(json.dumps(raw).encode())
