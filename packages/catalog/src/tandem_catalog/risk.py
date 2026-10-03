"""Static risk *estimate* from declared text; a heuristic hint, never an audit result."""

import json
import re

from .contracts import Resource

WEIGHTS = {"destructive": 3, "needs_secret": 2, "runs_command": 2}
# CommonMark fences: ``` or ~~~ (3+), optional info string; an unclosed fence runs to the end of
# the document (bodies are also truncated at 20 KB, which cuts fences open).
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\n`]*)$")
SHELL_INFO = re.compile(r"^(?:bash|sh|shell|zsh|console|terminal)\b", re.I)
SHELL = re.compile(r"(?:```|~~~)[ \t]*(?:bash|sh|shell|zsh|console)\b", re.I)  # manifest text
NETWORK = re.compile(r"\b(?:curl|wget)\b|https?://|\bfetch\(", re.I)
SECRET = re.compile(r"[A-Z0-9_]*(?:_KEY|_TOKEN|SECRET)[A-Z0-9_]*|\bpassword\b", re.I)
WRITES = re.compile(r">>|\btee\s|write_file|\b(?:Edit|Write)\b")
DESTRUCTIVE = re.compile(r"rm\s+-rf|git\s+push\s+(?:-f\b|--force)|git\s+reset\s+--hard|DROP\s+TABLE|chmod\s+777", re.I)
COMMENT = re.compile(r"^\s*(?:#|//|--|REM\b)")


