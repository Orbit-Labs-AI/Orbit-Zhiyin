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
            "text_truncated": 0,
            "attrs": sanitize(attrs),
            "ext": sanitize(self.ext),
            "contract_version": 1,
            "mapper_version": mapper_version,
        }


_validator = None

# Hand-written acceptance check for event-v1.schema.json. It only ever answers "certainly
# valid"; anything it does not recognise (including valid but unusual values such as
# 1.0 for an integer) falls back to the full jsonschema validator, which then raises the
# same ValidationError as before. Keep in sync with the schema (see test_contract_fast).
_TOP = frozenset(
    (
        "event_uid", "session_uid", "record_uid", "native_id", "native_key", "event_path",
        "seq", "ts", "parent_uid", "turn_uid", "call_id", "text", "text_truncated",
        "contract_version", "mapper_version", "kind", "actor", "ext", "attrs",
    )
)  # fmt: skip
_REQUIRED = (
    "event_uid", "session_uid", "record_uid", "native_key", "event_path", "seq", "ts",
    "kind", "actor", "attrs", "ext", "text_truncated", "contract_version", "mapper_version",
)  # fmt: skip
_KIND_SET = frozenset(KINDS)
_ACTORS = frozenset(("human", "assistant", "system", "tool", "hook", "subagent", "harness"))
_ORIGINS = frozenset(
    ("human", "queued", "notification", "peer", "automation", "injected", "unknown")
)
_ENUMS = {
    "origin": _ORIGINS,
    "usage_scope": frozenset(("call", "session_snapshot", "session_model_snapshot")),
    "measurement": frozenset(("delta", "cumulative")),
    "coverage": frozenset(("self", "root_tree", "unknown")),
    "status_scope": frozenset(
        ("direct_command", "tool_protocol", "outer_wrapper", "inner_aggregate", "unknown")
    ),
}
_NULLABLE_ENUMS = {
    "input_format": frozenset(("prompt", "question_reply")),
    "argument_digest_basis": frozenset(("canonical_json",)),
}
_TOKEN_ATTRS = (
    "input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
    "reasoning_tokens", "duration_ms", "original_chars", "known_command_results",
    "failed_command_results", "unknown_return_values",
)  # fmt: skip
_NULLABLE_STR_ATTRS = (
    "request_id", "message_digest", "argument_digest", "provider", "model_raw", "effort_raw",
)  # fmt: skip
_TIME_QUALITY = frozenset(("reported", "estimated", "missing"))
_TIME_SEMANTICS = frozenset(
    ("created", "request_start", "started", "completed", "written", "unknown")
)
_TIMEZONE_SOURCES = frozenset(("reported", "local_inferred", "unknown"))
_MEASURE_QUALITY = frozenset(("measured", "reported", "estimated", "missing"))


def _nonempty_str(value) -> bool:
    return type(value) is str and len(value) > 0


def _str_or_none(value) -> bool:
    return value is None or type(value) is str


def _token(value) -> bool:
    return value is None or (type(value) is int and value >= 0)


def _member(value, allowed) -> bool:
    return type(value) is str and value in allowed


def _measurement_ok(value) -> bool:
    if value is None:
        return True
    if type(value) is not dict:
        return False
    for name in ("chars", "surface", "quality", "complete"):
        if name not in value:
            return False
    return (
        _token(value["chars"])
        and type(value["surface"]) is str
        and _member(value["quality"], _MEASURE_QUALITY)
        and type(value["complete"]) is bool
    )


def _time_ok(time, ts) -> bool:
    if type(time) is not dict:
        return False
    for name in ("source_field", "semantics", "quality", "reported"):
        if name not in time:
            return False
    source_field, quality = time["source_field"], time["quality"]
    if not (
        _str_or_none(source_field)
        and type(time["reported"]) is dict
        and _member(quality, _TIME_QUALITY)
        and _member(time["semantics"], _TIME_SEMANTICS)
    ):
        return False
    if "timezone" in time and not _str_or_none(time["timezone"]):
        return False
    if "timezone_source" in time and not _member(time["timezone_source"], _TIMEZONE_SOURCES):
        return False
    if ts is None:
        return quality == "missing"
    return quality != "missing" and _nonempty_str(source_field)


