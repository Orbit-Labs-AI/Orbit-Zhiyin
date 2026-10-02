import itertools
import json
import tomllib

import pytest

from tandem_backend.install import ops
from tandem_backend.install.errors import OpConflict


def mj(pointer, content, **kw):
    return {"idx": 0, "action": "merge_json", "pointer": pointer, "content": content,
            "write_mode": kw.pop("write_mode", "add"), **kw}


def blk(action, text, bid="tandem:demo"):
    return {"idx": 0, "action": action, "content": text, "block_id": bid}


def dumps(obj, indent=2):
    return (json.dumps(obj, indent=indent) + "\n").encode()


# ---------------------------------------------------------------- merge_json


def test_merge_list_append_dedup_and_create_containers():
    cur = dumps({"permissions": {"allow": ["git status"]}, "model": "x"})
    r = ops.render(mj("/permissions/allow", ["git status", "git diff"]), cur)
    data = json.loads(r["new"])
    assert data["permissions"]["allow"] == ["git status", "git diff"]
    assert r["applied"]["added"] == ["git diff"] and r["status"] == "modify"
    assert list(data) == ["permissions", "model"]  # key order kept

    r2 = ops.render(mj("/hooks/PreToolUse", [{"matcher": "Bash"}]), None)
    assert r2["status"] == "create"
    assert r2["applied"]["created_paths"] == ["/hooks", "/hooks/PreToolUse"]
    assert ops.render(mj("/permissions/allow", ["git status"]), cur)["status"] == "noop"


def test_merge_conflicts():
    cur = dumps({"permissions": {"deny": ["git push"]}, "a": {"k": 1}, "s": "str"})
    with pytest.raises(OpConflict) as e:
        ops.render(mj("/permissions/allow", ["git push"]), cur)
    assert e.value.code == "deny_conflict"
    with pytest.raises(OpConflict) as e:
        ops.render(mj("/a", {"k": 2}), cur)
    assert e.value.code == "key_exists_different"
    with pytest.raises(OpConflict) as e:
        ops.render(mj("/s", ["x"]), cur)
    assert e.value.code == "container_type"
    with pytest.raises(OpConflict) as e:
        ops.render(mj("", {"x": 1}), b"{ // comment\n}")
    assert e.value.code == "parse_error"


def test_merge_set_records_previous_and_unrender():
    cur = dumps({"a": {"k": 1, "z": 0}})
    r = ops.render(mj("/a", {"k": 2, "n": 3}, write_mode="set"), cur)
    assert r["applied"]["previous"] == {"k": 1, "n": {"__absent__": True}}
    u = ops.unrender(r["applied"], {}, r["new"])
    assert u["status"] == "reverted" and json.loads(u["new"]) == {"a": {"k": 1, "z": 0}}
    assert ops.unrender(r["applied"], {}, u["new"])["status"] == "already_reverted"
    edited = json.loads(r["new"])
    edited["a"]["k"] = 9
    assert ops.unrender(r["applied"], {}, dumps(edited))["status"] == "modified"


def test_indent_and_unknown_keys_preserved():
    cur = b'{\n    "zz": [1, 2],\n    "\xe4\xb8\xad": "\xe6\x96\x87"\n}'
    r = ops.render(mj("/mcpServers", {"x": {"command": "npx"}}), cur)
    text = r["new"].decode()
    assert '\n    "zz"' in text and "中" in text and not text.endswith("\n")
    tab = ops.render(mj("", {"b": 1}), b'{\n\t"a": 1\n}\n')["new"].decode()
    assert '\n\t"b": 1' in tab


def test_list_unrender_and_created_cleanup():
    r = ops.render(mj("/permissions/allow", ["git log"]), b"{}\n")
    u = ops.unrender(r["applied"], {}, r["new"])
    assert u["new"] == b"{}\n"
    r = ops.render(mj("/permissions/allow", ["git log"]), None)
    assert ops.unrender(r["applied"], {}, r["new"])["delete"] is True


def test_guard_hash_scoped_to_pointer():
    t = mj("/mcpServers", {"x": {}})
    a = dumps({"mcpServers": {"a": 1}, "numStartups": 1})
    b = dumps({"mcpServers": {"a": 1}, "numStartups": 2, "tips": {}}, indent=4)
    c = dumps({"mcpServers": {"a": 2}, "numStartups": 1})
    assert ops.guard_hash(t, a) == ops.guard_hash(t, b) != ops.guard_hash(t, c)
    assert ops.guard_hash(t, None) == "absent"
    assert ops.guard_hash(t, b"{}") == "absent"
    assert ops.guard_hash({"action": "create_file"}, b"x").startswith("sha256:")


# ---------------------------------------------------------------- blocks


def test_md_block_lifecycle():
    t = blk("md_block", "## Tandem\n- use uv")
    new = ops.render(t, None)
    assert new["status"] == "create" and new["applied"]["created_file"]
    cur = b"# Project\nnotes"
    r = ops.render(t, cur)
    assert r["new"].decode().startswith("# Project\nnotes\n\n<!-- tandem:demo begin -->")
    assert ops.render(t, r["new"])["status"] == "noop"
    with pytest.raises(OpConflict) as e:
        ops.render(blk("md_block", "other"), r["new"])
    assert e.value.code == "block_exists_different"
    # user edits outside the block -> unit-level undo keeps their edit
    edited = b"# Changed title\n" + r["new"][len(b"# Project\n"):] + b"\nmore\n"
    u = ops.unrender(r["applied"], t, edited)
    assert u["status"] == "reverted" and u["new"] == b"# Changed title\nnotes\nmore\n"
    inside = r["new"].replace(b"- use uv", b"- use pip")
    assert ops.unrender(r["applied"], t, inside)["status"] == "modified"
    assert ops.unrender(r["applied"], t, cur)["status"] == "already_reverted"
    assert ops.unrender(new["applied"], t, new["new"])["delete"] is True


