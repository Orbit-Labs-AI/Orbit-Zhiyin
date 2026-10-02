"""Self-checks for generated artifacts: lint (AI-07.1) and static safety scan (AI-07.2)."""

from __future__ import annotations

import json
import re

from .templates import load
from .util import content, sha256_text

MAX_RULE_LINES = 200
DUPLICATE_JACCARD = 0.8
CONFLICT_JACCARD = 0.5
_NEGATION = re.compile(r"不要|禁止|never|don't|do not", re.I)
_READABILITY_WARN = {"inflated_language", "unverified_certainty"}

_METACHAR = re.compile(r"[;&|`<>]|\$\(")
_URL_HOST = re.compile(r"https?://|\b(?:[\w-]+\.)+(?:com|net|org|io|dev|ai|cn|co|app|sh|xyz|local|internal|lan)\b"
                       r"|\b\d{1,3}(?:\.\d{1,3}){3}\b", re.I)
_CREDENTIAL = re.compile(r"~/\.ssh|id_rsa|(?<![\w])\.env\b|auth\.json|\.aws/credentials|\.netrc", re.I)
_DESTRUCTIVE = re.compile(r"\brm\s+-[a-z]*(?:rf|fr)|--force\b|\bpush\s+-f\b|\b(?:curl|wget)\b[^\n]*\|\s*(?:ba|z)?sh\b"
                          r"|\bsudo\b|\bchmod\s+777\b|\bmkfs|\bdd\s+if=", re.I)
_PRIVILEGE = re.compile(r"bypassPermissions|--dangerously|Bash\(\*\)")
_SCRIPT_FIELDS = {"hook": ("message", "command_heads", "file_glob", "command")}


# ---------------------------------------------------------------- lint

def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower())


def _grams(text: str) -> set[str]:
    text = _norm(text)
    return {text[i:i + 3] for i in range(max(len(text) - 2, 1))} if text else set()


