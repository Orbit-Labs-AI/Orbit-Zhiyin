from pathlib import PurePosixPath

from tandem_data.connectors.base import BaseMapper, Mapping
from tandem_data.contract import unused


class ClaudeMapper(BaseMapper):
    def native_key(self, record):
        if record.data.get("uuid"):
            return [record.source_id, record.data["uuid"]]
        return super().native_key(record)

    def map(self, record):
        data = record.data
        events = []
        if self.first:
            parent = None
            native = str(data.get("sessionId", PurePosixPath(record.relative_path).stem))
            kind = "main"
            if "subagents" in PurePosixPath(record.relative_path).parts:
                parent, kind = native, "subagent"
                native = native + ":" + PurePosixPath(record.relative_path).stem
                if "workflows" in PurePosixPath(record.relative_path).parts:
                    kind = "workflow_agent"
            events.append(
                self.meta(
                    record,
                    native,
                    kind=kind,
                    parent_native_id=parent,
                    cwd=data.get("cwd"),
                    git_branch=data.get("gitBranch"),
                    harness_version=data.get("version"),
                    client=data.get("entrypoint"),
                )
            )
            self.first = False
        self.effort = data.get("perTurnEffort", data.get("effort", self.effort))
        typ = data.get("type")
        if typ in ("user", "assistant"):
            message = data.get("message", {})
            if not isinstance(message, dict):
                return self.unknown(record)
            self.model = message.get("model", self.model)
            origin = data.get("origin", {}).get("kind", "human")
            origin = {"task-notification": "notification"}.get(origin, origin)
            if origin not in ("human", "queued", "notification", "peer", "automation", "injected"):
                origin = "unknown"
            if data.get("isMeta") or data.get("isCompactSummary"):
                origin = "injected"
            attrs = {
                "cwd": data.get("cwd"),
                "effort_raw": self.effort,
                "native_parent_id": data.get("parentUuid"),
                "logical_parent_id": data.get("logicalParentUuid"),
                "native_turn_id": data.get("promptId"),
                "attribution": {
                    key: value for key, value in data.items() if key.startswith("attribution")
                },
            }
            contents = self.message(record, {"role": typ, **message}, origin=origin, **attrs)
            if data.get("isCompactSummary"):
                for event in contents:
                    if event.kind == "context.inject":
                        event.kind = "context.compaction"
            for event in contents:
                if data.get("parentUuid"):
                    event.parent_native_key = [record.source_id, data["parentUuid"]]
            if contents:
                contents[0].ext["envelope"] = unused(
                    data,
                    (
                        "type",
                        "message",
                        "uuid",
                        "parentUuid",
                        "logicalParentUuid",
                        "timestamp",
                        "sessionId",
                        "cwd",
                        "version",
                        "origin",
                        "isMeta",
                        "promptId",
                        "effort",
                        "perTurnEffort",
                    ),
                )
            events.extend(contents)
            if typ == "assistant" and message.get("usage") and message.get("id"):
                events.append(
                    self.usage(
                        record,
                        message["usage"],
                        "claude_code",
                        request_id=message["id"],
                        request_key=[record.source_id, message["id"]],
                        stop_reason=message.get("stop_reason"),
                        cwd=data.get("cwd"),
                    )
                )
        elif typ in ("custom-title", "ai-title", "agent-name"):
            events.append(
                self.make(
                    record,
                    "session.title",
                    "title",
                    text=data.get("customTitle", data.get("title", data.get("agentName"))),
                    attrs={"title_source": "custom" if typ == "custom-title" else "ai"},
                    ext=unused(data, ("type", "customTitle", "title", "agentName")),
                )
            )
        elif typ == "system" and data.get("subtype") == "turn_duration":
            events.append(
                self.make(
                    record,
                    "turn.end",
                    "turn.end",
                    attrs={"status": "completed", "duration_ms": data.get("durationMs")},
                )
            )
        elif typ == "cost-state":
            models = data.get("modelUsage", {})
            for model, value in models.items():
                self.model = model
                reported = {
                    "input_tokens": value.get("inputTokens"),
                    "output_tokens": value.get("outputTokens"),
                    "cache_read_input_tokens": value.get("cacheReadInputTokens"),
                    "cache_creation_input_tokens": value.get("cacheCreationInputTokens"),
                }
                events.append(
                    self.usage(
                        record,
                        reported,
                        "claude_code",
                        scope="session_model_snapshot",
                        coverage="root_tree",
                        path="cost-state.modelUsage." + model,
                        cost_usd=value.get("costUSD"),
                        cost_source="reported",
                    )
                )
            if not models:
                events.append(self.make(record, "ui.state", "cost-state", ext=data))
        elif typ == "system":
            kind = (
                "context.compaction"
                if data.get("subtype") == "compact_boundary"
                else "error"
                if data.get("subtype") == "api_error"
                else "hook.run"
                if "hook" in str(data.get("subtype"))
                else "session.meta"
            )
            events.append(self.make(record, kind, "system", ext=data))
        elif typ in ("attachment", "mode", "permission-mode"):
            events.append(
                self.make(
                    record,
                    "context.inject" if typ == "attachment" else "setting.change",
                    typ,
                    ext=data,
                )
            )
        elif typ in ("pr-link", "file-history-snapshot", "file-history-delta", "queue-operation"):
            events.append(
                self.make(
                    record,
                    {"pr-link": "link", "queue-operation": "queue"}.get(typ, "file.change"),
                    typ,
                    ext=data,
                )
            )
        else:
            return (
                Mapping(events, "ignored", "non-trajectory UI record")
                if events
                else Mapping(disposition="ignored", reason="non-trajectory UI record")
                if typ in ("last-prompt", "atis-latch", "bridge-session", "frame-link")
                or str(typ).startswith("artifact-")
                else self.unknown(record)
            )
        return Mapping(events)