def test_toml_block():
    cur = b'# my config\nmodel = "o3"\n\n[mcp_servers.old]\ncommand = "a"\n'
    t = blk("toml_block", '[mcp_servers.new]\ncommand = "npx"\nargs = ["-y", "x"]')
    r = ops.render(t, cur)
    parsed = tomllib.loads(r["new"].decode())
    assert parsed["mcp_servers"]["new"]["args"] == ["-y", "x"]
    assert r["new"].startswith(cur) and b"# >>> tandem:demo >>>" in r["new"]
    assert ops.unrender(r["applied"], t, r["new"])["new"] == cur
    with pytest.raises(OpConflict) as e:
        ops.render(blk("toml_block", '[mcp_servers.old]\ncommand = "b"'), cur)
    assert e.value.code == "toml_table_exists"
    with pytest.raises(OpConflict) as e:
        ops.render(blk("toml_block", 'model = "dup"'), cur)
    assert e.value.code == "toml_invalid"
    with pytest.raises(OpConflict) as e:
        ops.render(blk("toml_block", "[x]\nbroken = "), cur)
    assert e.value.code == "toml_invalid"


def test_create_file_states():
    t = {"idx": 0, "action": "create_file", "content": "hi\n", "display": "~/x"}
    assert ops.render(t, None)["status"] == "create"
    r = ops.render(t, b"hi\n")
    assert r["status"] == "noop" and r["applied"]["preexisting_identical"]
    with pytest.raises(OpConflict) as e:
        ops.render(t, b"other")
    assert e.value.code == "file_exists_different"
    applied = ops.render(t, None)["applied"]
    assert ops.unrender(applied, t, b"hi\n")["delete"] is True
    assert ops.unrender(applied, t, b"edited")["status"] == "modified"
    assert ops.unrender(applied, t, None)["status"] == "already_reverted"


def test_run_command_is_noop():
    t = {"action": "run_command", "content": {"argv": ["claude", "plugin", "install", "x"]}}
    assert ops.render(t, b"a")["status"] == "noop"
    assert ops.units(t)[0]["label"] == "claude plugin install x"


# ---------------------------------------------------------------- units/select (EV-13)

MD = """## Rules

- run `uv sync` first
- prefer small commits
  with a reason

```bash
pnpm check

uv run pytest
```

Final paragraph
spanning two lines."""


def _fences_closed(text):
    return sum(1 for ln in text.splitlines() if ln.strip().startswith("```")) % 2 == 0


def _subsets(n):
    for k in range(1, n + 1):
        yield from itertools.combinations(range(n), k)


@pytest.mark.parametrize("target,current,check", [
    (mj("/permissions/allow", ["a", "b", {"x": 1}, "d"]), dumps({"permissions": {}}),
     lambda b: json.loads(b)),
    (mj("/mcpServers", {"a": {"command": "x"}, "b": {"url": "u"}, "c": 1}), None,
     lambda b: json.loads(b)),
    (blk("md_block", MD), b"# Top\n", lambda b: _fences_closed(b.decode()) or 1 / 0),
    (blk("toml_block", '[mcp_servers.z]\ncommand = "x"'), b"",
     lambda b: tomllib.loads(b.decode())),
    ({"idx": 0, "action": "create_file", "content": "x"}, None, lambda b: b),
])
def test_every_subset_renders_valid(target, current, check):
    us = ops.units(target)
    assert 1 <= len(us) <= 6
    for combo in _subsets(len(us)):
        picked = ops.select(target, [us[i]["id"] for i in combo])
        check(ops.render(picked, current)["new"])
    with pytest.raises(OpConflict) as e:
        ops.select(target, [])
    assert e.value.code == "empty_selection"


def test_md_units_shape():
    us = ops.units(blk("md_block", MD))
    assert [u["label"] for u in us] == ["## Rules", "- run `uv sync` first",
                                        "- prefer small commits", "```bash",
                                        "Final paragraph"]
    two = ops.select(blk("md_block", MD), ["u1", "u2"])["content"]
    assert two == "- run `uv sync` first\n- prefer small commits\n  with a reason"


def test_merge_same_name_mcp_server_conflicts_instead_of_merging():
    cur = dumps({"mcpServers": {"foo": {"type": "stdio", "command": "npx",
                                        "args": ["-y", "a", "b"], "env": {"K": "v"}}}})
    spec = {"type": "stdio", "command": "npx", "args": ["x"]}
    for pointer, data in (("/mcpServers/foo", cur),
                          ("/projects/~1p/mcpServers/foo",
                           dumps({"projects": {"/p": json.loads(cur)}}))):
        with pytest.raises(OpConflict) as e:
            ops.render(mj(pointer, spec, write_mode="set"), data)
        assert e.value.code == "mcp_exists"
    same = {"type": "stdio", "command": "npx", "args": ["-y", "a", "b"]}
    assert ops.render(mj("/mcpServers/foo", same, write_mode="set"), cur)["status"] == "noop"
