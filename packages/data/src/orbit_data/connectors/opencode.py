from orbit_data.connectors.base import BaseMapper, Mapping, decode_json, text_content
from orbit_data.contract import time_fields, unused

# opencode ToolState.status -> canonical tool status ("error" is a failed call).
TOOL_STATUS = {"completed": "completed", "error": "failed"}


def error_event_fields(error) -> tuple[str | None, dict]:
    """opencode NamedError {name, data: {message, statusCode?, isRetryable?}}."""
    if not isinstance(error, dict):
        return (error if isinstance(error, str) else None), {"error_class": None}
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    message = data.get("message")
    return (message if isinstance(message, str) else None), {
        "error_class": error.get("name") if isinstance(error.get("name"), str) else None,
        "status_code": data.get("statusCode"),
        "retryable": data.get("isRetryable"),
    }


class OpenCodeMapper(BaseMapper):
    def prepare(self, records):
        self.messages = {}
        self.v2_sessions = set()
        self.session_settings = {}

        def inspect(record):
            table, row = record.data.get("table"), record.data.get("row", {})
            if table == "message":
                self.messages[row["id"]] = {**decode_json(row.get("data"), {}), **row}
            elif table == "session_message":
                self.v2_sessions.add(row["session_id"])

        self.prepare_each(records, inspect)

    def make(self, record, *args, **kwargs):
        row = record.data.get("row", {})
        kwargs.setdefault("ts_value", row.get("time_created"))
        kwargs.setdefault("ts_field", "row.time_created")
        kwargs.setdefault("ts_unit", "milliseconds")
        event = super().make(record, *args, **kwargs)
        event.attrs["order"] = {
            "quality": "reported" if record.data.get("table") == "session_message" else "derived",
            "basis": "native_seq"
            if record.data.get("table") == "session_message"
            else "message(time_created,id),part(id)",
        }
        return event

    def map(self, record):
        table, row = record.data.get("table"), record.data.get("row", {})
        data = decode_json(row.get("data"), {}) or {}
        session_id = row.get("session_id", row.get("id") if table == "session" else None)
        if not session_id:
            return self.unknown(record)
        self.session_uid = self.store.identity(record.source_id, str(session_id))
        key = [record.source_id, str(row.get("id"))]
        if table == "session":
            meta = self.meta(
                record,
                str(row["id"]),
                kind="subagent" if row.get("parent_id") else "main",
                parent_native_id=row.get("parent_id"),
                cwd=row.get("directory"),
                title=row.get("title"),
                title_source="native",
                harness_version=row.get("version"),
            )
            meta.ext = unused(row, ("id", "directory", "title", "version", "parent_id"))
            events = [meta]
            if row.get("revert"):
                events.append(
                    self.make(
                        record,
                        "branch",
                        "session.revert",
                        attrs={"operation": "rewind"},
                        ext={"revert": decode_json(row["revert"])},
                    )
                )
            return Mapping(events)
        if table in ("message", "part") and session_id in self.v2_sessions:
            return Mapping(
                disposition="ignored", reason="V2 session_message is canonical for this session"
            )
        if table == "message":
            # V1 message holds metadata; content and per-step usage are in part rows.
            events = [
                self.make(
                    record,
                    "session.meta",
                    "message.metadata",
                    native_key=key,
                    attrs={
                        "model_raw": data.get("modelID"),
                        "provider": data.get("providerID"),
                        "effort_raw": data.get("variant"),
                        "cwd": data.get("path", {}).get("cwd"),
                    },
                    ext=data,
                )
            ]
            if data.get("role") == "assistant" and data.get("error"):
                text, attrs = error_event_fields(data["error"])
                events.append(
                    self.make(
                        record, "error", "message.error", native_key=key, text=text, attrs=attrs
                    )
                )
            return Mapping(events)
        if table == "part":
            message = self.messages.get(row.get("message_id"), {})
            self.model, self.provider = message.get("modelID"), message.get("providerID")
            self.effort = message.get("variant")
            self.native_turn = message.get("parentID") or (
                message.get("id") if message.get("role") == "user" else None
            )
            typ = data.get("type")
            if typ in ("text", "reasoning", "file"):
                events = self.message(
                    record,
                    {"role": message.get("role", "assistant"), "content": [data]},
                    origin="injected" if data.get("synthetic") else "human",
                    key=key,
                )
                return Mapping(events)
            if typ == "tool":
                state = data.get("state", {})
                call_id = str(data.get("callID", row["id"]))
                call = self.make(
                    record,
                    "tool.call",
                    "tool.call",
                    actor="assistant",
                    call_id=call_id,
                    native_key=key,
                    attrs={
                        "name": data.get("tool", "unknown"),
                        "input": state.get("input"),
                        "status": state.get("status"),
                    },
                )
                call.ts, call.attrs["time"] = time_fields(
                    state.get("time", {}).get("start"),
                    "part.state.time.start",
                    "milliseconds",
                    "started",
                )
                events = [call]
                if state.get("status") in ("completed", "error"):
                    result = self.make(
                        record,
                        "tool.result",
                        "tool.result",
                        actor="tool",
                        call_id=call_id,
                        native_key=key,
                        text=state.get("output", state.get("error")),
                        attrs={
                            "status": TOOL_STATUS[state["status"]],
                            "status_scope": "tool_protocol",
                        },
                        ext=state.get("metadata", {}),
                    )
                    result.ts, result.attrs["time"] = time_fields(
                        state.get("time", {}).get("end"),
                        "part.state.time.end",
                        "milliseconds",
                        "completed",
                    )
                    events.append(result)
                return Mapping(events)
            if typ == "step-finish":
                return Mapping(
                    [
                        self.usage(
                            record,
                            data.get("tokens", {}),
                            "opencode",
                            request_key=[record.source_id, self.session_uid, row["id"]],
                            cost_usd=data.get("cost"),
                            cost_source="native_estimate",
                            stop_reason=data.get("reason"),
                        )
                    ]
                )
            if typ == "subtask":
                # A subtask part is the request that runs another agent as a child.
                return Mapping(
                    [
                        self.make(
                            record,
                            "subagent.spawn",
                            "part.subtask",
                            native_key=key,
                            text=data.get("prompt")
                            if isinstance(data.get("prompt"), str)
                            else None,
                            attrs={
                                "agent_name": data.get("agent")
                                if isinstance(data.get("agent"), str)
                                else None
                            },
                            ext=unused(data, ("prompt",)),
                        )
                    ]
                )
            kinds = {
                "step-start": "context.inject",
                "patch": "file.change",
                "compaction": "context.compaction",
                # An agent part is an @agent mention inside a prompt, not a spawn.
                "agent": "context.inject",
                "snapshot": "file.change",
            }
            return Mapping(
                [self.make(record, kinds.get(typ, "unknown"), "part", native_key=key, ext=data)]
            )
        if table == "session_message":
            message = {**data, "id": row["id"], "type": row["type"]}
            typ = message["type"]
            if isinstance(message.get("model"), dict):
                self.session_settings[session_id] = message["model"]
            model = self.session_settings.get(session_id, {})
            self.model, self.provider, self.effort = (
                model.get("id"),
                model.get("providerID"),
                model.get("variant"),
            )
            if typ == "user":
                self.native_turn = str(row["id"])
            if typ in ("user", "assistant", "synthetic", "system"):
                payload = {
                    **message,
                    "role": typ if typ in ("user", "assistant") else "system",
                    "model": self.model,
                    "content": message.get("content", message.get("text", "")),
                }
                events = self.message(
                    record,
                    payload,
                    origin="human" if typ in ("user", "assistant") else "injected",
                    key=key,
                    include_tool_calls=False,
                )
                for event in events:
                    event.ts, event.attrs["time"] = time_fields(
                        message.get("time", {}).get("created"),
                        "message.time.created",
                        "milliseconds",
                        "created",
                    )
                if typ == "assistant":
                    blocks = message.get("content", [])
                    if isinstance(blocks, dict):
                        blocks = [blocks]
                    for index, block in enumerate(blocks if isinstance(blocks, list) else []):
                        if isinstance(block, dict) and block.get("type") == "tool":
                            try:
                                events.extend(self._v2_tool(record, block, key, index))
                            except (KeyError, TypeError, AttributeError, ValueError):
                                # One malformed tool must not discard the answer and
                                # healthy tools beside it. Keep its complete evidence.
                                events.append(
                                    self.make(
                                        record,
                                        "unknown",
                                        f"content[{index}].tool",
                                        native_key=key,
                                        ext={"block": block},
                                    )
                                )
                    if message.get("error"):
                        text, attrs = error_event_fields(message["error"])
                        events.append(
                            self.make(
                                record,
                                "error",
                                "assistant.error",
                                native_key=key,
                                text=text,
                                attrs=attrs,
                                ext=message["error"]
                                if isinstance(message["error"], dict)
                                else {"error": message["error"]},
                            )
                        )
                if typ == "assistant" and message.get("tokens"):
                    events.append(
                        self.usage(
                            record,
                            message["tokens"],
                            "opencode",
                            request_key=[record.source_id, self.session_uid, row["id"]],
                            cost_usd=message.get("cost"),
                            cost_source="native_estimate",
                        )
                    )
                return Mapping(events)
            if typ == "shell":
                call = self.make(
                    record,
                    "tool.call",
                    "shell.call",
                    actor="human",
                    call_id=message["callID"],
                    native_key=key,
                    attrs={"name": "shell", "input": {"command": message.get("command")}},
                )
                call.ts, call.attrs["time"] = time_fields(
                    message.get("time", {}).get("created"),
                    "message.time.created",
                    "milliseconds",
                    "started",
                )
                result = self.make(
                    record,
                    "tool.result",
                    "shell.result",
                    actor="tool",
                    call_id=message["callID"],
                    native_key=key,
                    text=message.get("output"),
                    attrs={"status": "unknown", "status_scope": "direct_command"},
                )
                result.ts, result.attrs["time"] = time_fields(
                    message.get("time", {}).get("completed"),
                    "message.time.completed",
                    "milliseconds",
                    "completed",
                )
                return Mapping([call, result])
            kinds = {
                "compaction": "context.compaction",
                "model-switched": "setting.change",
                "agent-switched": "setting.change",
            }
            return Mapping(
                [
                    self.make(
                        record, kinds.get(typ, "unknown"), "message", native_key=key, ext=message
                    )
                ]
            )
        return self.unknown(record)

    def _v2_tool(self, record, block, key, index):
        state, times = block.get("state", {}), block.get("time", {})
        call = self.make(
            record,
            "tool.call",
            f"content[{index}].call",
            actor="assistant",
            native_key=key,
            call_id=block["id"],
            attrs={
                "name": block["name"],
                "input": decode_json(state.get("input")),
                "status": state.get("status", "unknown"),
            },
        )
        call.ts, call.attrs["time"] = time_fields(
            times.get("ran"), f"content[{index}].time.ran", "milliseconds", "started"
        )
        events = [call]
        if state.get("status") in ("completed", "error"):
            result = self.make(
                record,
                "tool.result",
                f"content[{index}].result",
                actor="tool",
                native_key=key,
                call_id=block["id"],
                text=text_content(state.get("content"))
                or error_event_fields(state.get("error"))[0],
                attrs={
                    "status": TOOL_STATUS[state["status"]],
                    "status_scope": "tool_protocol",
                    "name": block["name"],
                },
                ext=state,
            )
            result.ts, result.attrs["time"] = time_fields(
                times.get("completed"),
                f"content[{index}].time.completed",
                "milliseconds",
                "completed",
            )
            events.append(result)
        return events
