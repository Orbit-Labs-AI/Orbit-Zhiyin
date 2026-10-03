"""Interaction vocabulary and the single lexical correction verdict.

``correction_verdict`` is the only correction rule set in the backend: ``is_correction`` here,
``uiview.sessions.is_correction``, ``uiview.a4a6_sentiment.corrections``, ``ai.pack.is_correction``
and the ``signals`` correction/frustration detectors all reuse it. It separates

* ``correction`` — the user redirects the agent ("不对，应该改配置文件", "这个方向错了，先回滚再说",
  "没看懂，换个直观的例子", "No, revert that change");
* ``result_feedback`` — the user only reports the outcome of the agent's work
  ("还是不行，测试依然失败", "still failing with the same error"): friction, but not a redirect,
  so it does not count as a correction unless another rule also fires.

Lexical rules are candidates, not annotated ground truth; measured on the constructed sets in
``tests/ai/analysis/test_correction_labels.py`` and ``tests/analytics/test_lexicon_labelled.py``.
"""

import re

from ...privacy import direct_user_text
from ..lexicon import CORRECTION_EXTRA_HINT, RESULT_FEEDBACK_RULES, correction_hits

# Clause-initial markers ("try again" was dropped: alone it is a client retry, and "还是不行" now
# lives in the lexicon's result-feedback rule).
CORRECTION = re.compile(r"(?:^|[，。！？；,;!\n]\s*)(?:不对(?:[，。！？；,;!\s]|$)|不是我说的|我说的是|你理解错了|请?重新|请?改成|wrong\b|not what I meant\b|instead\b)", re.I)

QUOTED = re.compile(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"|`[^`]*`')

# Direct characters of a message that can be a correction (product default, not calibrated):
# 2 admits the commonest Chinese short rejections ("错了", "重来", "不对"); above 200 the message
# is a pasted spec/log/prompt where a lexical hit is mostly quoted or descriptive material
# (the former ``ai.pack.CORRECTION_MAX_CHARS`` used the same 200).
CORRECTION_CHARS = (2, 200)
# A bare client retry ("Try again", "continue") re-runs the turn; it does not push back.
CLIENT_RETRY = re.compile(r"^(?:try again|retry|continue|please continue|go on|keep going)[.!。！]?$", re.I)
# Every term the verdict can return contains one of these substrings (cheap prefilter; the
# verdict parses markdown, ~0.3 ms per message). ``test_lexicon_labelled`` guards the superset.
CORRECTION_HINT = re.compile(
    r"不对|不是我说的|我说的是|你理解错了|重新|改成|wrong|not what I meant|instead", re.I)


INTENTS = {"request", "clarification", "correction", "feedback", "other"}


FRICTIONS = {"understanding", "scope", "execution", "verification"}


EXECUTION_KINDS = {"message.assistant", "tool.call", "tool.result", "error",
                   "subagent.spawn", "subagent.result", "turn.interrupted"}


def correction_verdict(text) -> dict:
    """``{"kind": "correction" | "result_feedback" | None, "hits": [{"rule", "term"}]}``.

    Quotes/examples are excluded (``direct_user_text`` fences, inline quotes, hypothetical
    clauses in the lexicon). No length gate here; ``is_correction`` adds it.
    """
    text = QUOTED.sub('', direct_user_text(text or ""))
    hits = [{"rule": "clause_marker", "term": m.group(0).strip("，。！？；,;! \n")}
            for m in CORRECTION.finditer(text)]
    hits += correction_hits(text)
    if not hits:
        return {"kind": None, "hits": []}
    feedback_only = all(h["rule"] in RESULT_FEEDBACK_RULES for h in hits)
    return {"kind": "result_feedback" if feedback_only else "correction", "hits": hits}


def verdict_terms(verdict: dict) -> list[str]:
    """Distinct terms of a verdict's hits, in match order."""
    terms: list[str] = []
    for hit in verdict["hits"]:
        if hit["term"] not in terms:
            terms.append(hit["term"])
    return terms


def correction_terms(text) -> list[str]:
    """Distinct correction terms; empty for result feedback alone or no hit (no length gate)."""
    verdict = correction_verdict(text)
    return verdict_terms(verdict) if verdict["kind"] == "correction" else []


def result_feedback_terms(text) -> list[str]:
    """Terms of a message that only reports the agent's result ("还是不行，测试依然失败")."""
    verdict = correction_verdict(text)
    return verdict_terms(verdict) if verdict["kind"] == "result_feedback" else []


def correction_kind(text) -> str | None:
    """``correction`` / ``result_feedback`` / ``None`` for one human message, with the length and
    client-retry gates of ``is_correction``."""
    if not text or not (CORRECTION_HINT.search(text) or CORRECTION_EXTRA_HINT.search(text)):
        return None
    direct = direct_user_text(text).strip()
    if not CORRECTION_CHARS[0] <= len(direct) <= CORRECTION_CHARS[1] or CLIENT_RETRY.match(direct):
        return None
    return correction_verdict(text)["kind"]


def is_correction(text) -> bool:
    """A human message that redirects the agent (result feedback alone does not count)."""
    return correction_kind(text) == "correction"
