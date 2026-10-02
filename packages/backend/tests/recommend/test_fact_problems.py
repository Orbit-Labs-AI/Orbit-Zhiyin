"""SQL-fact problems: unlabelled Codex-style logs still produce recurring problems and cards."""

from __future__ import annotations

import pytest
from fact_db import GROUP, build

from tandem_backend import features
from tandem_backend.recommend import engine, problems, section


@pytest.fixture(autouse=True)
def _unbound_features(monkeypatch):
    """The analysis worker has no FeatureService; inventory must use the raw-scan fallback."""
    monkeypatch.setattr(features, "_service", None)


@pytest.fixture
def inputs(tmp_path):
    store, memo, info = build(tmp_path)
    result = section.compute(store, None, {"_rev": [1, 1]}, memo)
    result["_groups"] = info["groups"]
    return result


def test_facts_from_events_and_sequences(inputs):
    facts, groups = inputs["facts"], inputs["_groups"]
    heads = {row["command_head"]: row for row in facts["readonly_prompts"]}
    assert set(heads) >= {"git status", "ls", "gh pr view"}
    assert all(row["source"] == "permission_event" for row in heads.values())
    assert heads["git status"]["sessions"] == GROUP and facts["readonly_prompt_sessions"] == GROUP
    failures = {(row["software"], row["error_class"]): row for row in facts["failures_by_software"]}
    assert failures[("wrangler", "command_not_found")]["sessions"] == GROUP
    assert facts["retry_runs"]["sessions"] == GROUP
    assert facts["retry_runs"]["max_len"] == 4 and facts["retry_runs"]["segments"] == 2 * GROUP
    assert "pytest" in facts["retry_runs"]["examples"]
    assert facts["compactions"]["sessions"] == GROUP
    assert facts["compactions"]["count"] == 2 * GROUP
    assert facts["compactions"]["followed_by_user"] == GROUP
    assert facts["unverified_edits"]["sessions"] == GROUP
    assert set(facts["unverified_edits"]["session_uids"]) == set(groups["edits"])
    assert facts["unverified_edits"]["edits_median"] == 12
    assert facts["test_failures"]["sessions"] == GROUP
    assert facts["test_failures"]["commands"] == ["pytest"]
    days = {day["session_uid"]: day for day in facts["session_days"]}
    assert all(days[uid]["tasks"] == 3 for uid in groups["mixed"])
    assert all(days[uid]["tasks"] == 1 for uid in groups["edits"])
    assert all("tasks" in days[uid] or "task_types" in days[uid] for uid in groups["compaction"])
    assert all(days[uid]["readonly_prompts"] == 3 for uid in groups["approval"])
    inventory = {item["inv_id"]: item for item in inputs["inventory"]}
    assert inventory["skill:pdf-tools"]["lines"] == 400
    # a skill keeps only its header / first paragraph resident, never the whole 400-line file
    assert 0 < inventory["skill:pdf-tools"]["resident_tokens"] < 400
    assert inventory["rule:agents-md"]["lines"] == 261
    assert inventory["rule:agents-md"]["resident_tokens"] > 0
    assert inventory["mcp:figma"]["resident_tokens"] is None
    assert all(item["enabled"] is None for item in inventory.values())


