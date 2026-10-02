"""Measure a requested writing surface without treating required detail as overload.

These measurements are explicit formatting checks. They do not grade mathematical
correctness, emotional tone, or whether the reader actually understands a passage.
"""

import re

UPPER_BOUND_PATTERN = r"(\d+)\s*(?:字|字符)\s*(?:以内|内|以下)|(?:不超过|不要超过|不得超过|最多|控制在|限于|限制为)\s*(\d+)\s*(?:字|字符)"


def length_contract(text: str, start: int, end: int) -> dict:
    """A local brevity requirement can constrain the abstract instead of the full reply."""
    boundaries = "，,、。；;\n"
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
    cap = re.search(UPPER_BOUND_PATTERN, clause)
    body = bool(targets and targets[-1][0] in ("正文", "完整证明"))
    if re.search(r'合计|总共', clause):
        summary, body = False, False
    return {"surface": "summary" if summary else "body" if body else "reply",
            "char_limit": int(cap[1] or cap[2]) if cap else None,
            "requires_full_body": bool(re.search(r"(?:完整|详细).{0,8}(?:证明|推导|正文)|(?:证明|推导|正文).{0,8}(?:完整|详细)|不省略(?:条件|步骤)", text)),
            "basis": "explicit_request"}


def merge_length_contracts(text: str, spans: list[tuple[int, int]]) -> list[dict]:
    """Compatible bounds combine per surface; an explicit replacement uses its new bound."""
    merged = {}
    for start, end in spans:
        contract = length_contract(text, start, end)
        left = max(text.rfind(c, 0, start) for c in "，,、。；;\n") + 1
        replacement = bool(re.search(r"改成|改为|调整为|改到", text[left:end]))
        surfaces = _shared_surfaces(text, start, end) or [contract['surface']]
        for surface in surfaces:
            current = {**contract, 'surface': surface}
            previous = merged.get(surface)
            if previous and previous["char_limit"] is not None and not replacement:
                bound = current["char_limit"]
                current["char_limit"] = min(previous["char_limit"], bound) if bound is not None else previous["char_limit"]
            merged[surface] = current
    return list(merged.values())


def _shared_surfaces(text: str, start: int, end: int) -> list[str]:
    """Only an explicit distributive word makes one cap apply to several objects."""
    left = max(text.rfind(c, 0, start) for c in '，,。；;\n') + 1
    ends = [text.find(c, end) for c in '，,。；;\n' if text.find(c, end) >= 0]
    clause = text[left:min(ends) if ends else len(text)]
    cap = re.search(UPPER_BOUND_PATTERN, clause)
    if not cap:
        return []
    target = r'摘要|总结|概要|概述|开头|首段|首层|正文|全文|完整证明|完整回复|回答|回复|报告'
    coordinated = re.search(r'((?:' + target + r')(?:\s*(?:和|与|及|、)\s*(?:' + target + r'))+)\s*(?:各(?:自)?|分别|均|都)\s*(?:控制在|最多|限于)?\s*$', clause[:cap.start()])
    if not coordinated:
        return []
    surfaces = []
    for name in re.findall(target, coordinated[1]):
        surface = 'summary' if re.fullmatch(r'摘要|总结|概要|概述|开头|首段|首层', name) else 'body' if name in ('正文', '完整证明') else 'reply'
        if surface not in surfaces:
            surfaces.append(surface)
    return surfaces


def canceled_length_surfaces(text: str) -> set[str]:
    """Explicit cancellation changes pending limits, not past profile evidence."""
    pattern = (r"(?:取消|撤销|去掉|移除)[^，,。；;\n]{0,12}(?:字数|篇幅|长度|\d+字)[^，,。；;\n]{0,6}(?:限制|上限|要求)|"
               r"(?:不再|不|不用|无需)限制(?:字数|篇幅|长度)")
    surfaces = set()
    for match in re.finditer(pattern, text):
        left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
        prefix = text[left:match.start()]
        if re.search(r"(?:不要|别|不用|不需要|不是让你|不是要)[^，,。；;\n]{0,6}$", prefix):
            continue
        governors = list(re.finditer(r"介绍|解释|讨论|分析|如何|怎么|请|现在|另外|再", prefix))
        if governors and governors[-1][0] in ("介绍", "解释", "讨论", "分析", "如何", "怎么"):
            continue
        local = text[left:match.end()]
        targets = list(re.finditer(r"摘要|总结|正文|完整证明|回答|回复|全文", local))
        if not targets:
            surfaces.update(("summary", "body", "reply"))
        elif targets[-1][0] in ("摘要", "总结"):
            surfaces.add("summary")
        elif targets[-1][0] in ("正文", "完整证明"):
            surfaces.add("body")
        else:
            surfaces.add("reply")
    return surfaces


