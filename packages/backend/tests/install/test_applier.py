import json
import os
import threading
from pathlib import Path

import pytest

from orbit_backend.install import applier, ops
from orbit_backend.install.errors import ApplyFailed, OpConflict, StaleError


def tgt(idx, path, action="merge_json", **kw):
    return {"idx": idx, "agent": "claude_code", "scope": "user", "path": str(path),
            "display": str(path), "action": action, "pointer": kw.pop("pointer", None),
            "content": kw.pop("content", None), "write_mode": "add", "mappable": True,
            "block_id": kw.pop("block_id", None), "file_mode": kw.pop("file_mode", None), **kw}


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return {"home": home, "backup_dir": tmp_path / "backups" / "i1",
            "lock_dir": tmp_path / "locks"}


def run(targets, env, expect=None, selected=None):
    prep = applier.preflight(targets, selected=selected or {}, expect=expect, home=env["home"])
    return applier.apply_targets(prep, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"],
                                 install_id="i1", home=env["home"])


def test_preflight_stale_lists_all(env):
    a = env["home"] / "a.json"
    a.write_text('{"permissions": {"allow": []}}')
    b = env["home"] / "b.md"
    b.write_text("x\n")
    targets = [tgt(0, a, pointer="/permissions/allow", content=["ls"]),
               tgt(1, b, "md_block", content="r", block_id="orbit:r")]
    with pytest.raises(StaleError) as e:
        applier.preflight(targets, selected={}, expect={0: "sha256:0", 1: "sha256:0"},
                          home=env["home"])
    assert e.value.detail == {"targets": [0, 1]} and e.value.http == 409
    good = {0: ops.guard_hash(targets[0], a.read_bytes()), 1: ops.sha256(b.read_bytes())}
    assert len(applier.preflight(targets, selected={}, expect=good, home=env["home"])) == 2


def test_lock_timeout(env, monkeypatch):
    monkeypatch.setattr(applier, "LOCK_TIMEOUT", 0.2)
    path = env["home"] / "s.json"
    prep = applier.preflight([tgt(0, path, pointer="", content={"a": 1})], selected={},
                             expect=None, home=env["home"])
    held, release = threading.Event(), threading.Event()

    def holder():
        with applier._lock(env["lock_dir"], path):
            held.set()
            release.wait(5)

    th = threading.Thread(target=holder)
    th.start()
    held.wait(5)
    try:
        with pytest.raises(ApplyFailed) as e:
            applier.apply_targets(prep, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"],
                                  install_id="i1", home=env["home"])
        assert e.value.code == "locked" and e.value.http == 423
    finally:
        release.set()
        th.join()
    assert not path.exists()


def test_backup_and_meta(env):
    path = env["home"] / "settings.json"
    path.write_text('{"model": "x"}\n')
    os.chmod(path, 0o600)
    recs = run([tgt(0, path, pointer="", content={"a": 1})], env)
    bk = Path(recs[0]["backup_path"])
    assert bk.read_text() == '{"model": "x"}\n'
    meta = json.loads(bk.with_name(bk.name + ".meta.json").read_text())
    assert meta["install_id"] == "i1" and meta["mode"] == 0o600
    assert env["backup_dir"].stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    r = recs[0]
    assert r["status"] == "modify" and r["before_hash"] != r["after_hash"]
    assert r["after_hash"] == ops.sha256(path.read_bytes())


def test_atomic_write_failure_leaves_original(env, monkeypatch):
    path = env["home"] / "s.json"
    path.write_text('{"k": 1}\n')

    def boom(*a, **k):
        raise OSError("disk full")

    prep = applier.preflight([tgt(0, path, pointer="", content={"a": 1})], selected={},
                             expect=None, home=env["home"])
    monkeypatch.setattr(applier.os, "replace", boom)
    with pytest.raises(ApplyFailed) as e:
        applier.apply_targets(prep, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"],
                              install_id="i1", home=env["home"])
    assert e.value.detail["failed_idx"] == 0 and e.value.detail["rolled_back"] == []
    assert path.read_text() == '{"k": 1}\n'
    assert not [p for p in env["home"].iterdir() if p.name.startswith(".orbit-")]


def test_second_target_failure_rolls_back_first(env):
    a = env["home"] / "CLAUDE.md"
    a.write_bytes(b"# mine\r\nkeep\n")
    b = env["home"] / "bad.json"
    b.write_text('{"x": 1}')
    targets = [tgt(0, a, "md_block", content="rule", block_id="orbit:r"),
               tgt(1, b, pointer="", content={"y": 2})]
    prep = applier.preflight(targets, selected={}, expect=None, home=env["home"])
    b.write_text('{"x": "changed"}')  # unrelated change: merge_json re-renders, still ok
    b.write_text("not json")  # now unparsable -> guard differs -> stale
    with pytest.raises(StaleError) as e:
        applier.apply_targets(prep, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"],
                              install_id="i1", home=env["home"])
    assert e.value.detail["failed_idx"] == 1 and e.value.detail["rolled_back"] == [0]
    assert a.read_bytes() == b"# mine\r\nkeep\n"