def code_blocks(body: str) -> list[tuple[str, str]]:
    """(info string, code) for fenced (``` / ~~~, closed or not) and indented code blocks.

    Indented blocks follow CommonMark: 4 spaces or a tab, and they cannot interrupt a paragraph
    (the previous line must be blank or already part of the block).
    """
    blocks, lines = [], body.splitlines()
    i = 0
    while i < len(lines):
        fence = FENCE.match(lines[i])
        if fence:
            marker, info, code = fence.group(1), fence.group(2).strip(), []
            i += 1
            while i < len(lines) and not re.match(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$", lines[i]):
                code.append(lines[i])
                i += 1
            blocks.append((info, "\n".join(code)))
            i += 1
            continue
        if re.match(r"^(?: {4}|\t)\S", lines[i]) and (i == 0 or not lines[i - 1].strip()):
            code = []
            while i < len(lines) and (re.match(r"^(?: {4}|\t)", lines[i]) or not lines[i].strip()):
                code.append(lines[i][4:] if lines[i].startswith("    ") else lines[i][1:])
                i += 1
            blocks.append(("", "\n".join(code).strip("\n")))
            continue
        i += 1
    return blocks


def destructive_command(code: str) -> bool:
    """DESTRUCTIVE in an executable line; comment lines ("# never rm -rf") are prose, not commands."""
    return any(DESTRUCTIVE.search(line) for line in code.splitlines() if not COMMENT.match(line))


def allowed_tools(manifest: dict) -> list[str]:
    frontmatter = manifest.get("frontmatter") if isinstance(manifest.get("frontmatter"), dict) else {}
    value = manifest.get("allowed_tools") or manifest.get("allowed-tools") or frontmatter.get("allowed-tools") or []
    if isinstance(value, str):
        value = re.split(r"[,\s]+", value)
    return [str(v) for v in value if v] if isinstance(value, list) else []


def declared_env(manifest: dict) -> list[dict]:
    """Env var names declared by a manifest (MCP registry packages or plain env maps)."""
    found = {}
    env = manifest.get("env")
    if isinstance(env, dict):
        for name in env:
            found[str(name)] = bool(SECRET.fullmatch(str(name)))
    elif isinstance(env, list):
        for name in env:
            if isinstance(name, str):
                found[name] = bool(SECRET.fullmatch(name))
    for package in manifest.get("packages") or []:
        for var in (package.get("environmentVariables") or []) if isinstance(package, dict) else []:
            if isinstance(var, dict) and var.get("name"):
                found[var["name"]] = bool(var.get("isSecret")) or bool(SECRET.fullmatch(var["name"]))
    return [{"name": k, "secret": v} for k, v in sorted(found.items())]


def assess(resource: Resource) -> tuple[list[str], int]:
    """Returns (flags, risk_level 0-3). Labelled an estimate in every response that shows it.

    Command-shaped flags (network, writes, destructive) come only from command context: code
    blocks, declared hook / MCP / install commands. Prose such as "Never run `rm -rf`" is a warning,
    not a command, so it no longer marks an item destructive.
    """
    manifest_text = json.dumps(resource.manifest, ensure_ascii=False)
    blocks = code_blocks(resource.body)
    declared = _commands(resource)
    code = "\n".join([*(c for _, c in blocks), *declared])
    commands = code + " " + json.dumps(resource.install, ensure_ascii=False)
    tools = allowed_tools(resource.manifest)
    flags = set(resource.risk)
    if resource.type == "hook" or any(SHELL_INFO.match(info) for info, _ in blocks) or SHELL.search(manifest_text) or any(
            t.startswith("Bash") for t in tools):
        flags.add("runs_command")
    if NETWORK.search(commands):
        flags.add("network")
    if SECRET.search(manifest_text) or any(e["secret"] for e in declared_env(resource.manifest)):
        flags.add("needs_secret")
    if WRITES.search(code) or any(t in ("Edit", "Write", "MultiEdit") for t in tools):
        flags.add("writes_files")
    if destructive_command(code):
        flags.add("destructive")
    if resource.type == "mcp_server":
        flags.add("external_tools")
    if any("scripts/" in c for c in resource.components) or "scripts/" in (resource.repo_path or ""):
        flags.add("scripts")
    score = sum(WEIGHTS.get(flag, 1) for flag in flags)
    level = 0 if score == 0 else 1 if score <= 2 else 2 if score <= 4 else 3
    return sorted(flags), level


def _commands(resource: Resource) -> list[str]:
    """Shell commands a hook / MCP server would run, from its manifest and install declaration."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            head = node.get("command") or node.get("cmd")
            if isinstance(head, str):
                args = node.get("args") if isinstance(node.get("args"), list) else []
                found.append(" ".join([head, *map(str, args)]))
            for key, value in node.items():
                if key not in ("command", "cmd", "args"):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(resource.manifest.get("hooks"))
    walk(resource.install)
    if resource.type == "mcp_server":
        for package in resource.manifest.get("packages") or []:
            if isinstance(package, dict) and package.get("identifier"):
                found.append(f"{package.get('registryType') or package.get('registry_type') or 'package'} "
                             f"{package['identifier']}")
    return found


def scan(resource: Resource, flags: list[str] | None = None, level: int | None = None) -> dict:
    """Per-item static scan for the detail page: an estimate from text, never an audit result."""
    if flags is None or level is None:
        flags, level = assess(resource)
    reasons = list(flags)
    commands = _commands(resource)
    if commands and "runs_command" not in reasons:
        reasons.append("runs_command")
    destructive = "destructive" in reasons or any(destructive_command(c) for c in commands)
    if destructive and "destructive" not in reasons:
        reasons.append("destructive")
    reasons.extend(f"needs_secret:{e['name']}" for e in declared_env(resource.manifest) if e["secret"])
    if destructive or level >= 3:
        verdict = "dangerous"
    elif level or commands:
        verdict = "caution"
    elif resource.body_policy == "licensed" and resource.body:
        verdict = "safe"  # Text was read and nothing risky was found in it (still an estimate).
    else:
        verdict = "unknown"  # Metadata only: nothing was read, so absence of flags proves nothing.
        reasons.append("body_not_read")
    return {"verdict": verdict, "reasons": sorted(set(reasons)), "level": level, "estimate": True,
            "commands": [c[:300] for c in commands[:10]]}
