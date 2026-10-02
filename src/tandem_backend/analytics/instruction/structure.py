"""Observable prompt structure for the Instruction feature family."""

import re

CONSTRAINT = re.compile(r"必须|不要|只能|要求|\b(?:must|do not|don't|only|require)\b", re.I)
FILE = re.compile(r"(?<![\w.])(?:[\w@~-]+/)*[\w.-]+\.(py|ts|tsx|js|jsx|tex|md|json|yaml|yml|rs|go|java|cpp|c|h|sh|html|css|ipynb)\b", re.I)


def structure(e):
    text = e.get("text")
    if text is None:
        return None
    attrs = e.get("attrs", {})
    out = {"prompt_char_count": attrs.get("original_chars", len(text)),
           "prompt_line_count": len(text.splitlines()) if text else 0,
           "paragraph_count": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
           "question_mark_count": len(re.findall(r"[?？]", text)),
           "bullet_count": len(re.findall(r"(?m)^\s*[-*+]\s+", text)),
           "numbered_list_count": len(re.findall(r"(?m)^\s*\d+[.)、]\s*", text)),
           "code_block_count": None,  # Legacy normalization removed fenced material.
           "url_count": len(re.findall(r"https?://[^\s<>]+", text)),
           "file_reference_count": len(FILE.findall(text)),
           "explicit_format_request_count": len(re.findall(r"(?:请|用|输出为|写成).{0,8}(?:表格|列表|JSON|Markdown|分点)", text, re.I)),
           "explicit_tool_mention_count": len(re.findall(r"(?:使用|调用|用)\s*`?[\w.]*?(?:MCP|工具|skill|pytest|git|bash)\b", text, re.I)),
           "constraint_marker_count": len(CONSTRAINT.findall(text))}
    if "prompt_structure" in attrs:
        out.update(attrs["prompt_structure"])
    out["constraint_density"] = (out["constraint_marker_count"] / len(text) if text else None)
    out["quality"] = "lower_bound" if e.get("text_truncated") else "normalized_text"
    out["event_uid"] = e["event_uid"]
    return out

