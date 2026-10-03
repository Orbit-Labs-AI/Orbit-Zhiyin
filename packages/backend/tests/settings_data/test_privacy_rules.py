"""SET-10: redaction rule table, toggles, custom patterns and the preview."""

from __future__ import annotations

from tandem_data.privacy import REDACTION_VERSION

from tandem_backend import privacy_rules
from tandem_backend.ai.redact import redact2

KEY = "sk-ant-" + "a" * 24
SAMPLE = (f"token {KEY} mail alice@example.com path /Users/alice/x host 10.0.0.8 "
          "call 13800138000 by alice")


def hits_by_rule(body: dict) -> dict:
    out: dict[str, int] = {}
    for hit in body["hits"]:
        out[hit["rule"]] = out.get(hit["rule"], 0) + 1
    return out


def test_rule_table(client):
    body = client.get("/v1/privacy/rules").json()
    ids = [r["id"] for r in body["rules"]]
    assert ids == ["credentials", "home_user", "email", "private_host", "local_user", "phone",
                   "custom"]
    credentials = body["rules"][0]
    assert credentials["locked"] and credentials["stage"] == "ingest"
    assert {r["stage"] for r in body["rules"][1:]} == {"outbound"}
    # The rule table is versioned with the ingest redaction it describes (data layer constant).
    assert body["version"] == REDACTION_VERSION and body["active_count"] == 6 and body["custom"] == []
    assert "scope_note" in body
    assert client.get("/v1/status").json()["privacy"] == {"active_rules": 6}


def test_preview_hits_and_spans(client):
    body = client.post("/v1/privacy/preview", json={"text": SAMPLE}).json()
    assert hits_by_rule(body) == {"credentials": 1, "email": 1, "home_user": 1,
                                  "private_host": 1, "phone": 1, "local_user": 1}
    assert body["n"] == 6
    for raw in (KEY, "alice@example.com", "/Users/alice", "10.0.0.8", "13800138000", "alice"):
        assert raw not in body["text"]
    for hit in body["hits"]:  # Spans index the returned text.
        assert body["text"][hit["start"]:hit["end"]] == hit["replacement"]


def test_toggles_change_hits_and_redact2(client):
    off = {"email": False, "phone": False, "local_user": False}
    preview = client.post("/v1/privacy/preview", json={"text": SAMPLE, "enabled": off}).json()
    assert "alice@example.com" in preview["text"] and "13800138000" in preview["text"]
    assert hits_by_rule(preview).keys() == {"credentials", "home_user", "private_host"}
    # Preview never stores anything.
    assert client.get("/v1/privacy/rules").json()["active_count"] == 6
    saved = client.put("/v1/privacy/rules", json={"enabled": off}).json()
    assert saved["active_count"] == 3
    text, n = redact2(SAMPLE)
    # redact2 counts hidden values; folding the home directory to "~" is not one.
    assert "alice@example.com" in text and "13800138000" in text and KEY not in text and n == 2
    client.put("/v1/privacy/rules", json={"enabled": {k: True for k in off}})
    assert redact2(SAMPLE)[1] == 5


def test_locked_rule_cannot_be_disabled(client):
    response = client.put("/v1/privacy/rules", json={"enabled": {"credentials": False}})
    assert response.status_code == 422 and response.json()["error"]["code"] == "locked_rule"
    unknown = client.put("/v1/privacy/rules", json={"enabled": {"nope": True}})
    assert unknown.status_code == 422


def test_custom_rules(client):
    custom = [{"pattern": r"ACME-\d{4}", "replacement": "[ticket]"}]
    body = client.put("/v1/privacy/rules", json={"custom": custom}).json()
    assert body["custom"] == [{"id": "custom-1", "pattern": r"ACME-\d{4}",
                               "replacement": "[ticket]", "enabled": True}]
    assert body["active_count"] == 7
    assert redact2("see ACME-1234 now")[0] == "see [ticket] now"
    # The custom switch turns every custom pattern off.
    client.put("/v1/privacy/rules", json={"enabled": {"custom": False}})
    assert redact2("see ACME-1234 now")[0] == "see ACME-1234 now"


def test_bad_custom_rules_rejected(client):
    for custom in ([{"pattern": "("}], [{"pattern": "a" * 201}], [{"pattern": "x*"}],
                   [{"pattern": "(a+)+$"}], [{"pattern": f"t{i}"} for i in range(6)]):
        response = client.put("/v1/privacy/rules", json={"custom": custom})
        assert response.status_code == 422, custom
        assert response.json()["error"]["code"] == "bad_regex"
    assert client.get("/v1/privacy/rules").json()["custom"] == []


def test_preview_does_not_write_platform_kv(client, gateway):
    client.post("/v1/privacy/preview", json={"text": SAMPLE, "enabled": {"email": False},
                                             "custom": [{"pattern": "alice"}]})
    with gateway.appdb.read() as db:
        assert db.execute("SELECT COUNT(*) FROM platform_kv WHERE key = ?",
                          (privacy_rules.KV_KEY,)).fetchone()[0] == 0
    assert client.post("/v1/privacy/preview", json={"text": "x" * 20_001}).status_code == 422


def test_unbound_defaults(user_home):
    privacy_rules.bind(None)
    text, n = redact2(SAMPLE)
    assert n == 5 and "[phone]" in text
