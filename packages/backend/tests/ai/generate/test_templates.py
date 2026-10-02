from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from tandem_backend.ai.generate import templates
from tandem_backend.ai.generate.hooks_replay import decide_fn


def test_manifest_hashes_match_files():
    manifest = json.loads((templates.ROOT / "manifest.json").read_text())
    for template_id, entry in manifest.items():
        assert hashlib.sha256((templates.ROOT / entry["file"]).read_bytes()).hexdigest() == entry["sha256"], template_id
    loaded = templates.load()
    assert set(loaded) == set(manifest)
    assert {t.kind for t in loaded.values()} == {"rule", "hook", "skill", "subagent", "command"}


def test_changed_template_without_version_bump_fails(tmp_path, monkeypatch):
    for entry in ("manifest.json", "rules"):
        src = templates.ROOT / entry
        if src.is_dir():
            (tmp_path / entry).mkdir()
            for f in src.iterdir():
                (tmp_path / entry / f.name).write_bytes(f.read_bytes())
        else:
            manifest = {k: v for k, v in json.loads(src.read_text()).items() if v["kind"] == "rule"}
            (tmp_path / entry).write_text(json.dumps(manifest))
    (tmp_path / "rules" / "paragraph@1.md").write_text("tampered\n")
    monkeypatch.setattr(templates, "ROOT", tmp_path)
    templates.load.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="version bump"):
            templates.load()
    finally:
        templates.load.cache_clear()


def _decide(template_id):
    return decide_fn(templates.get(template_id))


def _bash(name, command, ok=True):
    event = {"hook_event_name": name, "tool_name": "Bash", "tool_input": {"command": command}}
    if name == "PostToolUse":
        event["tool_response"] = {"success": ok, "exit_code": 0 if ok else 1}
    return event


EDIT = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/a.ts"},
        "tool_response": {"success": True}}


def test_retry_breaker_allow_and_block():
    decide, state, cfg = _decide("retry-breaker"), {}, {"threshold": 2, "message": "stop"}
    assert decide(_bash("PreToolUse", "pnpm test"), cfg, state) == ("allow", None)
    decide(_bash("PostToolUse", "pnpm test --run", ok=False), cfg, state)
    assert decide(_bash("PreToolUse", "pnpm test"), cfg, state)[0] == "allow"
    decide(_bash("PostToolUse", "pnpm test", ok=False), cfg, state)
    assert decide(_bash("PreToolUse", "pnpm test"), cfg, state) == ("block", "stop")
    decide(_bash("PostToolUse", "pnpm test", ok=True), cfg, state)
    assert decide(_bash("PreToolUse", "pnpm test"), cfg, state)[0] == "allow"
    # command_heads limits what is tracked
    other = {}
    for _ in range(3):
        decide(_bash("PostToolUse", "ls", ok=False), {"threshold": 2, "command_heads": ["pnpm test"]}, other)
    assert decide(_bash("PreToolUse", "ls"), {"threshold": 2, "command_heads": ["pnpm test"]}, other)[0] == "allow"


def test_verify_before_commit():
    decide, state, cfg = _decide("verify-before-commit"), {}, {"command_heads": ["pnpm test"]}
    assert decide(_bash("PreToolUse", "git commit -m x"), cfg, state)[0] == "allow"
    decide(EDIT, cfg, state)
    assert decide(_bash("PreToolUse", "git commit -m x"), cfg, state)[0] == "block"
    decide(_bash("PostToolUse", "pnpm test", ok=False), cfg, state)
    assert decide(_bash("PreToolUse", "git commit -m x"), cfg, state)[0] == "block"
    decide(_bash("PostToolUse", "pnpm test", ok=True), cfg, state)
    assert decide(_bash("PreToolUse", "git commit -m x"), cfg, state)[0] == "allow"


def test_post_edit_check():
    decide, cfg = _decide("post-edit-check"), {"file_glob": "*.ts", "command": "pnpm lint", "message": "检查"}
    assert decide(EDIT, cfg, {}) == ("warn", "检查（pnpm lint）")
    py = {**EDIT, "tool_input": {"file_path": "a.py"}}
    assert decide(py, cfg, {})[0] == "allow"
    assert decide(_bash("PostToolUse", "ls"), cfg, {})[0] == "allow"


def test_stop_verify_blocks_once():
    decide, state, cfg = _decide("stop-verify"), {}, {"command_heads": ["pnpm test"]}
    stop = {"hook_event_name": "Stop", "stop_hook_active": False}
    assert decide(stop, cfg, {})[0] == "allow"
    decide(EDIT, cfg, state)
    assert decide({**stop, "stop_hook_active": True}, cfg, state)[0] == "allow"
    assert decide(stop, cfg, state)[0] == "block"
    assert decide(stop, cfg, state)[0] == "allow"


def test_compaction_reminder_and_scope_guard():
    remind = _decide("compaction-reminder")
    assert remind({"hook_event_name": "PreCompact"}, {"message": "m"}, {}) == ("warn", "m")
    assert remind(_bash("PreToolUse", "ls"), {}, {})[0] == "allow"
    guard, cfg = _decide("scope-guard"), {"command_heads": ["git push --force"], "message": "no"}
    assert guard(_bash("PreToolUse", "git push --force origin main"), cfg, {}) == ("block", "no")
    assert guard(_bash("PreToolUse", "git push origin main"), cfg, {})[0] == "allow"
    assert guard(_bash("PostToolUse", "git push --force"), cfg, {})[0] == "allow"


@pytest.mark.parametrize("event,code,out", [
    ({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf build"},
      "session_id": "t1"}, 2, ""),
    ({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "t1"}, 0, ""),
])
def test_scope_guard_script_exit_codes(tmp_path, event, code, out):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"command_heads": ["rm -rf"]}))
    script = templates.get("scope-guard").path
    proc = subprocess.run([sys.executable, str(script), "--config", str(cfg)], input=json.dumps(event),
                          capture_output=True, text=True, env={"TMPDIR": str(tmp_path)}, timeout=10)
    assert proc.returncode == code
    assert proc.stdout.strip() == out
    assert (tmp_path / "tandem-hooks" / "t1-scope-guard.json").exists()


def test_warn_script_prints_system_message(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"message": "留档"}))
    proc = subprocess.run([sys.executable, str(templates.get("compaction-reminder").path), "--config", str(cfg)],
                          input='{"hook_event_name": "PreCompact"}', capture_output=True, text=True,
                          env={"TMPDIR": str(tmp_path)}, timeout=10)
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"systemMessage": "留档"}
