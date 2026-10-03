"""Large homes must not turn per-call evidence into a gigabyte payload or snapshot."""

from tandem_backend.analytics.history import history_for
from tandem_backend.analytics.products import analyze_product_store
from tandem_backend.analytics.products.payload import compact
from tandem_backend.analytics.products.tools import EVIDENCE_LIMIT, analyze_tools
from tandem_backend.cli import demo_home
from tandem_backend.data_access.ingest import ingest
from tandem_backend.data_access.store import CanonicalStore


def _calls(sessions: int, per_session: int) -> list[dict]:
    """Synthetic calls alternating two tools, every session fully ordered."""
    return [
        {"session_uid": f"s{s:03d}", "call_uid": f"s{s:03d}-c{i:03d}", "seq": i,
         "name_raw": ("read", "edit")[i % 2], "kind": ("read", "write")[i % 2],
         "status": "success"}
        for s in range(sessions) for i in range(per_session)
    ]


def test_tool_transitions_and_shares_keep_counts_but_bound_evidence():
    tools = analyze_tools({"tool_sequence": _calls(120, 30), "status": "available"})
    for matrix in tools["transitions"].values():
        assert "next_calls" not in matrix  # One row per adjacency grew to 93 MB.
        assert matrix["pair_count"] == 120 * 29 == sum(r["count"] for r in matrix["rows"])
        assert all(len(r["evidence"]) <= EVIDENCE_LIMIT for r in matrix["rows"])
    for row in tools["by_name"]:
        assert row["session_count"] == 120 and len(row["session_uids"]) == EVIDENCE_LIMIT
    for row in tools["patterns"]:
        assert row["support_sessions"] == row["session_count"] == 120
        assert len(row["session_uids"]) == EVIDENCE_LIMIT


def test_compact_caps_evidence_arrays_and_records_their_length():
    product = {"statistics": {"metrics": {"m": {"n": 500, "unknown_n": 0, "samples": [
        {"value": i, "evidence_ids": [f"e{i}-{j}" for j in range(80)]} for i in range(500)]}}},
        "sessions": [{"journey": {"lanes": [{"events": [{"seq": i} for i in range(300)]}]}}],
        "lexical": {"terms": [{"term": f"t{i}"} for i in range(300)]}}
    small = compact(product)
    metric = small["statistics"]["metrics"]["m"]
    assert len(metric["samples"]) == EVIDENCE_LIMIT and metric["samples_total"] == 500
    assert len(metric["samples"][0]["evidence_ids"]) == EVIDENCE_LIMIT
    assert metric["samples"][0]["evidence_ids_total"] == 80
    lane = small["sessions"][0]["journey"]["lanes"][0]
    assert len(lane["events"]) == EVIDENCE_LIMIT and lane["events_total"] == 300
    assert len(small["lexical"]["terms"]) == 300  # Only evidence keys are capped.
    assert len(product["statistics"]["metrics"]["m"]["samples"]) == 500  # Input untouched.


def test_identical_product_request_reuses_snapshot_instead_of_recomputing(tmp_path, monkeypatch):
    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "source"))
    store = CanonicalStore(home)
    first = analyze_product_store(store)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("identical request at the same revision must not recompute")

    monkeypatch.setattr("tandem_backend.analytics.products.service._product_store", forbidden)
    assert analyze_product_store(store) == first and not calls
    runs = history_for(store).list_runs(engine="products")
    assert runs["total"] == 2 and {r["status"] for r in runs["items"]} == {"completed"}
    assert len({r["snapshot_id"] for r in runs["items"]}) == 1
    assert runs["items"][0]["request"]["data_revision"] is not None


def test_presentation_bounds_per_call_evidence_but_keeps_aggregates():
    """20 000 calls: the raw projection carries ≈1 KB/call of refs; the served one is capped."""
    import json
    from pathlib import Path

    from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
    from tandem_backend.analytics.presentation import bounded_presentation, build_presentation
    from tandem_backend.analytics.service import analyze_bundle

    raw = json.loads((Path(__file__).parents[1] / "fixtures/bottleneck-features-v1.json")
                     .read_text(encoding="utf-8"))
    analysis = analyze_bundle(AnalysisInputBundle.from_dict(raw), Scope(), with_text=False)
    n, failed = 20_000, 20_000 // 4  # every 4th call failed: 5 000 failed, 15 000 success
    calls = [{"call_uid": f"c{i:05d}", "session_uid": "root", "seq": i,
              "name_raw": ("read", "edit")[i % 2], "kind": ("read", "write")[i % 2],
              "tool_result_status": "failed" if i % 4 == 0 else "success"} for i in range(n)]
    respond = analysis["bottleneck_features"]["respond"]
    respond.update(tool_sequence=calls, status="available")

    full = build_presentation(analysis)
    served = bounded_presentation(analysis)
    tools, capped = full["diagnostics"]["tools"], served["diagnostics"]["tools"]
    assert len(json.dumps(full["diagnostics"])) > 2_000_000  # the cap is what bounds it
    assert len(json.dumps(served)) < 2_000_000

    # Aggregates are untouched: 5 000 / 20 000 failed among known statuses.
    assert capped["error_rate"]["numerator"] == failed and capped["error_rate"]["denominator"] == n
    assert capped["error_rate"]["value"] == tools["error_rate"]["value"] == failed / n
    matrix = capped["transition_matrix"]
    assert sum(map(sum, matrix["counts"])) == n - 1 == sum(map(sum, tools["transition_matrix"]["counts"]))

    # Evidence keeps ≤ 50 samples plus the exact length.
    assert len(matrix["evidence_refs"]) == EVIDENCE_LIMIT and matrix["evidence_refs_total"] == n - 1
    for rate in ("success_rate", "error_rate"):
        assert len(capped[rate]["evidence_refs"]) == EVIDENCE_LIMIT
        assert capped[rate]["evidence_refs_total"] == n
    for finding in served["diagnostics"]["findings"]:
        assert len(finding["evidence_refs"]) <= EVIDENCE_LIMIT
    failure = next(f for f in served["diagnostics"]["findings"] if f["rule_id"] == "tool_failure")
    assert failure["evidence_refs_total"] == failed
