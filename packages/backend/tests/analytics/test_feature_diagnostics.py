"""Diagnostic projections preserve unknowns, evidence units and actual decisions."""

import copy
import json

from orbit_backend.analytics.diagnostics import diagnostics, family_diagnostics, terminal_text
from orbit_backend.analytics.service import analyze_bundle


def test_missing_sources_cannot_look_like_eight_successful_empty_extractors():
    report = diagnostics({})
    assert len(report["families"]) == 8
    assert all(f["status"] == "unavailable" for f in report["families"].values())
    assert report["skills"]["items"] is None
    assert report["profile"]["iteration"]["task_trajectories"] is None
    assert "unknown" in terminal_text(report)
    json.dumps(report, allow_nan=False)


def test_real_projection_distinguishes_inputs_candidates_and_structured_features(fixtures):
    _, event, bundle = fixtures
    data = analyze_bundle(
        bundle(
            [
                event("请修复 Python 代码。请用 JSON 输出", "u1", 0),
                event("不对，请重写", "u2", 1),
            ]
        ),
        with_text=False,
    )
    before = copy.deepcopy(data)
    report = diagnostics(data)
    interaction = report["families"]["interaction"]
    assert interaction["status"] == "candidates_only"
    assert interaction["analyzed"]["reviewed_intents"]["value"] == 0
    assert interaction["analyzed"]["confirmed_corrections"]["value"] is None
    assert interaction["analyzed"]["lexical_candidates"]["value"] == 1
    instruction = report["families"]["instruction"]["analyzed"]
    assert instruction["evidence_quality"]["value"]["explicit_messages"] >= 1
    assert instruction["evidence_quality"]["value"]["inferred_messages"] == 0
    text = terminal_text(report)
    assert "format_requirements" in text and "software" in text and "domain_distribution" in text
    assert data == before


def test_unavailable_usage_does_not_hide_independently_reported_wall_time():
    features = family_diagnostics(
        {
            "bottleneck_features": {
                "cost_time": {
                    "usage": {
                        "status": "unavailable",
                        "request_count": 0,
                        "total_tokens": 0,
                        "token_buckets": {
                            "input_tokens": 0,
                            "cache_read_tokens": 0,
                            "cache_write_tokens": 0,
                            "output_tokens": 0,
                        },
                    },
                    "durations": {"wall_elapsed_sum_ms": 1234, "native_execution_sum_ms": None},
                }
            }
        }
    )["cost_time"]
    assert features["input"]["request_rows"]["value"] is None
    for key in (
        "valid_requests",
        "total_tokens",
        "uncached_input",
        "cached_input",
        "cache_write",
        "output_tokens",
    ):
        assert features["analyzed"][key]["value"] is None
    assert features["analyzed"]["wall_elapsed"]["value"] == 1234
    assert features["analyzed"]["native_execution"]["value"] is None


def test_authoritative_unavailable_or_excluded_masks_compatibility_zeros():
    report = family_diagnostics(
        {
            "bottleneck_features": {
                "interaction": {
                    "status": "excluded",
                    "message_intents": [],
                    "effective_samples": {"human_messages": 0},
                },
                "respond": {
                    "status": "unavailable",
                    "tool_sequence": [],
                    "subagent_instance_count": 0,
                },
                "outcome": {"status": "unavailable", "validation_runs": [], "effective_n": 0},
            },
            "instruction": {"summary": {"status": "unavailable", "effective_n": 0}},
        }
    )
    for name in ("interaction", "respond", "objective_outcome", "instruction"):
        assert report[name]["status"] in {"unavailable", "excluded"}
        assert all(m["value"] is None for m in report[name]["analyzed"].values())


def test_different_counting_grains_do_not_form_a_fake_monotone_funnel():
    report = family_diagnostics(
        {
            "bottleneck_features": {
                "interaction": {"message_intents": [], "effective_samples": {"human_messages": 0}},
                "respond": {"tool_sequence": []},
                "outcome": {
                    "validation_runs": [
                        {"session_uid": "s", "validation_uid": "v1"},
                        {"session_uid": "s", "validation_uid": "v2"},
                    ],
                    "validation_result_counts": {"failed": 1},
                    "effective_n": 1,
                },
            }
        }
    )
    objective = report["objective_outcome"]
    assert objective["input"]["calls"]["value"] == 0
    assert objective["analyzed"]["executed_checks"]["value"] == 2
    assert objective["analyzed"]["resolved_criteria"]["unit"] == "acceptance_criterion"
    assert objective["analyzed"]["executed_checks"]["unit"] == "validation_attempt"
    assert objective["evidence"]["count"] == 2


def test_unselected_skill_preserves_grounded_signal_and_pending_context():
    signal = {
        "signal_id": "sig",
        "rule_id": "tool_failures",
        "reason": "three failures",
        "metrics": [{"path": "respond.failure_count", "value": 3}],
        "evidence": [{"session_uid": "s", "id": "call"}],
    }
    result = {
        "status": "ready",
        "signals": [signal],
        "resource_assessments": [
            {
                "resource_id": "skill",
                "family": "skills",
                "name": "Skill",
                "status": "not_selected_after_ranking",
                "matched_signal_ids": ["sig"],
                "pending_requirements": ["tools:pytest"],
                "evaluated_candidates": 1,
                "reasons": ["ranking_limit_or_diversity"],
            }
        ],
    }
    report = diagnostics({}, result)
    item = report["skills"]["items"][0]
    assert item["selected_cards"] == 0
    assert item["pending_requirements"] == ["tools:pytest"]
    assert item["input_use"]["signal_ids"] == ["sig"]
    assert item["input_use"]["evidence"]["count"] == 1
    assert item["utility"]["observed_uplift"] is None
    assert item["utility"]["saved_tokens"] is None
    assert "three failures" in terminal_text(report)


def test_unknown_model_calls_count_invalid_rows_and_conflicting_request_ids():
    from pathlib import Path

    from orbit_backend.analytics.inputs import AnalysisInputBundle

    raw = json.loads((Path(__file__).parents[1] / "fixtures/bottleneck-features-v1.json")
                     .read_text(encoding="utf-8"))
    clean = analyze_bundle(AnalysisInputBundle.from_dict(copy.deepcopy(raw)), with_text=False)
    assert clean["unknown_counts"]["model_calls"] == 0  # both fixture rows are valid deltas
    good = raw["model_calls"][0]
    raw["model_calls"] += [
        {**good, "call_uid": None},                       # invalid: no request identity
        {**good, "call_uid": "cum", "measurement": "cumulative"},  # invalid: not a delta
        {**good, "call_uid": "dup"}, {**good, "call_uid": "dup", "output_tokens": 1},  # conflict
        {**good, "call_uid": "same"}, {**good, "call_uid": "same"},  # exact duplicate: known
    ]
    noisy = analyze_bundle(AnalysisInputBundle.from_dict(raw), with_text=False)
    assert noisy["unknown_counts"]["model_calls"] == 2 + 1
    raw["model_calls"] = None
    raw["coverage"]["model_calls"] = {"status": "unavailable"}
    absent = analyze_bundle(AnalysisInputBundle.from_dict(raw), with_text=False)
    assert absent["unknown_counts"]["model_calls"] is None
