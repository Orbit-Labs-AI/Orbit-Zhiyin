"""Versioned projection redaction. Exact bytes remain only in the local L0 archive."""

import hashlib
import json
import re

REDACTION_VERSION = "1.1.0"
HIDDEN_KEYS = {
    "creator_user_id",
    "creator_account_id",
    "user_id",
    "session_key",
    "chat_id",
    "display_name",
    "origin_json",
}


def is_secret_key(key: str) -> bool:
    return secret_key(key)


def secret_key(key: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return bool(
        re.search(
            r"(?:^|_)(?:api_?key|private_?key|signing_?key|token|authorization|credentials?)$",
            normalized,
        )
        or re.search(r"(?:^|_)(?:secret|password|passwd)(?:_|$)", normalized)
    )


def redact(text: str) -> str:
    if text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            clean = _json_secrets(parsed)
            if clean != parsed:
                return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        except (ValueError, TypeError):
            pass
    text = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "<redacted:private_key>",
        text,
    )
    text = re.sub(
        r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b",
        "<redacted:api_key>",
        text,
    )
    text = re.sub(
        r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}", "Bearer <redacted:token>", text, flags=re.I
    )

    def assignment(match):
        if not is_secret_key(match["key"]):
            return match[0]
        value = match["value"]
        quote = value[0] if value[0] in (chr(34), chr(39)) else ""
        return match["prefix"] + quote + "<redacted:secret>" + quote

    # JSON/YAML keys and shell assignments, including quoted values with spaces.
    assignment_pattern = r"(?P<prefix>\b(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)[\"']?\s*[=:]\s*)(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s\"'`,;}{]+)"
    text = re.sub(assignment_pattern, assignment, text)
    return re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1<redacted:credentials>@", text)


def _json_secrets(value, key=""):
    if secret_key(key):
        return "<redacted:secret>"
    if isinstance(value, dict):
        value = _opaque_fields(value)
        return {
            name: _json_secrets(item, name)
            for name, item in value.items()
            if name not in HIDDEN_KEYS
        }
    if isinstance(value, list):
        return [_json_secrets(item, key) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def _opaque_fields(value):
    if isinstance(value.get("$binary"), str):
        value = {
            **value,
            "$binary": "<opaque:sha256:"
            + hashlib.sha256(value["$binary"].encode()).hexdigest()
            + ">",
        }
    if value.get("type") == "base64" and isinstance(value.get("data"), str):
        value = {
            **value,
            "data": "<opaque:sha256:" + hashlib.sha256(value["data"].encode()).hexdigest() + ">",
        }
    elif value.get("type") == "image" and isinstance(value.get("data"), str):
        value = {
            **value,
            "data": "<opaque:sha256:" + hashlib.sha256(value["data"].encode()).hexdigest() + ">",
        }
    return value


def sanitize(value, key=""):
    if is_secret_key(key):
        return "<redacted:secret>"
    if isinstance(value, dict):
        value = _opaque_fields(value)
        return {
            name: sanitize(item, name) for name, item in value.items() if name not in HIDDEN_KEYS
        }
    if isinstance(value, list):
        return [sanitize(item, key) for item in value]
    if isinstance(value, str):
        digest = hashlib.sha256(value.encode()).hexdigest()
        if (
            key
            in (
                "encrypted_content",
                "encrypted",
                "signature",
                "thinkingSignature",
                "thoughtSignature",
                "textSignature",
            )
            or value.startswith("data:")
            and ";base64," in value[:128]
        ):
            return f"<opaque:sha256:{digest}>"
        clean = redact(value)
        limit = (
            8192 if key in ("output", "stdout", "stderr", "aggregated_output", "result") else 32768
        )
        if len(clean.encode()) > limit:
            return clean.encode()[:limit].decode(errors="ignore") + f"<truncated:sha256:{digest}>"
        return clean
    return value
