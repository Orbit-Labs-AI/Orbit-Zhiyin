"""B6: rules / skills behind a symlink inside the user's home install through the link."""

import os

from tandem_backend.install.targets import reason_text

from .test_service import run, snapshot, spec_source, svc  # noqa: F401

RULE = {"kind": "rule", "id": "commits", "payload": {"text": "Prefer small commits.", "heading": "Commits"}}


def test_rule_into_symlinked_agents_md(svc, fake_home):  # noqa: F811
    shared = fake_home / ".agents/AGENTS.md"
    shared.parent.mkdir()
    shared.write_text("# shared\n")
    link = fake_home / ".codex/AGENTS.md"
    link.unlink()
    os.symlink(shared, link)
    before = snapshot(fake_home)
    plan, preview, result = run(svc, spec_source(RULE), agents=["codex"])
    target = preview["targets"][0]
    assert target["mappable"] and target["status"] != "unmappable", target
    assert "→" in target["display"]
    assert os.path.islink(link), "the link must stay a link"
    assert "Prefer small commits." in shared.read_text()
    assert svc.revert(result["install_id"])["ok"]
    assert os.path.islink(link) and snapshot(fake_home) == before


def test_symlink_outside_home_stays_unmappable_with_text(svc, fake_home, tmp_path):  # noqa: F811
    outside = tmp_path / "dotfiles/AGENTS.md"
    outside.parent.mkdir()
    outside.write_text("# x\n")
    link = fake_home / ".codex/AGENTS.md"
    link.unlink()
    os.symlink(outside, link)
    plan = svc.plan(spec_source(RULE), agents=["codex"])
    t = plan["targets"][0]
    assert t["mappable"] is False and t["reason"] == "path_policy:symlink_escape"
    assert t["reason_text"] and "symlink" not in t["reason_text"]
    preview = svc.preview(plan["plan_id"])
    assert preview["targets"][0]["reason_text"] == t["reason_text"]


def test_reason_text_never_raw():
    assert reason_text("capability_unavailable:hooks") and reason_text("whatever_new")
    assert reason_text(None) is None
