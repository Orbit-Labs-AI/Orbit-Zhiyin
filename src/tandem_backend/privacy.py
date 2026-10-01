"""Redact common secrets before persistence. This is a guard, not an anonymizer."""

import json
import re

from .content import fenced_parts

_PATTERNS = [
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
    if text.startswith(("# AGENTS.md", "<environment_context>", "<external_", "<permissions")):
        return ""
    if "<INSTRUCTIONS>" in text or text.startswith("<turn_aborted>"):
        return ""
    # Remove examples and quotations: a quoted complaint is not the speaker's complaint.
    text = "".join(part for fenced, part in fenced_parts(text) if not fenced)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))
    return redact(text.strip())
