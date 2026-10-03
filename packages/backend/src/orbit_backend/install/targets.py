"""Install landing table (IN-01): which file, which pointer, which format, for each kind × agent × scope.

Only user and local layers are written. Managed settings, a project's shared
``.claude/settings.json`` and anything that resolves outside the agent roots (symlink
escape) are refused. ``run_command`` style installs (``claude plugin install``) are not
executed in v1. Renderers here are pure; markers for md/toml blocks are added by the ops
layer, so ``content`` is the block body only.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .env import Env, display

KINDS = ("permission_rule", "rule", "skill", "hook", "mcp", "plugin", "subagent", "command", "setting")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
NAME = re.compile(r"[A-Za-z0-9._-]{1,128}")
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
MAX_SKILL_FILES = 50
KIND_CAPABILITY = {"permission_rule": "permission_rules", "rule": "rules", "skill": "skills", "hook": "hooks",
                   "mcp": "mcp", "plugin": "plugins", "subagent": "subagents", "command": "commands"}


class PlanError(Exception):
    def __init__(self, code: str, message: str = "", http: int = 422):
        super().__init__(message or code)
        self.code, self.message, self.http = code, message or code, http


@dataclass(frozen=True)
class Row:
    """One landing rule. ``reason`` set means the combination is not mappable."""

    action: str | None = None
    path: str | None = None  # template: {root} {claude_json} {proj} {skills} {name} {id} {rel}
    pointer: str | None = None  # template: {event} {name} {proj}
    write_mode: str = "add"
    scope: str | None = None  # overrides the spec scope ('local' for private project files)
    shared_layer: bool = False
    requires_trust: bool = False
    note: str | None = None
    reason: str | None = None
    chain: str | None = None  # md_block whose file is picked by ``context_file``


C, X, D, P, H, OC = "claude_code", "codex", "dsh", "pi", "hermes", "opencode"
SCOPES = ("user", "project")
TABLE: dict[tuple[str, str, str], Row] = {
    ("permission_rule", C, "user"): Row("merge_json", "{root}/settings.json", "/permissions/allow"),
    ("permission_rule", C, "project"): Row("merge_json", "{proj}/.claude/settings.local.json", "/permissions/allow",
                                           scope="local"),
    ("setting", C, "user"): Row("merge_json", "{root}/settings.json", "", write_mode="set"),
    ("setting", C, "project"): Row("merge_json", "{proj}/.claude/settings.local.json", "", write_mode="set",
                                   scope="local"),
    ("rule", C, "user"): Row("md_block", "{root}/CLAUDE.md"),
    ("rule", C, "project"): Row("md_block", "{proj}/CLAUDE.md", shared_layer=True),
    ("skill", C, "user"): Row("create_file", "{root}/skills/{name}/{rel}"),
    ("skill", C, "project"): Row("create_file", "{proj}/.claude/skills/{name}/{rel}", shared_layer=True),
    ("subagent", C, "user"): Row("create_file", "{root}/agents/{name}.md"),
    ("subagent", C, "project"): Row("create_file", "{proj}/.claude/agents/{name}.md", shared_layer=True),
    ("command", C, "user"): Row("create_file", "{root}/commands/{name}.md"),
    ("command", C, "project"): Row("create_file", "{proj}/.claude/commands/{name}.md", shared_layer=True),
    ("hook", C, "user"): Row("merge_json", "{root}/settings.json", "/hooks/{event}"),
    ("hook", C, "project"): Row("merge_json", "{proj}/.claude/settings.local.json", "/hooks/{event}", scope="local"),
    ("mcp", C, "user"): Row("merge_json", "{claude_json}", "/mcpServers/{name}", write_mode="set"),
    # Claude Code's private "local" MCP scope lives in ~/.claude.json under the project's path.
    ("mcp", C, "project"): Row("merge_json", "{claude_json}", "/projects/{proj}/mcpServers/{name}",
                               write_mode="set", scope="local"),
    ("plugin", C, "user"): Row("merge_json", "{root}/settings.json", "/enabledPlugins"),
    ("plugin", C, "project"): Row("merge_json", "{proj}/.claude/settings.local.json", "/enabledPlugins",
                                  scope="local"),
    # ---- Codex (third_party/codex/codex-rs). Project layers (``<proj>/.codex``) load only for
    # trusted projects (core/src/exec_policy.rs:662 "Disabled project layers already represent the
    # trust decision"; hooks/src/engine/discovery.rs:146), hence ``requires_trust``.
    # rules/*.rules + prefix_rule(pattern=[...], decision="allow"): core/src/exec_policy.rs:54-56,679,
    # execpolicy/src/parser.rs prefix_rule.
    ("permission_rule", X, "user"): Row("create_file", "{root}/rules/orbit-{id}.rules"),
    ("permission_rule", X, "project"): Row("create_file", "{proj}/.codex/rules/orbit-{id}.rules",
                                           requires_trust=True, shared_layer=True),
    # AGENTS.override.md shadows AGENTS.md: codex-home/src/instructions/mod.rs:12-13,43 and
    # core/src/agents_md.rs:271 candidate_filenames.
    ("rule", X, "user"): Row("md_block", chain="codex_user"),
    ("rule", X, "project"): Row("md_block", chain="codex_project", shared_layer=True),
    # ~/.agents/skills (user) and <repo>/.agents/skills (repo): ext/skills/src/host_roots.rs:24-25,96-107,137-172.
    ("skill", X, "user"): Row("create_file", "{skills}/{name}/{rel}"),
    ("skill", X, "project"): Row("create_file", "{proj}/.agents/skills/{name}/{rel}", shared_layer=True),
    ("command", X, "user"): Row(reason="codex_custom_prompts_removed"),
    ("command", X, "project"): Row(reason="codex_custom_prompts_removed"),
    # hooks.json beside config.toml, Claude-compatible schema: hooks/src/engine/discovery.rs:339-380.
    ("hook", X, "user"): Row("merge_json", "{root}/hooks.json", "/hooks/{event}", requires_trust=True),
    ("hook", X, "project"): Row("merge_json", "{proj}/.codex/hooks.json", "/hooks/{event}", requires_trust=True,
                                shared_layer=True),
    # [mcp_servers.<name>] stdio / streamable_http only: config/src/mcp_types.rs:614 McpServerTransportConfig.
    ("mcp", X, "user"): Row("toml_block", "{root}/config.toml"),
    ("mcp", X, "project"): Row("toml_block", "{proj}/.codex/config.toml", requires_trust=True, shared_layer=True),
    **{(k, X, s): Row(reason=r) for k, r in (("subagent", "codex_has_no_subagent_files"),
                                             ("plugin", "codex_plugin_install_unsupported_v1"),
                                             ("setting", "codex_settings_unsupported_v1"))
       for s in SCOPES},
    # ---- dsh (third_party/deepseek-harness). Skills: packages/skill/skill-filesystem/README.md
    # "Roots and priority" (<dshHome>/skills, <projectRoot>/.dsh/skills). Rules: $DSH_HOME/AGENTS.md
    # plus every AGENTS.md/CLAUDE.md in the project chain, no shadowing
    # (packages/context/agent-instructions/README.md:32,64,66). MCP and hooks are Cordis YAML
    # plugin patches (docs/user/guide/mcp-memory.md, packages/hooks/README.md): not written in v1.
    ("rule", D, "user"): Row("md_block", "{root}/AGENTS.md"),
    ("rule", D, "project"): Row("md_block", "{proj}/AGENTS.md", shared_layer=True),
    ("skill", D, "user"): Row("create_file", "{root}/skills/{name}/{rel}"),
    ("skill", D, "project"): Row("create_file", "{proj}/.dsh/skills/{name}/{rel}", shared_layer=True),
    **{(k, D, s): Row(reason="dsh_cordis_patch_unsupported_v1") for k in ("mcp", "hook") for s in SCOPES},
    # ---- pi (third_party/pi/packages/coding-agent/src). Agent dir config.ts:563; skills/prompts
    # under it and under <proj>/.pi, project ones only for trusted projects
    # (core/package-manager.ts:2446-2520); mcp.json {mcpServers} (extensions/mcp/config.ts:1-25,117-118);
    # context file = first of AGENTS.override.md/AGENTS.md/CLAUDE.md per dir (core/resource-loader.ts:184-245).
    ("rule", P, "user"): Row("md_block", chain="pi_user"),
    ("rule", P, "project"): Row("md_block", chain="pi_project", shared_layer=True),
    ("skill", P, "user"): Row("create_file", "{root}/skills/{name}/{rel}"),
    ("skill", P, "project"): Row("create_file", "{proj}/.pi/skills/{name}/{rel}", requires_trust=True,
                                 shared_layer=True),
    ("command", P, "user"): Row("create_file", "{root}/prompts/{name}.md"),
    ("command", P, "project"): Row("create_file", "{proj}/.pi/prompts/{name}.md", requires_trust=True,
                                   shared_layer=True),
    ("mcp", P, "user"): Row("merge_json", "{root}/mcp.json", "/mcpServers/{name}", write_mode="set"),
    ("mcp", P, "project"): Row("merge_json", "{proj}/.pi/mcp.json", "/mcpServers/{name}", write_mode="set",
                               requires_trust=True, shared_layer=True),
    **{("hook", P, s): Row(reason="pi_hooks_are_extensions") for s in SCOPES},
    # ---- Hermes (third_party/hermes-agent). Skills under $HERMES_HOME/skills, walked recursively
    # (tools/skill_manager_tool.py:70, agent/skill_utils.py:781); project <root>/.hermes/skills only
    # for skills.trusted_project_dirs (agent/skill_utils.py:429-436). Project context priority
    # .hermes.md > AGENTS.md > CLAUDE.md > .cursorrules, first non-empty type wins
    # (agent/prompt_builder.py:1690-1760). The only user-level file is SOUL.md, the identity slot
    # (prompt_builder.py:1627). MCP and hooks live in config.yaml (hermes_cli/config.py:1004,3200).
    ("rule", H, "user"): Row(reason="hermes_soul_md_is_identity"),
    ("rule", H, "project"): Row("md_block", chain="hermes_project", shared_layer=True),
    ("skill", H, "user"): Row("create_file", "{root}/skills/{name}/{rel}"),
    ("skill", H, "project"): Row("create_file", "{proj}/.hermes/skills/{name}/{rel}", requires_trust=True,
                                 shared_layer=True),
    **{(k, H, s): Row(reason="hermes_yaml_config_unsupported_v1") for k in ("mcp", "hook") for s in SCOPES},
    # ---- OpenCode (third_party/opencode/packages). Config dir core/src/global.ts:13,64; opencode.json /
    # opencode.jsonc (opencode/src/config/config.ts:272-274); skills {skill,skills}/**/SKILL.md
    # (opencode/src/skill/index.ts:24,205); commands {command,commands}/**/*.md (config/command.ts:15);
    # mcp local/remote (core/src/v1/config/mcp.ts); permission.bash pattern map, last match wins
    # (core/src/v1/config/permission.ts, opencode/src/permission/index.ts:32, core/src/util/wildcard.ts).
    # Global AGENTS.md shadows ~/.claude/CLAUDE.md; per project the first of AGENTS.md/CLAUDE.md wins
    # (opencode/src/session/instruction.ts:60-131).
    ("rule", OC, "user"): Row("md_block", chain="opencode_user"),
    ("rule", OC, "project"): Row("md_block", chain="opencode_project", shared_layer=True),
    ("skill", OC, "user"): Row("create_file", "{cfg}/skills/{name}/{rel}"),
    ("skill", OC, "project"): Row("create_file", "{proj}/.opencode/skills/{name}/{rel}", shared_layer=True),
    ("command", OC, "user"): Row("create_file", "{cfg}/commands/{name}.md"),
    ("command", OC, "project"): Row("create_file", "{proj}/.opencode/commands/{name}.md", shared_layer=True),
    ("mcp", OC, "user"): Row("merge_json", "{oc_user}", "/mcp/{name}", write_mode="set"),
    ("mcp", OC, "project"): Row("merge_json", "{oc_proj}", "/mcp/{name}", write_mode="set", shared_layer=True),
    ("permission_rule", OC, "user"): Row("merge_json", "{oc_user}", "/permission/bash"),
    ("permission_rule", OC, "project"): Row("merge_json", "{oc_proj}", "/permission/bash", shared_layer=True),
    # Claude-style ``tools: Read, Grep`` front matter fails OpenCode's agent schema (tools is a map),
    # and a bad agent file aborts config loading (config/agent.ts:13).
    **{("subagent", OC, s): Row(reason="opencode_subagent_format_differs") for s in SCOPES},
    **{("hook", OC, s): Row(reason="opencode_hooks_are_plugins") for s in SCOPES},
}
# Everything not listed for the newer agents has no landing point upstream.
for _agent in (D, P, H, OC):
    for _kind in KINDS:
        for _scope in SCOPES:
            TABLE.setdefault((_kind, _agent, _scope), Row(reason="not_mappable"))

# Context-file chains: ordered candidates (path template, ours?). The first existing one (non-empty
# where the agent skips empty files) is the file the agent reads; writing a different one would be
# ignored or would shadow it. A foreign file (another tool's CLAUDE.md, .cursorrules) is never
# rewritten on this agent's behalf: the target is refused instead.
CHAINS: dict[str, tuple[bool, tuple[tuple[str, bool], ...]]] = {
    "codex_user": (True, (("{root}/AGENTS.override.md", True), ("{root}/AGENTS.md", True))),
    "codex_project": (False, (("{proj}/AGENTS.override.md", True), ("{proj}/AGENTS.md", True))),
    "pi_user": (False, (("{root}/AGENTS.override.md", True), ("{root}/AGENTS.md", True),
                        ("{root}/CLAUDE.md", False))),
    "pi_project": (False, (("{proj}/AGENTS.override.md", True), ("{proj}/AGENTS.md", True),
                           ("{proj}/CLAUDE.md", False))),
    "hermes_project": (True, (("{proj}/.hermes.md", True), ("{proj}/HERMES.md", True),
                              ("{proj}/AGENTS.override.md", True), ("{proj}/AGENTS.md", True),
                              ("{proj}/CLAUDE.md", False), ("{proj}/.cursorrules", False))),
    "opencode_user": (False, (("{cfg}/AGENTS.md", True), ("{home}/.claude/CLAUDE.md", False))),
    "opencode_project": (False, (("{proj}/AGENTS.md", True), ("{proj}/CLAUDE.md", False))),
}
CHAIN_DEFAULT = "AGENTS.md"


def context_file(chain: str, values: dict) -> tuple[str | None, str | None]:
    """(path, None) for the file the agent actually reads, or (None, reason) when it is foreign."""
    skip_empty, candidates = CHAINS[chain]
    for template, ours in candidates:
        path = template.format(**values)
        try:
            if not os.path.isfile(path) or (skip_empty and not Path(path).read_text("utf-8", "replace").strip()):
                continue
        except OSError:
            continue
        return (path, None) if ours else (None, f"context_file_shadowed:{os.path.basename(path)}")
    base = os.path.dirname(candidates[0][0].format(**values))
    return os.path.join(base, CHAIN_DEFAULT), None


def opencode_config_file(directory: str) -> str:
    """The OpenCode JSON config to merge into: an existing opencode.json, else opencode.jsonc, else new json.

    A .jsonc with comments is refused by the JSON merge (``parse_error``) rather than stripped.
    """
    for name in ("opencode.json", "opencode.jsonc"):
        if os.path.isfile(os.path.join(directory, name)):
            return os.path.join(directory, name)
    return os.path.join(directory, "opencode.json")


def lookup(kind: str, agent: str, scope: str) -> Row | None:
    return TABLE.get((kind, agent, scope))


# ---- validation -----------------------------------------------------------------------------

HOOKS_DIR = "{orbit.hooks}"
HOOK_FILE = re.compile(r"[A-Za-z0-9._@-]{1,128}")


def hook_file(value) -> str:
    """File name inside the Orbit hooks dir; AI templates use ``<id>@<version>.py``."""
    if not isinstance(value, str) or not HOOK_FILE.fullmatch(value) or value.startswith("."):
        raise PlanError("unsafe_name", f"unsafe hook file name: {value!r}")
    return value


def safe_name(value) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value) or ".." in value or value in (".",):
        raise PlanError("unsafe_name", f"unsafe name: {value!r}")
    return value


def safe_rel(value) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise PlanError("unsafe_path", f"unsafe relative path: {value!r}")
    parts = PurePosixPath(value).parts
    if len(parts) > 8:
        raise PlanError("unsafe_path", f"path too deep: {value!r}")
    for part in parts:
        safe_name(part)
    return "/".join(parts)


def pointer_token(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


# ---- renderers ------------------------------------------------------------------------------

def _prefixes(payload: dict) -> list[str]:
    allow = payload.get("allow")
    if not isinstance(allow, list) or not allow:
        raise PlanError("invalid_payload", "permission_rule.allow must be a non-empty list")
    out = []
    for p in allow:
        if not isinstance(p, str) or not p.strip() or any(c in p for c in "\n\r()"):
            raise PlanError("invalid_payload", f"bad command prefix: {p!r}")
        out.append(" ".join(p.split()))
    return out


def render_claude_permissions(payload: dict) -> list[str]:
    return [f"Bash({p}:*)" for p in _prefixes(payload)]


def render_codex_rules(payload: dict) -> str:
    lines = []
    for p in _prefixes(payload):
        try:
            tokens = shlex.split(p)
        except ValueError as error:
            raise PlanError("invalid_payload", f"bad command prefix: {p!r}") from error
        lines.append(f"prefix_rule(pattern={json.dumps(tokens, ensure_ascii=False, separators=(',', ':'))}, "
                     f'decision="allow")')
    return "\n".join(lines) + "\n"


def render_md(payload: dict) -> str:
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise PlanError("invalid_payload", "rule.text is required")
    heading = payload.get("heading")
    body = text.strip("\n")
    return f"## {heading.strip()}\n\n{body}" if isinstance(heading, str) and heading.strip() else body


def render_hook_entry(payload: dict, command: str) -> list[dict]:
    hook = {"type": "command", "command": command}
    if payload.get("timeout") is not None:
        hook["timeout"] = int(payload["timeout"])
    entry: dict = {"hooks": [hook]}
    if payload.get("matcher") is not None:
        entry = {"matcher": str(payload["matcher"]), **entry}
    return [entry]


def _mcp_fields(payload: dict) -> tuple[str, str]:
    name = safe_name(payload.get("name"))
    transport = payload.get("transport") or ("http" if payload.get("url") else "stdio")
    if transport not in ("stdio", "http", "sse"):
        raise PlanError("invalid_payload", f"unknown MCP transport: {transport}")
    if transport == "stdio" and not payload.get("command"):
        raise PlanError("invalid_payload", "stdio MCP needs command")
    if transport != "stdio" and not payload.get("url"):
        raise PlanError("invalid_payload", "http/sse MCP needs url")
    return name, transport


def render_claude_mcp(payload: dict) -> dict:
    _, transport = _mcp_fields(payload)
    if transport == "stdio":
        out = {"type": "stdio", "command": payload["command"], "args": list(payload.get("args") or [])}
        if payload.get("env"):
            out["env"] = dict(payload["env"])
        return out
    out = {"type": transport, "url": payload["url"]}
    if payload.get("headers"):
        out["headers"] = dict(payload["headers"])
    return out


def _toml_key(key: str) -> str:
    return key if BARE_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=False)


def _toml_table(name: str, values: dict) -> list[str]:
    lines = [f"[{name}]"]
    for k, v in values.items():
        lines.append(f"{_toml_key(str(k))} = {json.dumps(v if isinstance(v, list) else str(v), ensure_ascii=False)}")
    return lines


def render_pi_mcp(payload: dict) -> dict:
    """pi ``mcpServers`` entry (pi core/mcp-servers.ts McpStdioServerConfig / McpHttpServerConfig)."""
    _, transport = _mcp_fields(payload)
    if transport == "stdio":
        out = {"command": payload["command"], "args": [str(a) for a in payload.get("args") or []]}
        if payload.get("env"):
            out["env"] = dict(payload["env"])
        return out
    out = {"type": "http", "url": payload["url"]}
    if payload.get("headers"):
        out["headers"] = dict(payload["headers"])
    return out


def render_opencode_mcp(payload: dict) -> dict:
    """OpenCode ``mcp`` entry (opencode core/src/v1/config/mcp.ts Local / Remote)."""
    _, transport = _mcp_fields(payload)
    if transport == "stdio":
        out = {"type": "local", "command": [str(payload["command"]), *(str(a) for a in payload.get("args") or [])]}
        if payload.get("env"):
            out["environment"] = dict(payload["env"])
        return out
    out = {"type": "remote", "url": payload["url"]}
    if payload.get("headers"):
        out["headers"] = dict(payload["headers"])
    return out


def render_opencode_permissions(payload: dict) -> dict:
    """``permission.bash`` patterns; ``"git status *"`` also matches bare ``git status`` (core/src/util/wildcard.ts)."""
    out = {}
    for p in _prefixes(payload):
        if any(c in p for c in "*?"):
            raise PlanError("invalid_payload", f"wildcards are not allowed in a command prefix: {p!r}")
        out[f"{p} *"] = "allow"
    return out


# Transports an agent cannot speak: Codex has stdio + streamable HTTP only
# (codex config/src/mcp_types.rs:614); pi has stdio + http only (pi core/mcp-servers.ts:45,96).
MCP_SSE_UNSUPPORTED = {"codex", "pi"}


def render_codex_mcp(payload: dict) -> str:
    name, transport = _mcp_fields(payload)
    table = f"mcp_servers.{_toml_key(name)}"
    if transport == "stdio":
        lines = _toml_table(table, {"command": payload["command"], "args": [str(a) for a in payload.get("args") or []]})
        if payload.get("env"):
            lines += _toml_table(table + ".env", payload["env"])
    else:
        lines = _toml_table(table, {"url": payload["url"]})
        if payload.get("headers"):
            lines += _toml_table(table + ".http_headers", payload["headers"])
    return "\n".join(lines)


# ---- path policy ----------------------------------------------------------------------------

def _inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def check_path(path: str | Path, env: Env | None, env_info: dict, project_path: str | None) -> str | None:
    """None when writable by policy, else a short reason."""
    lexical = os.path.abspath(str(path))
    real = os.path.realpath(lexical)
    for agent in env_info.get("agents", []):
        for lay in agent.get("layers", []):
            if lay.get("managed") and real in (os.path.realpath(lay["path"]), lay["path"]):
                return "managed_layer"
    if lexical.startswith("/Library/") or lexical.startswith("/etc/"):
        return "managed_layer"
    if project_path and lexical == os.path.join(os.path.abspath(project_path), ".claude", "settings.json"):
        return "project_shared_settings"
    roots, files = [], []
    for agent in env_info.get("agents", []):
        if agent.get("install_support") != "full":
            continue
        roots.append(agent["root_abs"])
        roots += [d["path"] for d in (agent.get("dirs") or {}).values() if d]
        files += [lay["path"] for lay in agent.get("layers", []) if lay["id"] == "mcp_user"]
    if project_path:
        roots.append(os.path.abspath(project_path))
    for f in files:
        if lexical == os.path.abspath(f):
            return None
    lexical_hit = [r for r in roots if _inside(lexical, os.path.abspath(r))]
    if not lexical_hit:
        return "outside_agent_roots"
    if not any(_inside(real, os.path.realpath(r)) for r in lexical_hit):
        return "symlink_escape"
    return None


def follow_link(path: str | Path, home: Path) -> str | None:
    """Real path behind a symlinked target that may be written in place of the link (B6).

    ``~/.codex/AGENTS.md -> ~/.agents/AGENTS.md`` is a common dotfiles layout. Writing the
    link path would replace the link with a copy, so the write goes to the resolved file,
    allowed only when it stays inside the user's home, outside ``.git`` and ``~/Library``,
    and is a regular file (or a new file in an existing directory).
    """
    lexical = os.path.abspath(str(path))
    real = os.path.realpath(lexical)
    if real == lexical:
        return None
    home_real = os.path.realpath(str(home))
    if not _inside(real, home_real) or real == home_real or ".git" in Path(real).parts \
            or _inside(real, os.path.join(home_real, "Library")):
        return None
    if os.path.lexists(real):
        return real if os.path.isfile(real) and not os.path.islink(real) else None
    return real if os.path.isdir(os.path.dirname(real)) else None


REASON_TEXT = {
    "agent_not_supported_v1": "这个 Agent 暂不支持自动安装。",
    "collect_not_available": "Orbit 实时采集暂未支持这个 Agent，会话仍可通过导入获得。",
    "codex_config_unparsable": "Codex 的 config.toml 无法解析，Orbit 不会改写；修正后重新预览。",
    "codex_notify_in_use": "Codex 已配置 notify，Orbit 不会覆盖；如需实时采集请先移除现有 notify。",
    "kimi_unverified_no_source": "Kimi Code 的配置落点尚未核实，暂不自动写入。",
    "codex_custom_prompts_removed": "Codex 已不再读取自定义 prompts 目录，命令请改装为 Skill。",
    "mcp_transport_unsupported": "这个 Agent 不支持该 MCP 传输方式（SSE），未自动写入。",
    "context_file_shadowed": "该目录已有其他工具的说明文件在生效，新建规则文件会覆盖它的作用，请手动添加。",
    "dsh_cordis_patch_unsupported_v1": "dsh 的 MCP 与 Hook 需要写入 Cordis 配置补丁，暂不自动安装。",
    "pi_hooks_are_extensions": "Pi 的 Hook 以 TypeScript 扩展实现，无法自动安装。",
    "hermes_soul_md_is_identity": "Hermes 的用户级说明文件 SOUL.md 是人格设定，不自动写入规则，请改装到项目级。",
    "hermes_yaml_config_unsupported_v1": "Hermes 的 MCP 与 Hook 位于 config.yaml，暂不自动改写。",
    "opencode_subagent_format_differs": "OpenCode 子代理格式与 Claude 不兼容，未自动写入。",
    "opencode_hooks_are_plugins": "OpenCode 的 Hook 以插件实现，无法自动安装。",
    "not_mappable": "这个 Agent 没有对应的落地位置。",
    "codex_has_no_subagent_files": "Codex 没有子代理文件，无法安装此类条目。",
    "codex_plugin_install_unsupported_v1": "Codex 暂不支持插件安装。",
    "codex_settings_unsupported_v1": "Codex 暂不支持写入此类设置。",
    "capability_unavailable": "当前 Agent 版本不支持这类条目。",
    "skipped_binary": "二进制文件不会被写入，请手动复制。",
    "path_policy:managed_layer": "目标是企业托管配置，Orbit 不会改写。",
    "path_policy:project_shared_settings": "项目共享的 .claude/settings.json 不自动改写，请改装到本地层 settings.local.json。",
    "path_policy:outside_agent_roots": "目标不在 Agent 配置目录内，未自动写入。",
    "path_policy:symlink_escape": "目标是指向主目录之外的符号链接，未自动写入；请在链接指向的文件里手动添加。",
}


def reason_text(reason: str | None) -> str | None:
    """Human-readable sentence for an unmappable ``reason`` code (never shows the raw code)."""
    if not reason:
        return None
    return REASON_TEXT.get(reason) or REASON_TEXT.get(reason.split(":", 1)[0]) or "这个目标无法自动安装。"


# ---- resolution -----------------------------------------------------------------------------

def _validate(spec: dict) -> None:
    if spec.get("kind") not in KINDS:
        raise PlanError("invalid_kind", f"unknown kind: {spec.get('kind')!r}")
    if not isinstance(spec.get("id"), str) or not SLUG.fullmatch(spec["id"]):
        raise PlanError("invalid_id", f"bad id: {spec.get('id')!r}")
    if spec.get("scope", "user") not in ("user", "project"):
        raise PlanError("invalid_scope", f"bad scope: {spec.get('scope')!r}")
    if spec.get("scope") == "project":
        p = spec.get("project_path")
        if not isinstance(p, str) or not os.path.isabs(p) or not os.path.isdir(p):
            raise PlanError("project_path_required", "project scope needs an existing absolute project_path")
    if not isinstance(spec.get("payload"), dict):
        raise PlanError("invalid_payload", "payload must be an object")


def resolve_targets(spec: dict, env_info: dict, *, env: Env | None = None) -> list[dict]:
    _validate(spec)
    kind, scope, payload = spec["kind"], spec.get("scope") or "user", spec["payload"]
    project = os.path.abspath(spec["project_path"]) if scope == "project" else None
    home = Path(env_info.get("home") or (env.home if env else Path.home()))
    infos = {a["agent"]: a for a in env_info.get("agents", [])}
    out: list[dict] = []

    def unmappable(agent: str, reason: str, **extra) -> None:
        out.append({"idx": len(out), "agent": agent, "kind": kind, "mappable": False, "reason": reason,
                    "reason_text": reason_text(reason), **extra})

    for agent in spec.get("agents") or []:
        info = infos.get(agent)
        if not info or info.get("install_support") != "full":
            unmappable(agent, (info or {}).get("unsupported_reason") or "agent_not_supported_v1")
            continue
        row = lookup(kind, agent, scope)
        if row is None or row.reason:
            unmappable(agent, row.reason if row else "not_mappable")
            continue
        cap = KIND_CAPABILITY.get(kind)
        if cap and not (info.get("capabilities") or {}).get(cap, True):
            unmappable(agent, f"capability_unavailable:{cap}")
            continue
        note = "agent_not_detected" if not info.get("installed") else row.note
        layers = {lay["id"]: lay["path"] for lay in info.get("layers", [])}
        dirs = info.get("dirs") or {}
        cfg = (dirs.get("config") or {}).get("path", "")
        values = {"root": info["root_abs"], "proj": project or "", "id": spec["id"], "home": str(home),
                  "claude_json": layers.get("mcp_user", ""), "cfg": cfg,
                  "skills": (dirs.get("skills") or {}).get("path", ""),
                  "oc_user": opencode_config_file(cfg) if agent == OC else "",
                  "oc_proj": opencode_config_file(project) if agent == OC and project else ""}

        # "unknown": no checked minimum version for this agent, so it is not shown as compatible.
        vcheck = ("unknown" if cap in (info.get("capabilities") or {}).get("version_unknown", ())
                  else "known")

        def target(path: str, content, *, action=None, pointer=None, row=row, agent=agent, note=note,
                   vcheck=vcheck, **extra) -> None:
            reason = check_path(path, env, env_info, project)
            shown = display(path, home)
            if reason == "symlink_escape" and (real := follow_link(path, home)):
                extra = {**extra, "link_path": path}
                shown = f"{shown} → {display(real, home)}"
                path, reason = real, None
            if reason:
                unmappable(agent, f"path_policy:{reason}", path=path)
                return
            act = action or row.action
            t = {"idx": len(out), "agent": agent, "scope": row.scope or scope, "path": path,
                 "display": shown, "action": act,
                 "pointer": pointer if act == "merge_json" else None, "content": content,
                 "write_mode": row.write_mode if act == "merge_json" else "set", "file_mode": None,
                 "block_id": f"orbit:{spec['id']}" if act in ("md_block", "toml_block") else None,
                 "requires_trust": row.requires_trust, "mappable": True, "reason": None, "note": note,
                 "version_check": vcheck,
                 "group": None, "shared_layer": row.shared_layer or (project is not None and _inside(path, project)
                                                                     and row.scope != "local"), "kind": kind}
            t.update(extra)
            out.append(t)

        if row.chain:
            path, shadow = context_file(row.chain, values)
            if shadow:
                unmappable(agent, shadow)
                continue
        else:
            path = row.path.format(**values, name="{name}", rel="{rel}")
        if kind == "permission_rule":
            renderer = {C: render_claude_permissions, OC: render_opencode_permissions}.get(agent, render_codex_rules)
            target(path, renderer(payload), pointer=row.pointer)
        elif kind == "setting":
            settings = payload.get("settings")
            if not isinstance(settings, dict) or not settings:
                raise PlanError("invalid_payload", "setting.settings must be a non-empty object")
            target(path, settings, pointer="")
        elif kind == "rule":
            target(path, render_md(payload))
        elif kind in ("subagent", "command"):
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise PlanError("invalid_payload", f"{kind}.text is required")
            target(path.replace("{name}", safe_name(payload.get("name"))), text)
        elif kind == "skill":
            name = safe_name(payload.get("name"))
            files = payload.get("files") or []
            if not isinstance(files, list) or not files:
                raise PlanError("invalid_payload", "skill.files must be a non-empty list")
            if len(files) > MAX_SKILL_FILES:
                raise PlanError("too_many_files", f"skill has more than {MAX_SKILL_FILES} files")
            for f in files:
                rel = safe_rel(f.get("rel") if isinstance(f, dict) else None)
                text = f.get("text")
                if not isinstance(text, str) or "\x00" in text:
                    unmappable(agent, "skipped_binary", rel=rel, group=f"skill:{name}")
                    continue
                target(path.replace("{name}", name).replace("{rel}", rel), text, group=f"skill:{name}")
        elif kind == "hook":
            bindings = payload.get("event_bindings") or [{"event": payload.get("event"),
                                                           "matcher": payload.get("matcher")}]
            for b in bindings:
                if not isinstance(b, dict) or not isinstance(b.get("event"), str) or not NAME.fullmatch(b["event"]):
                    raise PlanError("invalid_payload", "hook.event is required")
            command = payload.get("command")
            if not isinstance(command, str) or not command.strip():
                raise PlanError("invalid_payload", "hook.command is required")
            group = f"hook:{spec['id']}"
            base = project + {C: "/.claude", X: "/.codex"}[agent] if project else info["root_abs"]
            # AI hooks address their files as "{orbit.hooks}/<file>" inside a double-quoted command.
            hooks_dir = f"{base}/hooks/orbit" if HOOKS_DIR in command else None
            if hooks_dir and any(c in hooks_dir for c in '"$`\\'):
                raise PlanError("unsafe_path", f"hooks directory cannot be quoted safely: {hooks_dir!r}")
            script = payload.get("script")
            if script:
                if not isinstance(script, dict) or not isinstance(script.get("text"), str):
                    raise PlanError("invalid_payload", "hook.script.text is required")
                if hooks_dir:
                    script_path = f"{hooks_dir}/{hook_file(script.get('name'))}"
                else:
                    script_path = f"{base}/hooks/orbit-{spec['id']}-{safe_name(script.get('name'))}"
                target(script_path, script["text"], action="create_file", file_mode=0o755, group=group,
                       scope=scope, shared_layer=project is not None)
                command = command.replace("{script_path}", shlex.quote(script_path))
            for extra in payload.get("extra_files") or []:
                if not hooks_dir or not isinstance(extra, dict) or not isinstance(extra.get("text"), str):
                    raise PlanError("invalid_payload", "hook.extra_files need {name, text} and {orbit.hooks}")
                target(f"{hooks_dir}/{hook_file(extra.get('name'))}", extra["text"], action="create_file",
                       group=group, scope=scope, shared_layer=project is not None)
            if hooks_dir:
                command = command.replace(HOOKS_DIR, hooks_dir)
            for b in bindings:
                target(path, render_hook_entry({**payload, "matcher": b.get("matcher")}, command),
                       pointer=row.pointer.format(event=pointer_token(b["event"])), group=group)
        elif kind == "mcp":
            name, transport = _mcp_fields(payload)
            if transport == "sse" and agent in MCP_SSE_UNSUPPORTED:
                unmappable(agent, "mcp_transport_unsupported")
                continue
            if agent == X:
                target(path, render_codex_mcp(payload))
            else:
                render = {C: render_claude_mcp, P: render_pi_mcp, OC: render_opencode_mcp}[agent]
                pointer = row.pointer.format(name=pointer_token(name), proj=pointer_token(project or ""))
                target(path, render(payload), pointer=pointer)
        elif kind == "plugin":
            plugin, market = safe_name(payload.get("plugin")), safe_name(payload.get("marketplace"))
            group = f"plugin:{spec['id']}"
            source = payload.get("marketplace_source")
            target(path, {f"{plugin}@{market}": True}, pointer="/enabledPlugins", group=group,
                   note=note if source else "marketplace_must_exist")
            if source:
                if not isinstance(source, dict) or source.get("source") != "github" or not re.fullmatch(
                        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(source.get("repo", ""))):
                    raise PlanError("invalid_payload", "marketplace_source must be {source:'github', repo:'o/r'}")
                target(path, {market: {"source": dict(source)}}, pointer="/extraKnownMarketplaces", group=group)
    return out
