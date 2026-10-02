"""Card fidelity: A7 / A1 / Lite / menubar / widget read backend card fields directly.

Offline only: ``fixtures/parity_inputs.json`` is RecInputs sanitised from the synthetic
parity probe (36 synthetic Codex sessions + the upstream signals they should emit).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from test_rec_routes import env  # noqa: F401 - shared FastAPI fixture (fake gateway + inputs)

from tandem_backend.recommend import engine, relations, runs, store

FIXTURE = Path(__file__).parent / "fixtures" / "parity_inputs.json"
MEMORY = {"now": 0, "state": {}, "labels": {}, "muted_kb_rules": [], "muted_problem_types": [], "weights": {},
          "posteriors": {}, "level": None, "settings": {}}


# -- 0. run stability ----------------------------------------------------------------------

def test_empty_catalog_keeps_run_id(env, monkeypatch):  # noqa: F811
    """catalog.db present but empty (fresh install): repeated GETs reuse one run."""
    client, gw, _ = env
    gw.catalog = object()
    monkeypatch.setattr(runs, "_catalog_state", lambda catalog: (0, 0))
    first = client.get("/v1/recommendations").json()
    second = client.get("/v1/recommendations").json()
    assert first["run"]["run_id"] == second["run"]["run_id"]
    with gw.appdb.read() as conn:
        scope = store.get_run(conn, first["run"]["run_id"])["scope"]
    assert runs.run(gw, scope)["reused"] is True
    cid = first["items"][0]["candidate_id"]
    assert client.get(f"/v1/recommendations/{cid}").status_code == 200


# -- engine over the parity inputs ---------------------------------------------------------

def _inputs(variant: str | None = None) -> dict:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    inputs = doc["inputs"]
    return {**inputs, **doc["variants"][variant]} if variant else inputs


@pytest.fixture(scope="module", params=[None, "claude_code"], ids=["codex", "claude_code"])
def slate(request):
    inputs = _inputs(request.param)
    out = engine.build_slate(copy.deepcopy(inputs), copy.deepcopy(MEMORY))
    out["_variant"] = request.param
    return out


def _ranked(slate: dict) -> list[dict]:
    return [c for c in slate["candidates"] if c.get("rank")]


def _shown(slate: dict) -> list[dict]:
    return [c for c in slate["candidates"] if "ui" in c]


def _texts(cand: dict) -> list[str]:
    ui, ex = cand["ui"], cand["explain"]
    texts = [ui["title"], ui["gain"], ui["why"], ui["ev"], ui["compat"], ui["primary"], ui["target"],
             ui["save"]["label"], ui["save"]["basis"], *ui["steps"], *(row[0] for row in ui["track"]),
             *(ex[k] or "" for k in ("reason", "mechanism", "trial", "limitation", "capability"))]
    return [str(t) for t in texts]


def test_slate_ranks_cards(slate):
    assert slate["status"] == "ready" and len(_ranked(slate)) >= 10


def test_no_template_or_plan_ids_leak(slate):
    for cand in _shown(slate):
        for text in _texts(cand):
            assert "{" not in text and "RC-" not in text, (cand["rec_key"], text)


def test_save_tok_n(slate):
    for cand in _shown(slate):
        if not cand.get("problem"):
            continue
        ui = cand["ui"]
        assert ui["save"]["min_month"] > 0 or ui["tok"] < 0, cand["rec_key"]
        assert re.match(r"^≈ ", ui["save"]["label"]), ui["save"]
        assert ui["save"]["low"] <= ui["save"]["min_month"] <= ui["save"]["high"]
        assert ui["n"] == [cand["problem"]["denominator"], None] and isinstance(ui["tok"], int)
    removal = [c for c in _shown(slate) if c["kind"] == "removal"]
    assert removal and all(c["ui"]["tok"] < 0 and c["ui"]["gain"].endswith("常驻 token") for c in removal)
    allow = next(c for c in _shown(slate) if c["rec_key"] == "kb:readonly-allowlist")
    assert allow["ui"]["save"]["basis"].startswith("近 4.2 周共 36 次审批 × 每次 0.5 分钟 × 生效率 0.9")


def test_gain_is_monthly(slate):
    for cand in _shown(slate):
        problem = cand.get("problem") or {}
        if (problem.get("weekly_count") or 0) > 0 and cand["kind"] != "removal":
            assert not cand["ui"]["gain"].endswith("个会话出现"), cand["ui"]["gain"]
            assert cand["ui"]["gain"].startswith("−") and cand["ui"]["gain"].endswith("/ 月")


def test_track_has_three_rows_with_baseline(slate):
    for cand in _shown(slate):
        if not cand.get("problem"):
            continue
        track = cand["ui"]["track"]
        assert len(track) == 3 and track[0][1] is not None, (cand["rec_key"], track)
        assert all(len(row) == 4 and row[2] is None for row in track)
    env_rule = next(c for c in _shown(slate) if c["rec_key"].startswith("kb:env-quirks-rule"))
    assert env_rule["ui"]["track"][0][0] == "wrangler 相关失败"


def test_targets_name_projects_and_follow_agent(slate):
    codex = slate["_variant"] is None
    for cand in _shown(slate):
        assert "project_" not in cand["ui"]["target"], cand["ui"]["target"]
        assert "project_" not in str(cand["target"].get("path_hint") or "")
        assert set(cand["target"]["agents"]) <= ({"codex"} if codex else {"claude_code"})
        if codex:
            assert not cand["ui"]["target"].startswith("~/.claude"), cand["ui"]["target"]
    allow = next(c for c in _shown(slate) if c["rec_key"] == "kb:readonly-allowlist")
    lines = [line for line, mark in allow["ui"]["file"] if mark == "+"]
    if codex:
        assert allow["ui"]["target"] == "~/.codex/config.toml" and allow["ui"]["compat"] == "Codex"
        assert 'command = "git status"' in lines and "[[permissions.allow]]" in lines
    else:
        assert allow["ui"]["target"] == "~/.claude/settings.json"
        assert '      "Bash(gh pr view:*)",' in lines  # measured heads, not the static KB list
    project_card = next(c for c in _shown(slate) if c["rec_key"] == "kb:completion-contract")
    assert project_card["ui"]["target"] == "paper-site/AGENTS.md"


def test_titles_and_catalog_copy(slate):
    rule = next(c for c in _shown(slate) if c["rec_key"] == "kb:repeated-instruction-rule")
    assert rule["ui"]["title"] == "把重复说的要求写进规则：正文不超过 9 页"
    for cand in _shown(slate):
        if (cand.get("source") or {}).get("origin") != "catalog" or not cand.get("problem"):
            continue
        assert cand["explain"]["mechanism"].startswith("资源库条目：用")
        assert not re.search(r"对照|统计", cand["explain"]["trial"]) and len(cand["explain"]["trial"]) <= 60
    example = [c for c in _shown(slate) if c["rec_key"] == "catalog:claude-sdk-tool-hooks-example"]
    assert all(c["ui"]["lvl"] == 4 and c["ui"]["primary"] == "查看方案" for c in example)


def test_primary_follows_action(slate):
    by_key = {c["rec_key"]: c["ui"] for c in _shown(slate)}
    assert by_key["template:verify-ladder"]["primary"] == "查看教程" and by_key["template:verify-ladder"]["lvl"] == 4
    assert by_key["kb:readonly-allowlist"]["primary"] == "一键应用"
    assert by_key["kb:verify-checklist"]["primary"] == "复制片段"
    assert by_key["removal:inv_syn_2"]["primary"] == "一键移除"
    ladder = next(c for c in _shown(slate) if c["rec_key"] == "template:verify-ladder")
    assert ladder["level"] == 4  # stored level column agrees with ui.lvl


def test_removal_evidence(slate):
    removal = [c for c in _shown(slate) if c["kind"] == "removal"]
    for cand in removal:
        assert cand["ui"]["evq"]["session_uids"], cand["rec_key"]
        assert len(cand["ui"]["evq"]["session_uids"]) <= 20
    unused = next(c for c in removal if c["rec_key"] == "removal:inv_syn_2")
    assert unused["ui"]["ev"] == "36 个会话（均未调用）"
    assert unused["ui"]["evq"]["session_uids"][0] == "session_syn_35"  # newest first


def test_relations_one_per_pair(slate):
    out = relations.relations(_ranked(slate))
    pairs = [frozenset((r["a"], r["b"])) for r in out]
    assert len(pairs) == len(set(pairs))
    for r in out:
        keys = {r["a"], r["b"]}
        if any(k.startswith("kb:env-quirks-rule") for k in keys) and "kb:retry-breaker" in keys:
            assert r["relation"] != "conflicts"


# -- unit checks ---------------------------------------------------------------------------

def test_relations_priority_and_key_rules():
    def card(key, kind, pkey, **kw):
        return {"rec_key": key, "kind": kind, "problem": {"problem_id": pkey, "type": "tool_env_failure",
                                                          "key": pkey}, "source": {}, "links": {}} | kw

    same = relations.relations([card("r", "rule", "k1"), card("h", "hook", "k1")])
    assert [r["relation"] for r in same] == ["conflicts"]
    assert relations.relations([card("r", "rule", "k1"), card("h", "hook", "k2")]) == []
    # Same type, different key and kind: no duplicate on problem.type alone.
    assert relations.relations([card("a", "skill", "k1"), card("b", "skill", "k2")]) == []
    via_ref = [card("kb:x", "skill", "k1", source={"origin": "kb", "item_id": "x", "catalog_ref": "cat-x"}),
               card("catalog:cat-x", "skill", "k2", source={"origin": "catalog", "item_id": "cat-x"})]
    assert [r["relation"] for r in relations.relations(via_ref)] == ["duplicates"]


def test_instruction_var_and_title_fallback():
    from tandem_backend.recommend import kb, problems
    from tandem_backend.recommend.recall import kb_route

    signal = {"rule_id": "repeated_requirements", "reason": "重复要求：用 pnpm 而不是 npm",
              "scope": {"group": "pnpm"}}
    assert problems.instruction_of(signal) == "用 pnpm 而不是 npm"
    assert problems.instruction_of({"scope": {"group": "page-limit"}}) == "page-limit"
    rule = kb.by_id(kb.load()[0])["repeated-instruction-rule"]
    cand = kb_route.from_rule(rule, None, {}, rec_key="kb:x", match_basis="t")
    assert cand["title"] == "把重复说的要求写进规则"


def test_store_counts_and_problem_filter(env):  # noqa: F811
    client, gw, _ = env
    body = client.get("/v1/recommendations").json()
    run_id = body["run"]["run_id"]
    cards = body["items"]
    now = runs.now_ms()
    with gw.appdb.write() as conn:
        store.record_exposure(conn, cards[0]["candidate_id"], "A7", 1, "dismiss", now)
        store.record_exposure(conn, cards[1]["candidate_id"], "A7", 2, "snooze", now)
        counts = store.counts(conn, run_id, now)
        # Legacy cards carry no problem: nothing matches a problem filter, everything passes without one.
        assert store.candidates(conn, run_id, problem_ids=["nope"]) == []
        assert len(store.candidates(conn, run_id, problem_ids=None)) == len(cards)
        conn.execute("UPDATE rec_candidate SET card = json_set(card, '$.problem', json('{\"problem_id\":\"p9\"}')) "
                     "WHERE candidate_id=?", (cards[2]["candidate_id"],))
        assert [c["candidate_id"] for c in store.candidates(conn, run_id, problem_ids=["p9"])] == \
            [cards[2]["candidate_id"]]
    assert counts == {"pending": len(cards) - 2, "installed": 0, "not_applicable": 1, "snoozed": 1}
