"""Fact rows over the synthetic Codex 90 + Claude Code 60 store: analysis parity + basis."""

import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from tandem_backend.uiview import facts

from .synth import analysed


def _rows():
    return analysed()[4]["rows"]


def test_rows_match_analysis_counts():
    _, store, _, result, body = analysed()
    counts = result["overview"]["counts"]
    rows = body["rows"]
    assert len(rows) == counts["main_sessions"] == 150
    assert sum(r["msgs"] for r in rows) == counts["human_messages"]
    assert sum(r["corr"] for r in rows) == counts["correction_signals"]
    with store.connect() as conn:
        (calls,) = conn.execute("SELECT count(*) FROM tool_call").fetchone()
    assert sum(r["tools"] for r in rows) == calls
    assert body["meta"]["counts"]["main_sessions"] == len(rows)
    assert {a["id"]: a["n"] for a in body["agents"]} == {"codex": 90, "claude_code": 60}
    assert sum(p["n"] for p in body["projects"]) == 150


def test_every_row_has_the_prototype_shape():
    for row in _rows():
        assert set(facts.ROW_KEYS) <= set(row)
        assert row["mood"] is None or -1 <= row["mood"] <= 1
        assert row["corr_basis"] == "lexical_candidate"
        assert row["out"] in ("ok", "part", "fail", None)
        assert row["out"] is None or row["out_basis"] == "estimate"
        assert row["fric"] is None or row["fric"] in facts.FRIC
        assert row["topic"] is None or row["topic"] in facts.TOPICS
        assert 0 <= row["h"] <= 23 and 0 <= row["mi"] <= 59
        assert row["dur"] <= row["span"] + 1e-6  # idle gaps are capped, never added


def test_codex_unknown_tool_status_stays_null_not_zero():
    rows = _rows()
    codex = [r for r in rows if r["a"] == "codex"]
    claude = [r for r in rows if r["a"] == "claude_code"]
    assert codex and all(r["errors"] is None for r in codex)
    assert claude and all(isinstance(r["errors"], int) for r in claude)
    assert any(r["errors"] for r in claude)


def test_tokens_sum_l1_model_calls():
    _, store, _, _, body = analysed()
    with store.connect() as conn:
        (total,) = conn.execute(
            "SELECT sum(COALESCE(input_tokens,0) + COALESCE(cache_read_tokens,0) + "
            "COALESCE(cache_write_tokens,0) + COALESCE(output_tokens,0)) FROM model_call"
        ).fetchone()
    rows = body["rows"]
    assert total and sum(r["tok"] for r in rows if r["tok"] is not None) == total
    assert {r["tok_basis"] for r in rows} <= {"l1_model_call", "cumulative_estimate"}


def test_all_null_tokens_stay_null():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE model_call (session_uid, model_id, effort_raw, coverage, "
                 "input_tokens, cache_read_tokens, cache_write_tokens, output_tokens)")
    conn.executemany("INSERT INTO model_call VALUES (?,?,?,?,?,?,?,?)",
                     [("s1", "m", None, None, None, None, None, None),
                      ("s2", "m", "high", None, 10, None, None, 5)])
    tok, _, models, efforts = facts._models(conn, json.dumps(["s1", "s2"]),
                                            {"s1": "s1", "s2": "s2"})
    assert "s1" not in tok and tok["s2"] == 15
    assert models["s1"]["m"] == 1 and efforts["s2"]["high"] == 1


def test_excluded_sessions_come_back_flagged():
    _, store, scope, result, _ = analysed()
    gone = result["sessions"][0]["session_uid"]
    trimmed = {**result, "sessions": [s for s in result["sessions"]
                                      if s["session_uid"] != gone]}
    fake = SimpleNamespace(display_timezone="UTC", excluded_session_uids=[gone])
    with store.connect() as conn:
        body = facts.build_facts(conn, trimmed, fake)
    flagged = [r for r in body["rows"] if r["excluded"]]
    assert [r["id"] for r in flagged] == [gone]
    assert flagged[0]["msgs"] is None and flagged[0]["a"] in ("codex", "claude_code")
    assert body["meta"]["counts"]["excluded"] == 1


