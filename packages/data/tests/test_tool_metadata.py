"""tool_metadata: per-agent name -> kind tables, file extraction and argv command specs.

Expected values are written by hand from each harness's argument shapes (see
tandem_data/tool_kinds.py for the upstream references), not copied from reducer output.
"""

import json

import pytest

from tandem_data.contract import canonical
from tandem_data.reduce import tool_metadata
from tandem_data.store import Store
from tandem_data.tool_kinds import AGENT_TOOL_KINDS, file_ops, tool_kind

PATCH = """*** Begin Patch
*** Update File: /repo/src/app.py
@@ def main():
-    pass
+    run()
*** Add File: docs/new.md
+hello
*** Delete File: old/legacy.js
*** Update File: /repo/a.rs
*** Move to: /repo/b.rs
*** End Patch"""


@pytest.mark.parametrize(
    ("name", "agent", "args", "expected"),
    [
        # Codex custom_tool_call: the raw patch string is the whole input.
        (
            "apply_patch",
            "codex",
            PATCH,
            [
                ("/repo/src/app.py", "update"),
                ("docs/new.md", "add"),
                ("old/legacy.js", "delete"),
                ("/repo/a.rs", "update"),
                ("/repo/b.rs", "move"),
            ],
        ),
        # Codex function_call / OpenCode: patch text under a key.
        ("apply_patch", "codex", {"input": "*** Update File: x/y.go\n"}, [("x/y.go", "update")]),
        ("apply_patch", "opencode", {"patchText": "*** Add File: z.ts\n+1"}, [("z.ts", "add")]),
        # Codex patch_apply_begin: changes dict keyed by absolute path.
        (
            "apply_patch",
            "codex",
            {"/a/b.py": {"update": {"unified_diff": ""}}, "/a/c.md": {"add": {"content": ""}}},
            [("/a/b.py", "update"), ("/a/c.md", "add")],
        ),
        (
            "apply_patch",
            "codex",
            {"changes": {"/a/b.py": {"type": "update"}, "/a/n.txt": {"type": "add"}}},
            [("/a/b.py", "update"), ("/a/n.txt", "add")],
        ),
        # Codex app-server FileChange item: list of {path, kind}.
        (
            "FileChange",
            "codex",
            [{"path": "/r/x.ts", "kind": {"type": "update"}}, {"path": "/r/y.ts", "kind": "add"}],
            [("/r/x.ts", "update"), ("/r/y.ts", "add")],
        ),
        (
            "NotebookEdit",
            "claude_code",
            {"notebook_path": "/n/a.ipynb"},
            [("/n/a.ipynb", "unknown")],
        ),
        ("Read", "claude_code", {"file_path": "/r/README.md"}, [("/r/README.md", "unknown")]),
        ("read", "opencode", {"filePath": "/r/main.go"}, [("/r/main.go", "unknown")]),
        ("ReadFile", "kimi", {"path": "src/lib.rs"}, [("src/lib.rs", "unknown")]),
        (
            "MultiRead",
            None,
            {"paths": ["/a.py", "/b.css", 3]},
            [("/a.py", "unknown"), ("/b.css", "unknown")],
        ),
        ("Bash", "claude_code", {"command": "ls"}, []),
    ],
)
def test_files_and_ops_from_every_argument_shape(name, agent, args, expected):
    meta = tool_metadata(name, {"input": args}, agent=agent)
    assert meta["file_ops"] == expected
    assert json.loads(meta["files"]) == [path for path, _ in expected]


@pytest.mark.parametrize(
    ("argv", "head"),
    [
        (["bash", "-lc", "git status"], "git status"),
        (["/bin/zsh", "-lc", "cd /r && pytest -q"], "pytest"),
        (["git", "diff", "--stat"], "git diff"),
    ],
)
def test_argv_commands_get_the_same_spec_as_strings(argv, head):
    array = tool_metadata("shell", {"input": {"command": argv, "workdir": "/r"}}, agent="codex")
    joined = " ".join(argv[:2]) + " '" + argv[2] + "'" if argv[1] == "-lc" else " ".join(argv)
    string = tool_metadata("Bash", {"input": {"command": joined}, "cwd": "/r"}, agent="claude_code")
    assert array["kind"] == "shell" and array["command_head"] == head
    assert array["command_spec"] is not None
    assert json.loads(array["command_spec"]) == json.loads(string["command_spec"])


def test_local_shell_call_bare_argv_input():
    meta = tool_metadata("local_shell_call", {"input": ["bash", "-lc", "make test"]}, agent="codex")
    assert meta["kind"] == "shell" and meta["command_head"] == "make test"
    assert json.loads(meta["command_spec"])["cwd"] is None


