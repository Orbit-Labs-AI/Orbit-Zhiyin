"""Real token, phrase, co-occurrence and similarity measurements over eligible human text."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from itertools import combinations
from typing import Any
from zoneinfo import ZoneInfo

import jieba

from ..common import semantic_coverage, semantic_messages
from ..context import AnalysisContext
from .feedback import calendar_key

Record = dict[str, Any]
LEXICAL_VERSION = "lexical-v2"
# A long message repeated verbatim this often is a template (automation loop, pasted
# boilerplate); its phrases count once in total instead of once per copy.
TEMPLATE_MIN_COPIES = 3
TEMPLATE_MIN_TOKENS = 12
EVIDENCE_LIMIT = 20
STOPWORDS = frozenset(
    "的 了 和 是 在 我 你 他 她 它 我们 你们 他们 请 一个 这个 那个 这些 那些 一下 以及 然后 可以 进行 需要 当前 the a an and or to of in on for is are be it this that with as i you we please".split()
)
NEGATIONS = frozenset(("不", "无", "没"))
REDACTED = re.compile(r"\[(?:REDACTED[^\]]*|redacted[^\]]*|hidden[^\]]*)\]|<redacted[^>]*>", re.I)
BOUNDARY = re.compile(r"[，,。！？!?；;：:\n\r()（）\[\]{}]+")
PIECE = re.compile(r"[\u3400-\u9fff]+|[a-zA-Z][a-zA-Z0-9_+.#'-]*")


@lru_cache(maxsize=1)
def tokenizer() -> jieba.Tokenizer:
    """Use a private, fixed dictionary without learning words from user messages."""
    jieba.setLogLevel(30)
    instance = jieba.Tokenizer()
    instance.initialize()
    return instance


@lru_cache(maxsize=1)
def dictionary_digest() -> str:
    """Pin the actual bundled segmentation dictionary in every result's method metadata."""
    with tokenizer().get_dict_file() as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def sentences(text: str) -> list[list[str]]:
    """Segment Chinese and preserve technical Latin words; punctuation remains a phrase boundary."""
    normalized = unicodedata.normalize("NFKC", REDACTED.sub(" ", text)).casefold()
    result = []
    for clause in BOUNDARY.split(normalized):
        tokens = []
        for piece in PIECE.findall(clause):
            piece = piece.strip(".-'")
            words = (
                tokenizer().cut(piece, HMM=False)
                if re.search(r"[\u3400-\u9fff]", piece)
                else [piece]
            )
            for word in words:
                if word in STOPWORDS or len(word) < 2 and word not in NEGATIONS:
                    # A removed token breaks adjacency; phrases do not jump across stopwords.
                    tokens.append("")
                else:
                    tokens.append(word)
        if tokens:
            result.append(tokens)
    return result


