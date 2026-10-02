"""Static risk gate for an install (IN-05). Regex only — nothing is executed.

Texts are collected from ``spec.payload`` and every target's ``content`` and tagged by
context (``hook_cmd``, ``mcp_cmd``, ``script``, ``env``, ``url``, ``perm``, ``text``) so
context-sensitive rules (network egress, shell metacharacters, literal secrets) only fire
where they mean something. ``level`` is the highest finding severity (info -> safe).
"""

from __future__ import annotations

import json
import re
from typing import Any

SEVERITY = {"info": 0, "caution": 1, "dangerous": 2}
LEVEL = {0: "safe", 1: "caution", 2: "dangerous"}
SCRIPT_EXT = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".ts", ".rb", ".pl")

_PIPE_SHELL = [
    re.compile(r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?((ba|z|da)?sh|python3?|node)\b"),
    re.compile(r"\bbase64\s+(-d|-D|--decode)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b"),
    re.compile(r"\beval\s+[\"']?\$\("),
]
_RM_RF = re.compile(r"\brm\s+(?:-[a-zA-Z]*(?:rf|fr)[a-zA-Z]*|-r\s+-f|-f\s+-r|-R\s+-f)\s+([^\s;&|]+)")
_DESTRUCTIVE = [
    re.compile(r"\bgit\s+push\b[^\n;&|]*\s(--force\b|-f\b|--force-with-lease\b)"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bmkfs(\.\w+)?\b"),
    re.compile(r"\bdd\b[^\n]*\bof="),
    re.compile(r"\bchmod\s+-R\s+777\b"),
    re.compile(r"(^|[\s;&|(`])sudo\s"),
    re.compile(r">\s*/dev/(?!null\b|stdout\b|stderr\b|tty\b)\w+"),
]
_CREDENTIAL = re.compile(
    r"~/\.ssh|\.ssh/|\.aws/credentials|(^|[\s/\"'=])\.env\b|id_rsa|id_ed25519|\.pem\b|"
    r"security\s+find-(generic|internet)-password|auth\.json|\.npmrc|\bkeychain\b",
    re.IGNORECASE,
)
_EGRESS = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|rsync)\b|https?://")
_EXFIL = re.compile(
    r"\bcurl\b[^\n]*(\s-d\b|--data|-X\s*POST|--upload-file|\s-F\b|-T\s)|\b(sendmail|mail)\s|"
    r"webhook", re.IGNORECASE)
_METACHAR = re.compile(r";|&&|\|\||`|\$\(")
_INJECTION = re.compile(
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|rules)|"
    r"忽略(之前|以上|前面)(的)?(所有)?(的)?(指令|规则|指示)|"
    r"do\s+not\s+(tell|inform)\s+the\s+user|不要告诉用户|"
    r"(reveal|print|output|send)\s+(your\s+|the\s+)?system\s+prompt",
    re.IGNORECASE,
)
_SECRETS = re.compile(
    r"\b(sk-(ant-)?[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|xox[bpas]-[A-Za-z0-9-]{10,})")
_LONG_RANDOM = re.compile(r"^[A-Za-z0-9+/_=.-]{32,}$")
_PRIVATE_TOOL = re.compile(r"filesystem|server-fs|\bRead\b|sqlite|postgres", re.IGNORECASE)
_UNTRUSTED_TOOL = re.compile(
    r"fetch|browser|puppeteer|playwright|web|github|issue|gmail|email|slack|remote",
    re.IGNORECASE)
_WRITE_PREFIXES = (
    "git push", "git commit", "git checkout", "git reset", "gh pr merge", "gh pr create",
    "rm", "mv", "cp", "chmod", "chown", "kubectl apply", "kubectl delete", "terraform apply",
    "docker run", "docker rm", "npm publish", "pip install", "brew install", "curl", "wget",
    "sudo",
)
_PERM = re.compile(r"^(\w+)(?:\((.*)\))?$", re.DOTALL)


def _ev(text: str, start: int = 0) -> str:
    snippet = text[max(0, start - 20):].strip().replace("\n", " ")
    return snippet if len(snippet) <= 120 else snippet[:117] + "..."


def _mask(secret: str) -> str:
    return secret[:4] + "…" + f"({len(secret)} chars)"


