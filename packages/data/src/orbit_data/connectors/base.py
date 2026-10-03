"""Small connector interface. One native reader maps into the shared contract."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from orbit_data.contract import EventDraft, RawRecord, normalize_usage, time_fields, uid, unused

# Exact native-key match through the compact tail index (migration 009). The tail term is
# implied by the full comparison, so results equal ``native_key=?1``.
NATIVE_KEY_MATCH = "substr(native_key,-24)=substr(?1,-24) AND native_key=?1"


@dataclass
class Mapping:
    events: list[EventDraft] = field(default_factory=list)
    disposition: str | None = None
    reason: str | None = None
    references: list[str] = field(default_factory=list)


class Connector(Protocol):
    def prepare(self, records: Iterable[RawRecord]) -> None: ...
    def map(self, record: RawRecord) -> Mapping: ...


def text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if "content" in content:
            return text_content(content["content"])
        return json.dumps(content, ensure_ascii=False)
    if not isinstance(content, list):
        return ""
    return "\n".join(block if isinstance(block, str) else text_content(block) for block in content)


def decode_json(value, fallback=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback if fallback is not None else value
    return value if value is not None else fallback


def media_type(block: dict) -> str | None:
    """Anthropic blocks nest {source: {media_type}}; pi puts mimeType on the block.
    Some harnesses write source as a bare URL/path string, which carries no type."""
    source = block.get("source")
    value = source.get("media_type") if isinstance(source, dict) else block.get("mimeType")
    return value if isinstance(value, str) else None


class BaseMapper:
    def __init__(self, store, file_info):
        self.store = store
        self.info = file_info
        self.header = {}
        self.session_uid = None
        self.model = None
        self.provider = None
        self.effort = None
        self.native_turn = None
        self.first = True

    def prepare(self, records: Iterable[RawRecord]) -> None:
        first = next(iter(records), None)
        if first:
            self.header = first.data

    def prepare_each(self, records, callback):
        """One malformed record must not prevent healthy neighbours from mapping."""
        self.preparation_failures = set()
        for record in records:
            try:
                callback(record)
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                self.preparation_failures.add(record.record_uid)
                self.store.issue(
                    record.source_id,
                    "native_preparation_error",
                    file_id=record.file_id,
                    record_uid=record.record_uid,
                    detail={"exception": type(error).__name__},
                )
                self.store.db.execute(
                    "UPDATE raw_record SET disposition='unparsed',note=? WHERE record_uid=?",
                    ('{"reason":"native_preparation_error"}', record.record_uid),
                )

    def native_key(self, record: RawRecord) -> list:
        native = record.data.get("uuid", record.data.get("id"))
        return [
            record.source_id,
            record.relative_path,
            native if native is not None else record.ordinal,
        ]

    def make(
        self,
        record: RawRecord,
        kind: str,
        path: str,
        *,
        actor="harness",
        attrs=None,
        text=None,
        call_id=None,
        native_key=None,
        ext=None,
        ts_value=None,
        ts_field="timestamp",
        ts_unit="iso",
        semantics="written",
        relation="mapped",
    ) -> EventDraft:
        if text is not None and not isinstance(text, str):
            raise ValueError("Native text must be a string")
        for attr_name in (
            "cwd",
            "model_raw",
            "provider",
            "effort_raw",
            "name",
            "native_id",
            "title",
            "git_branch",
            "git_sha",
            "git_remote",
        ):
            value = (attrs or {}).get(attr_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"Native {attr_name} must be a string")
        stamp, time = time_fields(
            record.data.get(ts_field) if ts_value is None else ts_value,
            ts_field,
            ts_unit,
            semantics,
        )
        for time_field in ("timestamp", "time"):
            if time_field in record.data:
                time["reported"].setdefault(time_field, record.data[time_field])
        attributes = {
            "time": time,
            "order": {"quality": "reported", "basis": "source_position"},
            **(attrs or {}),
        }
        for key, value in (
            ("model_raw", self.model),
            ("provider", self.provider),
            ("effort_raw", self.effort),
        ):
            if value is not None:
                attributes.setdefault(key, value)
        if self.native_turn is not None:
            attributes.setdefault("native_turn_id", str(self.native_turn))
        event = EventDraft(
            self.session_uid,
            native_key or self.native_key(record),
            path,
            kind,
            actor,
            stamp,
            attributes,
            ext if ext is not None else {},
            text,
            call_id,
            str(record.data.get("uuid", record.data.get("id")))
            if record.data.get("uuid", record.data.get("id")) is not None
            else None,
            relation=relation,
        )
        return event

    def meta(self, record: RawRecord, native_id: str, *, file_scope=None, **attrs) -> EventDraft:
        self.session_uid = self.store.identity(record.source_id, native_id, file_scope)
        parent_id = attrs.pop("parent_native_id", None)
        if parent_id:
            attrs["parent_uid"] = self.store.identity(record.source_id, parent_id)
        attrs = {"kind": "main", "native_id": native_id, **attrs}
        return self.make(
            record,
            "session.meta",
            "envelope.session",
            native_key=[record.source_id, record.relative_path, native_id, "session"],
            attrs=attrs,
        )

    def usage(
        self,
        record: RawRecord,
        reported: dict,
        dialect: str,
        *,
        request_id=None,
        request_key=None,
        scope="call",
        coverage="self",
        path="message.usage",
        **attrs,
    ):
        request_key = request_key or [
            record.source_id,
            self.session_uid,
            request_id or self.native_key(record),
        ]
        attributes = {
            **normalize_usage(reported, dialect),
            "usage_scope": scope,
            "measurement": "delta" if scope == "call" else "cumulative",
            "coverage": coverage,
            "provider": self.provider,
            "model_raw": self.model,
            "effort_raw": self.effort,
            "purpose": "main",
            "request_id": request_id,
            **attrs,
        }
        if scope == "call":
            attributes["request_key"] = request_key
            key = ["request", request_key]
        else:
            attributes["request_id"] = None
            attributes.setdefault(
                "snapshot_key",
                uid(
                    "snapshot_key",
                    record.source_id,
                    self.session_uid,
                    scope,
                    self.provider,
                    self.model,
                    attributes["purpose"],
                    coverage,
                ),
            )
            attributes.setdefault("counter_cycle", "unknown")
            key = [record.source_id, record.record_uid, "snapshot"]
        return self.make(
            record, "model.usage", path, actor="assistant", attrs=attributes, native_key=key
        )

    def message(
        self,
        record: RawRecord,
        message: dict,
        *,
        origin="human",
        base_path="message",
        key=None,
        include_tool_calls=True,
        **attrs,
    ) -> list[EventDraft]:
        role = message.get("role", "assistant")
        is_tool = role in ("tool", "toolResult")
        content = message.get("content", message.get("text", ""))
        if is_tool:
            call_id = message.get("tool_call_id", message.get("toolCallId"))
            if not call_id:
                return [self.make(record, "unknown", base_path, ext={"message": message})]
            return [
                self.make(
                    record,
                    "tool.result",
                    base_path + ".result",
                    actor="tool",
                    call_id=str(call_id),
                    text=text_content(content),
                    native_key=key,
                    attrs={
                        "name": message.get("toolName", message.get("tool_name")),
                        "status": "failed"
                        if message.get("isError") is True
                        else "completed"
                        if message.get("isError") is False
                        else "unknown",
                        **attrs,
                    },
                    ext=unused(
                        message,
                        (
                            "role",
                            "content",
                            "text",
                            "tool_call_id",
                            "toolCallId",
                            "toolName",
                            "tool_name",
                            "isError",
                        ),
                    ),
                )
            ]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        elif isinstance(content, dict):
            content = [content]
        result = []
        for index, block in enumerate(content or []):
            if isinstance(block, str):
                block = {"type": "text", "text": block}
            if not isinstance(block, dict):
                result.append(
                    self.make(
                        record, "unknown", f"{base_path}.content[{index}]", ext={"block": block}
                    )
                )
                continue
            typ = block.get("type", "unknown")
            path = f"{base_path}.content[{index}]"
            block_attrs = dict(attrs)
            consumed = ("type",)
            if typ in ("text", "input_text", "output_text", "Text"):
                kind = "message.user" if role == "user" else "message.assistant"
                if role in ("system", "developer") or origin == "injected":
                    kind = "context.inject"
                if kind == "message.user":
                    block_attrs["origin"] = origin
                block_attrs["phase"] = message.get("phase")
                block_attrs["model_raw"] = message.get("model", self.model)
                consumed = ("type", "text")
                event = self.make(
                    record,
                    kind,
                    path + ".text",
                    actor="human"
                    if kind == "message.user" and origin == "human"
                    else "assistant"
                    if role == "assistant"
                    else "system",
                    attrs=block_attrs,
                    text=block.get("text"),
                    native_key=key,
                )
            elif typ in ("thinking", "reasoning"):
                event = self.make(
                    record,
                    "reasoning",
                    path + ".reasoning",
                    actor="assistant",
                    attrs=block_attrs,
                    text=block.get("thinking", block.get("text")),
                    native_key=key,
                )
                consumed = ("type", "thinking", "text")
            elif typ in ("tool_use", "toolCall", "tool-call", "tool"):
                if not include_tool_calls:
                    continue
                call_id = block.get("id", block.get("callID"))
                if not call_id or not block.get("name", block.get("tool")):
                    event = self.make(record, "unknown", path, ext={"block": block})
                else:
                    block_attrs.update(
                        name=block.get("name", block.get("tool")),
                        input=decode_json(block.get("input", block.get("arguments"))),
                    )
                    event = self.make(
                        record,
                        "tool.call",
                        path + ".call",
                        actor="assistant",
                        call_id=str(call_id),
                        attrs=block_attrs,
                        native_key=key,
                    )
                consumed = ("type", "id", "callID", "name", "tool", "input", "arguments")
            elif typ in ("tool_result", "tool-result"):
                call_id = block.get("tool_use_id", block.get("toolCallId"))
                if not call_id:
                    event = self.make(record, "unknown", path, ext={"block": block})
                else:
                    event = self.make(
                        record,
                        "tool.result",
                        path + ".result",
                        actor="tool",
                        call_id=str(call_id),
                        text=text_content(block.get("content")),
                        native_key=key,
                        attrs={
                            "status": "failed"
                            if block.get("is_error", block.get("isError")) is True
                            else "completed"
                            if block.get("is_error", block.get("isError")) is False
                            else "unknown",
                            **block_attrs,
                        },
                    )
                consumed = ("type", "tool_use_id", "toolCallId", "content", "is_error", "isError")
            elif typ in (
                "image",
                "input_image",
                "local_image",
                "localImage",
                "LocalImage",
                "Image",
                "document",
                "file",
                "audio",
                "Audio",
            ):
                event = self.make(
                    record,
                    "context.inject",
                    path + ".attachment",
                    actor="system",
                    native_key=key,
                    attrs={
                        "content_type": typ,
                        "raw_content_path": path,
                        "mime_type": media_type(block),
                        **block_attrs,
                    },
                )
                # Large inline bytes stay in the exact L0 record, addressed by raw_content_path.
                consumed = tuple(block)
            else:
                event = self.make(record, "unknown", path, native_key=key, ext={"block": block})
            event.ext.update(unused(block, consumed))
            result.append(event)
        if result:
            result[0].ext["message_fields"] = unused(
                message, ("role", "content", "text", "usage", "model", "phase")
            )
        return result

    def unknown(self, record: RawRecord) -> Mapping:
        return Mapping([self.make(record, "unknown", "raw", ext=record.data)])