def _attrs_ok(attrs, kind, ts) -> bool:
    if type(attrs) is not dict or "time" not in attrs or not _time_ok(attrs["time"], ts):
        return False
    get = attrs.get
    for name, allowed in _ENUMS.items():
        if name in attrs and not _member(attrs[name], allowed):
            return False
    for name, allowed in _NULLABLE_ENUMS.items():
        value = get(name)
        if value is not None and not _member(value, allowed):
            return False
    for name in _TOKEN_ATTRS:
        if name in attrs and not _token(attrs[name]):
            return False
    for name in _NULLABLE_STR_ATTRS:
        if name in attrs and not _str_or_none(attrs[name]):
            return False
    if "request_key" in attrs:
        value = attrs["request_key"]
        if type(value) is not list or not value:
            return False
    if "snapshot_key" in attrs and not _nonempty_str(attrs["snapshot_key"]):
        return False
    if "counter_cycle" in attrs and type(attrs["counter_cycle"]) is not str:
        return False
    if "cost_usd" in attrs:
        value = attrs["cost_usd"]
        if value is not None and not (type(value) in (int, float) and value >= 0):
            return False
    if "is_wrapper" in attrs and type(attrs["is_wrapper"]) is not bool:
        return False
    if "artifact_body_present" in attrs:
        value = attrs["artifact_body_present"]
        if value is not None and type(value) is not bool:
            return False
    if "writing_measurements" in attrs:
        value = attrs["writing_measurements"]
        if value is not None:
            if type(value) is not dict:
                return False
            for name in ("reply", "summary", "body"):
                if name in value and not _measurement_ok(value[name]):
                    return False
    if kind == "message.user":
        return "origin" in attrs
    if kind == "tool.call":
        return _nonempty_str(get("name"))
    if kind == "model.usage":
        for name in ("usage_scope", "measurement", "coverage", "reported"):
            if name not in attrs:
                return False
        scope, measurement = attrs["usage_scope"], attrs["measurement"]
        if scope == "call":
            return measurement == "delta" and "request_key" in attrs
        return (
            measurement == "cumulative"
            and "snapshot_key" in attrs
            and get("request_id") is None
        )
    return True


def event_certainly_valid(event) -> bool:
    """True only when ``event`` satisfies event-v1.schema.json (no false positives)."""
    if type(event) is not dict:
        return False
    for name in _REQUIRED:
        if name not in event:
            return False
    for name in event:
        if name not in _TOP:
            return False
    get = event.get
    kind, ts = event["kind"], event["ts"]
    if not (
        _nonempty_str(event["event_uid"])
        and _nonempty_str(event["session_uid"])
        and _nonempty_str(event["record_uid"])
        and _nonempty_str(event["event_path"])
        and _nonempty_str(event["mapper_version"])
        and _str_or_none(get("native_id"))
        and _str_or_none(get("parent_uid"))
        and _str_or_none(get("turn_uid"))
        and _str_or_none(get("call_id"))
        and _str_or_none(get("text"))
        and type(event["native_key"]) is list
        and event["native_key"]
        and type(event["seq"]) is int
        and event["seq"] >= 0
        and (ts is None or type(ts) is int)
        and type(event["text_truncated"]) is int
        and event["text_truncated"] in (0, 1)
        and type(event["contract_version"]) is int
        and event["contract_version"] == 1
        and _member(kind, _KIND_SET)
        and _member(event["actor"], _ACTORS)
        and type(event["ext"]) is dict
    ):
        return False
    if kind in ("tool.call", "tool.result") and not _nonempty_str(get("call_id")):
        return False
    return _attrs_ok(event["attrs"], kind, ts)


def validate_event(event: dict) -> None:
    if event_certainly_valid(event):
        return
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
