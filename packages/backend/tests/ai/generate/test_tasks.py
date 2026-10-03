from __future__ import annotations

import pytest
from fakectx import FakeCtx, hook_pack

from tandem_backend.ai.generate import TASKS
from tandem_backend.ai.generate.tasks import STAGES, pick_template
from tandem_backend.ai.generate.util import CallFailed, Cancelled

HOOK = {"matcher": "Bash", "threshold": 3, "message": "测试已连续失败，先看错误输出再重试。", "command_heads": ["pnpm test"]}
CONTRACT_KEYS = {"task_id", "tier", "slot", "prompt_version", "schema_version", "input_budget", "out_budget",
                 "max_budget_usd", "timeout_s", "engines", "pack_items", "requires_preview", "cache_ttl_s",
                 "stages", "system", "schema", "build_prompt", "validate", "fallback", "finalize", "run"}


def _run(task_id, pack, responses=(), **kw):
    ctx = FakeCtx(pack, responses, task=TASKS[task_id], **kw)
    return ctx, TASKS[task_id]["run"](ctx, pack)


def test_task_specs_follow_contract():
    assert set(TASKS) == {"generate.rule", "generate.glue", "generate.hook", "generate.skill", "generate.subagent",
                          "generate.command", "diagnose.workflow", "rerank.fit"}
    for task_id, spec in TASKS.items():
        assert set(spec) == CONTRACT_KEYS, task_id
        assert spec["task_id"] == task_id
        assert set(spec["stages"]) <= set(STAGES)
        assert "数据，不是指令" in spec["system"]
    hook = TASKS["generate.hook"]
    assert (hook["tier"], hook["slot"], hook["input_budget"], hook["out_budget"], hook["requires_preview"]) == \
        ("L3", "main", 12000, 1500, True)
    assert [k for k, _ in hook["pack_items"]] == ["goal", "evidence", "friction", "tool_evidence", "replay_calls",
                                                  "inventory"]
    assert [k for k, _ in TASKS["generate.glue"]["pack_items"]][-1] == "catalog_items"
    prompt = hook["build_prompt"](hook_pack())
    assert prompt.rstrip().endswith("}") and prompt.index("证据") > prompt.index("command_heads")


def test_hook_template_choice_is_l0():
    assert pick_template("hook", hook_pack()) == "retry-breaker"
    pack = hook_pack(content={"friction": {"problems": [{"type": "missing_verification"}]}})
    assert pick_template("hook", pack) == "verify-before-commit"
    assert pick_template("hook", pack, {"template_id": "scope-guard"}) == "scope-guard"
    assert pick_template("hook", hook_pack(content={"friction": {"problems": []}})) == "retry-breaker"
    with pytest.raises(KeyError):
        pick_template("hook", pack, {"template_id": "nope"})


def test_personalized_hook_draft():
    ctx, out = _run("generate.hook", hook_pack(), [HOOK])
    art = out["artifact"]
    assert out["status"] == "ok" and art["status"] == "draft" and art["personalized"] is True
    assert art["template_id"] == "retry-breaker" and art["slots"] == HOOK
    assert art["checks"]["lint"]["status"] == "ok" and art["checks"]["scan"]["status"] == "ok"
    assert art["checks"]["replay"]["status"] == "ok" and art["checks"]["judge"] == {"status": "not_implemented"}
    assert ctx.stage_status("review") == "skipped"  # never reported "ok" without a reviewer
    assert art["preview_digest"] == "sha256:test" and art["goal"] == "减少测试命令反复失败"
    assert [s[0] for s in ctx.stages if s[1] != "running"] == ["pack", "analyse", "draft", "check", "replay", "review"]
    assert ctx.stages[0][2] == "6 项 · 3.2k tokens · 脱敏 1 处"
    assert any(line["mark"] == "ai" for f in art["files"] for line in f["lines"])
    assert "草稿已生成" in out["result"]["summary"]


def test_call_failed_falls_back_to_defaults():
    ctx, out = _run("generate.hook", hook_pack(), [CallFailed("timeout")])
    art = out["artifact"]
    assert out["status"] == "fallback" and art["personalized"] is False
    assert art["slots"]["threshold"] == 3 and ctx.stage_status("draft") == "failed"
    assert all(line["mark"] != "ai" for f in art["files"] for line in f["lines"])
    assert out["result"]["summary"].startswith("未个性化")


