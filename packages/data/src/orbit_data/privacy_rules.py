"""DT-10 MVP read-only rule list and preview. The engine stays ``privacy.redact``.

The list documents what ``privacy.redact`` / ``privacy.sanitize`` (REDACTION_VERSION) do,
in the order they apply. Rules are fixed in the MVP: none can be disabled or edited.
``preview`` calls ``redact`` itself, so a preview equals what import writes for text.
"""

from __future__ import annotations

import re

from orbit_data.privacy import HIDDEN_KEYS, REDACTION_VERSION, redact

MAX_PREVIEW_CHARS = 100_000
_MARKER = re.compile(r"<(redacted|opaque):([a-z_]+)")

RULES: tuple[dict, ...] = (
    {
        "id": "json_secret_keys",
        "category": "credential",
        "scope": "json",
        "marker": "<redacted:secret>",
        "description": "JSON 文本或结构化字段中键名像凭据（api_key、token、password、secret、cookie 等）时，整个值替换。",
        "example": '{"api_key": "synthetic-value-123"}',
    },
    {
        "id": "hidden_identity_keys",
        "category": "identity",
        "scope": "json",
        "marker": None,
        "description": "删除账号与会话身份字段：" + "、".join(sorted(HIDDEN_KEYS)) + "。",
        "example": '{"user_id": "u-123", "text": "hello"}',
    },
    {
        "id": "auth_headers",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:header>",
        "description": "Authorization、Proxy-Authorization、Cookie、Set-Cookie 头的值（含续行与引号内参数）。",
        "example": "Authorization: Basic dW5pdDpzZWNyZXQ=",
    },
    {
        "id": "private_key_block",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:private_key>",
        "description": "PEM 私钥块（-----BEGIN … PRIVATE KEY----- 到 END）。",
        "example": "-----BEGIN PRIVATE KEY-----\nMIIfixture\n-----END PRIVATE KEY-----",
    },
    {
        "id": "api_key_tokens",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:api_key>",
        "description": "已知格式的密钥：sk-/sk-proj-/sk-ant-、GitHub ghp_/gho_/ghu_/ghs_/ghr_、github_pat_、AWS AKIA/ASIA、Slack xox?-、Google AIza、Hugging Face hf_、npm_、Stripe sk_/rk_live|test_、GitLab glpat-。",
        "example": "key sk-proj-ABCDEFGHIJKLMNOP1234",
    },
    {
        "id": "jwt",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:token>",
        "description": "JWT（eyJ… . eyJ… . 签名 三段 base64url）。",
        "example": "id_token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmaXh0dXJlIn0.c2lnbmF0dXJlLXZhbHVl",
    },
    {
        "id": "cli_credentials",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:secret>",
        "description": "命令行凭据参数：curl -u user:pass（保留用户名）、mysql/mariadb -pPASS（紧贴形式）、--password/--token/--api-key/--secret 等后的值。",
        "example": "curl -u fixture-user:fixture-pass https://example.invalid",
    },
    {
        "id": "bearer_token",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:token>",
        "description": "Bearer 后 12 位以上的令牌。",
        "example": "use Bearer abcdefghijklmnop.qrstu",
    },
    {
        "id": "secret_assignment",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:secret>",
        "description": "键名像凭据的赋值（KEY=value、key: value、带引号的值），只替换值。",
        "example": 'DATABASE_PASSWORD="synthetic pass phrase"',
    },
    {
        "id": "url_credentials",
        "category": "credential",
        "scope": "text",
        "marker": "<redacted:credentials>",
        "description": "URL 中 user:password@ 形式的凭据，保留主机与路径。",
        "example": "postgresql://fixture-user:fixture-password@example.invalid/db",
    },
    {
        "id": "opaque_payloads",
        "category": "binary",
        "scope": "structured",
        "marker": "<opaque:sha256:…>",
        "description": "结构化字段中的 base64 / 图片数据、加密内容与签名字段、data: URI 只保留 sha256 摘要（导入时 sanitize 生效，纯文本预览不适用）。",
        "example": None,
    },
)


def rules() -> dict:
    return {
        "version": REDACTION_VERSION,
        "count": len(RULES),
        "editable": False,
        "rules": [{**rule, "enabled": True, "can_disable": False} for rule in RULES],
    }


def preview(text: str) -> dict:
    """Redact sample text without storing it. Counts are per marker kind."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if len(text) > MAX_PREVIEW_CHARS:
        raise ValueError(f"text must be at most {MAX_PREVIEW_CHARS} characters")
    redacted = redact(text)
    before = _count(text)
    after = _count(redacted)
    matches = {kind: after[kind] - before.get(kind, 0) for kind in after}
    return {
        "version": REDACTION_VERSION,
        "redacted": redacted,
        "changed": redacted != text,
        "matches": {kind: count for kind, count in sorted(matches.items()) if count > 0},
    }


def _count(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in _MARKER.finditer(text):
        kind = match[2]
        counts[kind] = counts.get(kind, 0) + 1
    return counts
