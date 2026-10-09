"""Per-agent tool name -> kind tables and argument-level file extraction.

Every table lists the names an agent's harness actually registers, so an unknown name is a
real gap (reported as ``ingest_issue(unmapped_tool_name)``) instead of silently landing in
``other``. Names that exist but have no analytic category (browser, memory, TTS ...) are
mapped to ``other`` explicitly and are *not* reported.

Sources (pinned submodules under ``third_party/``; see docs/research/agent-sessions/):

- claude_code: Claude Code tool list (docs/research/agent-sessions/claude-code.md; the
  ``mcp__<server>__<tool>`` form is from the same note) plus names observed in local
  transcripts (``NotebookEdit``, ``BashOutput``, ``KillShell``/``KillBash``).
- codex: third_party/codex codex-rs/core/src/tools (``shell``, ``shell_command``,
  ``exec_command``, ``write_stdin``, ``apply_patch``, ``update_plan``, ``view_image``,
  ``request_user_input`` and the ``_async`` variant seen in local rollouts), the
  ``local_shell_call`` response item and the app-server thread item types
  (``CommandExecution``, ``FileChange``, ``WebSearch``, ``ImageView``) the connector emits.
- dsh: docs/research/agent-sessions/dsh.md (local name census: bash, read, grep,
  todo_write, edit, glob, subagent, report, list_agents) and deepseek-harness tools.
- pi: third_party/pi packages/coding-agent/src/core/tools/*.ts (``name: "..."``).
- opencode: third_party/opencode packages/opencode/src/tool/*.ts (``Tool.define(id)``;
  shell/id.ts keeps the exposed shell id ``bash``). MCP tools are ``<client>_<tool>``
  (mcp/catalog.ts ``toolName``), indistinguishable by name alone: the connector must pass
  ``mcp_server``/``mcp_tool``.
- hermes: third_party/hermes-agent tools/*.py ``registry.register(name=...)``.
- kimi: Kimi Code (MoonshotAI/kimi-cli ``src/kimi_cli/tools``; not vendored): ``Shell``,
  ``ReadFile``, ``WriteFile``, ``StrReplaceFile``, ``Glob``, ``Grep``, ``SearchWeb``,
  ``FetchURL``, ``Task``, ``SetTodoList``, ``Think``, ``ReadMediaFile``.
"""

from __future__ import annotations

import re
import shlex

KINDS = (
    "shell",
    "file.read",
    "file.edit",
    "file.write",
    "search",
    "web.search",
    "web.fetch",
    "subagent",
    "skill",
    "plan",
    "ask_user",
    "other",
)


def _table(**kinds: tuple[str, ...]) -> dict[str, str]:
    table = {}
    for kind, names in kinds.items():
        kind = kind.replace("_dot_", ".")
        assert kind in KINDS, kind
        for name in names:
            table[name.lower()] = kind
    return table


AGENT_TOOL_KINDS: dict[str, dict[str, str]] = {
    "claude_code": _table(
        shell=("Bash", "BashOutput", "KillShell", "KillBash", "PowerShell"),
        file_dot_read=("Read", "NotebookRead", "LS"),
        file_dot_edit=("Edit", "MultiEdit", "NotebookEdit"),
        file_dot_write=("Write",),
        search=("Grep", "Glob"),
        web_dot_search=("WebSearch",),
        web_dot_fetch=("WebFetch",),
        subagent=("Task", "Agent"),
        skill=("Skill",),
        plan=("TodoWrite", "ExitPlanMode", "EnterPlanMode"),
        ask_user=("AskUserQuestion",),
        other=("SlashCommand", "ListMcpResourcesTool", "ReadMcpResourceTool", "ToolSearch"),
    ),
    "codex": _table(
        shell=(
            "shell",
            "shell_command",
            "exec_command",
            "write_stdin",
            "local_shell",
            "local_shell_call",
            "CommandExecution",
            "unified_exec",
            "container.exec",
            "exec",
        ),
        file_dot_read=("view_image", "ImageView", "read_file", "list_dir"),
        file_dot_edit=("apply_patch", "FileChange"),
        search=("grep_files", "tool_search_call", "tool_search"),
        web_dot_search=("web_search", "web_search_call", "WebSearch", "web.search"),
        subagent=("spawn_agent", "send_input", "wait", "close_agent"),
        plan=("update_plan",),
        ask_user=("request_user_input", "request_user_input_async"),
        other=(
            "image_generation_call",
            "Extension",
            "image_gen",
            "image_gen.generation",
            "clock.sleep",
        ),
    ),
    "dsh": _table(
        shell=("bash",),
        file_dot_read=("read",),
        file_dot_edit=("edit",),
        file_dot_write=("write",),
        search=("grep", "glob"),
        web_dot_search=("web_search", "web"),
        web_dot_fetch=("web_fetch",),
        subagent=("subagent", "list_agents"),
        plan=("todo_write",),
        other=("report",),
    ),
    "pi": _table(
        shell=("bash", "powershell"),
        file_dot_read=("read", "ls"),
        file_dot_edit=("edit",),
        file_dot_write=("write",),
        search=("grep", "find"),
    ),
    "opencode": _table(
        shell=("bash", "pwsh", "powershell", "cmd", "shell"),
        file_dot_read=("read", "list", "lsp"),
        file_dot_edit=("edit", "apply_patch", "multiedit", "patch"),
        file_dot_write=("write",),
        search=("grep", "glob", "codesearch"),
        web_dot_search=("websearch",),
        web_dot_fetch=("webfetch",),
        subagent=("task",),
        skill=("skill",),
        plan=("todowrite", "todoread", "plan_exit", "plan_enter"),
        ask_user=("question",),
        other=("invalid", "code_mode"),
    ),
    "hermes": _table(
        shell=("terminal", "execute_code", "process_manage", "read_terminal", "close_terminal"),
        file_dot_read=("read_file",),
        file_dot_edit=("patch",),
        file_dot_write=("write_file",),
        search=("search_files", "session_search"),
        web_dot_search=("web_search", "x_search"),
        web_dot_fetch=("web_extract",),
        subagent=("delegate_task",),
        skill=("skill_view", "skills_list", "skill_manage"),
        plan=("todo", "todo_list"),
        ask_user=("clarify",),
        other=(
            "memory",
            "browser_cdp",
            "browser_dialog",
            "browser_exec",
            "computer_use",
            "vision_analyze",
            "image_generate",
            "text_to_speech",
            "cronjob_manage",
            "video_analyze",
            "video_generate",
        ),
    ),
    "kimi": _table(
        shell=("Shell",),
        file_dot_read=("ReadFile", "ReadMediaFile"),
        file_dot_edit=("StrReplaceFile",),
        file_dot_write=("WriteFile",),
        search=("Glob", "Grep"),
        web_dot_search=("SearchWeb",),
        web_dot_fetch=("FetchURL",),
        subagent=("Task",),
        plan=("SetTodoList",),
        other=("Think",),
    ),
}

