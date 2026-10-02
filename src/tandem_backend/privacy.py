"""Redact common secrets before persistence. This is a guard, not an anonymizer."""

import json
import re

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark")
PLATFORM_TAGS = ('recommended_plugins', 'skills_instructions', 'environment_context',
                 'permissions', 'collaboration_mode', 'multi_agent_role', 'multi_agent_mode', 'app-context', 'INSTRUCTIONS')


def without_platform_blocks(text: str) -> str:
    """Remove known native metadata blocks, preserving requests outside them.

    Tags must start a source line. A literal inline reference is not metadata;
    a cut-off native block stays excluded because its boundary is unavailable.
    """
    for tag in PLATFORM_TAGS:
        opening = r'(?m)^[ \t]*<' + re.escape(tag) + r'(?=[\s>])[^>]*>'
        closing = r'</' + re.escape(tag) + r'(?:\s+[^>]*)?>'
        text = re.sub(opening + r'[\s\S]*?' + closing, '', text)
        unfinished = re.search(opening, text)
        if unfinished:
            text = text[:unfinished.start()]
    return text.strip()

_PATTERNS = [
    (r'''(?i)((?:["']?)(?:api[_-]?key|access[_-]?token|password|secret)(?:["']?)\s*[=:]\s*)(["'])(?:\\.|(?!\2)[^\\\r\n])+\2''', r'\1\2[密钥已隐藏]\2'),
    (r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{15,}|github_pat_[A-Za-z0-9_]{15,})", "[密钥已隐藏]"),
    (r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{12,}", r"\1[密钥已隐藏]"),
    (r"(?i)((?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*)[^\s,;\"']{8,}", r"\1[密钥已隐藏]"),
    (r"(?<=://)[^/@\s:]+:[^/@\s]+@", "[认证已隐藏]@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def direct_user_text(text: str) -> str:
    """Separate native prompt wrappers from the actual request, conservatively.

    Attachments, instructions, and quotes are data, not user preference observations.
    We deliberately do not evaluate imported executable text.
    """
    text = text.strip()
    if text.startswith("The following is the Codex agent history"):
        return ""
    if text.startswith("<send_user_message_question_reply>"):
        # The desktop callback repeats the assistant's questions. Only answer
        # fields are human observations; neither questions nor item IDs are.
        wrapper = re.fullmatch(r"<send_user_message_question_reply>\s*([\s\S]*?)\s*</send_user_message_question_reply>", text)
        if not wrapper:
            return ""
        try:
            replies = json.loads(wrapper[1])
        except (ValueError, TypeError):
            return ""
        if not isinstance(replies, list) or not all(isinstance(reply, dict) for reply in replies):
            return ""
        text = "\n".join(reply["answer"].strip() for reply in replies
                         if isinstance(reply.get("answer"), str)).strip()
    if "## My request:" in text:
        text = text.split("## My request:", 1)[1].strip()
    # Remove examples and quotations: a quoted complaint is not the speaker's complaint.
    # CommonMark distinguishes quoted code from indented list paragraphs. Only
    # parse block structure: never render HTML, open links or execute code.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    quoted_lines = set()
    for token in _MARKDOWN.parse(text):
        if token.type in ("fence", "code_block", "blockquote_open") and token.map:
            quoted_lines.update(range(*token.map))
    text = "\n".join(line for index, line in enumerate(text.split("\n")) if index not in quoted_lines)
    text = without_platform_blocks(text)
    if text.startswith(("# AGENTS.md", "<external_")):
        return ""
    if text.startswith("<turn_aborted>"):
        return ""
    return redact(text.strip())
