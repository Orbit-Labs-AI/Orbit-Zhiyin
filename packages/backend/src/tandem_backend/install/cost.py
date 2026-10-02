"""Context-cost estimate of an install (rough token counts, no tokenizer).

``resident`` tokens are loaded into every session (CLAUDE.md blocks, skill name +
description); ``trigger`` tokens load only when the component fires (skill body, command
body). MCP tool schemas are unknown before the server runs, so they get a flat guess.
"""

from __future__ import annotations

import math
import re

MCP_FLAT = 400
_FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


def tokens(text: str) -> int:
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    return math.ceil(ascii_n / 4 + (len(text) - ascii_n) / 1.5)


def _front(text: str) -> tuple[str, str]:
    """``(name+description lines, body)`` of a Markdown file with YAML frontmatter."""
    m = _FRONT.match(text)
    if not m:
        return "", text
    head = "\n".join(ln for ln in m.group(1).splitlines()
                     if ln.split(":", 1)[0].strip() in ("name", "description"))
    return head, m.group(2)


def _part(spec: dict, t: dict) -> tuple[int, int, str]:
    kind, action = spec.get("kind"), t.get("action")
    content = t.get("content")
    text = content if isinstance(content, str) else ""
    path = str(t.get("path") or "")
    if kind == "mcp" and action in ("merge_json", "toml_block"):
        return MCP_FLAT, 0, "tool schema unknown"
    if action in ("md_block", "toml_block"):
        return tokens(text), 0, "always loaded"
    if action != "create_file":
        return 0, 0, "config only"
    if kind == "skill":
        if path.endswith("SKILL.md"):
            head, body = _front(text)
            return tokens(head), tokens(body), "description resident, body on trigger"
        return 0, 0, "loaded on demand"
    if kind == "subagent":
        head, body = _front(text)
        return tokens(head), tokens(body), "description resident, body on delegation"
    if kind == "command":
        return 0, tokens(_front(text)[1]), "loaded when invoked"
    if kind == "rule":
        return tokens(text), 0, "always loaded"
    return 0, 0, "config only"


def estimate(spec: dict, targets: list[dict]) -> dict:
    parts = []
    for t in targets:
        if t.get("mappable") is False:
            continue
        resident, trigger, note = _part(spec, t)
        parts.append({"target_idx": t.get("idx"), "resident": resident, "trigger": trigger,
                      "note": note})
    return {"resident_tokens": sum(p["resident"] for p in parts),
            "trigger_tokens": sum(p["trigger"] for p in parts),
            "basis": "estimate", "parts": parts}
