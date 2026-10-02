"""R2: KB remedies Tandem writes itself plan as ``ready`` from the card, not the catalog twin.

Cards are built by the real KB route (``from_rule``) and stored the way the engine stores them
(internal fields dropped), then planned → previewed → applied → reverted in a fabricated home.
"""

import json

import pytest

from tandem_backend.install.errors import PlanError
from tandem_backend.recommend import kb
from tandem_backend.recommend.engine import INTERNAL
from tandem_backend.recommend.recall.kb_route import from_rule

from .test_service import CATALOG, snapshot, svc  # noqa: F401

RULES = kb.by_id(kb.load()[0])


def card(rule_id, vars_=None, project_ids=()):
    problem = {"problem_id": "p1", "type": "x", "key": "x", "vars": dict(vars_ or {}), "sessions": 1,
               "project_ids": list(project_ids),
               "evidence": {"session_uids": ["s1"], "signal_ids": [], "event_ids": []}}
    raw = from_rule(RULES[rule_id], problem, {}, rec_key=f"kb:{rule_id}", match_basis="problem")
    return {k: v for k, v in raw.items() if k not in INTERNAL}


def add(svc, cid, body):  # noqa: F811
    with svc.appdb.write() as db:
        db.execute("INSERT INTO rec_candidate (candidate_id, run_id, rec_key, kind, dim, title, passed, card, "
                   "created_at) VALUES (?, 'run1', ?, ?, ?, ?, 1, ?, 1)",
                   (cid, body["rec_key"], body["kind"], body["dim"], body["title"], json.dumps(body)))


def cycle(svc, cid):  # noqa: F811
    """plan → preview → apply → revert; returns (plan, preview, files written)."""
    before = snapshot(svc.env.home)
    asked = []
    svc.catalog_lookup = lambda item_id: asked.append(item_id)  # KB cards never reach the catalog
    plan = svc.plan({"type": "candidate", "id": cid}, agents=["claude_code"])
    assert plan["status"] == "ready", plan
    assert plan["link_reason"] is None and plan["targets"] and asked == []
    preview = svc.preview(plan["plan_id"])
    assert preview["can_apply"], preview
    assert any(t["diff"]["adds"] for t in preview["targets"])
    result = svc.apply(plan["plan_id"], preview["preview_digest"])
    written = {w["path"]: open(w["path"], encoding="utf-8").read() for w in result["written"]}
    assert all(p.startswith(str(svc.env.home)) for p in written)
    assert svc.revert(result["install_id"])["ok"]
    assert snapshot(svc.env.home) == before
    return plan, preview, written


def test_readonly_allowlist_plans_ready_and_round_trips(svc, fake_home):  # noqa: F811
    add(svc, "c-allow", card("readonly-allowlist", {"head_list": ["git status", "ls", "gh pr view"]}))
    plan, preview, written = cycle(svc, "c-allow")
    assert plan["kind"] == "permission_rule" and plan["source"]["type"] == "candidate"
    diff = [r["text"] for t in preview["targets"] for r in t["diff"]["lines"] if r["op"] == "+"]
    assert any("Bash(git status:*)" in line for line in diff)
    settings = json.loads(written[str(fake_home / ".claude/settings.json")])
    assert settings["permissions"]["allow"] == ["Bash(git status:*)", "Bash(ls:*)", "Bash(gh pr view:*)"]


def test_readonly_allowlist_without_heads_uses_preview_lines(svc):  # noqa: F811
    add(svc, "c-allow2", card("readonly-allowlist"))
    plan = svc.plan({"type": "candidate", "id": "c-allow2"}, agents=["claude_code"])
    assert plan["status"] == "ready"


def test_kb_hook_uses_tandem_template_script(svc, fake_home):  # noqa: F811
    add(svc, "c-hook", card("retry-breaker"))
    plan, _, written = cycle(svc, "c-hook")
    assert plan["kind"] == "hook"
    script = fake_home / ".claude/hooks/tandem/retry-breaker@1.py"
    assert str(script) in written and "HOOK_ID = \"retry-breaker\"" in written[str(script)]
    config = json.loads(written[str(fake_home / ".claude/hooks/tandem/retry-breaker@1.config.json")])
    assert config["matcher"] == "Bash" and config["threshold"] == 3
    hooks = json.loads(written[str(fake_home / ".claude/settings.json")])["hooks"]
    assert set(hooks) == {"PreToolUse", "PostToolUse"}
    command = hooks["PostToolUse"][0]["hooks"][0]["command"]
    assert command.startswith("python3 ") and str(script) in command and "{tandem.hooks}" not in command


def test_kb_command_hook_from_preview(svc, fake_home):  # noqa: F811
    add(svc, "c-build", card("project-build-hook", {"build_command": "pnpm build"}))
    _, _, written = cycle(svc, "c-build")
    hooks = json.loads(written[str(fake_home / ".claude/settings.json")])["hooks"]
    assert hooks == {"PostToolUse": [{"matcher": "Edit|Write",
                                      "hooks": [{"type": "command", "command": "pnpm build"}]}]}


def test_kb_rule_writes_block(svc, fake_home):  # noqa: F811
    add(svc, "c-rule", card("verify-checklist"))
    plan, preview, written = cycle(svc, "c-rule")
    assert plan["kind"] == "rule"
    text = written[str(fake_home / ".claude/CLAUDE.md")]
    assert "## 完成前" in text and "声称完成前运行测试或编译" in text and text.startswith("# me")
    assert any(r["op"] == "ai" for t in preview["targets"] for r in t["diff"]["lines"])  # ai-marked line


def test_kb_skill_and_subagent(svc, fake_home):  # noqa: F811
    add(svc, "c-skill", card("pr-review-cap"))
    _, _, written = cycle(svc, "c-skill")
    skill = written[str(fake_home / ".claude/skills/pr-review-cap/SKILL.md")]
    assert skill.startswith("---\nname: pr-review-cap") and "Codex" not in skill
    add(svc, "c-agent", card("readonly-reviewer-subagent"))
    _, _, written = cycle(svc, "c-agent")
    assert "name: readonly-reviewer" in written[str(fake_home / ".claude/agents/readonly-reviewer.md")]


def test_kb_rule_with_unfilled_slot_is_not_renderable(svc):  # noqa: F811
    add(svc, "c-env", card("env-quirks-rule"))
    with pytest.raises(PlanError) as error:
        svc.plan({"type": "candidate", "id": "c-env"}, agents=["claude_code"])
    assert error.value.code == "candidate_not_renderable"
    add(svc, "c-env2", card("env-quirks-rule", {"software": "gh"}))
    assert svc.plan({"type": "candidate", "id": "c-env2"}, agents=["claude_code"])["status"] == "ready"


def test_kb_card_for_third_party_skill_installs_its_catalog_ref(svc):  # noqa: F811
    body = card("systematic-debugging")
    body["source"]["catalog_ref"] = "foo-skill"  # a catalog skill the fake fetcher serves
    add(svc, "c-ref", body)
    svc.catalog_lookup = CATALOG.get
    plan = svc.plan({"type": "candidate", "id": "c-ref"}, agents=["claude_code"], fetch=True)
    assert plan["status"] == "ready" and plan["kind"] == "skill"
