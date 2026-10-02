import json

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.contract import canonical
from tandem_data.privacy import REDACTION_VERSION, sanitize
from tandem_data.store import Store


def test_secret_variants_and_embedded_json_keep_usage_fields():
    secret = "synthetic-secret-value"
    value = {
        "token": secret,
        "client_secret": secret,
        "AWS_SECRET_ACCESS_KEY": secret,
        "apiKey": secret,
        "githubToken": secret,
        "input_tokens": 100,
        "output_tokens": 10,
        "last_token_usage": {"input_tokens": 10},
        "request_key": ["request"],
        "payload": json.dumps({"OPENAI_API_KEY": secret, "input_tokens": 10}),
    }
    clean = sanitize(value)
    assert secret not in canonical(clean)
    assert clean["input_tokens"] == 100 and clean["output_tokens"] == 10
    assert clean["last_token_usage"]["input_tokens"] == 10
    assert clean["request_key"] == ["request"]
    assert json.loads(clean["payload"])["input_tokens"] == 10


def test_peer_web_extension_and_modified_seed_context_are_not_human(tmp_path):
    parent = [
        {"type": "session_meta", "ordinal": 0, "payload": {"id": "p", "session_id": "p"}},
        {"type": "turn_context", "ordinal": 1, "payload": {"turn_id": "t", "model": "test"}},
    ]
    child = [
        {
            "type": "session_meta",
            "ordinal": 0,
            "payload": {
                "id": "c",
                "session_id": "p",
                "parent_thread_id": "p",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "p"}}},
                "subagent_history_start_ordinal": 2,
            },
        },
        {
            "type": "world_state",
            "ordinal": 1,
            "payload": {"full": True, "state": {"model": "test", "child_instructions": True}},
        },
        {
            "type": "response_item",
            "ordinal": 2,
            "payload": {
                "type": "agent_message",
                "id": "peer",
                "author": "p",
                "recipient": "c",
                "content": [{"type": "text", "text": "peer message"}],
            },
        },
        {
            "type": "event_msg",
            "ordinal": 3,
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "Extension",
                    "kind": "web.search",
                    "id": "search",
                    "query": "synthetic query",
                    "action": {"type": "search", "queries": ["synthetic query"]},
                    "results": [],
                },
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("codex", tmp_path / "source")
        for name, rows in (("parent.jsonl", parent), ("child.jsonl", child)):
            store.capture_stream(source, name, [(canonical(row) + "\n").encode() for row in rows])
        store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM v_human_message").fetchone()[0] == 0
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM event WHERE kind='message.user' AND json_extract(attrs,'$.origin')='peer'"
            ).fetchone()[0]
            == 1
        )
        assert (
            store.db.execute("SELECT COUNT(*) FROM tool_call WHERE kind='web.search'").fetchone()[0]
            == 1
        )
        assert store.db.execute("SELECT argument_digest FROM tool_call").fetchone()[0] is not None
        assert store.verify()["unparsed"] == 0
        data = read_analysis(store.home, AnalysisScope("Asia/Shanghai"))
        assert data["redaction_version"] == REDACTION_VERSION


def test_persisted_credentials_exist_only_in_explicit_raw_read(tmp_path):
    secret = "synthetic-secret-value"
    rows = [
        {"type": "session", "id": "s"},
        {
            "type": "message",
            "id": "u",
            "message": {"role": "user", "content": json.dumps({"clientSecret": secret})},
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", tmp_path / "source")
        store.capture_stream(
            source, "session.jsonl", [(canonical(row) + "\n").encode() for row in rows]
        )
        store.rebuild()
        event = store.db.execute("SELECT * FROM event WHERE kind='message.user'").fetchone()
        assert secret not in event["text"] + event["attrs"] + event["ext"]
        assert secret.encode() in store.read_raw(event["record_uid"])
