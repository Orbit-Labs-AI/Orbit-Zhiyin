"""cost_time.usage: partial token totals, unknown-row accounting, 1h cache writes, service tiers.

Expected values are hand sums of the constructed rows below (not implementation output).
"""

from tandem_backend.analytics.cost_time import usage
from tandem_backend.analytics.inputs import Scope

SESSION = {"session_uid": "s", "kind": "main", "root_uid": "s", "project_id": "p", "started_at": 0}


def request(uid, *, input_tokens=100, cache_read=10, cache_write=20, output=30, **kw):
    return {"call_uid": uid, "session_uid": "s", "turn_uid": "t", "model_id": "m",
            "usage_scope": "call", "measurement": "delta", "boundary_reliable": True,
            "coverage": "self", "ts": 100, "input_tokens": input_tokens,
            "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
            "output_tokens": output, **kw}


def test_one_bad_row_keeps_a_known_row_lower_bound():
    rows = [
        request("a"),                                           # 100+10+20+30 = 160
        request("b", input_tokens=200, output=50),              # 200+10+20+50 = 280
        request("c", output=None),                              # token-unknown call
        request("d", boundary_reliable=False),                  # invalid request row
    ]
    u = usage(rows, [], [SESSION], Scope())
    assert u["total_tokens"] == 160 + 280
    assert u["total_basis"] == "call_delta_known_rows" and u["total_complete"] is False
    assert u["status"] == "partial" and u["total_note"]
    assert u["total_unknown"] == {"invalid_request_rows": 1, "conflicting_request_ids": 0,
                                  "token_unknown_calls": 1, "records_incomplete": False}


def test_complete_rows_keep_the_exact_basis():
    u = usage([request("a"), request("b")], [], [SESSION], Scope())
    assert (u["total_tokens"], u["total_basis"], u["total_complete"]) == (320, "call_delta", True)
    assert u["total_note"] is None


def test_no_known_row_stays_unknown():
    u = usage([request("a", output=None)], [], [SESSION], Scope())
    assert u["total_tokens"] is None and u["total_complete"] is None


def test_cache_write_1h_and_service_tier_from_model_call_columns():
    rows = [request("a", cache_write=20, cache_write_1h_tokens=15, service_tier="priority"),
            request("b", cache_write=20, cache_write_1h_tokens=0, service_tier="default"),
            request("c", cache_write=20)]                     # NULL = not reported, not zero
    u = usage(rows, [], [SESSION], Scope())
    assert u["cache_write_1h_tokens"] == 15 and u["cache_write_1h_reported_n"] == 2
    assert u["service_tiers"] == {"priority": 1, "default": 1, "unreported": 1}


def test_cost_subtotal_of_priced_rows():
    rows = [request("a", cost_usd=0.5, cost_source="reported"), request("b")]
    u = usage(rows, [], [SESSION], Scope())
    assert u["cost_usd"] is None and u["known_cost_usd"] == 0.5
    assert (u["cost_effective_n"], u["cost_unknown_n"]) == (1, 1)
