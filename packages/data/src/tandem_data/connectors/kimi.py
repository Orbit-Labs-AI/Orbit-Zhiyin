"""Kimi Code durable wire 1.0-1.5. See upstream wire-manifest and loopEventFold.

The wire is an event journal, not an OpenAI chat transcript. usage.record adds
one request's usage (usageScope only identifies its purpose); step.end mirrors it.
"""

from pathlib import PurePosixPath

from tandem_data.connectors.base import BaseMapper, Mapping, text_content
from tandem_data.contract import canonical, time_fields


class KimiMapper(BaseMapper):
    def prepare(self, records):
        self.has_usage = False
        self.session_native, self.agent_id = None, "main"
        self.index = {}
        self.content_groups = {}
        self.completed_steps = set()
        previous_group = None
        parts = PurePosixPath(self.info["relative_path"]).parts
        if "agents" in parts:
            position = parts.index("agents")
            self.session_native, self.agent_id = parts[position - 1], parts[position + 1]
        else:
            self.session_native = parts[-2] if len(parts) > 1 else parts[-1]

        def inspect(record):
            nonlocal previous_group
            if record.data.get("type") == "metadata":
                self.header = record.data
            if record.data.get("type") == "usage.record":
                self.has_usage = True
            loop = record.data.get("event", {})
            if record.data.get("type") == "context.append_loop_event" and isinstance(loop, dict):
                if loop.get("type") == "step.end":
                    self.completed_steps.add(loop.get("uuid"))
                part = loop.get("part", {})
                typ = part.get("type") if isinstance(part, dict) else None
                if loop.get("type") == "content.part" and typ in ("text", "think"):
                    signature = canonical(
                        [
                            loop.get("stepUuid"),
                            typ,
                            part.get("meta"),
                            part.get("detailsIndex"),
                            part.get("hidden"),
                            part.get("reasoningKey"),
                        ]
                    )
                    compatible = (
                        previous_group
                        and previous_group["signature"] == signature
                        and previous_group["last_ordinal"] + 1 == record.ordinal
                        and not part.get("encrypted")
                        and not previous_group["part"].get("encrypted")
                    )
                    if not compatible:
                        previous_group = {
                            "first": record.record_uid,
                            "signature": signature,
                            "part": dict(part),
                            "fragments": [],
                            "step": loop.get("stepUuid"),
                            "references": [],
                        }
                    previous_group["last_ordinal"] = record.ordinal
                    previous_group["fragments"].append(
                        part.get("text" if typ == "text" else "think", "")
                    )
                    self.content_groups[record.record_uid] = previous_group

        self.prepare_each(records, inspect)
        # Read only captured metadata. Index paths never grant access to other files.
        cache = getattr(self.store, "_kimi_indexes", None)
        if cache is None:
            cache = self.store._kimi_indexes = {}
        source_id = self.info["source_id"]
        if source_id not in cache:
            cache[source_id] = {}
            for row in self.store.db.execute(
                "SELECT file_id FROM source_file WHERE source_id=? AND role='session_index'",
                (source_id,),
            ):
                for record in self.store.iter_file(row["file_id"]):
                    if record.data.get("sessionId"):
                        cache[source_id].setdefault(record.data["sessionId"], {}).update(
                            record.data
                        )
        self.index = cache[source_id].get(self.session_native, {})

    def make(self, *args, **kwargs):
        kwargs.setdefault("ts_field", "time")
        kwargs.setdefault("ts_unit", "milliseconds")
        return super().make(*args, **kwargs)

    def native_key(self, record):
        data = record.data
        message = data.get("message", {})
        event = data.get("event", {})
        native = message.get("id") if isinstance(message, dict) else None
        if not native and isinstance(event, dict):
            native = event.get("uuid")
        # A message's identity is scoped to its agent; copied history requires proven lineage.
        return [record.source_id, self.session_uid, native or record.ordinal]

    @staticmethod
    def _origin(value):
        origin = value.get("kind") if isinstance(value, dict) else value
        return {
            "user": "human",
            "task": "notification",
            "system_trigger": "automation",
            "cron_job": "automation",
            "cron_missed": "automation",
        }.get(origin, "injected")

    def _message(self, record, message, path="message"):
        message = dict(message)
        blocks = []
        for part in message.get("content", []):
            if part.get("type") == "think":
                blocks.append({**part, "type": "thinking", "thinking": part.get("think")})
            elif part.get("type") in ("image_url", "audio_url", "video_url"):
                blocks.append({**part, "type": "file"})
            else:
                blocks.append(part)
        for call in message.get("toolCalls", []):
            blocks.append(
                {
                    "type": "toolCall",
                    "id": call["id"],
                    "name": call.get("name", call.get("function", {}).get("name")),
                    "arguments": call.get("arguments", call.get("function", {}).get("arguments")),
                }
            )
        message["content"] = blocks
        origin = (
            "human" if message.get("role") == "assistant" else self._origin(message.get("origin"))
        )
        if self.agent_id != "main" and message.get("role") == "user" and origin == "human":
            origin = "injected"
        events = self.message(record, message, origin=origin, base_path=path)
        for event in events:
            if event.kind == "tool.result":
                event.attrs["duration_ms"] = message.get("durationMs")
        return events

    def map(self, record):
        data, typ = record.data, record.data.get("type")
        if self.info["role"] == "session_index":
            if not data.get("sessionId"):
                return Mapping(disposition="ignored", reason="index_control")
            return Mapping(
                [
                    self.meta(
                        record,
                        str(data["sessionId"]),
                        cwd=data.get("workDir"),
                        archived=bool(data.get("deleted")),
                    )
                ]
            )
        events = []
        if self.first:
            native = (
                self.session_native
                if self.agent_id == "main"
                else self.session_native + ":" + self.agent_id
            )
            events.append(
                self.meta(
                    record,
                    native,
                    kind="main" if self.agent_id == "main" else "subagent",
                    parent_native_id=self.session_native if self.agent_id != "main" else None,
                    cwd=self.index.get("workDir"),
                    harness_version=self.header.get("protocol_version"),
                )
            )
            events[0].ts, events[0].attrs["time"] = time_fields(
                self.header.get("created_at"), "created_at", "milliseconds", "created"
            )
            self.first = False
        if typ == "metadata":
            if data.get("protocol_version") not in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5"):
                self.store.issue(
                    record.source_id, "unsupported_native_version", file_id=record.file_id
                )
            return Mapping(events)
        self.native_turn = data.get("turnId", self.native_turn)
        if typ == "context.append_message":
            events.extend(self._message(record, data["message"]))
            if not self.has_usage and data["message"].get("usage"):
                events.append(self.usage(record, data["message"]["usage"], "kimi"))
        elif typ == "context.append_loop_event":
            loop = data["event"]
            self.native_turn = loop.get("turnId", self.native_turn)
            sub = loop["type"]
            if sub == "content.part":
                group = self.content_groups.get(record.record_uid)
                if group and group["first"] != record.record_uid:
                    return Mapping(
                        disposition="folded",
                        references=group["references"],
                        reason="contiguous_stream_content",
                    )
                part = dict(group["part"]) if group else loop["part"]
                if group:
                    field = "text" if part["type"] == "text" else "think"
                    part[field] = "".join(group["fragments"])
                messages = self._message(
                    record, {"role": "assistant", "content": [part]}, "loop.part"
                )
                for event in messages:
                    event.attrs["partial"] = loop.get("stepUuid") not in self.completed_steps
                    event.attrs["step_id"] = loop.get("stepUuid")
                if group:
                    group["references"] = [event.event_uid for event in messages]
                events.extend(messages)
            elif sub == "tool.call":
                events.append(
                    self.make(
                        record,
                        "tool.call",
                        "loop.call",
                        actor="assistant",
                        call_id=loop["toolCallId"],
                        attrs={"name": loop["name"], "input": loop.get("args")},
                    )
                )
            elif sub == "tool.result":
                result = loop["result"]
                events.extend(
                    self._message(
                        record,
                        {
                            "role": "tool",
                            "toolCallId": loop["toolCallId"],
                            "content": [{"type": "text", "text": result["output"]}]
                            if isinstance(result["output"], str)
                            else result["output"],
                            "isError": result.get("isError"),
                            "durationMs": result.get("durationMs"),
                        },
                        "loop.result",
                    )
                )
            elif sub == "step.end" and not self.has_usage and loop.get("usage"):
                events.append(
                    self.usage(
                        record,
                        loop["usage"],
                        "kimi",
                        request_key=[record.source_id, self.session_uid, loop["uuid"]],
                    )
                )
            elif sub in ("step.begin", "step.end"):
                events.append(
                    self.make(
                        record,
                        "context.inject",
                        "loop." + sub,
                        attrs={"context_type": "step_boundary"},
                        ext=loop,
                    )
                )
            else:
                events.extend(self.unknown(record).events)
        elif typ == "usage.record":
            self.model = data.get("model", self.model)
            events.append(
                self.usage(
                    record,
                    data["usage"],
                    "kimi",
                    request_key=[record.source_id, self.session_uid, record.ordinal],
                    purpose="main" if data.get("usageScope") == "turn" else "auxiliary",
                )
            )
        elif typ in ("llm.request", "config.update", "profile.bind"):
            self.model = data.get("model", data.get("modelAlias", self.model))
            self.provider = data.get("provider", self.provider)
            self.effort = data.get("thinkingEffort", data.get("thinkingLevel", self.effort))
            events.append(
                self.make(
                    record,
                    "setting.change",
                    typ,
                    attrs={
                        "model_raw": self.model,
                        "provider": self.provider,
                        "effort_raw": self.effort,
                        "cwd": data.get("environmentDisclosure", {}).get("cwd"),
                    },
                    ext=data,
                )
            )
        elif typ == "turn.prompt":
            # The received prompt appears again as context.append_message; only the latter is human input.
            events.append(
                self.make(
                    record, "turn.start", typ, attrs={"origin": self._origin(data.get("origin"))}
                )
            )
        elif typ in ("turn.ended", "turn.cancel", "prompt.aborted"):
            reason = data.get("reason")
            reason = reason.get("kind") if isinstance(reason, dict) else reason
            status = (
                "interrupted"
                if typ != "turn.ended"
                else {
                    "completed": "completed",
                    "error": "failed",
                    "cancelled": "interrupted",
                    "aborted": "interrupted",
                }.get(reason, "unknown")
            )
            events.append(self.make(record, "turn.end", typ, attrs={"status": status}))
        else:
            kind = {
                "context.apply_compaction": "context.compaction",
                "full_compaction.begin": "context.compaction",
                "full_compaction.complete": "context.compaction",
                "full_compaction.cancel": "context.compaction",
                "context.clear": "branch",
                "context.undo": "branch",
                "context.undone": "branch",
                "agent.switched": "branch",
                "forked": "branch",
                "interaction.request": "permission.request",
                "interaction.resolved": "permission.decision",
                "permission.record_approval_result": "permission.decision",
                "permission.set_mode": "setting.change",
                "subagent.spawned": "subagent.spawn",
                "subagent.started": "subagent.spawn",
                "subagent.completed": "subagent.result",
                "subagent.failed": "subagent.result",
                "subagent.cancelled": "subagent.result",
                "file_history.checkpoint": "file.change",
                "file_history.tracked": "file.change",
                "plan.revision": "plan.update",
                "tools.update_store": "plan.update",
                "turn.step.interrupted": "error",
                "turn.step.retrying": "error",
                "turn.steer": "queue",
                "prompt.steered": "queue",
                "prompt.completed": "ui.state",
                "llm.tools_snapshot": "context.inject",
                "mcp.tools_discovered": "context.inject",
                "plugin.session_start": "context.inject",
                "interruptionReminder.recorded": "context.inject",
                "runtime.set_binding": "setting.change",
                "task.started": "subagent.spawn",
                "task.terminated": "subagent.result",
                "task.waitDelivered": "subagent.result",
            }.get(typ)
            if (
                kind is None
                and isinstance(typ, str)
                and typ.split(".")[0]
                in (
                    "cron",
                    "goal",
                    "plan_mode",
                    "swarm_mode",
                    "tower_mode",
                    "token_counting",
                    "tools",
                )
            ):
                kind = "context.inject" if typ.startswith("token_counting.") else "setting.change"
            events.append(
                self.make(
                    record,
                    kind or "unknown",
                    typ or "raw",
                    attrs={
                        "permission_id": data.get("requestId"),
                        "decision": data.get("decision"),
                    },
                    text=text_content(data.get("summary")) or None,
                    ext=data,
                )
            )
        return Mapping(events or [self.make(record, "context.inject", "empty.message", ext=data)])
