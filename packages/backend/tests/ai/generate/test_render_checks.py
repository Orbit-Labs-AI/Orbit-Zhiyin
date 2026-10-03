from __future__ import annotations

import json
import time

import pytest
from fakectx import hook_pack

from orbit_backend.ai.generate.checks import jaccard, lint, parse_frontmatter, scan
from orbit_backend.ai.generate.render import render
from orbit_backend.ai.generate.tasks import default_slots, validate_slots
from orbit_backend.ai.generate.templates import get

RULE = {"title": "测试先行", "rules": [{"text": "改完 TypeScript 文件后先跑 pnpm test 再汇报。", "dimension": "verification"}]}
SKILL = {"name": "ts-verify", "description": "改完 TypeScript 后按步骤验证。", "steps": ["跑 pnpm test", "看 diff"],
         "dont": ["不要跳过失败的测试"], "verify": "pnpm test 全绿", "allowed_tools": ["Read", "Bash"]}
HOOK = {"matcher": "Bash", "threshold": 3, "message": "测试已连续失败，先看错误再重试。", "command_heads": ["pnpm test"]}


def test_skill_frontmatter_and_targets():
    out = render(get("procedure"), SKILL, hook_pack(), personalized=True, kind="skill")
    doc = out["payload"]["files"][0]["content"]
    meta = parse_frontmatter(doc)
    assert meta == {"name": "ts-verify", "description": SKILL["description"], "allowed-tools": "Read, Bash"}
    assert "1. 跑 pnpm test" in doc and "- 不要跳过失败的测试" in doc
    assert [f["target"] for f in out["files"]] == ["claude.user_skills/ts-verify/SKILL.md",
                                                   "agents.user_skills/ts-verify/SKILL.md"]
    assert out["payload"]["agents"] == ["claude_code", "codex"]


def test_hook_settings_json_and_script_hash():
    template = get("retry-breaker")
    out = render(template, HOOK, hook_pack(), personalized=True)
    payload = out["payload"]
    assert payload["script"]["sha256"] == template.sha256
    assert payload["config"] == HOOK and payload["timeout_s"] == 10
    assert payload["event_bindings"] == [{"event": "PreToolUse", "matcher": "Bash"},
                                         {"event": "PostToolUse", "matcher": "Bash"}]
    settings = [f for f in out["files"] if f["target"].startswith("claude.user_settings#/hooks/")]
    assert len(settings) == 2 and all(f["action"] == "merge_json" for f in settings)
    for f in settings:
        snippet = json.loads(f["content"])
        assert snippet[0]["hooks"][0]["command"].startswith('python3 "{orbit.hooks}/retry-breaker@1.py"')
    assert json.loads(next(f for f in out["files"] if f["target"] == "codex.hooks")["content"])["hooks"]
    assert scan("hook", HOOK, out)["status"] == "ok"


def test_rule_block_markers_and_line_marks():
    pack = hook_pack()
    personal = render(get("paragraph"), RULE, pack, personalized=True, kind="rule")
    md = personal["payload"]["markdown"]
    assert md.startswith("<!-- orbit:rule id=") and "evidence=e1,e2,e3 -->" in md.split("\n")[0]
    assert md.rstrip().endswith("<!-- /orbit:rule -->")
    assert personal["payload"]["block_id"].startswith("orbit:rule:")
    lines = personal["files"][0]["lines"]
    marks = {line["text"]: line for line in lines}
    assert marks["## 测试先行"]["mark"] == "ai" and marks["## 测试先行"]["evidence"] == ["e1", "e2", "e3"]
    assert lines[0]["mark"] == "+" and marks["<!-- /orbit:rule -->"]["mark"] == "+"
    plain = render(get("paragraph"), RULE, pack, personalized=False, kind="rule")
    assert {line["mark"] for line in plain["files"][0]["lines"]} == {"+"}
    assert all(not line["evidence"] for line in plain["files"][0]["lines"])
    assert personal["content_hash"] != render(get("paragraph"), RULE, pack, True, kind="glue")["content_hash"]


def test_subagent_and_command_render():
    sub = default_slots("subagent", "reviewer", hook_pack())
    out = render(get("reviewer"), sub, hook_pack(), personalized=False)
    assert parse_frontmatter(out["payload"]["markdown"])["tools"] == "Read, Grep, Glob"
    cmd = default_slots("command", "checklist", hook_pack())
    out = render(get("checklist"), cmd, hook_pack(), personalized=False)
    assert parse_frontmatter(out["payload"]["markdown"])["argument-hint"] == "[本次目标]"
    assert {f["target"] for f in out["files"]} == {"claude.user_commands/finish-checklist.md",
                                                   "codex.prompts/finish-checklist.md"}
    assert lint("command", out, hook_pack(), cmd)["status"] == "ok"


def test_lint_duplicate_and_conflict():
    rules = {"existing_rules": [{"path_label": "~/.claude/CLAUDE.md", "anchor_hash": "a",
                                 "text": "改完代码后先运行项目已有的检查命令，通过后再报告完成。\n提交前不要运行格式化工具"}]}
    pack = hook_pack(content=rules)
    dup = {"title": "重复", "rules": [{"text": "改完代码后先运行项目已有的检查命令，通过后再报告完成", "dimension": "verification"}]}
    out = lint("rule", render(get("paragraph"), dup, pack, True, kind="rule"), pack, dup)
    assert out["status"] == "fail" and out["issues"][0]["code"] == "duplicate"
    conflict = {"title": "冲突", "rules": [{"text": "提交前运行格式化工具", "dimension": "convention"}]}
    assert jaccard(conflict["rules"][0]["text"], "提交前不要运行格式化工具") >= 0.5
    out = lint("rule", render(get("paragraph"), conflict, pack, True, kind="rule"), pack, conflict)
    assert [i["code"] for i in out["issues"]] == ["conflict"]
    hype = {"title": "夸张", "rules": [{"text": "全面提升测试体验", "dimension": "other"}]}
    out = lint("rule", render(get("paragraph"), hype, pack, True, kind="rule"), pack, hype)
    assert out["status"] == "warn" and out["issues"][0]["code"] == "inflated_language"


