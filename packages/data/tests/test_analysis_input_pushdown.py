"""read_analysis pushes member filters into SQLite without changing its output.

All sessions are constructed dsh records; no local agent history is read.
"""

from contextlib import contextmanager

import pytest

from tandem_data import analysis_input
from tandem_data.analysis_input import AnalysisScope, decoded, read_analysis
from tandem_data.contract import canonical
from tandem_data.store import Store, readonly_connection


def session_rows(n: int, base: int) -> list[dict]:
    """One constructed session: prompt, usage, two tool calls with approvals and results."""
    t = base
    rows = [
        {
            "type": "session",
            "id": f"s{n}",
            "version": 4,
            "createdAt": t,
            "cwd": f"/synthetic/p{n % 2}",
        },
        {"type": "session/title", "seq": 0, "time": t + 10, "data": {"title": f"会话 {n}"}},
        {"type": "turn/start", "seq": 1, "time": t + 20, "data": {"turn": 1}},
        {
            "type": "user/message",
            "seq": 2,
            "time": t + 30,
            "data": {
                "role": "user",
                "content": [{"type": "text", "text": f"请修复测试 {n}"}],
                "source": {"kind": "user"},
            },
        },
        {
            "type": "assistant/message",
            "seq": 3,
            "time": t + 40,
            "data": {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "好的"}],
                    "source": {"model": "m-a", "provider": "synthetic"},
                },
                "usage": {"input_tokens": 100 + n, "output_tokens": 10 + n},
            },
        },
    ]
    seq = 4
    for c in range(2):
        call = f"s{n}-c{c}"
        # Calls alternate between: decided before the cutoff, decided twice across the
        # cutoff (the last decision governs), and decided only after the cutoff.
        decisions = {0: [t + 60], 1: [t + 70, t + 2000]}[c] if n % 3 else [t + 2000]
        rows.append(
            {
                "type": "tool/call",
                "seq": seq,
                "time": t + 50 + c,
                "data": {"callId": call, "name": "bash", "arguments": "{}"},
            }
        )
        rows.append(
            {
                "type": "approval/asked",
                "seq": seq + 1,
                "time": t + 55 + c,
                "data": {"id": f"a-{call}", "callId": call},
            }
        )
        seq += 2
        for k, when in enumerate(decisions):
            rows.append(
                {
                    "type": "approval/decided",
                    "seq": seq,
                    "time": when,
                    "data": {"id": f"a-{call}", "outcome": ["allowed-once", "denied"][k % 2]},
                }
            )
            seq += 1
        rows.append(
            {
                "type": "tool/result",
                "seq": seq,
                "time": t + (90 if c == 0 else 2500),
                "data": {
                    "message": {
                        "role": "tool",
                        "toolCallId": call,
                        "toolName": "bash",
                        "content": [{"type": "text", "text": "ok"}],
                    }
                },
            }
        )
        seq += 1
    rows.append(
        {
            "type": "turn/end",
            "seq": seq,
            "time": t + 3000,
            "data": {"turn": 1, "reason": {"kind": "completed"}},
        }
    )
    return rows


def build(tmp_path, sessions: int):
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        for n in range(sessions):
            store.capture_stream(
                source,
                f"s{n}.jsonl",
                [(canonical(r) + "\n").encode() for r in session_rows(n, 1000 + n * 10)],
            )
        store.rebuild()
        return store.home


def full_scan(home, query, keep):
    """The former reader: decode every row, filter in Python, keep native scan order."""
    with readonly_connection(home / "tandem.db") as connection:
        return [decoded(row) for row in connection.execute(query) if keep(row)]


def legacy_approval_visible(home, call_uid, until_ts):
    """The former per-call approval query: the last decision by seq governs."""
    with readonly_connection(home / "tandem.db") as connection:
        decisions = connection.execute(
            "SELECT e.* FROM tool_call_event c JOIN event e USING(event_uid)"
            " WHERE c.call_uid=? AND c.role='permission.decision' ORDER BY e.seq",
            (call_uid,),
        ).fetchall()
    decision = decisions[-1] if decisions else None
    return not (decision is None or decision["ts"] is None or decision["ts"] >= until_ts)


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    return build(tmp_path_factory.mktemp("pushdown"), 9)


