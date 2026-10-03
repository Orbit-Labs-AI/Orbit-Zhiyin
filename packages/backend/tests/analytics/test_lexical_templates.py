"""a4a6-B11: a templated message repeated by an automation loop must not dominate phrases."""

from orbit_backend.analytics.inputs import AnalysisInputBundle
from orbit_backend.analytics.products import build_products

TEMPLATE = (
    "please run the nightly benchmark suite collect latency numbers compare against "
    "baseline report regressions summarise flaky cases archive artifacts notify owners"
)
HABITS = ["fix failing login test", "update readme section", "refactor config loader"]


def bundle():
    sessions, events = [], []
    for s in range(20):
        sid = f"s{s}"
        sessions.append({"session_uid": sid, "root_uid": sid, "kind": "main",
                         "source_id": "src", "project_id": "p"})
        texts = [TEMPLATE] * 25 + [HABITS[s % 3], "check build output"]
        for i, text in enumerate(texts):
            events.append({"event_uid": f"{sid}-{i}", "session_uid": sid, "turn_uid": f"{sid}-t{i}",
                           "seq": i, "kind": "message.user", "actor": "human",
                           "ts": 1790812800000 + s * 100_000 + i * 1000, "text": text,
                           "attrs": {"origin": "human"}})
    return AnalysisInputBundle(
        sessions, events, [], None,
        {"events": {"status": "available"}, "tool_calls": {"status": "available"},
         "model_calls": {"status": "unavailable"}},
        projects=[], versions={"content_digest": "synthetic-b11"})


def test_template_counts_once_and_cross_session_phrases_rank_first():
    lexical = build_products(bundle())["lexical"]
    phrases = lexical["phrases"]
    top = phrases[0]
    assert top["term"] == "check build output"
    assert top["session_count"] == 20
    template_terms = [p for p in phrases if p["term"] in TEMPLATE]
    assert template_terms and all(p["count"] == 1 and p["session_count"] == 1 for p in template_terms)
    assert len(lexical["templates"]) == 1
    assert lexical["templates"][0]["message_n"] == 500
    assert lexical["templates"][0]["session_n"] == 20
    assert len(lexical["templates"][0]["event_uids"]) <= 20


def test_phrase_evidence_is_capped_and_overlapping_ngrams_collapse():
    lexical = build_products(bundle())["lexical"]
    for row in lexical["phrases"]:
        assert len(row["evidence"]) <= 20
        assert row["evidence_n"] == row["message_count"]
    terms = {row["term"] for row in lexical["phrases"]}
    # "build output" never occurs outside "check build output": only the longer phrase is listed.
    assert "check build output" in terms and "build output" not in terms
    assert lexical["phrase_method"]["subsumed_phrase_n"] > 0
    # word evidence stays complete so word accounting still validates
    assert all(sum(e["count"] for e in r["evidence"]) == r["count"] for r in lexical["terms"])