# Agent unknown (registered at runtime, tests): the union, first table wins on conflicts.
_ANY: dict[str, str] = {}
for _table_ in AGENT_TOOL_KINDS.values():
    for _name, _kind in _table_.items():
        _ANY.setdefault(_name, _kind)


def tool_kind(name: str, agent: str | None) -> tuple[str, bool]:
    """(kind, known) for a tool name; ``known`` is False when no table lists the name."""
    table = AGENT_TOOL_KINDS.get(agent or "", _ANY)
    kind = table.get(name.lower())
    if kind is None:
        return "other", False
    return kind, True


# apply_patch envelope (codex-rs/apply-patch; opencode/hermes reuse the format).
_PATCH_HEADER = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M
)
_PATCH_OP = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$", re.M)
_PATH_KEYS = ("path", "file_path", "filename", "notebook_path", "filePath", "file")
_PATCH_KEYS = ("input", "patch", "patchText", "patch_text")


def patch_files(text: str) -> list[tuple[str, str]]:
    """(path, op) from ``*** Add/Update/Delete File:`` headers; a Move adds the destination."""
    out = []
    for match in _PATCH_HEADER.finditer(text):
        if match.group(1):
            op = _PATCH_OP.match(match.group(0)).group(1).lower()
            out.append((match.group(1), {"add": "add", "update": "update", "delete": "delete"}[op]))
        else:
            out.append((match.group(2), "move"))
    return out


def _change_op(value) -> str:
    kind = None
    if isinstance(value, dict):
        # codex protocol FileChange: {"add": {...}} | {"delete": {...}} | {"update": {...}}
        tagged = [key for key in ("add", "delete", "update") if key in value]
        if len(tagged) == 1:
            return tagged[0]
        kind = value.get("type", value.get("kind"))
        if isinstance(kind, dict):
            kind = kind.get("type")
    kind = str(kind or "").lower()
    return {"add": "add", "create": "add", "delete": "delete", "update": "update"}.get(
        kind, "update" if kind.startswith("update") else "unknown"
    )


def file_ops(args) -> list[tuple[str, str]]:
    """(path, op) pairs named by a tool's arguments; op is unknown when not stated.

    Handles the top-level path keys, ``paths[]``, Codex ``changes`` (dict keyed by path, or
    a list of ``{path, kind}``), and apply_patch text (a raw string, or under
    ``input``/``patch``/``patchText``).
    """
    out: list[tuple[str, str]] = []
    if isinstance(args, str):
        return patch_files(args)
    if isinstance(args, list):
        for item in args:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                out.append((item["path"], _change_op(item)))
        return out
    if not isinstance(args, dict):
        return out
    for key in _PATH_KEYS:
        if isinstance(args.get(key), str) and args[key]:
            out.append((args[key], "unknown"))
    paths = args.get("paths")
    if isinstance(paths, list):
        out.extend((p, "unknown") for p in paths if isinstance(p, str) and p)
    changes = args.get("changes")
    if isinstance(changes, dict):
        out.extend((path, _change_op(value)) for path, value in changes.items())
    elif isinstance(changes, list):
        out.extend(file_ops(changes))
    for key in _PATCH_KEYS:
        if isinstance(args.get(key), str) and "*** " in args[key]:
            out.extend(patch_files(args[key]))
    if not out and args and all(isinstance(k, str) and "/" in k for k in args):
        # Codex patch_apply_begin ``changes`` passed as the whole input: {path: change}.
        out.extend((path, _change_op(value)) for path, value in args.items())
    seen, unique = set(), []
    for path, op in out:
        if path not in seen:
            seen.add(path)
            unique.append((path, op))
    return unique


def command_text(command) -> str | None:
    """A shell command as one string: argv arrays are ``shlex.join``ed (``bash -lc X`` kept)."""
    if isinstance(command, str):
        return command
    if isinstance(command, list) and command and all(isinstance(p, str) for p in command):
        return shlex.join(command)
    return None
