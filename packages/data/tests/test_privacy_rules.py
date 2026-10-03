import pytest

from tandem_data.contract import canonical
from tandem_data.privacy import REDACTION_VERSION, redact
from tandem_data.privacy_rules import MAX_PREVIEW_CHARS, RULES, preview, rules

# Samples mirrored from test_security_and_native.py / test_native_connectors.py.
REPOSITORY_SAMPLES = [
    "Authorization: Basic dW5pdDpzZWNyZXQ=\r\nAccept: text/plain",
    "Cookie: session=unit-cookie-value; tracking=another-value\r\nAccept: text/plain",
    "curl -H 'Authorization: Basic dW5pdDpzZWNyZXQ=' -H 'Authorization: Negotiate private-scheme-value' https://example.invalid",
    "curl -H 'Set-Cookie: session=unit-cookie-value; tracking=another-value' https://example.invalid",
    "Authorization: Basic dW5pdDpzZWNyZXQ=\r\nCookie: session=fixture-cookie-secret\r\nAccept: application/json",
    "postgresql://fixture-user:fixture-password@example.invalid/db",
    "rediss://fixture-user:fixture-password@example.invalid/db",
    "HTTPS://fixture-user:fixture-password@example.invalid/db",
    *(
        canonical({key: "arbitrary credential with spaces"})
        for key in (
            "DATABASE_PASSWORD",
            "AWS_SECRET_ACCESS_KEY",
            "client_secret",
            "clientSecret",
            "service.api-key",
            "GITHUB_TOKEN",
            "refreshToken",
        )
    ),
    'GITHUB_TOKEN="arbitrary credential with spaces"',
    canonical({"OPENAI_API_KEY": "synthetic-secret-value", "input_tokens": 10}),
    "plain text without secrets 修复第 7 个问题",
]


def test_rule_list_matches_declared_rules():
    listing = rules()
    assert listing["version"] == REDACTION_VERSION
    assert listing["count"] == len(listing["rules"]) == len(RULES) == 9
    ids = [rule["id"] for rule in listing["rules"]]
    assert len(set(ids)) == len(ids)
    assert not listing["editable"]
    for rule in listing["rules"]:
        assert rule["description"] and rule["category"] and rule["enabled"]


@pytest.mark.parametrize("rule", [r for r in RULES if r["example"]], ids=lambda r: r["id"])
def test_every_text_rule_example_is_redacted_by_engine(rule):
    result = preview(rule["example"])
    assert result["redacted"] == redact(rule["example"])
    assert result["changed"]
    if rule["marker"]:
        assert rule["marker"] in result["redacted"]


@pytest.mark.parametrize("sample", REPOSITORY_SAMPLES)
def test_preview_equals_redact_on_repository_samples(sample):
    result = preview(sample)
    assert result["redacted"] == redact(sample)
    assert result["changed"] == (redact(sample) != sample)


def test_match_counts_ignore_markers_already_present():
    result = preview("<redacted:secret> and Bearer abcdefghijklmnopq and Bearer zyxwvutsrqponmlk")
    assert result["matches"] == {"token": 2}
    assert preview("nothing to hide")["matches"] == {}


def test_preview_limits():
    with pytest.raises(ValueError):
        preview("x" * (MAX_PREVIEW_CHARS + 1))
    with pytest.raises(TypeError):
        preview(None)


# Synthetic tokens are assembled at runtime so no literal resembles a live credential.
_ALNUM = "A1b2C3d4E5f6G7h8J9k0"
VENDOR_TOKENS = {
    "google": ("AI" + "za" + (_ALNUM * 2)[:35], "<redacted:api_key>"),
    "slack_bot": ("xo" + "xb-" + "1234567890-0987654321-" + _ALNUM, "<redacted:api_key>"),
    "slack_user": ("xo" + "xp-" + "1234567890-" + _ALNUM, "<redacted:api_key>"),
    "stripe_secret": ("sk" + "_live_" + _ALNUM + "XyZ", "<redacted:api_key>"),
    "stripe_restricted": ("rk" + "_live_" + _ALNUM, "<redacted:api_key>"),
    "stripe_test": ("sk" + "_test_" + _ALNUM, "<redacted:api_key>"),
    "huggingface": ("hf" + "_" + (_ALNUM * 2)[:34], "<redacted:api_key>"),
    "npm": ("np" + "m_" + (_ALNUM * 2)[:36], "<redacted:api_key>"),
    "gitlab": ("gl" + "pat-" + _ALNUM, "<redacted:api_key>"),
    "jwt": (
        "ey" + "JhbGciOiJIUzI1NiJ9" + ".ey" + "JzdWIiOiJmaXh0dXJlIn0" + "." + _ALNUM,
        "<redacted:token>",
    ),
}


@pytest.mark.parametrize("name", sorted(VENDOR_TOKENS))
def test_vendor_tokens_in_plain_text_are_redacted(name):
    token, marker = VENDOR_TOKENS[name]
    text = f"deploy failed, retry with {token} then report"
    assert redact(text) == f"deploy failed, retry with {marker} then report"


@pytest.mark.parametrize(
    "text",
    [
        "call hf_hub_download and npm_config_cache before AIzawa visits",
        "the sk_live_ prefix and rk_test_ prefix are Stripe conventions",
        "set xoxb- tokens in Slack; glpat- is the GitLab prefix",
        "a header eyJhbGciOiJIUzI1NiJ9 alone is not a JWT",
        "version 1.2.3.4 and file a.b.c are not tokens",
    ],
)
def test_vendor_prefixes_in_prose_are_not_redacted(text):
    assert redact(text) == text
