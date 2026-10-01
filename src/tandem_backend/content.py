"""Measure a requested writing surface without treating required detail as overload.

These measurements are explicit formatting checks. They do not grade mathematical
correctness, emotional tone, or whether the reader actually understands a passage.
"""

import re


def length_contract(text: str, start: int, end: int) -> dict:
    """A local brevity requirement can constrain the abstract instead of the full reply."""
    boundaries = "，,。；;\n"
    left = max(text.rfind(c, 0, start) for c in boundaries) + 1
    ends = [text.find(c, end) for c in boundaries if text.find(c, end) >= 0]
    right = min(ends) if ends else len(text)
    clause = text[left:right]
    summary = bool(re.search(r"摘要|总结|概要|概述|开头|首段|首层", clause))
    # Search the requirement clause, not incidental numeric facts in another clause.
    cap = re.search(r"(\d+)\s*(?:字|字符)\s*(?:以内|内|以下)|(?:不超过|最多|控制在|限于|限制为)\s*(\d+)\s*(?:字|字符)", clause)
    return {"surface": "summary" if summary else "reply",
            "char_limit": int(cap[1] or cap[2]) if cap else None,
            "requires_full_body": bool(re.search(r"(?:完整|详细).{0,8}(?:证明|推导|正文)|(?:证明|推导|正文).{0,8}(?:完整|详细)|不省略(?:条件|步骤)", text)),
            "basis": "explicit_request"}


def visible_text(text: str) -> tuple[str, str]:
    """Exclude balanced expandable details and link destinations from the first layer."""
    # An unmatched tag cannot hide arbitrary text. Partial logs remain conservative.
    literals = {}

    def mask(match):
        key = f"\x00LITERAL{len(literals)}\x00"
        literals[key] = match[0]
        return key

    text = re.sub(r"(?ms)^```[^\n]*\n.*?^```[ \t]*$", mask, text)
    text = re.sub(r"`[^`\n]+`", mask, text)
    complete = len(re.findall(r"<details\b", text, re.I)) == len(re.findall(r"</details>", text, re.I))
    quality = "first_layer" if complete else "unbalanced_details"
    if complete:
        # Nested details are collapsed by repeatedly removing innermost blocks.
        pattern = re.compile(r"<details\b[^>]*>(?:(?!<details\b).)*?</details>", re.S | re.I)
        while pattern.search(text):
            text = pattern.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    for key, literal in literals.items():
        text = text.replace(key, literal)
    return text.strip(), quality


def measure_length(text: str, contract: dict, original_chars: int | None = None) -> dict:
    visible, quality = visible_text(text)
    if contract["surface"] == "summary":
        headings = re.search(r"(?m)^#{1,6}\s*(?:完整证明|证明|推导|正文|附录|详细|细节)", visible)
        if headings:
            measured = visible[:headings.start()].strip()
            quality = "summary_before_heading"
        else:
            measured = re.split(r"\n\s*\n", visible, maxsplit=1)[0].strip()
            quality = "first_paragraph_proxy"
    else:
        measured = visible
        # If a plain reply was truncated, its recorded full length is still known.
        if original_chars and original_chars > len(text) and "<details" not in text:
            return {"chars": original_chars, "surface": "reply", "quality": "recorded_full_length"}
    return {"chars": len(measured), "surface": contract["surface"], "quality": quality}