SCOPES = [
    AnalysisScope("Asia/Shanghai"),
    AnalysisScope("Asia/Shanghai", until_ts=1063),
    AnalysisScope("Asia/Shanghai", until_ts=1500),
    AnalysisScope("Asia/Shanghai", from_ts=1040, until_ts=2600),
    AnalysisScope("Asia/Shanghai", include_children=False),
]


@pytest.mark.parametrize("scope", SCOPES, ids=lambda s: f"from={s.from_ts},until={s.until_ts}")
def test_pushdown_rows_match_former_full_scans(home, scope):
    data = read_analysis(home, scope)
    members = set(data["statistical_members"]["event_uids"])
    sessions = {e["session_uid"] for e in data["events"]} | {e["root_uid"] for e in data["events"]}

    expected_models = full_scan(
        home, "SELECT * FROM v_analysis_model_call", lambda r: r["usage_event_uid"] in members
    )
    assert expected_models and data["model_calls"] == expected_models
    expected_tools = full_scan(
        home,
        "SELECT * FROM v_analysis_tool_call",
        lambda r: r["call_event_uid"] in members or r["result_event_uid"] in members,
    )
    assert expected_tools
    assert [t["call_uid"] for t in data["tool_calls"]] == [t["call_uid"] for t in expected_tools]
    expected_sessions = full_scan(
        home, "SELECT * FROM session", lambda r: r["session_uid"] in sessions
    )
    assert [s["session_uid"] for s in data["sessions"]] == [
        s["session_uid"] for s in expected_sessions
    ]
    if scope.until_ts is None:
        # Without a cutoff the reader must not alter the stored rows at all.
        assert data["tool_calls"] == expected_tools
        assert data["sessions"] == expected_sessions
    else:
        for tool, stored in zip(data["tool_calls"], expected_tools, strict=True):
            visible = legacy_approval_visible(home, tool["call_uid"], scope.until_ts)
            assert tool["approval"] == (stored["approval"] if visible else None)
            if not visible:
                assert tool["approval_wait_ms"] is None


def test_cutoff_keeps_only_approvals_decided_before_it(home):
    data = read_analysis(home, AnalysisScope("Asia/Shanghai", until_ts=1500))
    approvals = [t["approval"] for t in data["tool_calls"]]
    # n % 3 == 0 sessions decide only after the cutoff; in the others the second call
    # is re-decided after the cutoff, so its last decision is not yet visible.
    assert approvals.count("allowed-once") == 6
    assert approvals.count(None) == 12


@pytest.mark.parametrize("sessions", [2, 8])
def test_approval_lookup_is_one_query_regardless_of_call_count(tmp_path, monkeypatch, sessions):
    home = build(tmp_path, sessions)
    statements = []

    @contextmanager
    def traced(path):
        with readonly_connection(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(analysis_input, "readonly_connection", traced)
    data = read_analysis(home, AnalysisScope("Asia/Shanghai", until_ts=1500))
    assert len(data["tool_calls"]) == 2 * sessions
    decision_queries = [
        s for s in statements if "permission.decision'" in s and "tool_call_event" in s
    ]
    assert len(decision_queries) == 1
    # Member rows are filtered in SQLite rather than decoded wholesale.
    full_reads = {
        "SELECT * FROM v_analysis_tool_call",
        "SELECT * FROM v_analysis_model_call",
        "SELECT * FROM session",
    }
    assert not full_reads & {s.strip() for s in statements}


def test_pushdown_binds_selections_beyond_the_sqlite_variable_limit(home):
    roots = sorted({e["root_uid"] for e in read_analysis(home, AnalysisScope("UTC"))["events"]})
    scope = AnalysisScope(
        "UTC", root_session_uids=[*(f"missing-{i}" for i in range(40_000)), *roots]
    )
    data = read_analysis(home, scope)
    assert [s["session_uid"] for s in data["sessions"]] == [
        s["session_uid"] for s in read_analysis(home, AnalysisScope("UTC"))["sessions"]
    ]