def test_fact_problems_are_active(inputs):
    rows = problems.build(inputs)
    by_key = {row["key"]: row for row in rows}
    expected = {"tool_env_failure:retry": "tool_env_failure", "context_loss:compaction": "context_loss",
                "missing_verification:unverified": "missing_verification",
                "buggy_output:test": "buggy_output",
                "would_prompt:readonly_shell": "permission_friction",
                "tool_env_failure:wrangler": "tool_env_failure"}
    for key, type_ in expected.items():
        assert by_key[key]["type"] == type_ and by_key[key]["status"] == "active", key
    for key in ("tool_env_failure:retry", "context_loss:compaction",
                "missing_verification:unverified", "buggy_output:test"):
        problem = by_key[key]
        assert problem["basis"] == "sql_fact" and problem["sessions"] == GROUP
        assert len(problem["evidence"]["session_uids"]) == GROUP
        assert {"k", "n", "weekly", "examples"} <= set(problem["vars"])
        assert problem["weekly_count"] > 0
        assert "{" not in problem["reason"]
    assert by_key["tool_env_failure:retry"]["reason"] == "6 个会话里出现失败后原样重试，最长连续 4 次"
    assert by_key["buggy_output:test"]["reason"] == "6 个会话里同一测试反复失败（pytest）"
    unused = [row for row in rows if row["type"] == "installed_unused"]
    assert {row["vars"]["name"] for row in unused} == {"pdf-tools", "old-helper", "figma"}
    assert all(row["status"] == "active" for row in unused)


def test_signals_take_precedence_per_root(inputs):
    root = inputs["facts"]["retry_runs"]["session_uids"][0]
    inputs["signals"] = [{"signal_id": "sig", "rule_id": "identical_retries",
                          "scope": {"root_session_uid": root}, "evidence": []}]
    retry = next(row for row in problems.build(inputs) if row["key"] == "tool_env_failure:retry")
    assert retry["sessions"] == GROUP - 1 and root not in retry["evidence"]["session_uids"]


def test_disabled_items_are_not_unused(inputs):
    for item in inputs["inventory"]:
        item["enabled"] = False
    assert not [row for row in problems.build(inputs) if row["type"] == "installed_unused"]


def test_slate_reaches_six_cards_across_dims(inputs):
    slate = engine.build_slate(inputs, {})
    ranked = [cand for cand in slate["candidates"] if cand.get("rank") is not None]
    keys = {cand["rec_key"] for cand in ranked}
    assert slate["status"] == "ready", slate["status"]
    assert len(ranked) >= 6, keys
    assert len({cand["dim"] for cand in ranked}) >= 4
    assert "kb:readonly-allowlist@would_prompt:readonly_shell" in keys or "kb:readonly-allowlist" in keys
    assert "kb:retry-breaker" in keys
    assert "template:split-mixed-session" in keys
    assert keys & {"template:verify-ladder", "kb:verify-checklist"}
    assert any(key.startswith("removal:") for key in keys)
    assert not [cand["title"] for cand in ranked if "…" in cand["title"] or "{" in cand["title"]]
    mixed = next(cand for cand in slate["candidates"] if cand["rec_key"] == "template:split-mixed-session")
    assert "纠偏" not in (mixed.get("explain") or {}).get("reason", "")


def test_missing_event_table_degrades(tmp_path):
    store, memo, _ = build(tmp_path)
    with store.connect() as conn:
        conn.execute("DROP TABLE event")
        conn.commit()
    result = section.compute(store, None, {}, memo)
    sources = {row["source"] for row in result["diagnostics"]}
    assert {"permission_event", "compactions"} <= sources
    assert result["facts"]["compactions"]["sessions"] == 0
    assert result["facts"]["retry_runs"]["sessions"] == GROUP


def test_classify_and_software_helpers():
    assert section.classify_failure(127, "") == "command_not_found"
    assert section.classify_failure(1, "Error: EACCES: permission denied") == "permission_denied"
    assert section.classify_failure(1, "curl: (6) Could not resolve host: x") == "network"
    assert section.classify_failure(1, "ModuleNotFoundError: No module named 'x'") == "missing_dependency"
    assert section.classify_failure(1, "AssertionError") is None
    assert section.software_of("npx vercel --prod") == "vercel"
    assert section.software_of("uv run pytest -q") == "pytest"
    assert section.software_of("pnpm dlx wrangler deploy") == "wrangler"
    assert section.software_of("npx") == "npx"
    assert section.retry_segments([(False, "a", True, "d1"), (False, "a", True, "d1"),
                                   (False, "a", True, "d2"), (False, "a", True, "d2"),
                                   (False, "a", True, "d2")]) == [(2, "a"), (3, "a")]
