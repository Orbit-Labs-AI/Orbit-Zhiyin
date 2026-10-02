"""Repository templates for generated artifacts: hash-pinned files plus the slot schemas.

The model only ever fills the typed slots below; everything else comes from these files and
`render.py`. Editing a template file without bumping its version fails `load()`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "assets" / "templates"

DIMENSIONS = ["clarity", "brevity", "grounding", "actionability", "autonomy", "planning",
              "verification", "scope", "convention", "other"]
SKILL_TOOLS = ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "WebFetch"]
READONLY_TOOLS = ["Read", "Grep", "Glob", "WebFetch", "WebSearch"]
KEBAB = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# Kind -> template id for everything except hooks (hooks are picked by L0, see tasks.pick_hook).
KIND_TEMPLATE = {"rule": "paragraph", "glue": "paragraph", "skill": "procedure",
                 "subagent": "reviewer", "command": "checklist"}
HOOK_BY_PROBLEM = {"tool_env_failure": "retry-breaker", "missing_verification": "verify-before-commit",
                   "context_loss": "compaction-reminder", "unsafe_operation": "scope-guard"}
TITLES = {"retry-breaker": "连续失败熔断", "verify-before-commit": "提交前先验证",
          "post-edit-check": "改后提醒检查", "stop-verify": "结束前补验证",
          "compaction-reminder": "压缩前留档", "scope-guard": "越界命令拦截"}


def _text(limit: int) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": limit}


def _list(item: dict, most: int, least: int = 0) -> dict:
    return {"type": "array", "items": item, "minItems": least, "maxItems": most}


def _object(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_RULE = {"title": _text(12),
         "rules": _list(_object({"text": _text(60), "dimension": {"enum": DIMENSIONS}}, ["text", "dimension"]), 5, 1)}
_NAME = {"type": "string", "pattern": KEBAB, "maxLength": 64}

SLOT_SCHEMAS: dict[str, dict] = {
    "rule": _object(_RULE, ["title", "rules"]),
    "glue": _object({**_RULE, "uses_catalog_items": _list({"type": "string"}, 3, 1)},
                    ["title", "rules", "uses_catalog_items"]),
    "hook": _object({"matcher": {"enum": ["Bash", "Edit", "Write", "Task", "*"]},
                     "threshold": {"type": "integer", "minimum": 2, "maximum": 5},
                     "message": _text(120),
                     "command_heads": _list(_text(80), 10),
                     "file_glob": _text(40), "command": _text(80)},
                    ["matcher", "threshold", "message", "command_heads"]),
    "skill": _object({"name": _NAME, "description": _text(1024),
                      "steps": _list(_text(80), 8, 1), "dont": _list(_text(80), 5),
                      "verify": _text(80), "allowed_tools": _list({"enum": SKILL_TOOLS}, len(SKILL_TOOLS))},
                     ["name", "description", "steps", "dont", "verify", "allowed_tools"]),
    "subagent": _object({"name": _NAME, "description": _text(200),
                         "tools": _list({"enum": READONLY_TOOLS}, len(READONLY_TOOLS)),
                         "body": _object({k: _text(120) for k in ("role", "inputs", "output_format", "forbidden")},
                                         ["role", "inputs", "output_format", "forbidden"])},
                        ["name", "description", "tools", "body"]),
    "command": _object({"name": _NAME, "description": _text(100), "body": _text(300),
                        "argument_hint": {"type": "string", "maxLength": 40}},
                       ["name", "description", "body", "argument_hint"]),
}
for _schema in SLOT_SCHEMAS.values():
    _schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"


@dataclass(frozen=True)
class Template:
    id: str
    version: int
    kind: str
    body: str
    sha256: str
    slot_schema: dict
    defaults: dict
    events: list
    file: str = ""

    @property
    def path(self) -> Path:
        return ROOT / self.file

    @property
    def script_name(self) -> str:
        return f"{self.id}@{self.version}.py"


@cache
def load() -> dict[str, Template]:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    templates = {}
    for template_id, entry in manifest.items():
        raw = (ROOT / entry["file"]).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry["sha256"]:
            raise RuntimeError(f"template {template_id} changed without a version bump "
                               f"(manifest {entry['sha256'][:12]}, file {digest[:12]})")
        templates[template_id] = Template(
            id=template_id, version=int(entry["version"]), kind=entry["kind"], body=raw.decode("utf-8"),
            sha256=digest, slot_schema=SLOT_SCHEMAS[entry["kind"]], defaults=entry["defaults"],
            events=list(entry.get("events") or []), file=entry["file"])
    return templates


def get(template_id: str) -> Template:
    templates = load()
    if template_id not in templates:
        raise KeyError(f"unknown template {template_id}")
    return templates[template_id]
