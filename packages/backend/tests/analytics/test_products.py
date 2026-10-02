"""UI-facing combinations with independent numeric oracles and native-import cases."""

import copy
import json
from pathlib import Path

import pytest

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.products import build_products
from tandem_backend.analytics.products.feedback import classify_emotion
from tandem_backend.analytics.products.render import export_report, html_report
from tandem_backend.analytics.products.tools import ordered_calls, transition_matrix
from tandem_backend.analytics.products.validation import validate_products

T = 1790812800000


def product_bundle():
    """Two sessions: read→shell→read→shell, then shell; never shell→shell across sessions."""
    sessions = [
        {
            "session_uid": sid,
            "root_uid": sid,
            "kind": "main",
            "source_id": "source-" + sid,
            "project_id": "project",
            "started_at": T,
            "title": "示例 " + sid,
        }
        for sid in ("a", "b")
    ]
    events, calls = [], []
    for index, (sid, name, kind, status) in enumerate(
        [
            ("a", "Read", "read", "success"),
            ("a", "Exec", "shell", "failed"),
            ("a", "Read", "read", "unknown"),
            ("a", "Exec", "shell", "success"),
            ("b", "Exec", "shell", "success"),
        ]
    ):
        uid, seq = f"c{index}", 10 + index * 2
        call = {
            "call_uid": uid,
            "session_uid": sid,
            "seq": seq,
            "turn_uid": "turn-" + sid,
            "name_raw": name,
            "kind": kind,
            "status": status,
            "status_scope": "command",
            "call_event_uid": uid,
            "result_event_uid": "r" + uid,
            "started_at": T + seq * 1000,
            "ended_at": T + (seq + 1) * 1000,
            "interval_reliable": True,
            "duration_ms": 1000,
            "duration_source": "native_bounds",
            "argument_digest": uid,
        }
        calls.append(call)
        for offset, event_kind, eid in ((0, "tool.call", uid), (1, "tool.result", "r" + uid)):
            events.append(
                {
                    "event_uid": eid,
                    "session_uid": sid,
                    "turn_uid": "turn-" + sid,
                    "seq": seq + offset,
                    "kind": event_kind,
                    "actor": "tool",
                    "ts": T + (seq + offset) * 1000,
                    "attrs": {"name": name},
                    "text": "",
                }
            )
    for seq, text, day in (
        (1, "请修复代码，先测试。", 0),
        (30, "我很满意。", 0),
        (31, "我很失望。", 1),
        (32, "请翻译：我很满意。", 1),
    ):
        events.append(
            {
                "event_uid": f"u{seq}",
                "session_uid": "a",
                "seq": seq,
                "turn_uid": "turn-a",
                "kind": "message.user",
                "actor": "human",
                "ts": T + day * 86400000 + seq * 1000,
                "text": text,
                "attrs": {"origin": "human"},
            }
        )
    return AnalysisInputBundle(
        sessions,
        events,
        calls,
        None,
        {
            "events": {"status": "available"},
            "tool_calls": {"status": "available"},
            "model_calls": {"status": "unavailable"},
        },
        projects=[{"project_id": "project", "name": "UI 测试"}],
        versions={"content_digest": "synthetic"},
    )


def test_tool_share_and_next_call_probability_use_independent_expected_values():
    bundle = product_bundle()
    before = copy.deepcopy(bundle)
    product = build_products(bundle)
    assert bundle == before
    rows = {r["name"]: r for r in product["tools"]["by_name"]}
    assert rows["Exec"]["count"] == 3 and rows["Exec"]["share"]["value"] == pytest.approx(0.6)
    assert rows["Read"]["count"] == 2 and rows["Read"]["share"]["value"] == pytest.approx(0.4)
    assert rows["Read"]["success_rate"]["value"] == 1
    assert rows["Read"]["success_rate"]["unknown_n"] == 1
    matrix = product["tools"]["transitions"]["kind"]
    assert {
        (r["from"], r["to"]): (r["count"], r["denominator"], r["probability"])
        for r in matrix["rows"]
    } == {("read", "shell"): (2, 2, 1), ("shell", "read"): (1, 1, 1)}
    assert matrix["pair_count"] == 3 and sum(matrix["terminal_counts"].values()) == 2
    assert validate_products(product)["status"] == "passed"