def fenced_parts(text: str) -> list[tuple[bool, str]]:
    """Separate Markdown fences; unclosed fences remain quoted literal material."""
    parts, prose, literal = [], [], []
    marker, width = "", 0
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if literal:
            literal.append(line)
            if re.fullmatch(r" {0,3}" + re.escape(marker) + "{" + str(width) + r",}[ \t]*", stripped):
                parts.append((True, "".join(literal)))
                literal = []
        else:
            opening = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", stripped)
            if opening and not (opening[1][0] == "`" and "`" in opening[2]):
                if prose:
                    parts.append((False, "".join(prose)))
                    prose = []
                marker, width = opening[1][0], len(opening[1])
                literal = [line]
            else:
                prose.append(line)
    if literal:
        parts.append((True, "".join(literal)))
    if prose:
        parts.append((False, "".join(prose)))
    return parts


def embedded_artifact_body(text: str) -> bool:
    """Recognize a marked body in a delivery message; this cannot prove completeness."""
    for link in re.finditer(r"\[[^\]]+\]\([^)]*\.(?:md|tex|docx)(?::\d+)?\)", text, re.I):
        if any(_marked_body(part) for part in (text[:link.start()], text[link.end():])):
            return True
    return False


def _marked_body(text: str) -> bool:
    if re.search(r"节选|片段|摘录", text[:120]):
        return False
    explicit = re.search(r"(?:以下(?:是|为)?|附上|附|提供)(?:文档|报告|讲义)?(?:正文|全文|完整内容)[：:。\s]*|(?:正文|全文|完整内容)如下[：:。\s]*", text)
    if explicit and text[explicit.end():].strip():
        return True
    for fenced, part in fenced_parts(text):
        if fenced and re.match(r"\s*(?:`{3,}|~{3,})(?:markdown|md|tex|latex)\b", part, re.I) and len(part.strip().splitlines()) >= 3:
            return True
    for heading in re.finditer(r"(?m)^#{1,6}\s+([^\n]+)\n", text):
        if not re.search(r"验证|测试|下一步|交付|修改|核对|完成情况|运行|文件清单|结果", heading[1]) and len(text[heading.end():].strip()) >= 20:
            return True
    return False


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
    parts = []
    for fenced, part in fenced_parts(text):
        if fenced:
            key = f"\x00LITERAL{len(literals)}\x00"
            literals[key] = part
            parts.append(key)
        else:
            parts.append(part)
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


def measure_length(text: str, contract: dict, original_chars: int | None = None, message_separator: str = "") -> dict:
    visible, quality = visible_text(text)
    complete = not original_chars or original_chars <= len(text)
    if contract["surface"] == "summary":
        headings = re.search(r"(?m)^#{1,6}\s*(?:完整证明|证明|推导|正文|附录|详细|细节)", visible)
        if headings:
            measured = visible[:headings.start()]
            quality = "summary_before_heading"
            complete = True  # The complete summary boundary is visible even if the body is truncated.
        else:
            measured = re.split(r"\n\s*\n", visible, maxsplit=1)[0]
            quality = "first_paragraph_proxy"
            complete = complete or bool(re.search(r"\n\s*\n", visible))
    elif contract["surface"] == "body":
        # An explicit body limit excludes the abstract. Without a marked body
        # boundary, its length is unknown rather than silently treated as zero.
        body_text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        boundary = re.search(r"(?m)^#{1,6}\s*(?:完整证明|证明|推导|正文|附录|详细)[^\n]*\n|正文[：:]\s*", body_text)
        measured = body_text[boundary.end():] if boundary else ""
        quality = "body_after_marker" if boundary else "body_boundary_missing"
        complete = complete and bool(boundary)
    else:
        measured = visible
    if message_separator:
        measured = measured.replace(message_separator, "")
    measured = measured.strip()
    if not complete and quality == "unbalanced_details":
        measured = ""  # A later closing tag might collapse all retained prose.
        quality = "partial_markup_boundary_unknown"
    if not complete and quality not in ("body_boundary_missing", "partial_markup_boundary_unknown"):
        quality = "truncated_lower_bound"
    return {"chars": len(measured), "surface": contract["surface"], "quality": quality, "complete": complete}