# One name -> kind table per agent. Names are the harness's registered tool ids.
AGENT_CASES = {
    "claude_code": {
        "Bash": "shell",
        "BashOutput": "shell",
        "KillShell": "shell",
        "Read": "file.read",
        "Edit": "file.edit",
        "MultiEdit": "file.edit",
        "NotebookEdit": "file.edit",
        "Write": "file.write",
        "Grep": "search",
        "Glob": "search",
        "WebSearch": "web.search",
        "WebFetch": "web.fetch",
        "Task": "subagent",
        "Skill": "skill",
        "TodoWrite": "plan",
        "AskUserQuestion": "ask_user",
    },
    "codex": {
        "shell": "shell",
        "shell_command": "shell",
        "exec_command": "shell",
        "write_stdin": "shell",
        "local_shell": "shell",
        "local_shell_call": "shell",
        "CommandExecution": "shell",
        "apply_patch": "file.edit",
        "FileChange": "file.edit",
        "view_image": "file.read",
        "web_search_call": "web.search",
        "spawn_agent": "subagent",
        "update_plan": "plan",
        "request_user_input": "ask_user",
        "request_user_input_async": "ask_user",
    },
    "dsh": {
        "bash": "shell",
        "read": "file.read",
        "edit": "file.edit",
        "grep": "search",
        "glob": "search",
        "todo_write": "plan",
        "subagent": "subagent",
    },
    "pi": {
        "bash": "shell",
        "powershell": "shell",
        "read": "file.read",
        "ls": "file.read",
        "edit": "file.edit",
        "write": "file.write",
        "grep": "search",
        "find": "search",
    },
    "opencode": {
        "bash": "shell",
        "read": "file.read",
        "edit": "file.edit",
        "apply_patch": "file.edit",
        "write": "file.write",
        "grep": "search",
        "glob": "search",
        "websearch": "web.search",
        "webfetch": "web.fetch",
        "task": "subagent",
        "skill": "skill",
        "todowrite": "plan",
        "question": "ask_user",
    },
    "hermes": {
        "terminal": "shell",
        "read_file": "file.read",
        "patch": "file.edit",
        "write_file": "file.write",
        "search_files": "search",
        "web_search": "web.search",
        "web_extract": "web.fetch",
        "delegate_task": "subagent",
        "skill_view": "skill",
        "clarify": "ask_user",
        "memory": "other",
    },
    "kimi": {
        "Shell": "shell",
        "ReadFile": "file.read",
        "StrReplaceFile": "file.edit",
        "WriteFile": "file.write",
        "Grep": "search",
        "SearchWeb": "web.search",
        "FetchURL": "web.fetch",
        "Task": "subagent",
        "SetTodoList": "plan",
    },
}


@pytest.mark.parametrize("agent", sorted(AGENT_CASES))
def test_agent_tool_tables(agent):
    assert agent in AGENT_TOOL_KINDS
    for name, kind in AGENT_CASES[agent].items():
        assert tool_kind(name, agent) == (kind, True), name
        assert tool_metadata(name, {}, agent=agent)["kind"] == kind


def test_unknown_names_are_reported_not_guessed():
    assert tool_kind("frobnicate", "codex") == ("other", False)
    # Agent-specific: pi has no "patch" tool even though Hermes does.
    assert tool_kind("patch", "pi") == ("other", False)
    assert tool_kind("patch", "hermes") == ("file.edit", True)
    # MCP: the Claude/Codex name form, or connector-supplied server/tool attrs.
    mcp = tool_metadata("mcp__github__create_issue", {}, agent="claude_code")
    assert (mcp["kind"], mcp["mcp_server"], mcp["mcp_tool"]) == ("mcp", "github", "create_issue")
    named = tool_metadata(
        "github_create_issue",
        {"mcp_server": "github", "mcp_tool": "create_issue"},
        agent="opencode",
    )
    assert (named["kind"], named["name"], named["kind_known"]) == ("mcp", "create_issue", True)


def test_file_ops_ignores_non_path_values():
    assert file_ops(None) == []
    assert file_ops({"path": "", "paths": "notalist"}) == []
    assert file_ops("plain text without patch headers") == []


def _assistant(id_, parent, calls, ts):
    return {
        "type": "message",
        "id": id_,
        "parentId": parent,
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "model": "test",
            "content": [
                {"type": "toolCall", "id": cid, "name": name, "arguments": args}
                for cid, name, args in calls
            ],
        },
    }


def test_session_features_and_unmapped_issue_from_a_pi_session(tmp_path):
    calls = [
        ("c1", "edit", {"path": "/r/a.py", "oldText": "x", "newText": "y"}),
        ("c2", "write", {"path": "/r/b.ts", "content": ""}),
        ("c3", "read", {"path": "/r/c.py"}),
        ("c4", "frobnicate", {"x": 1}),
    ]
    rows = [
        {"type": "session", "id": "s", "cwd": "/r"},
        {
            "type": "message",
            "id": "u",
            "timestamp": "2026-10-02T00:00:00Z",
            "message": {"role": "user", "content": "go"},
        },
        _assistant("a", "u", calls, "2026-10-02T00:00:01Z"),
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", tmp_path / "source")
        store.capture_stream(
            source, "s.jsonl", [(canonical(r) + "\n").encode() for r in rows], format_name="jsonl"
        )
        store.rebuild()
        features = {
            (row["feature"], row["value"]): row["n"]
            for row in store.db.execute("SELECT feature,value,n FROM session_feature")
        }
        assert features[("file_extension", ".py")] == 2
        assert features[("file_extension", ".ts")] == 1
        assert features[("tool_category", "file.edit")] == 1
        assert features[("tool_category", "file.write")] == 1
        assert features[("tool_category", "file.read")] == 1
        assert features[("tool_category", "other")] == 1
        issues = store.db.execute(
            "SELECT severity,detail FROM ingest_issue WHERE code='unmapped_tool_name'"
        ).fetchall()
        assert len(issues) == 1 and issues[0]["severity"] == "info"
        assert json.loads(issues[0]["detail"]) == {
            "agent": "pi",
            "name": "frobnicate",
            "calls": 1,
            "session_calls": 4,
            "share": 0.25,
        }