def _collect(spec: dict, targets: list[dict]) -> list[tuple[str, str, int | None]]:
    """``(text, context, target_idx)`` for every string worth scanning."""
    kind = spec.get("kind")
    out: list[tuple[str, str, int | None]] = []

    def walk(value: Any, ctx: str, idx: int | None, key: str = "") -> None:
        if isinstance(value, str):
            if key == "command" and kind in ("hook", "mcp"):
                ctx2 = "hook_cmd" if kind == "hook" else "mcp_cmd"
            elif key == "args" and kind == "mcp":
                ctx2 = "mcp_cmd"
            elif key == "url":
                ctx2 = "url"
            else:
                ctx2 = ctx
            out.append((value, ctx2, idx))
        elif isinstance(value, dict):
            for k, v in value.items():
                sub = "env" if k in ("env", "headers") else ("perm" if k == "allow" else ctx)
                if k == "script" and isinstance(v, dict):
                    walk(v.get("text"), "script", idx)
                    continue
                if isinstance(v, dict) and k in ("env", "headers"):
                    out.extend((str(x), "env", idx) for x in v.values() if isinstance(x, str))
                    continue
                walk(v, sub, idx, k if isinstance(k, str) else "")
        elif isinstance(value, list):
            for v in value:
                walk(v, ctx, idx, key)

    payload = spec.get("payload") or {}
    walk(payload, "perm" if kind == "permission_rule" else "text", None)
    files = payload.get("files")
    for f in files if isinstance(files, list) else []:
        if isinstance(f, dict) and str(f.get("rel", "")).endswith(SCRIPT_EXT):
            out.append((str(f.get("text", "")), "script", None))
    for t in targets:
        idx = t.get("idx")
        content = t.get("content")
        if t.get("action") == "create_file" and isinstance(content, str):
            is_script = str(t.get("path", "")).endswith(SCRIPT_EXT) or (
                (t.get("file_mode") or 0) & 0o111)
            out.append((content, "script" if is_script else "text", idx))
        elif t.get("pointer", "").endswith("/permissions/allow"):
            walk(content, "perm", idx)
        else:
            walk(content, "text", idx)
    seen: set[tuple[str, str]] = set()
    uniq = []
    for text, ctx, idx in out:
        if text and (text, ctx) not in seen:
            seen.add((text, ctx))
            uniq.append((text, ctx, idx))
    return uniq


def _rm_target_ok(path: str) -> bool:
    p = path.strip("'\"")
    if p.startswith("/tmp/") or p == "/tmp":
        return True
    if p.startswith(("/", "~", "$", "*")) or p in (".", "./", "..", "../") or ".." in p.split("/"):
        return False
    return True


def _perm_findings(item: str, idx: int | None) -> list[dict]:
    item = item.strip()
    m = _PERM.match(item)
    tool, arg = (m.group(1), m.group(2)) if m else (None, item)
    if m and tool[0].islower():  # plain command such as "git status"
        tool, arg = None, item
    found = [{"rule": "widens_permissions", "severity": "info", "evidence": _ev(item),
              "target_idx": idx}]
    if tool in ("Bash", "Write", "Edit", "MultiEdit") and arg in (None, "", "*", ":*"):
        found.append({"rule": "broad_allow", "severity": "dangerous", "evidence": _ev(item),
                      "target_idx": idx})
        return found
    if tool not in (None, "Bash") or arg is None:
        return found
    cmd = arg.replace(":*", "").strip().lstrip("*").strip()
    for prefix in _WRITE_PREFIXES:
        if cmd == prefix or cmd.startswith(prefix + " "):
            found.append({"rule": "write_prefix_in_allow", "severity": "dangerous",
                          "evidence": _ev(item), "target_idx": idx})
            break
    return found


def _strip_quotes(cmd: str) -> str:
    return re.sub(r"'[^']*'|\"(?:[^\"\\\\]|\\\\.)*\"", "''", cmd)