def test_ambiguous_order_cannot_create_adjacencies():
    calls = product_bundle().tool_calls
    calls[2]["seq"] = calls[1]["seq"]
    runs, unknown = ordered_calls(calls)
    assert unknown == 2
    assert transition_matrix(runs, "kind")["pair_count"] == 0
    calls[0]["seq"] = None
    runs, unknown = ordered_calls(calls)
    assert unknown == 4 and len(runs) == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("我很满意。", "positive"),
        ("我很失望。", "negative"),
        ("我很满意，但是我很失望。", "mixed"),
        ("我没有特别的感受。", "neutral"),
        ("请翻译：我很满意。", None),
        ("如果我很满意，就继续。", None),
        ("请不要再改其他文件。", None),
        ("我不满意吗？", None),
        ("我不太满意", None),
    ],
)
def test_emotion_requires_explicit_assertion(text, expected):
    assert classify_emotion(text) == expected


def test_feedback_chart_keeps_unknown_future_and_nonhuman_messages_out():
    bundle = product_bundle()
    bundle.events += [
        {
            "event_uid": "injected",
            "session_uid": "a",
            "seq": 99,
            "turn_uid": "turn-a",
            "kind": "message.user",
            "actor": "human",
            "ts": T,
            "text": "我很满意。",
            "attrs": {"origin": "injected"},
        }
    ]
    product = build_products(bundle, Scope(until_ts=T + 86400000))
    summary = product["feedback"]["summary"]
    assert summary["counts"] == {"unknown": 1, "positive": 1}
    assert summary["balance"]["value"] == 1 and summary["balance"]["unknown_n"] == 1
    assert len(product["feedback"]["by_day"]) == 1
    assert product["profile"]["type_code"] is None
    assert all(row["journey"]["outcome"]["task_success"] is None for row in product["sessions"])


def test_source_filter_empty_and_unavailable_data_preserve_meaning():
    bundle = product_bundle()
    assert build_products(bundle, Scope(source_ids=["source-b"]))["tools"]["call_count"] == 1
    empty = build_products(bundle, Scope(source_ids=[]))
    assert empty["tools"]["call_count"] == 0
    bundle.events = None
    bundle.tool_calls = None
    bundle.coverage["tool_calls"]["status"] = "unavailable"
    result = build_products(bundle)
    assert result["tools"]["call_count"] is None
    assert result["feedback"]["summary"] is None


def test_csv_html_and_json_exports_escape_untrusted_content(tmp_path):
    bundle = product_bundle()
    bundle.tool_calls[0]["name_raw"] = "=IMPORTXML('<script>')"
    product = build_products(bundle)
    files = export_report(product, tmp_path)
    assert json.loads(Path(files["analysis.json"]).read_text()) == product
    assert "<script>" not in html_report(product)
    assert "&lt;script&gt;" in html_report(product)
    assert "'=IMPORTXML" in Path(files["tools.csv"]).read_text()
    assert Path(files["analysis.json"]).stat().st_mode & 0o077 == 0


def test_requirement_retry_validation_and_feedback_are_combined_without_conflating_success():
    bundle = product_bundle()
    requirement = next(e for e in bundle.events if e["event_uid"] == "u1")
    requirement["text"] = "请修复代码。请运行测试。"
    scope = {
        "project_id": "project",
        "artifact_uid": "app",
        "artifact_revision": "v1",
        "coverage": "full",
    }
    requirement["attrs"].update(
        task_id="task-1",
        task_id_source="native",
        task_uid="task-1",
        acceptance={
            "state": "confirmed",
            "source": "synthetic-human-review",
            "available_at": T,
            "criteria_set_uid": "criteria-1",
            "complete": True,
            "scope": scope,
            "criteria": [{"criterion_uid": "test", "kind": "test"}],
        },
    )
    for call in (bundle.tool_calls[1], bundle.tool_calls[3]):
        call.update(
            task_uid="task-1",
            validation={
                "kind": "test",
                "executed": True,
                "source": "synthetic-check",
                "available_at": T,
                "scope": scope,
                "criterion_uids": ["test"],
            },
        )
    bundle.tool_calls[3]["retry_of_call_uid"] = "c1"
    product = build_products(bundle)
    session = next(s for s in product["sessions"] if s["session_uid"] == "a")
    assert session["journey"]["outcome"]["task_success"] is True
    assert session["outcomes"]["first_pass"][0]["attempts_to_first_pass"] == 2
    assert session["outcomes"]["human_feedback"]["accepted_feedback_count"] == 0
    assert product["tools"]["recovery"][0]["state"] == "recovered"
    assert product["tools"]["recovery"][0]["retry_execution_ms"]["value"] == 1000
    assert session["journey"]["tasks"][0]["effective_instructions"]["active"]
    assert (
        sum(e["phase"] == "verify" for lane in session["journey"]["lanes"] for e in lane["events"])
        == 2
    )


def test_validation_detects_broken_product_instead_of_pass_on_empty_checks():
    product = build_products(product_bundle())
    product["tools"]["by_name"][0]["count"] += 1
    assert validate_products(product)["status"] == "failed"
