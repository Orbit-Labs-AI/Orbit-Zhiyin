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


LANGUAGE_CASES = {"swift": "Swift", "kt": "Kotlin", "rb": "Ruby", "cs": "C#", "sql": "SQL",
                  "toml": "TOML", "php": "PHP", "lua": "Lua", "dart": "Dart", "tsx": "TypeScript",
                  "py": "Python", "h": "C/C++"}


def test_language_table_covers_common_extensions_and_matches_versions():
    from tandem_backend.analytics.features import LANG, LANGUAGE_TABLE_VERSION
    from tandem_backend.analytics.products.contracts import RULE_VERSIONS

    assert len(LANG) >= 60
    assert {ext: LANG[ext] for ext in LANGUAGE_CASES} == LANGUAGE_CASES
    assert RULE_VERSIONS["languages"] == LANGUAGE_TABLE_VERSION


def test_observed_languages_counts_known_extensions_and_reports_unknown_calls():
    from tandem_backend.analytics.products.summaries import observed_languages

    calls = [{"call_uid": f"c-{ext}", "files": [f"src/main.{ext}"]} for ext in LANGUAGE_CASES]
    calls += [{"call_uid": "c-unknown", "files": ["notes/readme.xyz", "Dockerfile"]},
              {"call_uid": "c-nofiles", "files": []},
              {"call_uid": "c-mixed", "files": [{"path": "App/View.swift"}, "a.unknownext"]}]
    result = observed_languages(calls)
    counts = {row["language"]: row["file_operation_count"] for row in result["rows"]}
    # One call per case; Swift gets a second file operation from c-mixed.
    expected = {language: 1 for language in LANGUAGE_CASES.values()}
    expected["Swift"] = 2
    assert counts == expected
    assert result["unknown_call_n"] == 2  # c-unknown and c-nofiles; c-mixed is measured
    assert result["status"] == "partial"


def test_session_language_signals_read_new_extensions_from_human_text():
    from tandem_backend.analytics.features import FILE_REFERENCE, session_features

    text = "改 Sources/App.swift 和 main.kt 以及 a.rb b.cs c.sql d.toml e.php f.lua g.dart，忽略 x.qqq"
    assert [m.lower() for m in FILE_REFERENCE.findall(text)] == [
        "swift", "kt", "rb", "cs", "sql", "toml", "php", "lua", "dart"]
    event = {"event_uid": "u1", "session_uid": "s", "kind": "message.user", "seq": 1,
             "ts": 1_790_000_000_000, "actor": "human", "text": text, "attrs": {"origin": "human"}}
    result = session_features({"session_uid": "s"}, [event], [], {"s"})
    signals = {row["extension"]: row["language"] for row in result["language_signals"]}
    assert signals == {"swift": "Swift", "kt": "Kotlin", "rb": "Ruby", "cs": "C#", "sql": "SQL",
                       "toml": "TOML", "php": "PHP", "lua": "Lua", "dart": "Dart"}


@pytest.mark.parametrize("text,expected", [
    ("한국어 테스트를 실행해", ["한국어", "테스트를", "실행해"]),          # Hangul eojeol
    ("Запусти тесты модуля", ["запусти", "тесты", "модуля"]),            # Cyrillic, casefolded
    ("テスト", ["テス", "スト"]),                                         # kana bigrams
])
def test_non_chinese_scripts_produce_tokens(text, expected):
    assert sentences(text) == [expected]


def test_out_of_dictionary_chinese_words_are_kept():
    from tandem_backend.analytics.products.lexical import tokenizer

    # "鉴权" and "竞态" are not words in jieba's bundled dictionary: dictionary-only cutting
    # splits them into single characters, which the length rule then discards.
    assert "鉴权" not in tokenizer().cut("鉴权", HMM=False)
    tokens = [t for clause in sentences("修复鉴权里的竞态问题") for t in clause if t]
    assert "鉴权" in tokens and "竞态" in tokens


def test_unsupported_scripts_are_counted_and_lower_coverage():
    bundle = corpus()
    bundle.events[1]["text"] = "สวัสดีครับ"  # Thai only: no tokens, counted as ignored
    bundle.events[2]["text"] = "한국어 테스트"
    lexical = build_products(bundle)["lexical"]
    assert lexical["unsupported_script_n"] == lexical["coverage"]["unsupported_script_n"] == 1
    assert lexical["status"] == lexical["coverage"]["status"] == "partial"
    assert "unsupported_script_text_ignored" in lexical["coverage"]["reasons"]
    documents = {row["event_uid"]: row for row in lexical["documents"]}
    assert documents["u1"]["token_count"] == 0 and documents["u1"]["unsupported_script_chars"] == 10
    assert documents["u2"]["token_count"] == 2


def test_lexical_rule_version_matches_module_version():
    from tandem_backend.analytics.products.contracts import RULE_VERSIONS
    from tandem_backend.analytics.products.lexical import LEXICAL_VERSION

    assert RULE_VERSIONS["lexical"] == LEXICAL_VERSION
