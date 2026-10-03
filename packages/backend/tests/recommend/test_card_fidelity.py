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

from orbit_backend.recommend import engine, relations, runs, store

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
        ui, save = cand["ui"], cand["ui"]["save"]
        # shares of the real trajectory (facts.trajectory), never an hours / minutes figure
        assert "min_month" not in save and not re.search(r"\d\s*(h|min|小时|分钟)\b", save["label"]), save
        for unit in ("time", "token"):
            pct, rng = save[f"{unit}_pct"], save[f"{unit}_range"]
            if pct is not None:
                assert rng[0] <= pct <= rng[1] <= save["share"][unit] + 1e-9, (cand["rec_key"], save)
        assert ui["n"] == [cand["problem"]["denominator"], None] and isinstance(ui["tok"], int)
    removal = [c for c in _shown(slate) if c["kind"] == "removal"]
    assert removal and all(c["ui"]["tok"] < 0 and c["ui"]["tok_pct"] < 0 for c in removal)
    assert all(c["ui"]["gain"].startswith("省 token ") and c["ui"]["save"]["time_pct"] is None for c in removal)
    assert all("时间代价未实测" in c["ui"]["save"]["basis"] for c in removal)


def test_gain_is_a_share(slate):
    for cand in _shown(slate):
        problem = cand.get("problem") or {}
        if (problem.get("weekly_count") or 0) > 0:
            gain = cand["ui"]["gain"]
            assert gain == cand["ui"]["save"]["label"] and "%" in gain and "/ 月" not in gain, (cand["rec_key"], gain)


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
    # The parity window is ~29 days: below the 90-day window features.linked needs before it calls
    # an item unused, so the MCP is only a resident-cost removal, never「均未调用」.
    resident = next(c for c in removal if c["rec_key"] == "removal:inv_syn_2")
    assert resident["ui"]["ev"] == "36 个会话（每次都加载）"
    assert "未调用" not in resident["ui"]["ev"]
    assert resident["ui"]["evq"]["session_uids"][0] == "session_syn_35"  # newest first


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
    from orbit_backend.recommend import kb, problems
    from orbit_backend.recommend.recall import kb_route

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


def test_section_projects_name_directories():
    import sqlite3

    from orbit_backend.recommend.section import _projects

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE project (project_id TEXT, name TEXT, paths TEXT)")
    conn.executemany("INSERT INTO project VALUES (?,?,?)", [
        ("project_a", "github.com/x/paper-site", '["/synthetic/paper-site/"]'), ("project_b", "bucket", "[]")])
    diagnostics: list = []
    assert _projects(conn, {"project_a", "project_b", None}, diagnostics) == {
        "project_a": {"name": "paper-site", "root": "/synthetic/paper-site/"},
        "project_b": {"name": "bucket", "root": None}}
    assert _projects(sqlite3.connect(":memory:"), {"project_a"}, diagnostics) == {}
    assert diagnostics and diagnostics[0]["source"] == "projects"