def test_new_dirs_cleaned_on_rollback(env, monkeypatch):
    path = env["home"] / "deep" / "er" / "f.md"
    prep = applier.preflight([tgt(0, path, "create_file", content="x")], selected={},
                             expect=None, home=env["home"])
    monkeypatch.setattr(applier.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(ApplyFailed):
        applier.apply_targets(prep, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"],
                              install_id="i1", home=env["home"])
    assert not (env["home"] / "deep").exists()


def test_read_only_and_forbidden_paths(env):
    ro = env["home"] / "ro.json"
    ro.write_text("{}")
    os.chmod(ro, 0o444)
    with pytest.raises(OpConflict) as e:
        applier.preflight([tgt(0, ro, pointer="", content={"a": 1})], selected={}, expect=None,
                          home=env["home"])
    assert e.value.code == "read_only"
    for bad in (env["home"] / "repo" / ".git" / "config",
                Path("/Library/Application Support/ClaudeCode/managed-settings.json")):
        with pytest.raises(OpConflict) as e:
            applier.preflight([tgt(0, bad, pointer="", content={"a": 1})], selected={},
                              expect=None, home=env["home"])
        assert e.value.code == "forbidden_path"


def test_symlink_escape_and_directory(env, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    link = env["home"] / "link.json"
    link.symlink_to(outside)
    with pytest.raises(OpConflict) as e:
        applier.preflight([tgt(0, link, pointer="", content={"a": 1})], selected={},
                          expect=None, home=env["home"])
    assert e.value.code == "symlink_escape"
    (env["home"] / "dir.md").mkdir()
    with pytest.raises(OpConflict) as e:
        applier.preflight([tgt(0, env["home"] / "dir.md", "create_file", content="x")],
                          selected={}, expect=None, home=env["home"])
    assert e.value.code == "not_regular_file"


def test_real_home_safety_net(env):
    real = applier._real_home() / ".claude" / "settings.json"
    with pytest.raises(ApplyFailed) as e:
        applier.preflight([tgt(0, real, pointer="", content={"a": 1})], selected={},
                          expect=None, home=env["home"])
    assert e.value.code == "refusing_real_home_in_tests"


def test_claude_json_unrelated_change_between_preflight_and_write(env):
    path = env["home"] / ".claude.json"
    path.write_text(json.dumps({"numStartups": 1, "mcpServers": {"a": {"command": "x"}}},
                               indent=2))
    t = tgt(0, path, pointer="/mcpServers", content={"b": {"command": "npx"}})
    expect = {0: ops.guard_hash(t, path.read_bytes())}
    prep = applier.preflight([t], selected={}, expect=expect, home=env["home"])
    data = json.loads(path.read_text())
    data["numStartups"] = 2
    data["projects"] = {"/p": {}}
    path.write_text(json.dumps(data, indent=2))
    applier.apply_targets(prep, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"],
                          install_id="i1", home=env["home"])
    out = json.loads(path.read_text())
    assert out["numStartups"] == 2 and out["projects"] == {"/p": {}}
    assert set(out["mcpServers"]) == {"a", "b"}


def test_two_targets_same_file(env):
    path = env["home"] / "settings.json"
    path.write_text("{}\n")
    targets = [tgt(0, path, pointer="/enabledPlugins", content={"p@m": True}),
               tgt(1, path, pointer="/extraKnownMarketplaces", content={"m": {"source": "x"}})]
    recs = run(targets, env)
    data = json.loads(path.read_text())
    assert data == {"enabledPlugins": {"p@m": True}, "extraKnownMarketplaces": {"m": {"source": "x"}}}
    res = applier.revert_records(recs, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"])
    assert [r["status"] for r in res] == ["reverted", "reverted"]
    assert path.read_text() == "{}\n"


def test_selected_units_and_noop(env):
    path = env["home"] / "s.json"
    path.write_text('{"permissions": {"allow": ["a"]}}\n')
    t = tgt(0, path, pointer="/permissions/allow", content=["a", "b", "c"])
    recs = run([t], env, selected={0: ["u2"]})
    assert json.loads(path.read_text())["permissions"]["allow"] == ["a", "c"]
    again = run([tgt(0, path, pointer="/permissions/allow", content=["a"])], env)
    assert again[0]["status"] == "noop" and again[0]["backup_path"] is None
    assert recs[0]["applied"]["added"] == ["c"]
