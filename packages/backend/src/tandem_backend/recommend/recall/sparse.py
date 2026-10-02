"""Dependency-free BM25 for technical keywords and short Chinese phrases."""

import math
import re
import unicodedata
from collections import Counter

from ..contracts import RecommendationItem, RecommendationState
from ._common import ranked

_PARTS = re.compile(r"[a-z0-9_]+(?:[./-][a-z0-9_]+)*[+#]*|[\u3400-\u4dbf\u4e00-\u9fff]+")
_CJK = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")


def tokenize(text: str) -> list[str]:
    """Casefold Latin technical names; use overlapping Chinese bigrams.

    Punctuation-bearing names (e.g. C++, C#, pytest-xdist) stay intact.
    Compound path/package names additionally expose meaningful components.
    Chinese bigrams avoid requiring a dictionary while not matching every
    document containing one common character. A one-character query remains
    searchable only when the catalogue also contains that standalone token.
    """
    tokens: list[str] = []
    for part in _PARTS.findall(unicodedata.normalize("NFKC", text).casefold()):
        if _CJK.fullmatch(part):
            tokens.extend(part[index:index + 2] for index in range(len(part) - 1)) \
                if len(part) > 1 else tokens.append(part)
        else:
            tokens.append(part)
            components = re.split(r"[./_-]+", part)
            if len(components) > 1:
                tokens.extend(component for component in components if len(component) > 1)
    return tokens


def item_text(item: RecommendationItem) -> str:
    """Search curated intervention descriptions, not unreviewed source content."""
    blocks = (item.target_task, item.trigger, item.capability)
    return " ".join([item.identity.name, *(
        text for block in blocks for text in (block.text, *block.tags)
    )])


def recall(state: RecommendationState, items: list[RecommendationItem],
           limit: int = 50, *, k1: float = 1.2, b: float = .75) -> list[tuple[str, float]]:
    """Retrieve with positive-IDF BM25; duplicate query terms do not inflate rank.

    idf = log(1 + (N - df + .5) / (df + .5)); term contribution is
    idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_length)).
    Corpus statistics include empty descriptions and are local to this call.
    """
    if (isinstance(k1, bool) or not isinstance(k1, (int, float)) or not math.isfinite(k1)
            or k1 <= 0 or isinstance(b, bool) or not isinstance(b, (int, float))
            or not math.isfinite(b) or not 0 <= b <= 1):
        raise ValueError("BM25 requires finite k1 > 0 and 0 <= b <= 1")
    query = set(tokenize(" ".join((state.task_text, state.problem_text, state.desired_effect_text))))
    # The catalogue normally rejects duplicates. Keep the first if this lower
    # level is used directly so duplicates cannot change corpus frequencies.
    documents: dict[str, Counter] = {}
    for item in items:
        if item.identity.id not in documents:
            documents[item.identity.id] = Counter(tokenize(item_text(item)))
    scores: dict[str, float] = {}
    if not query or not documents:
        return ranked(scores, limit)
    count = len(documents)
    lengths = {uid: sum(tokens.values()) for uid, tokens in documents.items()}
    average = sum(lengths.values()) / count
    if not average:
        return ranked(scores, limit)
    frequency: Counter = Counter(term for doc in documents.values() for term in doc)
    for uid, document in documents.items():
        score = 0.
        norm = k1 * (1 - b + b * lengths[uid] / average)
        for term in sorted(query & document.keys()):
            term_frequency = document[term]
            idf = math.log1p((count - frequency[term] + .5) / (frequency[term] + .5))
            score += idf * term_frequency * (k1 + 1) / (term_frequency + norm)
        scores[uid] = score
    return ranked(scores, limit)
