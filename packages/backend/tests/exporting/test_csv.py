"""Table allowlist and CSV streaming (EXP-02 / MB-06)."""

from __future__ import annotations

import csv
import io

from export_world import FAKE_SECRET, T0, client_for, fake_gateway, migration_columns

from orbit_backend.exporting import csv_export
from orbit_backend.exporting.tables import TABLES, header
from orbit_backend.sessionops import exclusion


def rows_of(response) -> list[list[str]]:
    return list(csv.reader(io.StringIO(response.text)))


def test_allowlist_columns_exist_and_exclude_everything_else():
    columns = migration_columns()
    for table in TABLES.values():
        for column in table.columns:
            source, name = column.origin.split(".")
            assert name in columns[source], column
        exported = {c.origin for c in table.columns}
        # Every column of the main source table that is not allowlisted stays out.
        hidden = {f"{table.source}.{c}" for c in columns[table.source]} - exported
        assert hidden and not hidden & exported
    names = {c.name for t in TABLES.values() for c in t.columns}
    for forbidden in ("files", "text", "attrs", "cwd", "argument_digest", "attribution"):
        assert forbidden not in names


def test_tables_endpoint(env):
    client, _, world = env
    world.session("s1")
    body = client.get("/v1/export/tables").json()
    ids = {t["id"]: t for t in body["tables"]}
    assert set(ids) == {"tool_calls", "sessions", "model_calls"}
    title = next(c for c in ids["sessions"]["columns"] if c["name"] == "title")
    assert title["redacted"] is True
    assert ids["sessions"]["approx_rows"] == 1
    assert "project_id" in ids["tool_calls"]["scope_filters"]


