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


C, X = "claude_code", "codex"
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
    ("permission_rule", X, "user"): Row("create_file", "{root}/rules/tandem-{id}.rules", note="语法待验证 V6"),
    ("permission_rule", X, "project"): Row(reason="codex_project_rules_unsupported_v1"),
    ("rule", X, "user"): Row("md_block", "{root}/AGENTS.md"),
    ("rule", X, "project"): Row("md_block", "{proj}/AGENTS.md", shared_layer=True),
    ("skill", X, "user"): Row("create_file", "{skills}/{name}/{rel}", note="skills 目录待验证 V6"),
    ("skill", X, "project"): Row(reason="codex_project_skills_unsupported_v1"),
    ("command", X, "user"): Row("create_file", "{root}/prompts/{name}.md"),
    ("command", X, "project"): Row(reason="codex_project_prompts_unsupported_v1"),
    ("hook", X, "user"): Row("merge_json", "{root}/hooks.json", "/hooks/{event}", requires_trust=True),
    ("hook", X, "project"): Row(reason="codex_project_hooks_unsupported_v1"),
    ("mcp", X, "user"): Row("toml_block", "{root}/config.toml"),
    ("mcp", X, "project"): Row(reason="codex_project_mcp_unsupported_v1"),
    **{(k, X, s): Row(reason=r) for k, r in (("subagent", "codex_has_no_subagent_files"),
                                             ("plugin", "codex_plugin_install_unsupported_v1"),
                                             ("setting", "codex_settings_unsupported_v1"))
       for s in ("user", "project")},
}


def lookup(kind: str, agent: str, scope: str) -> Row | None:
    return TABLE.get((kind, agent, scope))


# ---- validation -----------------------------------------------------------------------------

HOOKS_DIR = "{tandem.hooks}"
HOOK_FILE = re.compile(r"[A-Za-z0-9._@-]{1,128}")


def hook_file(value) -> str:
    """File name inside the Tandem hooks dir; AI templates use ``<id>@<version>.py``."""
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
    "not_mappable": "这个 Agent 没有对应的落地位置。",
    "codex_project_rules_unsupported_v1": "Codex 暂不支持项目级权限规则，请改装到用户级。",
    "codex_project_skills_unsupported_v1": "Codex 暂不支持项目级 Skill，请改装到用户级。",
    "codex_project_prompts_unsupported_v1": "Codex 暂不支持项目级命令，请改装到用户级。",
    "codex_project_hooks_unsupported_v1": "Codex 暂不支持项目级 Hook，请改装到用户级。",
    "codex_project_mcp_unsupported_v1": "Codex 暂不支持项目级 MCP，请改装到用户级。",
    "codex_has_no_subagent_files": "Codex 没有子代理文件，无法安装此类条目。",
    "codex_plugin_install_unsupported_v1": "Codex 暂不支持插件安装。",
    "codex_settings_unsupported_v1": "Codex 暂不支持写入此类设置。",
    "capability_unavailable": "当前 Agent 版本不支持这类条目。",
    "skipped_binary": "二进制文件不会被写入，请手动复制。",
    "path_policy:managed_layer": "目标是企业托管配置，Tandem 不会改写。",
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
            unmappable(agent, "agent_not_supported_v1")
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
        values = {"root": info["root_abs"], "proj": project or "", "id": spec["id"],
                  "claude_json": layers.get("mcp_user", ""),
                  "skills": ((info.get("dirs") or {}).get("skills") or {}).get("path", "")}

        def target(path: str, content, *, action=None, pointer=None, row=row, agent=agent, note=note,
                   **extra) -> None:
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
                 "block_id": f"tandem:{spec['id']}" if act in ("md_block", "toml_block") else None,
                 "requires_trust": row.requires_trust, "mappable": True, "reason": None, "note": note,
                 "group": None, "shared_layer": row.shared_layer or (project is not None and _inside(path, project)
                                                                     and row.scope != "local"), "kind": kind}
            t.update(extra)
            out.append(t)

        path = row.path.format(**values, name="{name}", rel="{rel}")
        if kind == "permission_rule":
            content = render_claude_permissions(payload) if agent == C else render_codex_rules(payload)
            target(path, content, pointer=row.pointer)
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
            base = project + "/.claude" if (project and agent == C) else info["root_abs"]
            # AI hooks address their files as "{tandem.hooks}/<file>" inside a double-quoted command.
            hooks_dir = f"{base}/hooks/tandem" if HOOKS_DIR in command else None
            if hooks_dir and any(c in hooks_dir for c in '"$`\\'):
                raise PlanError("unsafe_path", f"hooks directory cannot be quoted safely: {hooks_dir!r}")
            script = payload.get("script")
            if script:
                if not isinstance(script, dict) or not isinstance(script.get("text"), str):
                    raise PlanError("invalid_payload", "hook.script.text is required")
                if hooks_dir:
                    script_path = f"{hooks_dir}/{hook_file(script.get('name'))}"
                else:
                    script_path = f"{base}/hooks/tandem-{spec['id']}-{safe_name(script.get('name'))}"
                target(script_path, script["text"], action="create_file", file_mode=0o755, group=group,
                       scope=scope, shared_layer=project is not None)
                command = command.replace("{script_path}", shlex.quote(script_path))
            for extra in payload.get("extra_files") or []:
                if not hooks_dir or not isinstance(extra, dict) or not isinstance(extra.get("text"), str):
                    raise PlanError("invalid_payload", "hook.extra_files need {name, text} and {tandem.hooks}")
                target(f"{hooks_dir}/{hook_file(extra.get('name'))}", extra["text"], action="create_file",
                       group=group, scope=scope, shared_layer=project is not None)
            if hooks_dir:
                command = command.replace(HOOKS_DIR, hooks_dir)
            for b in bindings:
                target(path, render_hook_entry({**payload, "matcher": b.get("matcher")}, command),
                       pointer=row.pointer.format(event=pointer_token(b["event"])), group=group)
        elif kind == "mcp":
            name, _ = _mcp_fields(payload)
            if agent == C:
                pointer = row.pointer.format(name=pointer_token(name), proj=pointer_token(project or ""))
                target(path, render_claude_mcp(payload), pointer=pointer)
            else:
                target(path, render_codex_mcp(payload))
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
