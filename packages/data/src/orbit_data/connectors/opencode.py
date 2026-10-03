import re

from orbit_data import tool_kinds
from orbit_data.connectors.base import (
    BaseMapper,
    Mapping,
    decode_json,
    mcp_server_names,
    split_mcp_name,
    text_content,
)
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


def sanitize(value: str) -> str:
    """packages/opencode/src/mcp/catalog.ts ``sanitize``; MCP tools are registered as
    ``toolName(client, name) = sanitize(client) + "_" + sanitize(name)``."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)


# Exact messages of packages/core/src/v1/permission.ts errors, stored verbatim as the V1
# tool part ``state.error`` (session/processor.ts: ``error: errorMessage(error)``).
_REJECTED = "The user rejected permission to use this specific tool call."
_CORRECTED = "The user rejected permission to use this specific tool call with the following"
_RULE_DENIED = (
    "The user has specified a rule which prevents you from using this specific tool call."
)


def permission_refusal(error_text) -> str | None:
    """ "user" | "rule" when the tool error is an opencode permission refusal."""
    if not isinstance(error_text, str):
        return None
    if error_text == _REJECTED or error_text.startswith(_CORRECTED):
        return "user"
    if error_text.startswith(_RULE_DENIED):
        return "rule"
    return None


def tool_error_text(error) -> str | None:
    """V1 state.error is a string; V2 is ``{type: "unknown", message}`` (schema
    session-message.ts UnknownError); NamedError keeps ``data.message``."""
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        if isinstance(error.get("message"), str):
            return error["message"]
        return error_event_fields(error)[0]
    return None


def shell_exit(name, metadata) -> int | None:
    """Shell tool metadata ``exit`` (packages/opencode/src/tool/shell.ts)."""
    if name not in ("bash", "shell") or not isinstance(metadata, dict):
        return None
    code = metadata.get("exit")
    return code if isinstance(code, int) and not isinstance(code, bool) else None


class OpenCodeMapper(BaseMapper):
    def prepare(self, records):
        self.messages = {}
        self.v2_sessions = set()
        self.session_settings = {}
        self.v1_settings = {}
        self.mcp_servers = mcp_server_names(self.store, "opencode")

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
            # The session row is the session header; a message only records a setting
            # change when its model/provider/variant/cwd differ from the last one seen.
            path = data.get("path") if isinstance(data.get("path"), dict) else {}
            setting = {
                "model_raw": data.get("modelID"),
                "provider": data.get("providerID"),
                "effort_raw": data.get("variant"),
                "cwd": path.get("cwd"),
            }
            previous = self.v1_settings.setdefault(session_id, {})
            changed = {k: v for k, v in setting.items() if v is not None and previous.get(k) != v}
            previous.update(changed)
            events = []
            if changed:
                events.append(
                    self.make(
                        record,
                        "setting.change",
                        "message.metadata",
                        native_key=key,
                        attrs=setting,
                        ext=data,
                    )
                )
            if data.get("role") == "assistant" and data.get("error"):
                text, attrs = error_event_fields(data["error"])
                events.append(
                    self.make(
                        record, "error", "message.error", native_key=key, text=text, attrs=attrs
                    )
                )
            if not events:
                return Mapping(
                    disposition="ignored",
                    reason="message metadata unchanged; content is in part rows",
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
                        **self._mcp(data.get("tool")),
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
                    metadata = (
                        state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
                    )
                    attrs = self._result_attrs(
                        record,
                        events,
                        call_id,
                        data.get("tool"),
                        state,
                        metadata,
                        key,
                    )
                    result = self.make(
                        record,
                        "tool.result",
                        "tool.result",
                        actor="tool",
                        call_id=call_id,
                        native_key=key,
                        text=state.get("output", state.get("error")),
                        attrs=attrs,
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
                            # One step-finish part per LLM step (session/processor.ts).
                            request_id=str(row["id"]),
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
                    for index, block in enumerate(message.get("content", [])):
                        if block.get("type") == "tool":
                            events.extend(self._v2_tool(record, block, key, index))
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
                            # One V2 assistant message per step: created on
                            # session.next.step.started, tokens set on step.ended
                            # (core/src/session/message-updater.ts).
                            request_id=str(row["id"]),
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
                **self._mcp(block["name"]),
            },
        )
        call.ts, call.attrs["time"] = time_fields(
            times.get("ran"), f"content[{index}].time.ran", "milliseconds", "started"
        )
        events = [call]
        if state.get("status") in ("completed", "error"):
            structured = (
                state.get("structured") if isinstance(state.get("structured"), dict) else {}
            )
            attrs = self._result_attrs(
                record, events, block["id"], block["name"], state, structured, key
            )
            result = self.make(
                record,
                "tool.result",
                f"content[{index}].result",
                actor="tool",
                native_key=key,
                call_id=block["id"],
                text=text_content(state.get("content")) or tool_error_text(state.get("error")),
                attrs={**attrs, "name": block["name"]},
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

    def _mcp(self, name) -> dict:
        """mcp_server/mcp_tool for ``<client>_<tool>`` names of inventoried MCP servers."""
        if not isinstance(name, str) or tool_kinds.tool_kind(name, "opencode")[1]:
            return {}
        split = split_mcp_name(name, "", self.mcp_servers, sanitize)
        return {"mcp_server": split[0], "mcp_tool": split[1]} if split else {}

    def _result_attrs(self, record, events, call_id, name, state, metadata, key) -> dict:
        """Result status plus recorded failure evidence; appends a permission decision
        (before the result, so the reducer attaches it to the open call)."""
        attrs = {"status": TOOL_STATUS[state["status"]], "status_scope": "tool_protocol"}
        exit_code = shell_exit(name, metadata)
        if exit_code is not None:
            attrs["exit_code"] = exit_code
        if state["status"] != "error":
            return attrs
        error = state.get("error")
        if isinstance(error, dict) and isinstance(error.get("name"), str):
            attrs["error_class"] = error["name"]
        if metadata.get("interrupted") is True:
            # processor.ts marks aborted calls "Tool execution aborted" + interrupted.
            attrs["status"] = "interrupted"
        refusal = permission_refusal(tool_error_text(error))
        if refusal:
            attrs["error_class"] = "permission_refused"
            events.append(
                self.make(
                    record,
                    "permission.decision",
                    f"permission.{call_id}",
                    call_id=str(call_id),
                    native_key=[*key, "permission", str(call_id)],
                    attrs={"decision": "denied", "reason": refusal},
                )
            )
        return attrs