def jaccard(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def _sentences(text: str) -> list[str]:
    return [s.strip(" -*•\t") for s in re.split(r"[\n。！？!?；;]+", text or "") if len(_norm(s)) >= 3]


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    fields = {}
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not re.fullmatch(r"[\w-]+", key.strip()):
            return None
        value = value.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                return None
        fields[key.strip()] = value
    return fields


def _text_slots(kind: str, slots: dict) -> list[tuple[str, str]]:
    if kind in ("rule", "glue"):
        return [("title", slots.get("title", ""))] + [(f"rules[{i}]", r.get("text", ""))
                                                      for i, r in enumerate(slots.get("rules") or [])]
    if kind == "hook":
        return [("message", slots.get("message", ""))]
    if kind == "skill":
        return [("description", slots.get("description", "")), ("verify", slots.get("verify", ""))] + \
               [(f"steps[{i}]", s) for i, s in enumerate(slots.get("steps") or [])]
    if kind == "subagent":
        return [("description", slots.get("description", ""))] + list((slots.get("body") or {}).items())
    return [("description", slots.get("description", "")), ("body", slots.get("body", ""))]


def lint(kind: str, rendered: dict, pack: dict, slots: dict | None = None) -> dict:
    issues: list[dict] = []

    def issue(code, severity, message, ref=None):
        issues.append({"code": code, "severity": severity, "message": message, "ref": ref})

    data = content(pack)
    payload = rendered.get("payload") or {}
    if slots is None and kind in ("rule", "glue"):
        slots = {"title": payload.get("title", ""),
                 "rules": [{"text": line[2:]} for line in payload.get("markdown", "").split("\n")
                           if line.startswith("- ")]}
    slots = slots if slots is not None else payload.get("config") or {}
    name = rendered.get("name") or ""
    if kind in ("skill", "subagent", "command"):
        doc = rendered["files"][0]["content"]
        meta = parse_frontmatter(doc)
        if meta is None:
            issue("frontmatter_invalid", "error", "frontmatter 无法解析。", rendered["files"][0]["target"])
        else:
            if len(meta.get("name", name)) > 64:
                issue("name_too_long", "error", "名称超过 64 字符。", "name")
            limit = {"skill": 1024, "subagent": 200, "command": 100}[kind]
            if not meta.get("description") or len(meta["description"]) > limit:
                issue("description_length", "error", f"描述为空或超过 {limit} 字符。", "description")
    if kind != "rule" and kind != "glue":
        taken = {str(i.get("name", "")).lower() for i in data.get("inventory") or []}
        if name.lower() in taken:
            issue("name_conflict", "error", f"名称「{name}」与已安装组件重复。", "name")
    if kind in ("rule", "glue"):
        if len(payload.get("markdown", "").split("\n")) >= MAX_RULE_LINES:
            issue("rule_too_long", "error", f"规则块不少于 {MAX_RULE_LINES} 行。", "markdown")
        existing = [(r.get("path_label") or "", s) for r in data.get("existing_rules") or []
                    for s in _sentences(r.get("text", ""))]
        for i, rule in enumerate(slots.get("rules") or []):
            text = rule.get("text", "")
            for label, other in existing:
                score = jaccard(text, other)
                if score >= DUPLICATE_JACCARD:
                    issue("duplicate", "error", f"与已有规则重复：{other[:40]}", f"rules[{i}]@{label}")
                    break
                if score >= CONFLICT_JACCARD and bool(_NEGATION.search(text)) != bool(_NEGATION.search(other)):
                    issue("conflict", "error", f"可能与已有规则冲突：{other[:40]}", f"rules[{i}]@{label}")
                    break
    for file in rendered.get("files") or []:
        if file["action"] == "merge_json":
            try:
                json.loads(file["content"])
            except ValueError:
                issue("settings_json_invalid", "error", "settings 片段不是合法 JSON。", file["target"])
    try:
        from tandem_backend.evaluation.readability import evaluate_text
    except ImportError:  # pragma: no cover
        evaluate_text = None
    if evaluate_text is not None:
        for field, text in _text_slots(kind, slots):
            if not text:
                continue
            for found in evaluate_text(text, "status_update")["issues"]:
                if found["code"] in _READABILITY_WARN:
                    issue(found["code"], "warn", found["message"], field)
    status = "fail" if any(i["severity"] == "error" for i in issues) else "warn" if issues else "ok"
    return {"status": status, "issues": issues}


def lint_errors(result: dict) -> list[str]:
    return [f"{i['code']}: {i['message']}" for i in result["issues"] if i["severity"] == "error"]


# ---------------------------------------------------------------- scan

def _leaves(value, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _leaves(item, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


def _excerpt(text: str, match: re.Match) -> str:
    start = max(match.start() - 12, 0)
    return text[start:match.end() + 12]


def scan(kind: str, slots: dict, rendered: dict, template_id: str | None = None) -> dict:
    hits = []
    template_id = template_id or (rendered.get("payload") or {}).get("template_id")
    shell_fields = _SCRIPT_FIELDS.get(kind)
    for field, text in _leaves(slots):
        top = re.split(r"[.\[]", field)[0]
        checks = [("url_or_host", _URL_HOST), ("credential_path", _CREDENTIAL), ("privilege", _PRIVILEGE)]
        # scope-guard's command_heads are a deny-list: destructive prefixes are the point there.
        if not (template_id == "scope-guard" and top == "command_heads"):
            checks.append(("destructive_command", _DESTRUCTIVE))
        if kind in ("skill", "subagent", "command") or (shell_fields and top in shell_fields):
            checks.append(("shell_metachar", _METACHAR))
        for rule, pattern in checks:
            match = pattern.search(text)
            if match:
                hits.append({"rule": rule, "field": field, "excerpt": _excerpt(text, match)})
    script = (rendered.get("payload") or {}).get("script")
    if kind == "hook" and script:
        expected = load().get(template_id)
        if expected is None or script.get("sha256") != expected.sha256 or \
                sha256_text(script.get("content", "")) != expected.sha256:
            hits.append({"rule": "script_hash", "field": "payload.script", "excerpt": script.get("name", "")})
    return {"status": "blocked" if hits else "ok", "hits": hits}
