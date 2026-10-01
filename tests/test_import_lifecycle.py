"""An archive/restore lifecycle must not weaken the fixed-sample exclusion policy."""

import json

from tandem_backend.analysis import analyze
from tandem_backend.cli import demo_home, main
from tandem_backend.importers.codex import _status, parse_rollout
from tandem_backend.narrative import explain, markdown
from tandem_backend.recommend import recommend
from tandem_backend.store import Store, import_codex


def test_archive_restore_then_exclusion_removes_all_session_evidence(tmp_path):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    original = home / "sessions" / "demo-0.jsonl"
    archived = home / "archived_sessions" / "demo-0.jsonl"
    archived.parent.mkdir()
    original.rename(archived)
    import_codex(store, home)
    archived.rename(original)
    restored = import_codex(store, home)
    assert restored.imported == 1
    assert next(s for s in store.sessions() if s["id"] == "demo-0")["source_file"] == str(original.resolve())
    import_codex(store, home, exclude_sessions={"demo-0"})
    assert "demo-0" not in {s["id"] for s in store.sessions()}
    assert store.events(session_id="demo-0") == []


def test_replacing_source_identity_removes_previous_session_in_same_transaction(tmp_path):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    path = home / "sessions" / "demo-0.jsonl"
    path.write_text(path.read_text().replace('"demo-0"', '"replacement"'))
    import_codex(store, home)
    assert {s["id"] for s in store.sessions()} == {"replacement", "demo-1", "demo-2"}
    assert store.events(session_id="demo-0") == []
    import_codex(store, home, exclude_sessions={"replacement"})
    assert {s["id"] for s in store.sessions()} == {"demo-1", "demo-2"}


def test_disappeared_sources_are_reconciled_without_removing_another_home(tmp_path):
    first = demo_home(tmp_path / "first")
    second = demo_home(tmp_path / "second")
    path = second / "sessions" / "demo-0.jsonl"
    text = path.read_text().replace('"demo-0"', '"another-home"')
    path.write_text(text)
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, first)
    # Import just the distinct second-home session to avoid deliberately shared IDs.
    for name in ("demo-1.jsonl", "demo-2.jsonl"):
        (second / "sessions" / name).unlink()
    import_codex(store, second)
    (first / "sessions" / "demo-0.jsonl").unlink()
    import_codex(store, first)
    assert {s["id"] for s in store.sessions()} == {"demo-1", "demo-2", "another-home"}


def test_domain_exit_code_field_is_not_command_failure(tmp_path):
    home = demo_home(tmp_path / "codex")
    path = home / "sessions" / "demo-2.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        if row["payload"].get("type") == "function_call":
            row["payload"]["name"] = "mcp__business__read_fixture"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    parsed = parse_rollout(path)
    assert all(e.status is None for e in parsed.events if e.kind == "tool_result")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    assert "systematic-debugging" not in {r["resource_id"] for r in recommend(analyze(store))}
    assert _status('{"exit_code":1}', "mcp__business__read_fixture") is None
    assert _status('{"isError":true}', "mcp__business__read_fixture") == "failed"


def test_demo_does_not_open_unused_database(tmp_path):
    unused = tmp_path / "never-create.sqlite"
    main(["--db", str(unused), "demo", "--output", str(tmp_path / "demo")])
    assert not unused.exists()
    assert (tmp_path / "demo" / "demo.sqlite").exists()


def test_bottleneck_is_rendered_when_no_resource_matches(tmp_path):
    home = demo_home(tmp_path / "codex")
    path = home / "sessions" / "demo-0.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[3]["payload"]["content"][0]["text"] = "请解释这段代码，语言易读。"
    rows[4]["payload"]["content"][0]["text"] = "返回值说明。"
    rows.append({"type": "response_item", "timestamp": "2026-01-01T00:00:05Z", "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": "没看懂，请解释这段代码。"}]}})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    data = analyze(store)
    data["bottlenecks"] = [b for b in data["bottlenecks"] if b["type"] == "explanation_revision"]
    # This revision has no doc-coauthoring match in the coding scene.
    recs = [r for r in recommend(data) if r["bottleneck_id"] == data["bottlenecks"][0]["id"]]
    assert recs == []
    output = markdown(explain(data, recs))
    assert "待核对的卡点" in output
    assert "你随后要求调整说明" in output