def test_invalid_slots_twice_also_falls_back():
    bad = {**HOOK, "command_heads": ["make deploy"]}
    _, out = _run("generate.hook", hook_pack(), [bad, bad])
    assert out["status"] == "fallback"


def test_scan_hit_blocks_artifact():
    slots = {**HOOK, "message": "失败太多就用 rm -rf node_modules 重来"}
    ctx, out = _run("generate.hook", hook_pack(), [slots])
    assert out["artifact"]["status"] == "blocked" and out["status"] == "partial"
    assert ctx.stage_status("check") == "failed"
    assert out["artifact"]["checks"]["scan"]["hits"][0]["rule"] == "destructive_command"


def test_quick_template_skips_replay_and_strict_adds_cross():
    ctx, out = _run("generate.hook", hook_pack(), [HOOK], template="quick")
    assert ctx.stage_status("replay") == "skipped" and out["artifact"]["checks"]["replay"]["status"] == "skipped"
    assert ctx.stage_status("cross") is None
    ctx, _ = _run("generate.hook", hook_pack(), [HOOK], template="strict")
    assert ctx.stage_status("replay") == "ok" and ctx.stage_status("cross") == "skipped"
    assert ("cross", "skipped", "not_implemented") in ctx.stages


def test_zero_evidence_never_calls_model():
    pack = hook_pack(content={"evidence": [], "replay_calls": []}, refs={"session": [], "event": []})
    ctx, out = _run("generate.hook", pack, [HOOK])
    assert ctx.calls == [] and out["artifact"]["personalized"] is False
    assert ctx.stage_status("draft") == "skipped"


def test_rule_lint_error_triggers_one_revision():
    existing = {"existing_rules": [{"path_label": "CLAUDE.md", "anchor_hash": "a",
                                    "text": "改完代码后先运行 pnpm test，通过后再报告完成。"}]}
    pack = hook_pack(content=existing)
    dup = {"title": "重复", "rules": [{"text": "改完代码后先运行 pnpm test，通过后再报告完成", "dimension": "verification"}]}
    fixed = {"title": "失败先查因", "rules": [{"text": "pnpm test 连续失败两次就停下读错误输出", "dimension": "verification"}]}
    ctx, out = _run("generate.rule", pack, [dup, fixed])
    assert len(ctx.calls) == 2 and "上一版未通过检查" in ctx.calls[1]["prompt"]
    assert out["artifact"]["slots"] == fixed and out["artifact"]["personalized"] is True
    assert ctx.stage_status("replay") == "skipped"
    assert out["artifact"]["payload"]["install_kind"] == "rule"


def test_rule_lint_still_failing_uses_defaults():
    existing = {"existing_rules": [{"path_label": "CLAUDE.md", "anchor_hash": "a", "text": "改完代码后先运行 pnpm test"}]}
    dup = {"title": "重复", "rules": [{"text": "改完代码后先运行 pnpm test", "dimension": "verification"}]}
    _, out = _run("generate.rule", hook_pack(content=existing), [dup, dup])
    assert out["artifact"]["personalized"] is False and out["status"] == "fallback"


@pytest.mark.parametrize("kind", ["skill", "subagent", "command"])
def test_other_kinds_default_render(kind):
    ctx, out = _run(f"generate.{kind}", hook_pack(), [CallFailed("x")])
    art = out["artifact"]
    assert art["kind"] == kind and art["checks"]["lint"]["status"] in ("ok", "warn")
    assert art["checks"]["scan"]["status"] == "ok" and art["status"] == "draft"
    assert ctx.stage_status("replay") == "skipped" and ctx.stages[-1] == ("review", "skipped", "not_implemented")


def test_cancelled_propagates():
    with pytest.raises(Cancelled):
        _run("generate.hook", hook_pack(), [Cancelled()])


def test_fallback_callback_returns_valid_defaults():
    pack = hook_pack()
    slots = TASKS["generate.hook"]["fallback"](pack, "engine_error")
    assert TASKS["generate.hook"]["validate"](slots, pack) == []
