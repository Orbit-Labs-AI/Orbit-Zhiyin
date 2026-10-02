"""B5: stacked installs on one file revert cleanly in any order (no empty residue)."""

import json

import pytest

from .test_service import run, snapshot, spec_source, svc  # noqa: F401

HOOK_A = {"kind": "hook", "id": "fmt-a", "payload": {"event": "Stop", "matcher": "", "command": "echo a"}}
HOOK_B = {"kind": "hook", "id": "fmt-b", "payload": {"event": "Stop", "matcher": "", "command": "echo b"}}


@pytest.fixture
def no_hooks(fake_home):
    (fake_home / ".codex/hooks.json").unlink()
    return fake_home


@pytest.mark.parametrize("order", ["oldest_first", "newest_first"])
def test_stacked_hooks_revert_any_order_is_byte_exact(svc, no_hooks, order):  # noqa: F811
    before = snapshot(no_hooks)
    _, _, a = run(svc, spec_source(HOOK_A), agents=["codex"])
    _, _, b = run(svc, spec_source(HOOK_B), agents=["codex"])
    hooks = no_hooks / ".codex/hooks.json"
    assert hooks.exists()
    first, second = (a, b) if order == "oldest_first" else (b, a)
    assert svc.revert(first["install_id"])["ok"]
    assert hooks.exists()
    assert svc.revert(second["install_id"])["ok"]
    assert not hooks.exists()
    assert snapshot(no_hooks) == before


def test_stacked_revert_keeps_file_with_user_content(svc, no_hooks):  # noqa: F811
    _, _, a = run(svc, spec_source(HOOK_A), agents=["codex"])
    _, _, b = run(svc, spec_source(HOOK_B), agents=["codex"])
    hooks = no_hooks / ".codex/hooks.json"
    data = json.loads(hooks.read_text())
    data["mine"] = True
    hooks.write_text(json.dumps(data, indent=2))
    assert svc.revert(a["install_id"])["ok"]
    assert svc.revert(b["install_id"])["ok"]
    assert json.loads(hooks.read_text()) == {"mine": True}


def test_stacked_revert_refuses_when_user_edited_our_unit(svc, no_hooks):  # noqa: F811
    _, _, a = run(svc, spec_source(HOOK_A), agents=["codex"])
    _, _, b = run(svc, spec_source(HOOK_B), agents=["codex"])
    hooks = no_hooks / ".codex/hooks.json"
    hooks.write_text(hooks.read_text().replace("echo b", "echo user"))
    assert svc.revert(a["install_id"])["ok"]
    refused = svc.revert(b["install_id"])
    assert not refused["ok"] and refused["results"][0]["status"] == "modified"
    assert "echo user" in hooks.read_text()


RULE_A = {"kind": "rule", "id": "rule-a", "payload": {"text": "Prefer small commits.", "heading": "A"}}
RULE_B = {"kind": "rule", "id": "rule-b", "payload": {"text": "Run tests first.", "heading": "B"}}


def test_stacked_md_blocks_revert_oldest_first(svc, fake_home):  # noqa: F811
    (fake_home / ".codex/AGENTS.md").unlink()
    before = snapshot(fake_home)
    _, _, a = run(svc, spec_source(RULE_A), agents=["codex"])
    _, _, b = run(svc, spec_source(RULE_B), agents=["codex"])
    assert svc.revert(a["install_id"])["ok"] and svc.revert(b["install_id"])["ok"]
    assert snapshot(fake_home) == before
