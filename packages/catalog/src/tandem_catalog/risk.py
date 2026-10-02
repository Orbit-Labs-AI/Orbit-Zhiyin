"""Static risk *estimate* from declared text; a heuristic hint, never an audit result."""

import json
import re

from .contracts import Resource

WEIGHTS = {"destructive": 3, "needs_secret": 2, "runs_command": 2}
CODE_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.S)
SHELL = re.compile(r"```(?:bash|sh|shell|zsh|console)\b", re.I)
NETWORK = re.compile(r"\b(?:curl|wget)\b|https?://|\bfetch\(", re.I)
SECRET = re.compile(r"[A-Z0-9_]*(?:_KEY|_TOKEN|SECRET)[A-Z0-9_]*|\bpassword\b", re.I)
WRITES = re.compile(r">>|\btee\s|write_file|\b(?:Edit|Write)\b")
DESTRUCTIVE = re.compile(r"rm\s+-rf|git\s+push\s+(?:-f\b|--force)|git\s+reset\s+--hard|DROP\s+TABLE|chmod\s+777", re.I)


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
    """Returns (flags, risk_level 0-3). Labelled an estimate in every response that shows it."""
    manifest_text = json.dumps(resource.manifest, ensure_ascii=False)
    code = " ".join(m.group(2) for m in CODE_BLOCK.finditer(resource.body))
    commands = code + " " + json.dumps(resource.install, ensure_ascii=False)
    tools = allowed_tools(resource.manifest)
    flags = set(resource.risk)
    if resource.type == "hook" or SHELL.search(resource.body) or SHELL.search(manifest_text) or any(
            t.startswith("Bash") for t in tools):
        flags.add("runs_command")
    if NETWORK.search(commands):
        flags.add("network")
    if SECRET.search(manifest_text) or any(e["secret"] for e in declared_env(resource.manifest)):
        flags.add("needs_secret")
    if WRITES.search(code) or any(t in ("Edit", "Write", "MultiEdit") for t in tools):
        flags.add("writes_files")
    if DESTRUCTIVE.search(resource.body) or DESTRUCTIVE.search(manifest_text):
        flags.add("destructive")
    if resource.type == "mcp_server":
        flags.add("external_tools")
    if any("scripts/" in c for c in resource.components) or "scripts/" in (resource.repo_path or ""):
        flags.add("scripts")
    score = sum(WEIGHTS.get(flag, 1) for flag in flags)
    level = 0 if score == 0 else 1 if score <= 2 else 2 if score <= 4 else 3
    return sorted(flags), level
