"""Versioned projection redaction. Exact bytes remain only in the local L0 archive."""

import hashlib
import json
import re

REDACTION_VERSION = "1.0.1"
HIDDEN_KEYS = {"creator_user_id", "creator_account_id"}


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
    text = re.sub(
        r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[=:]\s*[\"']?)[^\s\"'`,;}{]{8,}",
        r"\1<redacted:secret>",
        text,
        flags=re.I,
    )
    return re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1<redacted:credentials>@", text)


def _json_secrets(value, key=""):
    if secret_key(key):
        return "<redacted:secret>"
    if isinstance(value, dict):
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


def sanitize(value, key=""):
    if secret_key(key):
        return "<redacted:secret>"
    if isinstance(value, dict):
        return {
            name: sanitize(item, name) for name, item in value.items() if name not in HIDDEN_KEYS
        }
    if isinstance(value, list):
        return [sanitize(item, key) for item in value]
    if isinstance(value, str):
        digest = hashlib.sha256(value.encode()).hexdigest()
        if (
            key in ("encrypted_content", "signature", "thinkingSignature")
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
