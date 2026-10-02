"""Interaction vocabulary and lexical candidate rules."""

import re

from ...privacy import direct_user_text
from ..lexicon import correction_hits

CORRECTION = re.compile(r"(?:^|[，。！？；,;!\n]\s*)(?:不对(?:[，。！？；,;!\s]|$)|不是我说的|还是不行|我说的是|你理解错了|请?重新|请?改成|wrong\b|not what I meant\b|try again\b|instead\b)", re.I)

QUOTED = re.compile(r'“[^”]*”|"[^"\n]*"|`[^`]*`')


INTENTS = {"request", "clarification", "correction", "feedback", "other"}


FRICTIONS = {"understanding", "scope", "execution", "verification"}


EXECUTION_KINDS = {"message.assistant", "tool.call", "tool.result", "error",
                   "subagent.spawn", "subagent.result", "turn.interrupted"}


def correction_terms(text):
    # Quotes/examples have already been excluded by the existing prompt fence rules.
    text = direct_user_text(text)
    text = QUOTED.sub('', text)
    terms = [m.group(0).strip("，。！？；,;! \n") for m in CORRECTION.finditer(text)]
    # zh/en lexicon (repeat failure, change approach, not-what-asked, scope constraint, rework).
    return terms + [hit["term"] for hit in correction_hits(text) if hit["term"] not in terms]