def normalized_key(text: str) -> str:
    """Whitespace and case do not make a templated message a different message."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def documents(context: AnalysisContext) -> tuple[list[Record], Record]:
    """Keep full per-message term counts and evidence IDs, not another copy of raw message text."""
    messages = semantic_messages(context.events, context.sessions)
    coverage = semantic_coverage(
        context.events if context.bundle.events is not None else None, messages
    )
    zone = ZoneInfo(context.scope.display_timezone)
    rows = []
    for event in messages:
        segments = sentences(event["semantic_text"])
        terms = Counter(term for segment in segments for term in segment if term)
        phrases = Counter()
        for segment in segments:
            for size in (2, 3):
                for index in range(len(segment) - size + 1):
                    words = segment[index : index + size]
                    if all(words):
                        phrases[" ".join(words)] += 1
        session = context.session_map[event["session_uid"]]
        rows.append(
            {
                "event_uid": event["event_uid"],
                "session_uid": event["session_uid"],
                "project_id": session.get("project_id"),
                "source_id": session.get("source_id"),
                "day": calendar_key(event.get("ts"), zone),
                "token_count": terms.total(),
                "term_counts": dict(sorted(terms.items())),
                "phrase_counts": dict(sorted(phrases.items())),
                "text_truncated": bool(event.get("text_truncated")),
                "normalized_text_sha256": hashlib.sha256(
                    normalized_key(event["semantic_text"]).encode()
                ).hexdigest(),
                "text_available": bool(event["semantic_text"]),
            }
        )
    return rows, coverage


def frequency(
    rows: list[Record], field: str = "term_counts", *, evidence_limit: int | None = None
) -> Record:
    """Measure occurrence count, message prevalence and session prevalence separately.

    ``evidence_limit`` keeps only the first N evidence refs; ``evidence_n`` stays exact.
    """
    counts, evidence, sessions_by_term, normalized_tf = (
        Counter(),
        defaultdict(list),
        defaultdict(set),
        Counter(),
    )
    eligible = [row for row in rows if row["token_count"] > 0]
    total_tokens = sum(row["token_count"] for row in eligible)
    session_ids = {row["session_uid"] for row in eligible}
    for row in eligible:
        for term, count in row[field].items():
            counts[term] += count
            evidence[term].append(
                {"event_uid": row["event_uid"], "session_uid": row["session_uid"], "count": count}
            )
            sessions_by_term[term].add(row["session_uid"])
            normalized_tf[term] += count / row["token_count"]
    terms = []
    for term, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])):
        document_n = len(evidence[term])
        idf = math.log((1 + len(eligible)) / (1 + document_n)) + 1
        terms.append(
            {
                "term": term,
                "count": count,
                "message_count": document_n,
                "session_count": len(sessions_by_term[term]),
                "per_1000_tokens": 1000 * count / total_tokens,
                "message_prevalence": document_n / len(eligible),
                "session_prevalence": len(sessions_by_term[term]) / len(session_ids),
                "tfidf_mean": normalized_tf[term] * idf / len(eligible),
                "evidence": evidence[term][:evidence_limit]
                if evidence_limit is not None
                else evidence[term],
            }
        )
        if evidence_limit is not None:
            terms[-1]["evidence_n"] = document_n
            terms[-1]["evidence_truncated"] = document_n > evidence_limit
    return {
        "token_count": total_tokens,
        "message_n": len(eligible),
        "session_n": len(session_ids),
        "vocabulary_size": len(terms),
        "rows": terms,
    }


def template_hashes(rows: list[Record]) -> dict[str, list[Record]]:
    """Long messages repeated verbatim (normalized) at least ``TEMPLATE_MIN_COPIES`` times."""
    groups = defaultdict(list)
    for row in rows:
        if row["text_available"] and not row["text_truncated"]:
            groups[row["normalized_text_sha256"]].append(row)
    return {
        key: items
        for key, items in groups.items()
        if len(items) >= TEMPLATE_MIN_COPIES and items[0]["token_count"] >= TEMPLATE_MIN_TOKENS
    }


def phrase_documents(rows: list[Record], templates: dict[str, list[Record]]) -> list[Record]:
    """One copy per template overall and one copy per repeated message per session."""
    seen, out = set(), []
    for row in rows:
        digest = row["normalized_text_sha256"]
        key = digest if digest in templates else (row["session_uid"], digest)
        if row["text_available"] and not row["text_truncated"]:
            if key in seen:
                continue
            seen.add(key)
        out.append(row)
    return out


def rank_phrases(rows: list[Record]) -> tuple[list[Record], int]:
    """Rank by session spread, then drop n-grams that never occur outside a longer phrase."""
    by_term = {row["term"]: row for row in rows}
    subsumed = set()
    for row in rows:
        words = row["term"].split(" ")
        for size in range(2, len(words)):
            for index in range(len(words) - size + 1):
                part = by_term.get(" ".join(words[index : index + size]))
                if part is not None and part["message_count"] == row["message_count"]:
                    subsumed.add(part["term"])
    kept = [row for row in rows if row["term"] not in subsumed]
    kept.sort(
        key=lambda row: (-row["session_count"], -row["message_count"], -row["count"], row["term"])
    )
    return kept, len(subsumed)


def cooccurrences(rows: list[Record], terms: list[Record], *, top_n: int = 40) -> Record:
    """Count message-level co-occurrence over an explicitly declared vocabulary subset."""
    vocabulary = {row["term"] for row in terms[:top_n]}
    eligible = [row for row in rows if row["token_count"]]
    term_df = {row["term"]: row["message_count"] for row in terms}
    evidence = defaultdict(list)
    for row in eligible:
        for pair in combinations(sorted(vocabulary & row["term_counts"].keys()), 2):
            evidence[pair].append(row["event_uid"])
    pairs = []
    for (first, second), ids in sorted(evidence.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        joint = len(ids) / len(eligible)
        pmi = math.log2(len(ids) * len(eligible) / (term_df[first] * term_df[second]))
        pairs.append(
            {
                "first": first,
                "second": second,
                "message_count": len(ids),
                "pmi": pmi if len(ids) >= 3 else None,
                "npmi": pmi / -math.log2(joint) if len(ids) >= 3 and joint < 1 else None,
                "evidence_event_uids": ids,
            }
        )
    return {
        "vocabulary_limit": top_n,
        "vocabulary": sorted(vocabulary),
        "message_n": len(eligible),
        "rows": pairs,
        "minimum_pair_messages_for_pmi": 3,
        "meaning": "same-message association; PMI is suppressed for fewer than three supporting messages",
    }


def text_similarity(rows: list[Record], *, max_sessions: int = 2000, neighbors: int = 3) -> Record:
    """Find local TF-IDF cosine neighbors; similarity never establishes shared task identity."""
    import numpy as np
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.feature_extraction.text import TfidfTransformer
    from sklearn.neighbors import NearestNeighbors

    groups = defaultdict(Counter)
    for row in rows:
        if row["token_count"]:
            groups[row["session_uid"]].update(row["term_counts"])
    ids = sorted(groups)
    if len(ids) < 2 or len(ids) > max_sessions:
        return {
            "status": "insufficient_samples" if len(ids) < 2 else "limit_exceeded",
            "session_n": len(ids),
            "max_sessions": max_sessions,
            "pairs": None,
        }
    matrix = DictVectorizer().fit_transform([dict(groups[sid]) for sid in ids])
    matrix = TfidfTransformer(sublinear_tf=True).fit_transform(matrix)
    distances, indices = (
        NearestNeighbors(
            n_neighbors=min(len(ids), neighbors + 1), metric="cosine", algorithm="brute"
        )
        .fit(matrix)
        .kneighbors(matrix)
    )
    pairs = {}
    for index, (ds, ns) in enumerate(zip(distances, indices, strict=False)):
        chosen = 0
        for distance, other in zip(ds, ns, strict=False):
            if index == other:
                continue
            if chosen == neighbors:
                break
            chosen += 1
            pair = tuple(sorted((ids[index], ids[other])))
            pairs[pair] = float(np.clip(1 - distance, 0, 1))
    return {
        "status": "available",
        "session_n": len(ids),
        "neighbors_per_session": neighbors,
        "pairs": [
            {"first_session_uid": a, "second_session_uid": b, "cosine_similarity": value}
            for (a, b), value in sorted(pairs.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        "meaning": "word TF-IDF cosine, local nearest neighbors rather than semantic equivalence",
    }


def lexical_analysis(context: AnalysisContext) -> Record:
    """Compute full frequencies and audit records; UI top-N limits never truncate the stored vocabulary."""
    if context.bundle.events is None:
        return {
            "status": context.event_status,
            "terms": None,
            "phrases": None,
            "documents": None,
            "groups": None,
            "by_day": None,
            "cooccurrence": None,
            "similarity": None,
        }
    rows, coverage = documents(context)
    templates = template_hashes(rows)
    terms = frequency(rows)
    phrases = frequency(
        phrase_documents(rows, templates), "phrase_counts", evidence_limit=EVIDENCE_LIMIT
    )
    phrase_rows, subsumed_n = rank_phrases(phrases["rows"])
    groups = []
    for field in ("project_id", "source_id"):
        selected = defaultdict(list)
        for row in rows:
            selected[row[field]].append(row)
        groups.extend(
            {"dimension": field, "group_id": key, **frequency(items)}
            for key, items in sorted(selected.items(), key=lambda pair: str(pair[0]))
        )
    days, duplicate_ids = defaultdict(list), defaultdict(list)
    for row in rows:
        if row["day"] is not None:
            days[row["day"]].append(row)
        if row["text_available"] and not row["text_truncated"]:
            duplicate_ids[row["normalized_text_sha256"]].append(row["event_uid"])
    return {
        "status": coverage["status"],
        "version": LEXICAL_VERSION,
        "coverage": coverage,
        "method": {
            "tokenizer": "jieba-0.42.1",
            "dictionary_sha256": dictionary_digest(),
            "hmm": False,
            "normalization": "NFKC+casefold",
            "stopwords_version": "stopwords-v1",
            "stopwords": sorted(STOPWORDS),
            "scope": "confirmed main-session human text, with quotations and code removed",
            "tfidf": "mean(message term count / message tokens) * (log((1+messages)/(1+document_frequency))+1)",
        },
        "token_count": terms["token_count"],
        "message_n": terms["message_n"],
        "session_n": terms["session_n"],
        "vocabulary_size": terms["vocabulary_size"],
        "zero_token_message_n": sum(row["token_count"] == 0 for row in rows),
        "terms": terms["rows"],
        "phrases": phrase_rows,
        "phrase_method": {
            "ranking": "session_count, message_count, count",
            "template_rule": f">={TEMPLATE_MIN_COPIES} identical normalized messages of "
            f">={TEMPLATE_MIN_TOKENS} tokens count once; other repeats count once per session",
            "subsumed_phrase_n": subsumed_n,
            "evidence_limit": EVIDENCE_LIMIT,
        },
        "templates": [
            {
                "normalized_text_sha256": key,
                "message_n": len(items),
                "session_n": len({row["session_uid"] for row in items}),
                "token_count": items[0]["token_count"],
                "event_uids": [row["event_uid"] for row in items[:EVIDENCE_LIMIT]],
            }
            for key, items in sorted(templates.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        ],
        "documents": rows,
        "groups": groups,
        "by_day": [{"day": day, **frequency(items)} for day, items in sorted(days.items())],
        "time_unknown_message_n": sum(row["day"] is None for row in rows),
        "exact_repetitions": [
            {"normalized_text_sha256": key, "event_uids": ids, "message_n": len(ids)}
            for key, ids in sorted(duplicate_ids.items())
            if len(ids) > 1
        ],
        "cooccurrence": cooccurrences(rows, terms["rows"]),
        "similarity": text_similarity(rows),
    }


def compare_vocabulary(current: Record, previous: Record) -> Record:
    """Compare normalized frequencies and prevalence, retaining zero and unknown denominators."""
    if current["terms"] is None or previous["terms"] is None:
        return {"status": "unavailable", "rows": None}
    left = {r["term"]: r for r in current["terms"]}
    right = {r["term"]: r for r in previous["terms"]}
    rows = []
    for term in sorted(left.keys() | right.keys()):
        a, b = left.get(term, {}), right.get(term, {})
        a_rate = a.get("per_1000_tokens", 0) if current["token_count"] else None
        b_rate = b.get("per_1000_tokens", 0) if previous["token_count"] else None
        rows.append(
            {
                "term": term,
                "current_count": a.get("count", 0),
                "previous_count": b.get("count", 0),
                "current_per_1000_tokens": a_rate,
                "previous_per_1000_tokens": b_rate,
                "difference_per_1000_tokens": a_rate - b_rate
                if a_rate is not None and b_rate is not None
                else None,
                "current_session_count": a.get("session_count", 0),
                "previous_session_count": b.get("session_count", 0),
            }
        )
    return {
        "status": "available",
        "current_message_n": current["message_n"],
        "previous_message_n": previous["message_n"],
        "rows": rows,
        "meaning": "descriptive vocabulary change; different task mixes can change word frequency",
    }
