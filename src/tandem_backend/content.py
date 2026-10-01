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
    # A following clause like '控制在100字以内' still refers to the preceding
    # abstract. A new explicit object ('正文') changes that surface.
    sentence_left = max(text.rfind(c, 0, left) for c in "。；;\n") + 1
    targets = list(re.finditer(r"摘要|总结|概要|概述|开头|首段|首层|正文|全文|完整证明|完整回复|回答|回复|报告", text[sentence_left:right]))
    summary = bool(targets and re.fullmatch(r"摘要|总结|概要|概述|开头|首段|首层", targets[-1][0]))
    # Search the requirement clause, not incidental numeric facts in another clause.
    cap = re.search(r"(\d+)\s*(?:字|字符)\s*(?:以内|内|以下)|(?:不超过|最多|控制在|限于|限制为)\s*(\d+)\s*(?:字|字符)", clause)
    return {"surface": "summary" if summary else "reply",
            "char_limit": int(cap[1] or cap[2]) if cap else None,
            "requires_full_body": bool(re.search(r"(?:完整|详细).{0,8}(?:证明|推导|正文)|(?:证明|推导|正文).{0,8}(?:完整|详细)|不省略(?:条件|步骤)", text)),
            "basis": "explicit_request"}


def merge_length_contracts(text: str, spans: list[tuple[int, int]]) -> list[dict]:
    """Compatible bounds combine per surface; an explicit replacement uses its new bound."""
    merged = {}
    for start, end in spans:
        contract = length_contract(text, start, end)
        surface = contract["surface"]
        previous = merged.get(surface)
        left = max(text.rfind(c, 0, start) for c in "，,。；;\n") + 1
        replacement = bool(re.search(r"改成|改为|调整为|改到", text[left:end]))
        if previous and previous["char_limit"] is not None and not replacement:
            bound = contract["char_limit"]
            contract["char_limit"] = min(previous["char_limit"], bound) if bound is not None else previous["char_limit"]
        merged[surface] = contract
    return list(merged.values())


def visible_text(text: str) -> tuple[str, str]:
    """Exclude balanced expandable details and link destinations from the first layer."""
    # An unmatched tag cannot hide arbitrary text. Partial logs remain conservative.
    literals = {}

    def mask(match):
        key = f"\x00LITERAL{len(literals)}\x00"
        literals[key] = match[0]
        return key

    # Fences may use tildes, four backticks, or remain open at the end. Their
    # literal HTML must never be interpreted as expandable details.
    parts, fenced, marker, width = [], [], "", 0
    for line in text.splitlines(keepends=True):
        if fenced:
            fenced.append(line)
            if re.fullmatch(r" {0,3}" + re.escape(marker) + "{" + str(width) + r",}[ \t]*(?:\n)?", line):
                literal = "".join(fenced)
                key = f"\x00LITERAL{len(literals)}\x00"
                literals[key] = literal
                parts.append(key)
                fenced = []
        elif opening := re.match(r" {0,3}(`{3,}|~{3,})", line):
            marker, width = opening[1][0], len(opening[1])
            fenced = [line]
        else:
            parts.append(line)
    if fenced:
        key = f"\x00LITERAL{len(literals)}\x00"
        literals[key] = "".join(fenced)
        parts.append(key)
    text = "".join(parts)
    text = re.sub(r"`[^`\n]+`", mask, text)
    depth, complete = 0, True
    for tag in re.finditer(r"<details\b[^>]*>|</details\s*>", text, re.I):
        if tag[0].startswith("</"):
            depth -= 1
            complete = complete and depth >= 0
        else:
            depth += 1
    complete = complete and depth == 0
    quality = "first_layer" if complete else "unbalanced_details"
    if complete:
        # Nested details are collapsed by repeatedly removing innermost blocks.
        pattern = re.compile(r"<details\b[^>]*>(?:(?!<details\b).)*?</details>", re.S | re.I)

        def collapse(match):
            opening = re.match(r"<details\b([^>]*)>", match[0], re.I)
            inner = match[0][opening.end():match[0].lower().rfind("</details>")]
            if re.search(r"(?:^|\s)open(?:\s|=|$)", opening[1], re.I):
                return re.sub(r"</?summary\b[^>]*>", "", inner, flags=re.I)
            summary = re.search(r"<summary\b[^>]*>([\s\S]*?)</summary>", inner, re.I)
            return summary[1] if summary else ""

        while pattern.search(text):
            text = pattern.sub(collapse, text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    for key, literal in literals.items():
        text = text.replace(key, literal)
    return text.strip(), quality


def measure_length(text: str, contract: dict, original_chars: int | None = None) -> dict:
    visible, quality = visible_text(text)
    complete = not original_chars or original_chars <= len(text)
    if contract["surface"] == "summary":
        headings = re.search(r"(?m)^#{1,6}\s*(?:完整证明|证明|推导|正文|附录|详细|细节)", visible)
        if headings:
            measured = visible[:headings.start()].strip()
            quality = "summary_before_heading"
            complete = True  # The complete summary boundary is visible even if the body is truncated.
        else:
            measured = re.split(r"\n\s*\n", visible, maxsplit=1)[0].strip()
            quality = "first_paragraph_proxy"
            complete = complete or bool(re.search(r"\n\s*\n", visible))
    else:
        measured = visible
    if not complete:
        quality = "truncated_lower_bound"
    return {"chars": len(measured), "surface": contract["surface"], "quality": quality, "complete": complete}
