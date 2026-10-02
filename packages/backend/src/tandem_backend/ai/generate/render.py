"""Render typed slots into install payloads and display files (with per-line diff marks).

`payload` matches the install area's InstallSpec{kind, payload}; `files[]` uses symbolic
targets that install resolves to real paths (e.g. `claude.user_skills/<name>/SKILL.md`).
"""

from __future__ import annotations

import json
import re

from .templates import TITLES, Template
from .util import canonical_json, goal_text, refs, sha256_text, slug

AGENTS = ["claude_code", "codex"]
HOOK_TIMEOUT_S = 10
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_CODE_SLOTS = {"block_id", "evidence"}  # filled by code, never by the model


def _quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # JSON strings are valid YAML scalars


def _fill(body: str, values: dict, personalized: bool, evidence: list[str]) -> list[dict]:
    """Expand `{{slot}}` lines; list values become one line each, None drops the line."""
    lines = []
    for raw in body.rstrip("\n").split("\n"):
        names = _PLACEHOLDER.findall(raw)
        if not names:
            lines.append({"text": raw, "mark": "+", "evidence": []})
            continue
        ai = personalized and any(n not in _CODE_SLOTS for n in names)
        mark, refs_ = ("ai", evidence) if ai else ("+", [])
        if len(names) == 1 and raw.strip() == "{{%s}}" % names[0] and isinstance(values.get(names[0]), list):
            expanded = values[names[0]]
        elif any(values.get(n) is None for n in names):
            continue
        else:
            expanded = [_PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), raw)]
        for text in expanded:
            for part in str(text).split("\n"):
                lines.append({"text": part, "mark": mark, "evidence": list(refs_)})
    return lines


def _file(target: str, action: str, lines: list[dict]) -> dict:
    content = "\n".join(line["text"] for line in lines) + "\n"
    return {"target": target, "action": action, "content": content, "sha256": sha256_text(content), "lines": lines}


def _json_lines(value, ai_keys: set[str], personalized: bool, evidence: list[str]) -> list[dict]:
    lines = []
    for text in json.dumps(value, ensure_ascii=False, indent=2).split("\n"):
        key = re.match(r'\s*"([^"]+)":', text)
        ai = personalized and key is not None and key.group(1) in ai_keys
        lines.append({"text": text, "mark": "ai" if ai else "+", "evidence": list(evidence) if ai else []})
    return lines


def _render_rule(template: Template, slots: dict, pack: dict, personalized: bool, evidence: list[str]):
    block = slug(slots.get("title", ""), goal_text(pack) + slots.get("title", ""))
    values = {"block_id": block, "evidence": ",".join(refs(pack, "event")[:3]) or "-",
              "title": slots["title"], "rules": [f"- {r['text']}" for r in slots["rules"]]}
    lines = _fill(template.body, values, personalized, evidence)
    markdown = "\n".join(line["text"] for line in lines) + "\n"
    payload = {"install_kind": "rule", "block_id": f"tandem:rule:{block}", "title": slots["title"],
               "markdown": markdown, "scope": "user", "agents": AGENTS}
    files = [_file("claude.user_memory", "append_block", lines),
             _file("codex.user_agents_md", "append_block", [dict(line) for line in lines])]
    return block, slots["title"], payload, files


def hook_command(template: Template) -> str:
    base = "{tandem.hooks}/" + template.script_name
    return f'python3 "{base}" --config "{base[:-3]}.config.json"'


