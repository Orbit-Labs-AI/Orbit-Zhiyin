"""Versioned projection redaction. Exact bytes remain only in the local L0 archive."""

import hashlib
import json
import re
from functools import lru_cache

REDACTION_VERSION = "1.4.1"
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
        marker = f"\x00orbit_header_{index}\x00"
        while marker in text or marker in protected:
            index += 1
            marker = f"\x00orbit_header_{index}\x00"
        protected[marker] = match["q"] + match["prefix"] + "<redacted:header>" + match["q"]
        return marker

    # Protect complete quoted header arguments so curl's surrounding command stays parseable.
    text = _QUOTED_HEADER.sub(quoted, text)
    text = _RAW_HEADER.sub(lambda match: match[1] + "<redacted:header>", text)
    for marker, header in protected.items():
        text = text.replace(marker, header)
    return text


# Vendor-documented token prefixes (lengths are the published minimums, so a bare prefix
# in prose such as "hf_hub_download" or "npm_config" does not match):
# OpenAI/Anthropic sk-; GitHub ghp_/gho_/ghu_/ghs_/ghr_/github_pat_; AWS AKIA (long-term)
# and ASIA (STS temporary) access key ids, 20 chars; Slack xoxb-/xoxp-/xoxa-/xoxr-/xoxs-;
# Google API keys AIza + 35; Hugging Face hf_ + 34; npm npm_ + 36; Stripe sk_/rk_ live/test;
# GitLab glpat- + 20.
_API_KEYS = re.compile(
    r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|hf_[A-Za-z0-9]{30,}"
    r"|npm_[A-Za-z0-9]{36}"
    r"|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|glpat-[A-Za-z0-9_-]{20,})(?![A-Za-z0-9_-])"
)
# JWS compact form (RFC 7515): base64url header "eyJ..." . payload "eyJ..." . signature.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
# Command-line credentials: curl/wget/httpie ``-u user:pass``; MySQL-family ``-pPASS``
# (attached form only: ``-p`` alone prompts, and ``-p 22``/``mkdir -p`` are not secrets);
# ``--password/--token/--api-key/...`` followed by a separate value.
_CLI_USER = re.compile(r"(?<!\S)(-u|--user)(\s+|=)(['\"]?)([^\s:'\"]+):[^\s'\"]+\3")
_CLI_MYSQL = re.compile(
    r"(\b(?:mysql|mysqldump|mysqladmin|mariadb|mariadb-dump)\b[^\n|;&]*?\s-p)(?!\s)([^\s'\"]+|'[^']*'|\"[^\"]*\")"
)
_CLI_FLAG = re.compile(
    r"(?<!\S)(--(?:password|passwd|pass|token|api-key|apikey|api-token|access-token|auth-token|secret|client-secret))"
    r"(\s+)(?!-)([^\s'\"]+|'[^']*'|\"[^\"]*\")"
)


# PEM and OpenPGP armored private keys. A block cut before its END line (``head key.pem``,
# a tool output the harness truncated) still loses its header fields and base64 body: every
# following line (real or JSON-escaped newline) that is ``Name: value`` or base64.
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
    r"(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
    r"|(?:(?:\r?\n|(?:\\r)?\\n)[ \t]*(?:[A-Za-z][A-Za-z-]*:[^\r\n\\]*|[A-Za-z0-9+/=]+)?)+)"
)


def _redact_cli(text: str) -> str:
    if "-" not in text:
        return text
    text = _CLI_USER.sub(lambda m: f"{m[1]}{m[2]}{m[3]}{m[4]}:<redacted:secret>{m[3]}", text)
    text = _CLI_MYSQL.sub(lambda m: m[1] + "<redacted:secret>", text)

    def flag(match):
        value = match[3]
        if value.startswith("<redacted:"):
            return match[0]
        quote = value[0] if value[0] in "'\"" else ""
        return f"{match[1]}{match[2]}{quote}<redacted:secret>{quote}"

    return _CLI_FLAG.sub(flag, text)


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
    text = _PRIVATE_KEY.sub("<redacted:private_key>", text)
    text = _API_KEYS.sub("<redacted:api_key>", text)
    text = _JWT.sub("<redacted:token>", text)
    text = _redact_cli(text)
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
    # Userinfo runs to the last "@" of the authority: raw "@" in passwords is common.
    return re.sub(
        r"\b([a-z][a-z0-9+.-]*://)[^\s/?#`<>]+@",
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
