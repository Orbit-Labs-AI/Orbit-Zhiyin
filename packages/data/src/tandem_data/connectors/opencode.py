from tandem_data.connectors.base import BaseMapper, Mapping, decode_json
from tandem_data.contract import time_fields, unused


class OpenCodeMapper(BaseMapper):
    def prepare(self, records):
        self.messages = {}
        self.v2_sessions = set()
        self.prepare_each(records, self.prepare_record)

    def prepare_record(self, record):
        table, row = record.data.get("table"), record.data.get("row", {})
        if table == "message":
            self.messages[row["id"]] = {**decode_json(row.get("data"), {}), **row}
        elif table == "session_message":
            self.v2_sessions.add(row["session_id"])

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
            return Mapping([meta])
        if table in ("message", "part") and session_id in self.v2_sessions:
            return Mapping(
                disposition="ignored", reason="V2 session_message is canonical for this session"
            )
        if table == "message":
            # V1 message holds metadata; content and per-step usage are in part rows.
            return Mapping(
                [
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
            )
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
                        attrs={"status": state["status"]},
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
            kinds = {
                "step-start": "context.inject",
                "patch": "file.change",
                "compaction": "context.compaction",
                "agent": "subagent.spawn",
                "subtask": "subagent.spawn",
                "snapshot": "file.change",
            }
            return Mapping(
                [self.make(record, kinds.get(typ, "unknown"), "part", native_key=key, ext=data)]
            )
        if table == "session_message":
            message = {**data, "id": row["id"], "type": row["type"]}
            typ = message["type"]
            self.model = message.get("model", {}).get("id")
            self.provider = message.get("model", {}).get("providerID")
            self.effort = message.get("model", {}).get("variant")
            if typ in ("user", "assistant", "synthetic", "system"):
                payload = {
                    **message,
                    "model": self.model,
                    "role": typ if typ in ("user", "assistant") else "system",
                    "content": message.get("content", message.get("text", "")),
                }
                events = self.message(
                    record,
                    payload,
                    origin="human"
                    if typ == "user"
                    else "unknown"
                    if typ == "assistant"
                    else "injected",
                    key=key,
                )
                for event in events:
                    event.ts, event.attrs["time"] = time_fields(
                        message.get("time", {}).get("created"),
                        "message.time.created",
                        "milliseconds",
                        "created",
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