def test_csv_header_rows_guard_quoting_and_redaction(env):
    client, _, world = env
    world.session("s1", project="p1", title=f'=SUM(A1) "q", x\nnext {FAKE_SECRET}')
    ev = world.event("s1", f'{{"command": "curl -H Authorization: Bearer {FAKE_SECRET}"}} ' * 5)
    world.tool_calls("s1", [("c1", "+Bash", "-rm", "failed", T0, ev),
                            ("c2", "@Read", None, "success", T0 + 1, None)])
    response = client.get("/v1/export/csv", params={"table": "sessions"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="orbit-sessions-')
    assert "\r\n" in response.text
    rows = rows_of(response)
    assert rows[0] == header(TABLES["sessions"])
    record = dict(zip(rows[0], rows[1], strict=True))
    assert record["title"].startswith("'=SUM(A1) \"q\", x\nnext")
    assert FAKE_SECRET not in response.text
    assert record["started_at"] == str(T0) and record["started_at_iso"].endswith("Z")
    assert record["model"] == ""  # NULL is an empty cell

    calls = rows_of(client.get("/v1/export/csv", params={"table": "tool_calls"}))
    by_uid = {r[0]: dict(zip(calls[0], r, strict=True)) for r in calls[1:]}
    assert by_uid["c1"]["name"] == "'+Bash" and by_uid["c1"]["command_head"] == "'-rm"
    assert by_uid["c2"]["name"] == "'@Read"
    summary = by_uid["c1"]["args_summary"]
    assert len(summary) <= 120 and FAKE_SECRET not in summary and "\n" not in summary
    assert by_uid["c2"]["args_summary"] == ""


def test_csv_streams_in_5k_chunks(world):
    world.session("s1")
    world.tool_calls("s1", [(f"c{i:05d}", "Bash", "ls", "success", T0 + i, None)
                            for i in range(12_000)])
    table = TABLES["tool_calls"]
    sql, params = csv_export.query(table, limit=100_000)
    chunks = list(csv_export.stream(csv_export.open_snapshot(world.path), table, sql, params,
                                    header(table)))
    assert len(chunks) == 4  # header + 5000 + 5000 + 2000
    assert [c.count("\r\n") for c in chunks[1:]] == [5000, 5000, 2000]
    gw = fake_gateway(world.home, data_rev=1)
    rows = rows_of(client_for(gw).get("/v1/export/csv", params={"table": "tool_calls"}))
    assert len(rows) == 12_001 and rows[1][0] == "c00000" and rows[-1][0] == "c11999"
    gw.appdb.close()


def test_csv_filters_limit_and_exclusions(env):
    client, gw, world = env
    world.session("a", project="p1", started_at=T0)
    world.session("b", project="p2", source="src-x", started_at=T0 + 10)
    world.session("c", project="p1", started_at=T0 + 20)
    world.model_call("m1", "a", "claude-x", T0, 100)
    world.model_call("m2", "b", "gpt-y", T0 + 10, 200)

    def uids(**params):
        rows = rows_of(client.get("/v1/export/csv", params={"table": "sessions", **params}))
        return [r[0] for r in rows[1:]]

    assert uids() == ["a", "b", "c"]
    assert uids(project_id=["p1"]) == ["a", "c"]
    assert uids(agent="codex") == ["b"]
    assert uids(from_ts=T0 + 5, until_ts=T0 + 20) == ["b"]
    assert uids(limit=1) == ["a"]
    exclusion.add(gw.appdb, "c", "test")
    assert uids() == ["a", "b"]
    assert uids(include_excluded="true") == ["a", "b", "c"]
    usage = rows_of(client.get("/v1/export/csv", params={"table": "model_calls",
                                                          "agent": "claude_code"}))
    assert usage[0][:3] == ["session_uid", "model_id", "ts"] and len(usage) == 2
    assert dict(zip(usage[0], usage[1], strict=True))["input_tokens"] == "100"


def test_csv_errors(env, tmp_path):
    client, _, _ = env
    assert client.get("/v1/export/csv", params={"table": "event"}).status_code == 422
    bad = client.get("/v1/export/csv", params={"table": "sessions", "text": "x"})
    assert bad.status_code == 422
    empty = tmp_path / "empty"
    empty.mkdir()
    gw = fake_gateway(empty)
    response = client_for(gw).get("/v1/export/csv", params={"table": "sessions"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "no_projection"
    gw.appdb.close()


def test_guard_and_lines():
    assert [csv_export.guard(v) for v in ("=1", "+1", "-1", "@a", "\tx", "\rx", "ok")] == \
        ["'=1", "'+1", "'-1", "'@a", "'\tx", "'\rx", "ok"]
    assert csv_export.lines([["a,b", 'say "hi"', "l1\nl2", ""]]) == \
        '"a,b","say ""hi""","l1\nl2",\r\n'


def test_args_summary_is_redacted_before_it_is_cut(env):
    client, _, world = env
    world.session("s1")
    # A 393-char key (redacted to one short placeholder) followed by a GitHub token that
    # starts at char 394 and so straddles the old 400-char read boundary.
    first = "sk-ant-api03-" + "A" * 380
    token = "ghp_" + "a1" * 18
    text = f"{first} {token} tail"
    assert text.index(token) == 394 and text.index(token) + len(token) > 400
    ev = world.event("s1", text)
    world.tool_calls("s1", [("c1", "Bash", "ls", "success", T0, ev)])
    calls = rows_of(client.get("/v1/export/csv", params={"table": "tool_calls"}))
    summary = dict(zip(calls[0], calls[1], strict=True))["args_summary"]
    assert "ghp_" not in summary and "a1a1" not in summary
    assert summary == "[密钥已隐藏] [密钥已隐藏] tail"


def test_csv_hides_disabled_sources(env):
    """SET-07: a disabled source's sessions stay out of the export, as on every page."""
    from orbit_backend.appdata import sources_scope

    client, _, world = env
    world.session("a", started_at=T0)
    world.session("b", source="src-x", started_at=T0 + 10)
    sources_scope.set_provider(lambda: [{"id": "src-c", "enabled": True},
                                        {"id": "src-x", "enabled": False}])
    rows = rows_of(client.get("/v1/export/csv", params={"table": "sessions"}))
    assert [r[0] for r in rows[1:]] == ["a"]