def scan(spec: dict, targets: list[dict]) -> dict:
    findings: list[dict] = []
    flags: set[str] = set()

    def hit(rule: str, sev: str, evidence: str, idx: int | None) -> None:
        findings.append({"rule": rule, "severity": sev, "evidence": evidence, "target_idx": idx})

    texts = _collect(spec, targets)
    exec_ctx = ("hook_cmd", "script")
    for text, ctx, idx in texts:
        for rx in _PIPE_SHELL:
            if m := rx.search(text):
                hit("pipe_to_shell", "dangerous", _ev(text, m.start()), idx)
                break
        for m in _RM_RF.finditer(text):
            if not _rm_target_ok(m.group(1)):
                hit("destructive", "dangerous", _ev(text, m.start()), idx)
                break
        else:
            for rx in _DESTRUCTIVE:
                if m := rx.search(text):
                    hit("destructive", "dangerous", _ev(text, m.start()), idx)
                    break
        if m := _CREDENTIAL.search(text):
            hit("credential_path", "caution", _ev(text, m.start()), idx)
        if ctx in exec_ctx and (m := _EGRESS.search(text)):
            hit("network_egress", "caution", _ev(text, m.start()), idx)
        if ctx in ("hook_cmd", "mcp_cmd") and (m := _METACHAR.search(_strip_quotes(text))):
            hit("shell_metachar", "caution", _ev(text, m.start()), idx)
        if m := _INJECTION.search(text):
            hit("prompt_injection", "caution", _ev(text, m.start()), idx)
        if m := _SECRETS.search(text):
            hit("literal_secret", "dangerous", _mask(m.group(0)), idx)
        elif ctx == "env" and "${" not in text and _LONG_RANDOM.match(text) and (
                re.search(r"\d", text) and re.search(r"[A-Za-z]", text)):
            hit("literal_secret", "dangerous", _mask(text), idx)
        if ctx == "perm":
            findings.extend(_perm_findings(text, idx))

    kind, payload = spec.get("kind"), spec.get("payload") or {}
    settings_blob = json.dumps(payload.get("settings") or {}) + json.dumps(
        [t.get("content") for t in targets if isinstance(t.get("content"), dict)], default=str)
    if m := re.search(r'"defaultMode":\s*"(bypassPermissions|acceptEdits)"', settings_blob):
        hit("broad_allow", "dangerous", _ev(m.group(0)), None)
    remote_mcp = kind == "mcp" and str(payload.get("transport", "")).lower() in (
        "http", "sse", "streamable-http") and payload.get("url")
    if remote_mcp:
        hit("network_egress", "caution", _ev(str(payload["url"])), None)

    src = spec.get("source") or {}
    if src.get("type") in ("catalog", "candidate"):
        lic = src.get("license") or {}
        if not lic or lic.get("status") == "link_only" or lic.get("spdx") in (None, "NOASSERTION"):
            hit("unverified_source", "caution", "license missing or link_only", None)
        elif src.get("type") == "catalog" and not src.get("sha256"):
            hit("unverified_source", "caution", "no sha256 for catalog source", None)

    is_hook = kind == "hook" or any(
        str(t.get("pointer") or "").startswith("/hooks") or str(t.get("path", "")).endswith(
            "hooks.json") for t in targets if t.get("mappable") is not False)
    if is_hook:
        hit("hook_exec", "caution", "runs a command on agent events", None)
        flags.add("executes_code")

    rules = {f["rule"] for f in findings}
    if "credential_path" in rules and "network_egress" in rules:
        for f in findings:
            if f["rule"] == "credential_path":
                f["severity"] = "dangerous"

    tool_names = " ".join(
        str(x) for x in (payload.get("name"), payload.get("command"), *(payload.get("args") or []))
        if x) if kind == "mcp" else ""
    all_text = "\n".join(t for t, _, _ in texts)
    private = "credential_path" in rules or bool(_PRIVATE_TOOL.search(tool_names))
    untrusted = bool(remote_mcp) or bool(_UNTRUSTED_TOOL.search(tool_names)) or bool(
        re.search(r"\b(WebFetch|WebSearch)\b", all_text))
    egress = bool(_EXFIL.search(all_text))
    if private and untrusted and egress:
        hit("lethal_trifecta", "dangerous", "private data + untrusted input + exfiltration", None)

    top = max((SEVERITY[f["severity"]] for f in findings), default=0)
    flags |= {f["rule"] for f in findings}
    return {"level": LEVEL[top], "flags": sorted(flags), "findings": findings}
