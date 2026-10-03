"""DSH physical formats 0-4; packed chunks are indexed without per-token expansion."""

from tandem_data.connectors.base import (
    NATIVE_KEY_MATCH,
    BaseMapper,
    Mapping,
    decode_json,
    text_content,
)
from tandem_data.contract import canonical, uid

CHUNKS = {"assistant/chunk", "text-chunks", "reasoning-chunks", "tool-call-chunks"}


class DshMapper(BaseMapper):
    def prepare(self, records):
        self.header, self.final_records, self.fragments = {}, {}, {}
        self.cut, self.parent, self.attempt = 0, None, 0
        self.record_steps = {}
        attempt = 0

        def inspect(record):
            nonlocal attempt
            data, typ = record.data, record.data.get("type")
            payload = data.get("data", {})
            if typ == "session":
                self.header, self.parent = data, data.get("parentSession")
                self.cut = data.get("seedLength", 0)
                self.session_uid = self.store.identity(record.source_id, str(data["id"]))
                if data.get("version", 0) not in range(5):
                    self.store.issue(
                        record.source_id, "unsupported_native_version", file_id=record.file_id
                    )
            if typ == "session/end-seed" and payload.get("inherited"):
                self.cut = data.get("seq", 0) + 1
            if typ == "llm/retry-started":
                attempt += 1
            key = (payload.get("turn"), payload.get("step"), attempt)
            if typ in CHUNKS or typ in ("assistant/message", "assistant/attempt"):
                self.record_steps[record.record_uid] = key
            if typ == "assistant/message":
                self.final_records[key] = (record.record_uid, self.native_key(record))
                if key in self.fragments:
                    self.fragments[key]["text"].clear()
                    self.fragments[key]["reasoning"].clear()
                    self.fragments[key]["last"] = None
            if typ in CHUNKS:
                fragment = self.fragments.setdefault(
                    key, {"records": [], "text": [], "reasoning": [], "usage": None, "last": record}
                )
                fragment["last"] = record
                fragment["records"].append(record.record_uid)
                if typ in ("text-chunks", "reasoning-chunks"):
                    texts = payload.get("texts", [])
                    if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
                        raise ValueError("Invalid packed strings")
                    dt = payload.get("dt", [])
                    if len(dt) != max(0, len(texts) - 1):
                        raise ValueError("Invalid packed timing")
                    fragment["text" if typ == "text-chunks" else "reasoning"].extend(texts)
                elif typ == "assistant/chunk":
                    chunk = payload.get("chunk", {})
                    if chunk.get("type") == "text-delta":
                        fragment["text"].append(chunk.get("text", chunk.get("delta", "")))
                    elif chunk.get("type") == "reasoning-delta":
                        fragment["reasoning"].append(chunk.get("text", chunk.get("delta", "")))
                    elif chunk.get("type") == "usage":
                        fragment["usage"] = chunk.get("usage")

        self.prepare_each(records, inspect)
        self.chunk_targets = {}
        for key, fragment in self.fragments.items():
            final = self.final_records.get(key)
            target_key = final[1] if final else self.native_key(fragment["last"])
            # A stable stream evidence event is emitted even for tool-only/empty responses.
            ref = uid("event", target_key, "context.inject", "stream.evidence")
            for record_id in fragment["records"]:
                self.chunk_targets[record_id] = ref

    def native_key(self, record):
        return [
            record.source_id,
            self.session_uid,
            record.data.get("seq", record.data.get("seq0", record.ordinal)),
        ]

    def make(self, *args, **kwargs):
        kwargs.setdefault("ts_field", "time")
        kwargs.setdefault("ts_unit", "milliseconds")
        return super().make(*args, **kwargs)

    def _stream_evidence(self, record, partial=False):
        return self.make(
            record,
            "context.inject",
            "stream.evidence",
            attrs={"context_type": "stream_provenance", "partial": partial},
        )

    def map(self, record):
        data, typ = record.data, record.data.get("type")
        payload = data.get("data", {})
        if typ == "session":
            meta = self.meta(
                record,
                str(data["id"]),
                kind="subagent" if data.get("origin") == "subagent" else "main",
                cwd=data.get("cwd"),
                harness_version=str(data.get("version")),
                depth=data.get("delegationDepth", 0),
                parent_native_id=data.get("parentSession")
                if data.get("origin") == "subagent"
                else None,
                forked_from_native=data.get("parentSession")
                if data.get("origin") != "subagent"
                else None,
            )
            from tandem_data.contract import time_fields

            if data.get("createdAt") is not None:
                meta.ts, meta.attrs["time"] = time_fields(
                    data["createdAt"], "createdAt", "milliseconds", "created"
                )
                if data.get("time") is not None:
                    meta.attrs["time"]["reported"]["time"] = data["time"]
            return Mapping([meta])
        if self.session_uid is None:
            raise ValueError("DSH session header required")
        self.native_turn = payload.get("turn", self.native_turn)
        seq = data.get("seq", data.get("seq0"))
        if seq is not None and seq < self.cut and self.parent:
            parent_uid = self.store.identity(record.source_id, self.parent)
            refs = [
                r[0]
                for r in self.store.db.execute(
                    "SELECT event_uid FROM event WHERE " + NATIVE_KEY_MATCH,
                    (canonical([record.source_id, parent_uid, seq]),),
                )
            ]
            return Mapping(
                disposition="replayed" if refs else "unparsed",
                references=refs,
                reason="inherited_seed_prefix",
            )
        key = self.record_steps.get(record.record_uid)
        if typ in CHUNKS:
            fragment = self.fragments[key]
            if key not in self.final_records and fragment["last"].record_uid == record.record_uid:
                events = [self._stream_evidence(record, True)]
                for field, kind in [("text", "message.assistant"), ("reasoning", "reasoning")]:
                    if fragment[field]:
                        events.append(
                            self.make(
                                record,
                                kind,
                                "partial." + field,
                                actor="assistant",
                                text="".join(fragment[field]),
                                attrs={"partial": True},
                            )
                        )
                if fragment["usage"]:
                    events.append(
                        self.usage(
                            record,
                            fragment["usage"],
                            "dsh",
                            request_key=[record.source_id, self.session_uid, list(key)],
                            purpose="incomplete_attempt",
                        )
                    )
                return Mapping(events)
            return Mapping(
                disposition="folded",
                references=[self.chunk_targets[record.record_uid]],
                reason="stream_to_response",
            )
        if typ in ("turn/start", "turn/end"):
            reason = payload.get("reason", {})
            reason = reason.get("kind") if isinstance(reason, dict) else reason
            state = {
                "aborted": "interrupted",
                "error": "failed",
                "interrupted": "interrupted",
                "completed": "completed",
                "max-tokens": "interrupted",
                "blocked": "interrupted",
                "forked": "interrupted",
            }.get(reason, "unknown")
            return Mapping(
                [
                    self.make(
                        record,
                        "turn.start" if typ.endswith("start") else "turn.end",
                        typ,
                        attrs={"status": "active" if typ.endswith("start") else state},
                        ext=payload,
                    )
                ]
            )
        if typ in ("assistant/message", "assistant/attempt"):
            message = payload.get("message", {})
            source = message.get("source")
            source = source if isinstance(source, dict) else {}
            self.model, self.provider = (
                source.get("model", self.model),
                source.get("provider", self.provider),
            )
            events = (
                self.message(record, message, include_tool_calls=False)
                if typ == "assistant/message"
                else [self.make(record, "error", "attempt", ext=payload)]
            )
            if (
                key in self.fragments
                and self.final_records.get(key, (None,))[0] == record.record_uid
            ):
                events.append(self._stream_evidence(record))
            usage = payload.get("usage")
            if usage is None:
                for part in payload.get("stream", []):
                    if part.get("type") == "chunk" and part.get("chunk", {}).get("type") == "usage":
                        usage = part["chunk"].get("usage")
            if usage:
                events.append(
                    self.usage(
                        record,
                        usage,
                        "dsh",
                        request_key=[
                            record.source_id,
                            self.session_uid,
                            data.get("seq", record.ordinal),
                        ],
                        purpose="main" if typ == "assistant/message" else "retry",
                    )
                )
            return Mapping(
                events or [self.make(record, "context.inject", "empty.response", ext=payload)]
            )
        if typ in ("user/message", "system/message", "developer/message"):
            message = payload.get("message", payload)
            source = message.get("source")
            source = source if isinstance(source, dict) else {}
            origin = source.get("kind")
            if origin == "plugin":
                origin = source.get("plugin")
            origin = (
                "human"
                if origin == "user" and self.header.get("origin") != "subagent"
                else "notification"
                if origin in ("subagent-settled", "agent-message", "subagent-report")
                else "automation"
                if origin == "goal"
                else "injected"
            )
            events = self.message(record, message, origin=origin)
            if isinstance(data.get("surfaceOp"), dict) and data["surfaceOp"].get("op") == "replace":
                for event in events:
                    event.kind, event.actor = "context.compaction", "harness"
            return Mapping(events or [self.make(record, "context.inject", typ, ext=payload)])
        if typ == "tool/call":
            call_id = str(payload["callId"])
            return Mapping(
                [
                    self.make(
                        record,
                        "tool.call",
                        "tool.call",
                        actor="assistant",
                        call_id=call_id,
                        attrs={
                            "name": payload["name"],
                            "input": decode_json(payload.get("arguments")),
                        },
                        ext=payload,
                    )
                ]
            )
        if typ == "tool/result":
            message = payload.get("message", payload)
            # v0-v3 tool role encloses a tool-result block; v4 lifts it to the message.
            if not message.get("toolCallId"):
                blocks = message.get("content", [])
                block = next(
                    (b for b in blocks if isinstance(b, dict) and b.get("type") == "tool-result"),
                    None,
                )
                if block:
                    message = {**block, "role": "tool"}
            events = self.message(record, message, origin="injected")
            if isinstance(data.get("surfaceOp"), dict) and data["surfaceOp"].get("op") == "replace":
                for event in events:
                    event.kind, event.actor = "context.compaction", "harness"
            for event in events:
                error = payload.get("error")
                event.attrs["error_class"] = error.get("code") if isinstance(error, dict) else None
            return Mapping(events)
        if typ in ("request/header", "request/context", "model/selection"):
            config = payload.get("header", {}).get("config", payload)
            self.model, self.provider = (
                config.get("model", self.model),
                config.get("provider", self.provider),
            )
            self.effort = config.get("reasoningEffort", self.effort)
            return Mapping(
                [
                    self.make(
                        record,
                        "setting.change",
                        typ,
                        attrs={
                            "model_raw": self.model,
                            "provider": self.provider,
                            "effort_raw": self.effort,
                        },
                        ext=payload,
                    )
                ]
            )
        if typ == "session/title":
            return Mapping(
                [
                    self.make(
                        record,
                        "session.title",
                        typ,
                        text=payload.get("title"),
                        attrs={"title_source": "native"},
                    )
                ]
            )
        if typ == "llm/retry":
            failure = payload.get("failure")
            failure = failure if isinstance(failure, dict) else {}
            message = failure.get("message")
            return Mapping(
                [
                    self.make(
                        record,
                        "error",
                        typ,
                        text=message if isinstance(message, str) else None,
                        attrs={
                            "error_class": failure.get("code"),
                            "retry_id": payload.get("retryId"),
                            "attempt": payload.get("retry"),
                            "max_retries": payload.get("maxRetries"),
                            "delay_ms": payload.get("delayMs"),
                            "provider": payload.get("provider")
                            if isinstance(payload.get("provider"), str)
                            else None,
                            "recoverable": True,
                        },
                        ext=payload,
                    )
                ]
            )
        kinds = {
            "approval/asked": "permission.request",
            "approval/decided": "permission.decision",
            "subagent/catalog": "subagent.spawn",
            "subagent/descriptor": "subagent.spawn",
            "todo/write": "plan.update",
            "hook/invoked": "hook.run",
            "hook/result": "hook.run",
            "sandbox/mode": "setting.change",
            "approval/policy": "setting.change",
            "permission/preset": "setting.change",
            "agent-preset/selected": "setting.change",
            # One retry writes `llm/retry` (failure + backoff) then `llm/retry-started`
            # (the re-issued request). Only the former is an error; the latter is
            # loop state, so a recovered retry counts once in error totals.
            "llm/retry-started": "ui.state",
            "agent/inbox/spliced": "queue",
            "command/run": "context.inject",
            "command/done": "context.inject",
            "session/title-llm-request": "context.inject",
            "web/deepseek-search-llm-request": "context.inject",
        }
        if typ in kinds:
            return Mapping(
                [
                    self.make(
                        record,
                        kinds[typ],
                        typ,
                        call_id=payload.get("callId"),
                        attrs={
                            "permission_id": payload.get("id"),
                            "decision": payload.get("outcome"),
                        },
                        ext=payload,
                    )
                ]
            )
        if str(typ).startswith("compaction/"):
            events = [
                self.make(
                    record,
                    "context.compaction",
                    typ,
                    text=text_content(payload.get("summary")),
                    ext=payload,
                )
            ]
            if payload.get("usage"):
                events.append(self.usage(record, payload["usage"], "dsh", purpose="compaction"))
            return Mapping(events)
        if typ in ("step/start", "step/end", "session/end-seed"):
            return Mapping(disposition="ignored", reason="control_record_in_L0")
        return self.unknown(record)
