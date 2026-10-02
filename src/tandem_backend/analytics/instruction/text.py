"""Instruction-specific normalization, shared by counts and constraint extraction."""

import re

from ...privacy import direct_user_text


def instruction_text(text):
    """Normalize wrappers and remove quotations; keep inline file/tool identifiers."""
    text = direct_user_text(text or "")
    text = re.sub(r'“[^”]*”|‘[^’]*’|"[^"\n]*"', "", text)
    text = re.sub(r"\x60([^\x60\n]*)\x60",
                  lambda m: m[1] if re.fullmatch(r"[A-Za-z0-9_./@~:+-]+", m[1]) else "", text)
    return text.strip()

