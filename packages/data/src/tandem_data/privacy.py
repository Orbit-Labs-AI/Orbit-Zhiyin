"""Versioned projection redaction. Exact bytes remain only in the local L0 archive."""

import hashlib
import json
import re
from functools import lru_cache

REDACTION_VERSION = "1.2.0"
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


@lru_cache(maxsize=4096)
def secret_key(key: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return bool(
        re.search(
            r"(?:^|_)(?:api_?key|private_?key|signing_?key|token|authorization|credentials?|cookies?|set_cookie)$",
            normalized,
        )
        or re.search(r"(?:^|_)(?:secret|password|passwd)(?:_|$)", normalized)
    )


_AUTH_HEADERS = r"(?:Proxy-Authorization|Authorization|Set-Cookie|Cookie)"
_QUOTED_HEADER = re.compile(
    r"(?P<q>[\"'])(?P<prefix>"
    + _AUTH_HEADERS
    + r"[ \t]*:[ \t]*)(?:\\.|(?!(?P=q))[^\r\n\\])*(?P=q)",
    re.I,
)
_RAW_HEADER = re.compile(
    r"(\b" + _AUTH_HEADERS + r"[ \t]*:[ \t]*)[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*", re.I
)


def _redact_headers(text: str) -> str:
    protected = {}

    def quoted(match):
        index = len(protected)
        marker = f"\x00tandem_header_{index}\x00"
        while marker in text or marker in protected:
            index += 1
            marker = f"\x00tandem_header_{index}\x00"
        protected[marker] = match["q"] + match["prefix"] + "<redacted:header>" + match["q"]
        return marker

    # Protect complete quoted header arguments so curl's surrounding command stays parseable.
    text = _QUOTED_HEADER.sub(quoted, text)
    text = _RAW_HEADER.sub(lambda match: match[1] + "<redacted:header>", text)
    for marker, header in protected.items():
        text = text.replace(marker, header)
    return text


def redact(text: str) -> str:
    if text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            clean = _json_secrets(parsed)
            if clean != parsed:
                return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        except (ValueError, TypeError):
            pass
    text = _redact_headers(text)
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
        if not is_secret_key(match["key"]) or match["value"].startswith("<redacted:"):
            return match[0]
        value = match["value"]
        quote = value[0] if value[0] in (chr(34), chr(39)) else ""
        return match["prefix"] + quote + "<redacted:secret>" + quote

    # JSON/YAML keys and shell assignments, including quoted values with spaces.
    assignment_pattern = r"(?P<prefix>\b(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)[\"']?\s*[=:]\s*)(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s\"'`,;}{]+)"
    text = re.sub(assignment_pattern, assignment, text)
    return re.sub(
        r"\b([a-z][a-z0-9+.-]*://)[^\s/@:]+(?::[^\s/@]*)?@",
        r"\1<redacted:credentials>@",
        text,
        flags=re.I,
    )


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
            # Hash only values that are replaced; most strings are only redacted.
            return f"<opaque:sha256:{hashlib.sha256(value.encode()).hexdigest()}>"
        clean = redact(value)
        return clean
    return value
