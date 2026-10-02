"""Dense fallback: signed feature hashing into 512 dims (no model, no download).

Used only when the catalog's E5 route is not ready. It approximates semantic
overlap via shared tokens and Chinese bigrams, which is enough to connect a
problem description to the few dozen local remedy texts.
"""

import math
from collections import Counter
from functools import lru_cache
from hashlib import blake2b

from .sparse import tokenize


class HashedEncoder:
    def __init__(self, dim: int = 512):
        self.dim = dim
        self._slots: dict[str, tuple[int, float]] = {}

    def _slot(self, token: str) -> tuple[int, float]:
        slot = self._slots.get(token)
        if slot is None:
            value = int.from_bytes(blake2b(token.encode(), digest_size=8).digest(), "little")
            slot = self._slots[token] = (value % self.dim, -1. if value >> 63 else 1.)
        return slot

    def encode(self, text: str) -> dict[int, float]:
        """Sparse L2-normalised vector {index: weight}; empty text gives {}."""
        vector: dict[int, float] = {}
        for token, tf in Counter(tokenize(text)).items():
            index, sign = self._slot(token)
            vector[index] = vector.get(index, 0.) + sign * (1 + math.log(tf))
        norm = math.sqrt(sum(value * value for value in vector.values()))
        return {index: value / norm for index, value in vector.items() if value} if norm else {}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(index, 0.) for index, value in a.items())


_ENCODER = HashedEncoder()


@lru_cache(maxsize=8192)
def _doc(text: str) -> dict[int, float]:
    """Corpus texts (KB rules, seeds) repeat across problems and runs; encode each once."""
    return _ENCODER.encode(text)


def rank(query: str, docs: dict[str, str], *, threshold: float = .15) -> list[tuple[str, float]]:
    """Cosine of each doc against the query, keeping scores >= threshold."""
    q = _ENCODER.encode(query)
    if not q:
        return []
    scored = [(uid, round(cosine(q, _doc(text)), 6)) for uid, text in docs.items()]
    return sorted(((uid, s) for uid, s in scored if s >= threshold), key=lambda row: (-row[1], row[0]))


def recall(problems: list[dict], rules, inputs: dict, memory: dict, legacy: tuple = ()) -> tuple[list, dict]:
    """Route 'dense': KB rules and legacy seeds by hashed cosine to each problem's description."""
    from .catalog_route import from_item
    from .kb_route import from_rule, rule_key

    muted = set(memory.get("muted_kb_rules") or ())
    rule_docs = {rule.id: " ".join([rule.title, rule.summary, *rule.tags, rule.explain.reason_template])
                 for rule in rules if rule.id not in muted and not rule.predicate
                 and rule.remedy.kind not in ("removal", "generate", "model")}
    by_id = {rule.id: rule for rule in rules}
    claimed = {type_ for rule in rules for type_ in rule.problem.types}
    items = {item["item_id"]: item for item in legacy}
    item_docs = {uid: item["text"] for uid, item in items.items()}
    best: dict[str, tuple[float, dict]] = {}
    for problem in problems:
        if problem["status"] not in ("active", "below_threshold"):
            continue
        query = " ".join([problem["reason"], problem["type"].replace("_", " "),
                          *(str(v) for v in problem["vars"].values() if isinstance(v, str))])
        for uid, score in rank(query, rule_docs):
            rule, prefix = by_id[uid], by_id[uid].problem.key_prefix
            # Cross-type matches only for problem types no rule claims; otherwise the KB is authoritative.
            if (problem["type"] in claimed and problem["type"] not in rule.problem.types) or (
                    prefix and not problem["key"].startswith(prefix)):
                continue
            key = rule_key(by_id[uid], problem)
            if score > best.get(key, (0, None))[0]:
                best[key] = (score, problem)
        for uid, score in rank(query, item_docs):
            key = "catalog:" + uid
            if score > best.get(key, (0, None))[0]:
                best[key] = (score, problem)
    rows, payload = [], {}
    for key, (score, problem) in sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0])):
        if key.startswith("kb:"):
            rule = by_id[key[3:].partition("@")[0]]
            payload[key] = from_rule(rule, problem, inputs, rec_key=key, match_basis="problem_rule")
        else:
            payload[key] = from_item(items[key[8:]], problem, inputs, match_basis="catalog_feature")
        rows.append((key, score))
    return rows, payload