def _render_hook(template: Template, slots: dict, pack: dict, personalized: bool, evidence: list[str]):
    bindings = [{"event": e["event"], "matcher": slots.get("matcher", "*") if e.get("matcher") is None else e["matcher"]}
                for e in template.events]
    entry = {"type": "command", "command": hook_command(template), "timeout": HOOK_TIMEOUT_S}
    payload = {"template_id": template.id, "event_bindings": bindings,
               "script": {"name": template.script_name, "content": template.body, "sha256": template.sha256},
               "config": dict(slots), "timeout_s": HOOK_TIMEOUT_S, "agents": AGENTS}
    slot_events = {b["event"] for b, e in zip(bindings, template.events, strict=True) if e.get("matcher") is None}
    files = [_file(f"tandem.hooks/{template.script_name}", "create",
                   [{"text": t, "mark": "+", "evidence": []} for t in template.body.rstrip("\n").split("\n")]),
             _file(f"tandem.hooks/{template.script_name[:-3]}.config.json", "create",
                   _json_lines(slots, set(slots), personalized, evidence))]
    for binding in bindings:
        snippet = [{"matcher": binding["matcher"], "hooks": [entry]}]
        ai_keys = {"matcher"} if binding["event"] in slot_events else set()
        files.append(_file(f"claude.user_settings#/hooks/{binding['event']}", "merge_json",
                           _json_lines(snippet, ai_keys, personalized, evidence)))
    codex = {"hooks": {b["event"]: [{"matcher": b["matcher"], "hooks": [entry]}] for b in bindings}}
    files.append(_file("codex.hooks", "merge_json", _json_lines(codex, {"matcher"} if slot_events else set(),
                                                                 personalized, evidence)))
    return template.id, TITLES.get(template.id, template.id), payload, files


def _render_skill(template: Template, slots: dict, pack: dict, personalized: bool, evidence: list[str]):
    values = {"name": slots["name"], "description": _quoted(slots["description"]),
              "allowed_tools": ", ".join(slots.get("allowed_tools") or []) or None,
              "steps": [f"{i}. {s}" for i, s in enumerate(slots["steps"], 1)],
              "dont": [f"- {d}" for d in slots.get("dont") or []], "verify": slots["verify"]}
    lines = _fill(template.body, values, personalized, evidence)
    content = "\n".join(line["text"] for line in lines) + "\n"
    payload = {"name": slots["name"], "files": [{"path": "SKILL.md", "content": content}], "agents": AGENTS}
    files = [_file(f"claude.user_skills/{slots['name']}/SKILL.md", "create", lines),
             _file(f"agents.user_skills/{slots['name']}/SKILL.md", "create", [dict(line) for line in lines])]
    return slots["name"], slots["name"], payload, files


def _render_subagent(template: Template, slots: dict, pack: dict, personalized: bool, evidence: list[str]):
    body = slots["body"]
    values = {"name": slots["name"], "description": _quoted(slots["description"]),
              "tools": ", ".join(slots.get("tools") or []) or None, **{k: body[k] for k in body}}
    lines = _fill(template.body, values, personalized, evidence)
    payload = {"name": slots["name"], "markdown": "\n".join(line["text"] for line in lines) + "\n"}
    return slots["name"], slots["name"], payload, [_file(f"claude.user_agents/{slots['name']}.md", "create", lines)]


def _render_command(template: Template, slots: dict, pack: dict, personalized: bool, evidence: list[str]):
    values = {"description": _quoted(slots["description"]),
              "argument_hint": _quoted(slots["argument_hint"]) if slots.get("argument_hint") else None,
              "body": slots["body"]}
    lines = _fill(template.body, values, personalized, evidence)
    payload = {"name": slots["name"], "markdown": "\n".join(line["text"] for line in lines) + "\n"}
    files = [_file(f"claude.user_commands/{slots['name']}.md", "create", lines),
             _file(f"codex.prompts/{slots['name']}.md", "create", [dict(line) for line in lines])]
    return slots["name"], slots["name"], payload, files


_RENDERERS = {"rule": _render_rule, "hook": _render_hook, "skill": _render_skill,
              "subagent": _render_subagent, "command": _render_command}


def render(template: Template, slots: dict, pack: dict, personalized: bool, kind: str | None = None) -> dict:
    kind = kind or template.kind
    evidence = refs(pack, "event")[:3] if personalized else []
    name, title, payload, files = _RENDERERS[template.kind](template, slots, pack, personalized, evidence)
    return {"name": name, "title": title, "payload": payload, "files": files,
            "content_hash": sha256_text(kind + canonical_json(payload))}
