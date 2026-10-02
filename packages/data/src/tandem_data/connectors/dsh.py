from tandem_data.connectors.base import BaseMapper, Mapping, decode_json, text_content
from tandem_data.contract import canonical, uid


class DshMapper(BaseMapper):
    def prepare(self, records):
        self.chunk_targets = {}
        self.cut = 0
        self.parent = None
        self.prepare_each(records, self.prepare_record)

    def prepare_record(self, record):
        data = record.data
        if data.get("type") == "session":
            self.header = data
            self.parent = data.get("parentSession")
            self.cut = data.get("seedLength", data.get("inheritedEventCount", 0))
            self.session_uid = self.store.identity(record.source_id, str(data["id"]))
        if data.get("type") == "session/end-seed" and data.get("data", {}).get("inherited"):
            self.cut = data.get("seq", 0)
        if data.get("type") == "assistant/message":
            payload = data.get("data", {})
            key = [record.source_id, self.session_uid, data.get("seq", record.ordinal)]
            paths = []
            for i, block in enumerate(payload.get("message", {}).get("content", [])):
                if block.get("type") in ("text", "reasoning"):
                    kind = "message.assistant" if block["type"] == "text" else "reasoning"
                    paths.append(
                        uid(
                            "event",
                            key,
                            kind,
                            f"message.content[{i}].{'text' if kind == 'message.assistant' else 'reasoning'}",
                        )
                    )
            if payload.get("usage"):
                request_key = [
                    record.source_id,
                    self.session_uid,
                    payload.get("message", {}).get("id", data.get("seq")),
                ]
                paths.append(uid("event", ["request", request_key], "model.usage", "message.usage"))
            for seq in data.get("sourceEventSeqs", []):
                self.chunk_targets[seq] = paths

    def native_key(self, record):
        return [record.source_id, self.session_uid, record.data.get("seq", record.ordinal)]

    def make(self, *args, **kwargs):
        kwargs.setdefault("ts_field", "time")
        kwargs.setdefault("ts_unit", "milliseconds")
        return super().make(*args, **kwargs)

    def map(self, record):
        data, typ = record.data, record.data.get("type")
        payload = data.get("data", {})
        if typ == "session":
            attrs = {
                "kind": "subagent" if data.get("origin") == "subagent" else "main",
                "cwd": data.get("cwd"),
                "harness_version": str(data.get("version")),
                "depth": data.get("delegationDepth", 0),
            }
            if attrs["kind"] == "subagent":
                attrs["parent_native_id"] = data.get("parentSession")
            elif data.get("parentSession"):
                attrs["forked_from_native"] = data["parentSession"]
            return Mapping([self.meta(record, str(data["id"]), **attrs)])
        if self.session_uid is None:
            raise ValueError("DSH session header is required")
        self.native_turn = payload.get("turn", self.native_turn)
        if data.get("seq", self.cut) < self.cut and self.parent:
            parent_uid = self.store.identity(record.source_id, self.parent)
            refs = [
                row[0]
                for row in self.store.db.execute(
                    "SELECT event_uid FROM event WHERE native_key=?",
                    (canonical([record.source_id, parent_uid, data.get("seq")]),),
                )
            ]
            return Mapping(
                disposition="replayed" if refs else "unparsed",
                references=refs,
                reason="seed prefix",
            )
        if typ in ("assistant/chunk", "text-chunks", "reasoning-chunks", "tool-call-chunks"):
            refs = self.chunk_targets.get(data.get("seq", data.get("seq0")), [])
            return Mapping(
                disposition="folded" if refs else "unparsed",
                references=refs,
                reason="stream folded into final assistant"
                if refs
                else "stream without final assistant",
            )
        if typ in ("turn/start", "turn/end"):
            return Mapping(
                [
                    self.make(
                        record,
                        "turn.start" if typ.endswith("start") else "turn.end",
                        typ,
                        attrs={
                            "status": "active"
                            if typ.endswith("start")
                            else {"aborted": "interrupted", "error": "failed"}.get(
                                payload.get("reason", {}).get("kind"), "completed"
                            )
                        },
                        ext=payload,
                    )
                ]
            )
        if typ == "assistant/message":
            message = payload.get("message", {})
            source = message.get("source", {})
            self.model = source.get("model", self.model)
            self.provider = source.get("provider", self.provider)
            events = self.message(record, message)
            for event in events:
                if event.kind == "tool.call":
                    event.native_key = [record.source_id, self.session_uid, "tool", event.call_id]
                    event.event_path = "tool.call"
            if payload.get("usage"):
                events.append(
                    self.usage(
                        record,
                        payload["usage"],
                        "dsh",
                        request_key=[
                            record.source_id,
                            self.session_uid,
                            message.get("id", data.get("seq")),
                        ],
                    )
                )
            return Mapping(events)
        if typ in ("user/message", "system/message", "developer/message"):
            message = payload.get("message", payload)
            source = message.get("source", {})
            source_kind = source.get("kind")
            if source_kind is None and isinstance(source.get("plugin"), dict):
                source_kind = source["plugin"].get("kind")
            origin = (
                "human"
                if source_kind == "user"
                else "notification"
                if source_kind in ("subagent-settled", "agent-message", "subagent-report")
                else "automation"
                if source_kind == "goal"
                else "injected"
            )
            return Mapping(self.message(record, message, origin=origin))
        if typ == "tool/call":
            call_id = str(payload.get("callId", record.record_uid))
            return Mapping(
                [
                    self.make(
                        record,
                        "tool.call",
                        "tool.call",
                        actor="assistant",
                        call_id=call_id,
                        native_key=[record.source_id, self.session_uid, "tool", call_id],
                        semantics="started",
                        attrs={
                            "name": payload.get("name", "unknown"),
                            "input": decode_json(payload.get("arguments")),
                        },
                        ext=payload,
                    )
                ]
            )
        if typ == "tool/result":
            message = payload.get("message", payload)
            if message.get("role") == "tool":
                return Mapping(self.message(record, message))
            return Mapping(self.message(record, message, origin="injected"))
        if typ in ("request/header", "request/context", "model/selection"):
            config = payload.get("header", {}).get("config", payload)
            self.model = config.get("model", self.model)
            self.provider = config.get("provider", self.provider)
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
                        ext=payload,
                    )
                ]
            )
        if typ in ("session/title-llm-request", "web/deepseek-search-llm-request"):
            return Mapping(
                [
                    self.make(
                        record,
                        "context.inject",
                        typ,
                        attrs={"purpose": "title" if typ.startswith("session/") else "web_search"},
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
            return Mapping(
                [
                    self.make(
                        record,
                        "context.compaction",
                        typ,
                        ext=payload,
                        text=text_content(payload.get("summary")),
                    )
                ]
            )
        if typ in ("step/start", "step/end", "session/end-seed", "agent/inbox/spliced"):
            return Mapping(disposition="ignored", reason="control record retained in L0")
        if typ in ("sandbox/mode", "approval/policy", "permission/preset"):
            return Mapping([self.make(record, "setting.change", typ, ext=payload)])
        return self.unknown(record)