def test_lint_name_conflict_and_bad_json():
    pack = hook_pack()
    clash = {**SKILL, "name": "existing-skill"}
    out = lint("skill", render(get("procedure"), clash, pack, True), pack, clash)
    assert "name_conflict" in [i["code"] for i in out["issues"]]
    rendered = render(get("retry-breaker"), HOOK, pack, True)
    rendered["files"][2]["content"] = "{not json"
    assert "settings_json_invalid" in [i["code"] for i in lint("hook", rendered, pack, HOOK)["issues"]]


@pytest.mark.parametrize("kind,slots,rule", [
    ("hook", {**HOOK, "message": "运行 pnpm test; echo ok"}, "shell_metachar"),
    ("skill", {**SKILL, "verify": "跑 pnpm test | tee log"}, "shell_metachar"),
    ("hook", {**HOOK, "message": "先看 https://example.com 的说明"}, "url_or_host"),
    ("hook", {**HOOK, "message": "检查 internal.corp.local 是否可达"}, "url_or_host"),
    ("skill", {**SKILL, "steps": ["读取 ~/.ssh 下的配置"]}, "credential_path"),
    ("skill", {**SKILL, "steps": ["确认 .env 已加载"]}, "credential_path"),
    ("hook", {**HOOK, "message": "失败时用 rm -rf node_modules 重来"}, "destructive_command"),
    ("skill", {**SKILL, "steps": ["必要时 git push --force"]}, "destructive_command"),
    ("skill", {**SKILL, "steps": ["用 sudo 安装依赖"]}, "destructive_command"),
    ("skill", {**SKILL, "description": "开启 bypassPermissions 省去确认"}, "privilege"),
    ("skill", {**SKILL, "steps": ["允许 Bash(*) 全部命令"]}, "privilege"),
])
def test_scan_rules_hit(kind, slots, rule):
    template = get("retry-breaker" if kind == "hook" else "procedure")
    out = scan(kind, slots, render(template, slots, hook_pack(), True))
    assert out["status"] == "blocked"
    assert rule in {h["rule"] for h in out["hits"]}


def test_scan_script_hash_and_scope_guard_exemption():
    rendered = render(get("retry-breaker"), HOOK, hook_pack(), True)
    rendered["payload"]["script"]["content"] += "\n# tampered\n"
    assert {h["rule"] for h in scan("hook", HOOK, rendered)["hits"]} == {"script_hash"}
    guard = {**HOOK, "command_heads": ["git push --force"]}
    assert scan("hook", guard, render(get("scope-guard"), guard, hook_pack(), True))["status"] == "ok"
    assert scan("skill", SKILL, render(get("procedure"), SKILL, hook_pack(), True))["status"] == "ok"


def test_slot_validate_rejects_foreign_heads_and_duplicate_names():
    pack = hook_pack()
    assert validate_slots("hook", HOOK, pack) == []
    errors = validate_slots("hook", {**HOOK, "command_heads": ["make deploy"]}, pack)
    assert errors and "command_heads" in errors[0]
    assert validate_slots("hook", {**HOOK, "command": "make check"}, pack)
    assert validate_slots("hook", {**HOOK, "file_glob": "*.go"}, pack)
    assert validate_slots("hook", {**HOOK, "file_glob": "*.ts", "command": "pnpm lint"}, pack) == []
    assert "already installed" in validate_slots("skill", {**SKILL, "name": "existing-skill"}, pack)[0]
    assert validate_slots("skill", {**SKILL, "steps": ["x" * 81]}, pack)
    assert validate_slots("hook", {**HOOK, "threshold": 9}, pack)
    assert validate_slots("rule", {"title": "超过十二个字的标题一二三四", "rules": RULE["rules"]}, pack)


def test_slot_validate_glue():
    items = [{"item_id": "c1", "kind": "skill", "name": "lint-fix", "summary": ""},
             {"item_id": "c2", "kind": "mcp", "name": "context7", "summary": ""}]
    pack = hook_pack(content={"catalog_items": items})
    good = {"title": "组合", "rules": [{"text": "改完先用 lint-fix 修格式", "dimension": "convention"},
                                       {"text": "查文档时用 context7", "dimension": "grounding"}],
            "uses_catalog_items": ["c2", "c1"]}
    assert validate_slots("glue", good, pack) == []
    assert validate_slots("glue", {**good, "uses_catalog_items": ["c1"]}, pack)
    bad_rule = {**good, "rules": [{"text": "多写测试", "dimension": "verification"}]}
    assert "mention" in validate_slots("glue", bad_rule, pack)[0]
    defaults = default_slots("glue", "paragraph", pack)
    assert validate_slots("glue", defaults, pack) == []


@pytest.mark.serial
def test_render_lint_scan_under_30ms():
    pack, template = hook_pack(), get("retry-breaker")
    render(template, HOOK, pack, True)
    start = time.perf_counter()
    rendered = render(template, HOOK, pack, True)
    lint("hook", rendered, pack, HOOK)
    scan("hook", HOOK, rendered)
    assert time.perf_counter() - start < 0.03
