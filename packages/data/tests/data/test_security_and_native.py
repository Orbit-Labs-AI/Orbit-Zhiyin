import json

import pytest

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


@pytest.mark.parametrize("end_time", [5000, None])
def test_bounded_session_and_turn_lifecycle_hide_unplaced_end(tmp_path, end_time):
    rows = [
        {"type": "session", "id": "s", "version": 4},
        {"type": "turn/start", "seq": 0, "time": 1000, "data": {"turn": 1}},
        {
            "type": "user/message",
            "seq": 1,
            "time": 1100,
            "data": {
                "role": "user",
                "content": [{"type": "text", "text": "task"}],
                "source": {"kind": "user"},
            },
        },
        {
            "type": "turn/end",
            "seq": 2,
            "time": end_time,
            "data": {"turn": 1, "reason": {"kind": "completed"}},
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        store.capture_stream(
            source, "session.jsonl", [(canonical(row) + "\n").encode() for row in rows]
        )
        store.rebuild()
        assert store.db.execute("SELECT status FROM session").fetchone()[0] == "completed"
        data = read_analysis(store.home, AnalysisScope("Asia/Shanghai", until_ts=2000))
        assert (
            data["sessions"][0]["status"] == "unknown" and data["sessions"][0]["ended_at"] is None
        )
        assert data["turns"][0]["status"] == "unknown" and data["turns"][0]["ended_at"] is None
        assert not any(e["kind"] == "turn.end" for e in data["events"])


def test_new_unfinished_turn_does_not_inherit_previous_completed_status(tmp_path):
    rows = [
        {"type": "session", "id": "s", "version": 4},
        {"type": "turn/start", "seq": 0, "time": 1000, "data": {"turn": 1}},
        {
            "type": "turn/end",
            "seq": 1,
            "time": 1100,
            "data": {"turn": 1, "reason": {"kind": "completed"}},
        },
        {"type": "turn/start", "seq": 2, "time": 1200, "data": {"turn": 2}},
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        store.capture_stream(
            source, "session.jsonl", [(canonical(row) + "\n").encode() for row in rows]
        )
        store.rebuild()
        assert store.db.execute("SELECT status FROM session").fetchone()[0] == "unknown"


def test_approval_has_its_own_cutoff_evidence_without_tool_result(tmp_path):
    rows = [
        {"type": "session", "id": "s", "version": 4, "createdAt": 900, "cwd": "/old"},
        {
            "type": "tool/call",
            "seq": 0,
            "time": 1000,
            "data": {"callId": "c", "name": "bash", "arguments": "{}"},
        },
        {"type": "approval/asked", "seq": 1, "time": 1100, "data": {"id": "a", "callId": "c"}},
        {
            "type": "approval/decided",
            "seq": 2,
            "time": 3000,
            "data": {"id": "a", "outcome": "allowed-once"},
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        store.capture_stream(
            source, "session.jsonl", [(canonical(row) + "\n").encode() for row in rows]
        )
        store.rebuild()
        assert store.db.execute("SELECT approval FROM tool_call").fetchone()[0] == "allowed-once"
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM tool_call_event WHERE role='permission.decision'"
            ).fetchone()[0]
            == 1
        )
        data = read_analysis(store.home, AnalysisScope("Asia/Shanghai", until_ts=2000))
        assert data["tool_calls"][0]["approval"] is None
        assert data["tool_calls"][0]["approval_wait_ms"] is None


def test_metadata_at_cutoff_does_not_use_future_title(tmp_path):
    rows = [
        {"type": "session", "id": "s", "version": 4, "createdAt": 900, "cwd": "/old"},
        {"type": "session/title", "seq": 0, "time": 1000, "data": {"title": "past"}},
        {
            "type": "user/message",
            "seq": 1,
            "time": 1100,
            "data": {
                "role": "user",
                "content": [{"type": "text", "text": "task"}],
                "source": {"kind": "user"},
            },
        },
        {"type": "session/title", "seq": 2, "time": 3000, "data": {"title": "future"}},
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        store.capture_stream(
            source, "session.jsonl", [(canonical(row) + "\n").encode() for row in rows]
        )
        store.rebuild()
        assert store.db.execute("SELECT title FROM session").fetchone()[0] == "future"
        data = read_analysis(store.home, AnalysisScope("Asia/Shanghai", until_ts=2000))
        assert data["sessions"][0]["title"] == "past" and data["sessions"][0]["cwd"] == "/old"


def test_secret_bearing_tool_arguments_have_no_offline_digest():
    from tandem_data.contract import EventDraft, time_fields

    _, time = time_fields(None, "timestamp")
    event = EventDraft(
        "s",
        ["key"],
        "call",
        "tool.call",
        call_id="c",
        attrs={"time": time, "name": "bash", "input": {"password": "guessable-password"}},
    )
    data = event.envelope("r", 0, "test")
    assert data["attrs"]["argument_digest"] is None
    assert data["attrs"]["input"]["password"] == "<redacted:secret>"


@pytest.mark.parametrize("header", ["Authorization", "Proxy-Authorization", "Cookie", "Set-Cookie"])
def test_authentication_header_values_are_atomic_secrets(header):
    import shlex

    from tandem_data.privacy import redact

    value = (
        "Basic dW5pdDpzZWNyZXQ="
        if "Authorization" in header
        else "session=unit-cookie-value; tracking=another-value"
    )
    raw = f"{header}: {value}\r\nAccept: text/plain"
    cleaned = redact(raw)
    assert value not in cleaned
    assert "dW5pdDpzZWNyZXQ=" not in cleaned
    assert "unit-cookie-value" not in cleaned
    assert "another-value" not in cleaned
    assert "Accept: text/plain" in cleaned
    command = f"curl -H '{header}: {value}' -H 'Authorization: Negotiate private-scheme-value' https://example.invalid"
    cleaned = redact(command)
    assert "private-scheme-value" not in cleaned and "unit-cookie-value" not in cleaned
    assert shlex.split(cleaned)[-1] == "https://example.invalid"
    assert sanitize({"headers": {header: value}})["headers"][header] == "<redacted:secret>"


def test_raw_auth_headers_are_absent_from_published_events_but_preserved_in_l0(tmp_path):
    token = "dW5pdDpzZWNyZXQ="
    cookie = "fixture-cookie-secret"
    body = f"Authorization: Basic {token}\r\nCookie: session={cookie}\r\nAccept: application/json"
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", tmp_path / "source")
        records = [
            {"type": "session", "id": "s"},
            {"type": "message", "id": "u", "message": {"role": "user", "content": body}},
        ]
        store.capture_stream(
            source, "session.jsonl", [(canonical(row) + "\n").encode() for row in records]
        )
        store.rebuild()
        event = dict(store.db.execute("SELECT * FROM event WHERE kind='message.user'").fetchone())
        assert token not in canonical(event) and cookie not in canonical(event)
        raw = store.read_raw(event["record_uid"])
        assert token.encode() in raw and cookie.encode() in raw
        assert store.verify()["unparsed"] == 0


@pytest.mark.parametrize("scheme", ["postgresql", "rediss", "HTTPS"])
def test_credentialed_uri_schemes_are_redacted(scheme):
    from tandem_data.privacy import redact

    value = f"{scheme}://fixture-user:fixture-password@example.invalid/db"
    cleaned = redact(value)
    assert "fixture-user" not in cleaned and "fixture-password" not in cleaned
    assert "example.invalid/db" in cleaned
