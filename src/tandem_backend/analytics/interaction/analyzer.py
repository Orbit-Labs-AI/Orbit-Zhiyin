"""Human interaction signals and evidence-backed annotations."""

import re

from ...privacy import direct_user_text

CORRECTION = re.compile(r"(?:^|[，。！？；,;!\n]\s*)(?:不对(?:[，。！？；,;!\s]|$)|不是我说的|还是不行|我说的是|你理解错了|请?重新|请?改成|wrong\b|not what I meant\b|try again\b|instead\b)", re.I)


def correction_terms(text):
    # Quotes/examples have already been excluded by the existing prompt fence rules.
    text = direct_user_text(text)
    text = re.sub(r'“[^”]*”|"[^"\n]*"|`[^`]*`', '', text)
    return [m.group(0).strip("，。！？；,;! \n") for m in CORRECTION.finditer(text)]
