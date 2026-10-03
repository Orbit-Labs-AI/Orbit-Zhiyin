"""Observable prompt structure for the Instruction feature family."""

import re
from functools import cache

from ...privacy import _MARKDOWN
from .text import instruction_text

CONSTRAINT = re.compile(r"必须|不要|只能|要求|\b(?:must|do not|don't|only|require)\b", re.I)


# File mentions that are not a programming/markup language in ``features.LANG`` but are
# still files a prompt points at.
NON_LANGUAGE_FILE_EXTENSIONS = ("txt", "log")


@cache
def file_pattern() -> re.Pattern:
    """A path-like token ending in a ``features.LANG`` extension (the session family's
    ``FILE_REFERENCE`` table, Linguist-named) or a ``NON_LANGUAGE_FILE_EXTENSIONS`` one.

    Built lazily: ``analytics.features`` imports this module."""
    from ..features import LANG

    extensions = sorted({*LANG, *NON_LANGUAGE_FILE_EXTENSIONS}, key=lambda e: (-len(e), e))
    return re.compile(r"(?<![\w.])(?:[\w@~-]+/)*[\w.-]+\.(" + "|".join(extensions) + r")\b", re.I)


def code_block_count(raw: str, direct: str, attrs: dict) -> int | None:
    """Fenced + indented CommonMark code blocks the user wrote (the material ``direct_user_text``
    removes before every other count). ``None`` when the importer already dropped fences
    (legacy store, ``attrs.fences_removed``); 0 when nothing of the message is the user's."""
    if attrs.get("fences_removed"):
        return None
    if not direct:
        return 0
    if "## My request:" in raw:
        raw = raw.split("## My request:", 1)[1]
    return sum(token.type in ("fence", "code_block") for token in _MARKDOWN.parse(raw))


def structure(e):
    raw = e.get("text")
    if raw is None:
        return None
    text = instruction_text(raw)
    attrs = e.get("attrs", {})
    original = attrs.get("original_chars")
    valid_original = isinstance(original, int) and not isinstance(original, bool) and original >= len(text)
    out = {"prompt_char_count": original if valid_original else len(text),
           "prompt_line_count": len(text.splitlines()) if text else 0,
           "paragraph_count": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
           "question_mark_count": len(re.findall(r"[?？]", text)),
           "bullet_count": len(re.findall(r"(?m)^\s*[-*+]\s+", text)),
           "numbered_list_count": len(re.findall(r"(?m)^\s*\d+[.)、]\s*", text)),
           "code_block_count": code_block_count(raw, text, attrs),
           "url_count": len(re.findall(r"https?://[^\s<>]+", text)),
           "file_reference_count": len(file_pattern().findall(text)),
           "explicit_format_request_count": len(re.findall(r"(?:请|用|输出为|写成).{0,8}(?:表格|列表|JSON|Markdown|分点)", text, re.I)),
           "explicit_tool_mention_count": len(re.findall(r"(?:使用|调用|用)\s*`?[\w.]*?(?:MCP|工具|skill|pytest|git|bash)\b", text, re.I)),
           "constraint_marker_count": len(CONSTRAINT.findall(text))}
    # Only known numeric measurements may be supplied by a canonical source.
    supplied = attrs.get("prompt_structure")
    if isinstance(supplied, dict):
        for key, value in supplied.items():
            if key in out and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                out[key] = value
    out["constraint_density"] = (out["constraint_marker_count"] / len(text) if text else None)
    out["quality"] = "lower_bound" if e.get("text_truncated") else "normalized_text"
    out["event_uid"] = e["event_uid"]
    return out