def test_compact_round_trip_and_live_overlay():
    body = analysed()[4]
    wire = facts.compact(body)
    back = facts.expand(wire)
    assert [r["id"] for r in back] == [r["id"] for r in body["rows"]]
    assert back[5]["a"] == body["rows"][5]["a"] and back[5]["fric"] == body["rows"][5]["fric"]
    uid = body["rows"][3]["id"]
    live = facts.overlay_live(body, {"sessions": [{"session_uid": uid, "state": "running"}]})
    row = next(r for r in live["rows"] if r["id"] == uid)
    assert row["live"] and row["out"] == "live"
    assert not next(r for r in body["rows"] if r["id"] == uid)["live"]  # snapshot untouched


def _bulk(n: int) -> dict:
    body = analysed()[4]
    base = body["rows"]
    rows = []
    for i in range(n):
        row = dict(base[i % len(base)])
        row["id"] = f"session_{i:064x}"
        rows.append(row)
    return {**body, "rows": rows}


@pytest.mark.serial
def test_wire_size_and_build_speed():
    _, store, scope, result, _ = analysed()
    started = time.perf_counter()
    with store.connect() as conn:
        facts.build_facts(conn, result, scope)
    assert time.perf_counter() - started < 1.0
    import gzip

    big = _bulk(2400)
    started = time.perf_counter()
    raw = json.dumps(facts.compact(big), ensure_ascii=False, separators=(",", ":")).encode()
    assert time.perf_counter() - started < 1.0
    assert len(raw) / 2.4 < 200_000  # ≤ 200 KB per 1000 sessions
    assert len(gzip.compress(raw, 5)) < 300_000


def test_section_reuses_the_memoised_analysis():
    from tandem_backend.services.sections import SECTIONS
    from tandem_backend.uiview import section

    _, store, scope, result, body = analysed()
    seen = []

    class Memo:
        def sections(self, store_, scope_, keys, with_text, revision):
            seen.append((tuple(keys), with_text, revision))
            return result

    out = section.compute(store, scope, {"_rev": 7}, Memo())
    # Only the sections build_facts reads, in the cache variant shared with analytics.
    assert seen == [(tuple(section.INPUTS), True, 7)]
    assert out["rows"] == body["rows"]
    assert SECTIONS["uiview_facts"].cost == "heavy"


@pytest.mark.parametrize(("raw", "want"), [
    ("Write a SwiftUI preview for the profile screen with dark mode and dynamic type",
     "Write a SwiftUI preview for the profile screen…"),
    ("x" * 48, "x" * 48),
    ("a" * 47 + " ", "a" * 47),
    ("  short title  ", "short title"),
    ("修复导入时界面反复重渲染导致下拉框关闭的问题，并补充回归测试以及截图核对多种窗口尺寸下的表现，同时检查深浅色",
     "修复导入时界面反复重渲染导致下拉框关闭的问题，并补充回归测试以及截图核对多种窗口尺寸下的表现，同时检查深浅色"[:48] + "…"),
    ("Write a SwiftUI preview for the profile         ", "Write a SwiftUI preview for the profile"),
])
def test_wire_title_ellipsis_without_trailing_space(raw, want):
    got = facts.wire_title(raw)
    assert got == want
    assert got == got.strip() and len(got) <= facts.WIRE_TITLE_LEN + 1


def test_compact_titles_end_with_ellipsis_not_space():
    body = analysed()[4]
    long = "Write a SwiftUI preview for the profile screen with many states"
    rows = [{**body["rows"][0], "title": long}, *body["rows"][1:]]
    wire = facts.compact({**body, "rows": rows})
    back = facts.expand(wire)
    assert back[0]["title"].endswith("…") and " …" not in back[0]["title"]


