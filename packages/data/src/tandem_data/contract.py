"""Shared types and validation for connector authors; no source-specific IO."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator

KINDS = (
    "session.meta",
    "session.title",
    "setting.change",
    "turn.start",
    "turn.end",
    "message.user",
    "message.assistant",
    "reasoning",
    "tool.call",
    "tool.result",
    "model.usage",
    "context.inject",
    "context.compaction",
    "permission.request",
    "permission.decision",
    "branch",
    "hook.run",
    "subagent.spawn",
    "subagent.result",
    "plan.update",
    "file.change",
    "link",
    "queue",
    "error",
    "ui.state",
    "unknown",
)
TOKENS = (
    "input_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
)


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def uid(namespace: str, *parts: Any) -> str:
    """Structured encoding prevents delimiter and cross-entity collisions."""
    return namespace + "_" + hashlib.sha256(canonical([namespace, *parts]).encode()).hexdigest()


def now_ms() -> int:
    return round(datetime.now(UTC).timestamp() * 1000)


def time_fields(
    value: Any,
    field_path: str,
    unit: str = "iso",
    semantics: str = "written",
    source_timezone: str | None = None,
) -> tuple[int | None, dict]:
    reported = {field_path: value} if value is not None else {}
    result = {
        "source_field": None,
        "semantics": semantics,
        "quality": "missing",
        "reported": reported,
    }
    try:
        if value is None or isinstance(value, bool):
            return None, result
        if unit == "iso":
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                if not source_timezone:
                    return None, result
                parsed = parsed.replace(tzinfo=ZoneInfo(source_timezone))
            stamp = round(parsed.timestamp() * 1000)
        elif unit in ("seconds", "milliseconds"):
            if not isinstance(value, int | float) or not math.isfinite(value):
                return None, result
            stamp = round(value * (1000 if unit == "seconds" else 1))
        else:
            raise ValueError(f"Unknown declared timestamp unit: {unit}")
        if not -(2**63) <= stamp < 2**63:
            return None, result
        result.update(source_field=field_path, quality="reported")
        return stamp, result
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return None, result


def shape(value: Any) -> Any:
    """Fingerprint keys and types, without leaking source values."""
    if isinstance(value, dict):
        return {key: shape(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return sorted({canonical(shape(child)) for child in value})
    return type(value).__name__


def unused(data: dict, consumed: tuple[str, ...] | list[str]) -> dict:
    """Nested leftovers are retained separately by the connector in block_ext."""
    return {key: value for key, value in data.items() if key not in consumed}


@dataclass(frozen=True)
class RawRecord:
    record_uid: str
    source_id: str
    agent: str
    file_id: str
    relative_path: str
    ordinal: int
    version: int
    native_type: str
    data: dict
    captured_at: int


@dataclass
class EventDraft:
    """Connector output. Store assigns event_uid, seq and version fields."""

    session_uid: str
    native_key: list
    event_path: str
    kind: str
    actor: str = "harness"
    ts: int | None = None
    attrs: dict = field(default_factory=dict)
    ext: dict = field(default_factory=dict)
    text: str | None = None
    call_id: str | None = None
    native_id: str | None = None
    parent_native_key: list | None = None
    relation: str = "mapped"

    @property
    def event_uid(self) -> str:
        return uid("event", self.native_key, self.kind, self.event_path)

    def envelope(self, record_uid: str, seq: int, mapper_version: str) -> dict:
        from tandem_data.privacy import redact, sanitize

        text = redact(self.text) if self.text is not None else None
        attrs = dict(self.attrs)
        if self.kind in ("message.user", "message.assistant") and text is not None:
            attrs.update(
                original_chars=len(text), message_digest=hashlib.sha256(text.encode()).hexdigest()
            )
            attrs.setdefault("input_format", "prompt" if self.kind == "message.user" else None)
            if self.kind == "message.assistant":
                attrs["writing_measurements"] = {
                    "reply": {
                        "chars": len(text),
                        "surface": "visible_reply",
                        "quality": "measured",
                        "complete": True,
                    },
                    "summary": None,
                    "body": None,
                }
                attrs.setdefault("artifact_body_present", None)
        if self.kind == "tool.call":
            if attrs.get("input") is not None:
                safe_input = sanitize(attrs["input"])
                attrs["argument_digest"] = (
                    uid("arguments", attrs["input"]) if safe_input == attrs["input"] else None
                )
                attrs["argument_digest_basis"] = (
                    "canonical_json" if safe_input == attrs["input"] else None
                )
            attrs.setdefault("is_wrapper", attrs.get("name") in ("exec", "run_code"))
        if self.kind == "tool.result":
            attrs.setdefault("status_scope", "unknown")
            for name in (
                "known_command_results",
                "failed_command_results",
                "unknown_return_values",
            ):
                attrs.setdefault(name, None)
        if self.kind in ("tool.call", "tool.result", "turn.end") and attrs.get("status"):
            attrs["status"] = {
                "error": "failed",
                "aborted": "interrupted",
                "in_progress": "running",
            }.get(attrs["status"], attrs["status"])
        truncated = 0
        if text is not None and len(text.encode("utf-8")) > 8192:
            text = text.encode("utf-8")[:8192].decode("utf-8", errors="ignore")
            truncated = 1
        return {
            "event_uid": self.event_uid,
            "session_uid": self.session_uid,
            "record_uid": record_uid,
            "native_id": self.native_id,
            "native_key": self.native_key,
            "event_path": self.event_path,
            "kind": self.kind,
            "actor": self.actor,
            "seq": seq,
            "ts": self.ts,
            "parent_uid": None,
            "turn_uid": None,
            "call_id": self.call_id,
            "text": text,
            "text_truncated": truncated,
            "attrs": sanitize(attrs),
            "ext": sanitize(self.ext),
            "contract_version": 1,
            "mapper_version": mapper_version,
        }


_validator = None


def validate_event(event: dict) -> None:
    global _validator
    if _validator is None:
        schema = json.loads(
            files("tandem_data").joinpath("schemas/event-v1.schema.json").read_text()
        )
        _validator = Draft202012Validator(schema)
    _validator.validate(event)


def normalize_usage(reported: dict, dialect: str) -> dict:
    """NULL survives. Cache input and reasoning output buckets do not overlap."""
    names = {
        "claude_code": (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
            "reasoning_tokens",
        ),
        "codex": (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ),
        "pi": ("input", "cacheRead", "cacheWrite", "output", "reasoning"),
        "dsh": (
            "inputTokens",
            "cacheReadTokens",
            "cacheWriteTokens",
            "outputTokens",
            "reasoningTokens",
        ),
        "opencode": ("input", "cache.read", "cache.write", "output", "reasoning"),
        "hermes": TOKENS,
        "kimi": ("inputOther", "inputCacheRead", "inputCacheCreation", "output", "reasoning"),
    }[dialect]

    def read(path):
        value = reported
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        return value

    values = dict(zip(TOKENS, (read(name) for name in names), strict=True))
    if dialect == "claude_code":
        values["reasoning_tokens"] = (reported.get("output_tokens_details") or {}).get(
            "thinking_tokens"
        )
    if dialect == "codex" and values["input_tokens"] is not None:
        cached = values["cache_read_tokens"]
        values["input_tokens"] = values["input_tokens"] - cached if cached is not None else None
        # Explicit cache writes are also included in the native input bucket.
        if values["input_tokens"] is not None and values["cache_write_tokens"] is not None:
            values["input_tokens"] -= values["cache_write_tokens"]
    if dialect == "opencode":
        output, reasoning = values["output_tokens"], values["reasoning_tokens"]
        values["output_tokens"] = (
            output + reasoning if output is not None and reasoning is not None else None
        )
    for key, value in values.items():
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError(f"Invalid normalized {key}")
    return {**values, "reported": reported}
