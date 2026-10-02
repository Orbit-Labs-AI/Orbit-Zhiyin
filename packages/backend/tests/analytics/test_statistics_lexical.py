"""Independent arithmetic oracles for full vocabulary, distributions and session-cluster inference."""

import math

import pytest

from tandem_backend.analytics.inputs import AnalysisInputBundle
from tandem_backend.analytics.products import build_products
from tandem_backend.analytics.products.lexical import compare_vocabulary, sentences
from tandem_backend.analytics.products.statistics import (
    bootstrap_difference,
    rank_association,
    summarize,
    wilson,
)


def corpus():
    sessions = [
        {
            "session_uid": sid,
            "root_uid": sid,
            "kind": "main",
            "source_id": "source",
            "project_id": "p" + sid,
        }
        for sid in ("a", "b")
    ]
    rows = [
        ("a", "apple apple banana。苹果 香蕉 苹果"),
        ("a", "banana carrot"),
        ("b", "apple carrot"),
    ]
    events = [
        {
            "event_uid": f"u{i}",
            "session_uid": sid,
            "turn_uid": f"t{i}",
            "seq": i,
            "kind": "message.user",
            "actor": "human",
            "ts": 1790812800000 + i * 1000,
            "text": text,
            "attrs": {"origin": "human"},
        }
        for i, (sid, text) in enumerate(rows)
    ]
    return AnalysisInputBundle(
        sessions,
        events,
        [],
        None,
        {
            "events": {"status": "available"},
            "tool_calls": {"status": "available"},
            "model_calls": {"status": "unavailable"},
        },
        projects=[],
        versions={"content_digest": "synthetic"},
    )


def test_real_word_counts_document_prevalence_phrases_and_groups():
    result = build_products(corpus())
    lexical = result["lexical"]
    rows = {row["term"]: row for row in lexical["terms"]}
    assert lexical["token_count"] == 10
    assert lexical["vocabulary_size"] == 5 and lexical["message_n"] == 3
    assert rows["apple"]["count"] == 3 and rows["apple"]["message_count"] == 2
    assert rows["apple"]["session_count"] == 2 and rows["apple"]["per_1000_tokens"] == 300
    assert rows["苹果"]["count"] == 2 and rows["香蕉"]["count"] == 1
    assert rows["apple"]["tfidf_mean"] == pytest.approx(
        ((2 / 6 + 1 / 2) / 3) * (math.log(4 / 3) + 1)
    )
    phrases = {row["term"]: row for row in lexical["phrases"]}
    assert phrases["apple apple banana"]["count"] == 1
    assert "banana 苹果" not in phrases
    assert len(lexical["documents"]) == 3
    assert lexical["similarity"]["status"] == "available"
    assert 0 < lexical["similarity"]["pairs"][0]["cosine_similarity"] < 1
    project_a = next(
        g for g in lexical["groups"] if g["dimension"] == "project_id" and g["group_id"] == "pa"
    )
    assert project_a["token_count"] == 8 and project_a["message_n"] == 2


def test_quoted_injected_and_truncated_text_preserve_evidence_boundaries():
    bundle = corpus()
    bundle.events[0]["text"] = "apple “privatequotedword”\n```\nsecretcodeword\n```"
    bundle.events[1]["attrs"]["origin"] = "injected"
    bundle.events[2]["text_truncated"] = True
    lexical = build_products(bundle)["lexical"]
    assert "privatequotedword" not in {row["term"] for row in lexical["terms"]}
    assert "secretcodeword" not in {row["term"] for row in lexical["terms"]}
    assert lexical["coverage"]["truncated_text"] == 1
    assert lexical["status"] == "partial"
    assert {row["event_uid"] for row in lexical["documents"]} == {"u0", "u2"}
    assert sentences("apple and banana")[0] == ["apple", "", "banana"]
    assert sentences("Apple. app.py don't")[0] == ["apple", "app.py", "don't"]


def test_distributions_and_outliers_match_arithmetic():
    rows = [
        {"sample_id": str(i), "session_uid": str(i), "value": value}
        for i, value in enumerate([1, 2, 3, 4, 10, None])
    ]
    result = summarize(rows, "ms", "tool_call")
    assert result["n"] == 5 and result["unknown_n"] == 1
    assert result["mean"] == 4 and result["median"] == 3
    assert result["stddev"] == pytest.approx(math.sqrt(12.5))
    assert result["quantiles"]["p90"] == pytest.approx(7.6)
    assert result["iqr"] == 2 and result["mad"] == 1
    assert result["outlier_sample_ids"] == ["4"]
    assert result["samples"] == rows
    assert summarize([], "ms", "tool_call")["mean"] is None
    assert wilson(5, 10) == pytest.approx([0.2365930905, 0.7634069095])


def test_bootstrap_resamples_sessions_and_preserves_pairing():
    previous = [{"session_uid": str(i), "value": i + 1} for i in range(5)]
    current = [{"session_uid": str(i), "value": i + 3} for i in range(5)]
    result = bootstrap_difference(current, previous)
    assert result["confidence_interval_95"] == pytest.approx([2, 2])
    assert result["shared_session_n"] == 5
    assert result == bootstrap_difference(current, previous)
    repeated_one_session = [{"session_uid": "only-one", "value": i} for i in range(100)]
    assert bootstrap_difference(repeated_one_session, previous)["status"] == "insufficient_sessions"


def test_vocabulary_comparison_normalizes_different_message_lengths():
    original = build_products(corpus())["lexical"]
    bundle = corpus()
    for row in bundle.events:
        row["text"] += " " + row["text"]
    doubled = build_products(bundle)["lexical"]
    result = compare_vocabulary(doubled, original)
    apple = next(r for r in result["rows"] if r["term"] == "apple")
    assert apple["current_count"] == 6 and apple["previous_count"] == 3
    assert apple["difference_per_1000_tokens"] == pytest.approx(0)


def test_rank_association_handles_monotonic_and_constant_inputs():
    first = [{"session_uid": str(i), "value": i} for i in range(6)]
    second = [{"session_uid": str(i), "value": 10 - i} for i in range(6)]
    assert rank_association(first, second)["rho"] == pytest.approx(-1)
    assert rank_association(first[:4], second[:4])["status"] == "insufficient_samples"
    constant = [{"session_uid": str(i), "value": 1} for i in range(6)]
    assert rank_association(first, constant)["status"] == "constant_input"