@pytest.mark.parametrize(("last_turn", "corr", "msgs", "tail", "expected"), [
    # Long session with a few corrections: 3/200 = 1.5% << 1/3, last turn completed.
    (("completed", True), 3, 200, ["success"], "ok"),
    # Old rule called this "fail" (corr >= 3); density 3/9 = 1/3 is rework, not failure.
    (("completed", True), 3, 9, ["success"], "part"),
    (("completed", True), 2, 7, [], "ok"),  # 2/7 < 1/3
    (("completed", False), 1, 2, [], "ok"),  # 1/2 dense but a single hit never decides
    # No human turn (agents without turns, steps=None): no evidence -> None.
    (None, None, None, None, None),
    (None, 0, 5, ["success", "success"], None),
    # A turn without status: a final reply is completion evidence, none is unknown.
    ((None, True), 0, 3, [], "ok"),
    ((None, False), 0, 3, [], None),
    # Unresolved failure streak at the end.
    (("completed", True), 0, 4, ["success", "failed", "failed", "failed"], "part"),
    (("completed", True), 0, 4, ["failed", "failed", "success"], "ok"),
] + [((status, True), 0, 3, [], "fail") for status in
     ("failed", "error", "interrupted", "aborted", "cancelled", "rejected")])
def test_outcome_of_boundaries(last_turn, corr, msgs, tail, expected):
    assert facts.outcome_of(last_turn, corr, msgs, tail) == expected


def test_outcome_labels_never_claim_abandoned():
    from tandem_backend.uiview import derive, outcome

    names = {oid: name for oid, name, _ in derive.OUT_IDS}
    assert names == {k: outcome.LABELS[k] for k in ("ok", "part", "fail")}
    assert "放弃" not in "".join(names.values())


def _bare_store():
    """A store with only ``session``/``source``: every L1 detail table is missing."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE source(source_id TEXT, agent TEXT);"
        "CREATE TABLE session(session_uid TEXT, source_id TEXT, kind TEXT, project_id TEXT,"
        " title TEXT, title_source TEXT, started_at INTEGER);"
        # tool_call exists but lacks turn_uid/status: 'no such column', not 'no such table'.
        "CREATE TABLE tool_call(call_uid TEXT, session_uid TEXT);")
    return conn


def test_schema_gaps_degrade_to_null_and_are_reported():
    """UT-08: a missing table/column leaves its fields null and lists them in meta.degraded."""
    conn = _bare_store()
    result = {"sessions": [{"session_uid": "s1", "kind": "main", "agent": "kimi",
                            "features": {"user_message_count": 4, "tool_call_count": 0,
                                         "correction_signal_count": 0}}]}
    body = facts.build_facts(conn, result, SimpleNamespace(display_timezone="UTC"))
    row = body["rows"][0]
    assert (row["dur"], row["steps"], row["verify"], row["out"], row["tok"]) == (
        None, None, None, None, None)
    assert row["msgs"] == 4  # analysis features are unaffected
    degraded = set(body["meta"]["degraded"])
    assert {"dur", "steps", "verify", "out", "errors", "tok", "title", "mood"} <= degraded


def test_real_sql_errors_raise():
    conn = _bare_store()
    with pytest.raises(sqlite3.OperationalError, match="syntax"):
        facts._rows(conn, "SELEC session_uid FROM session")
    assert facts._rows(conn, "SELECT turn_uid FROM tool_call", fields=("steps",)) == []
    assert facts.is_schema_gap(sqlite3.OperationalError("no such column: turn_uid"))
    assert not facts.is_schema_gap(sqlite3.OperationalError("database is locked"))


def test_compact_keeps_numeric_precision():
    """UT-10: mood (−1..1) survives the wire with 3 decimals, dur/span with 2."""
    row = {k: None for k in facts.ROW_KEYS}
    row.update(id="session_x", mood=-0.34567, dur=12.345, span=61.239, live=False,
               excluded=False)
    back = facts.expand(facts.compact({"rows": [row], "meta": {}, "aux": {}}))[0]
    assert back["mood"] == -0.346 and back["dur"] == 12.35 and back["span"] == 61.24
