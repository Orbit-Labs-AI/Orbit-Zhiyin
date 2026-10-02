from pathlib import PurePosixPath

from tandem_data.connectors.base import BaseMapper, Mapping, text_content
from tandem_data.contract import unused


class ClaudeMapper(BaseMapper):
    def prepare(self, records):
        self.header = {}
        self.usage_records = {}
        # Agent/Task tool_use id -> spawned agentId (from the paired toolUseResult).
        self.spawned = {}

        def inspect(record):
            data = record.data
            # Leading queue-operation/mode/title lines carry sessionId but no
            # context; take each header field from the first record that has it.
            for name in ("sessionId", "cwd", "gitBranch", "version", "entrypoint"):
                if data.get(name) and name not in self.header:
                    self.header[name] = data[name]
            message = data.get("message")
            result = data.get("toolUseResult")
            if (
                data.get("type") == "user"
                and isinstance(result, dict)
                and result.get("agentId")
                and isinstance(message, dict)
                and isinstance(message.get("content"), list)
            ):
                for block in message["content"]:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id")
                    ):
                        self.spawned[str(block["tool_use_id"])] = str(result["agentId"])
            if (
                data.get("type") == "assistant"
                and isinstance(message, dict)
                and message.get("id")
                and message.get("usage")
                and not data.get("isApiErrorMessage")
            ):
                score = (bool(message.get("stop_reason")), record.ordinal)
                previous = self.usage_records.get(message["id"])
                if previous is None or score > previous[0]:
                    self.usage_records[message["id"]] = (score, record.record_uid)

        self.prepare_each(records, inspect)

    def native_key(self, record):
        if record.data.get("uuid"):
            return [record.source_id, record.data["uuid"]]
        return super().native_key(record)

    def map(self, record):
        data = record.data
        if self.info["role"] in ("subagent_metadata", "session_title"):
            path = PurePosixPath(record.relative_path)
            if self.info["role"] == "subagent_metadata":
                parts = path.parts
                parent = parts[parts.index("subagents") - 1]
                native = parent + ":" + path.name.removesuffix(".meta.json")
                event = self.meta(
                    record,
                    native,
                    kind="workflow_agent" if "workflows" in parts else "subagent",
                    parent_native_id=parent,
                    depth=data.get("spawnDepth", 1),
                    spawn_native_call_id=data.get("toolUseId"),
                )
            else:
                self.session_uid = self.store.identity(
                    record.source_id, str(data.get("sessionId", path.parent.name))
                )
                event = self.make(
                    record,
                    "session.title",
                    "sidecar.title",
                    text=data.get("customTitle", data.get("title")),
                    attrs={"title_source": "custom"},
                )
            return Mapping([event])
        events = []
        usage_references = []
        if self.first:
            parent = None
            native = str(self.header.get("sessionId", PurePosixPath(record.relative_path).stem))
            kind = "main"
            if "subagents" in PurePosixPath(record.relative_path).parts:
                parent, kind = native, "subagent"
                native = native + ":" + PurePosixPath(record.relative_path).stem
                if "workflows" in PurePosixPath(record.relative_path).parts:
                    kind = "workflow_agent"
            self.session_kind = kind
            events.append(
                self.meta(
                    record,
                    native,
                    kind=kind,
                    parent_native_id=parent,
                    cwd=self.header.get("cwd"),
                    git_branch=self.header.get("gitBranch"),
                    harness_version=self.header.get("version"),
                    client=self.header.get("entrypoint"),
                )
            )
            self.first = False
        self.effort = data.get("perTurnEffort", data.get("effort", self.effort))
        typ = data.get("type")
        if typ in ("user", "assistant"):
            message = data.get("message", {})
            if isinstance(message, str):
                message = {"role": typ, "content": message}
            if not isinstance(message, dict):
                return self.unknown(record)
            self.model = message.get("model", self.model)
            origin_value = data.get("origin")
            origin = (
                origin_value.get("kind", "human") if isinstance(origin_value, dict) else "human"
            )
            origin = {"task-notification": "notification"}.get(origin, origin)
            if origin not in ("human", "queued", "notification", "peer", "automation", "injected"):
                origin = "unknown"
            if origin == "human" and typ == "user":
                # A subagent's prompts come from the parent agent or the workflow script.
                origin = {"subagent": "peer", "workflow_agent": "automation"}.get(
                    getattr(self, "session_kind", "main"), origin
                )
            body_text = text_content(message.get("content"))
            if (
                data.get("isMeta")
                or data.get("isCompactSummary")
                or body_text.lstrip().startswith(
                    (
                        "<command-name>",
                        "<local-command-stdout>",
                        "<system-reminder>",
                        "<task-notification>",
                    )
                )
            ):
                origin = "injected"
            if body_text.strip() in (
                "[Request interrupted by user]",
                "[Request interrupted by user for tool use]",
            ):
                events.append(
                    self.make(record, "turn.end", "interruption", attrs={"status": "interrupted"})
                )
                return Mapping(events, references=usage_references)
            self.native_turn = data.get("promptId", self.native_turn)
            attrs = {
                "cwd": data.get("cwd"),
                "effort_raw": self.effort,
                "native_parent_id": data.get("parentUuid"),
                "logical_parent_id": data.get("logicalParentUuid"),
                "native_turn_id": self.native_turn,
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
                agent = self.spawned.get(str(event.call_id)) if event.kind == "tool.call" else None
                if agent and self.header.get("sessionId"):
                    # Subagent transcripts live at <sessionId>/subagents/agent-<agentId>.jsonl.
                    event.attrs["subagent_session_uid"] = self.store.identity(
                        record.source_id, f"{self.header['sessionId']}:agent-{agent}"
                    )
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
                        # Stored once as ext.toolUseResult below, never again in the envelope.
                        "toolUseResult",
                    ),
                )
                if "toolUseResult" in data and not any(
                    event.kind == "tool.result" for event in contents
                ):
                    contents[0].ext["toolUseResult"] = data["toolUseResult"]
            result = data.get("toolUseResult")
            result = result if isinstance(result, dict) else {}
            for event in contents:
                if event.kind == "tool.result":
                    event.attrs.update(
                        duration_ms=result.get("durationMs"),
                        exit_code=result.get("exitCode"),
                        status_scope="tool_protocol",
                    )
                    if event.attrs.get("status") == "unknown":
                        # The Claude protocol signals failure explicitly (is_error, denial,
                        # interrupt): an observed tool_result without it is a completed call.
                        event.attrs["status"] = "completed"
                    denial = data.get("toolDenialKind")
                    if denial:
                        event.attrs["status"] = (
                            "interrupted" if denial == "interrupted" else "declined"
                        )
                        events.append(
                            self.make(
                                record,
                                "permission.decision",
                                "denial." + str(event.call_id),
                                call_id=event.call_id,
                                attrs={"decision": "denied", "reason": denial},
                            )
                        )
                    elif result.get("interrupted"):
                        event.attrs["status"] = "interrupted"
                    elif event.attrs.get("status") == "unknown":
                        # Claude Code omits is_error on success; a paired result
                        # without the flag is a protocol-level completion.
                        event.attrs["status"] = "completed"
                    event.ext["toolUseResult"] = data.get("toolUseResult", result)
            events.extend(contents)
            if (
                typ == "assistant"
                and message.get("usage")
                and message.get("id")
                and not data.get("isApiErrorMessage")
            ):
                usage_event = self.usage(
                    record,
                    message["usage"],
                    "claude_code",
                    request_id=message["id"],
                    request_key=[record.source_id, message["id"]],
                    stop_reason=message.get("stop_reason"),
                    cwd=data.get("cwd"),
                    coverage="unknown"
                    if data.get("isSidechain") and not message.get("stop_reason")
                    else "self",
                    estimated=bool(data.get("isSidechain") and not message.get("stop_reason")),
                )
                if self.usage_records.get(message["id"], (None, None))[1] == record.record_uid:
                    events.append(usage_event)
                else:
                    usage_references.append(usage_event.event_uid)
            if data.get("isApiErrorMessage"):
                events.append(
                    self.make(
                        record,
                        "error",
                        "api_error",
                        attrs={
                            "error_class": data.get("error"),
                            "status_code": data.get("apiErrorStatus"),
                        },
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
            previous_model = self.model
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
            self.model = previous_model
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
        elif typ == "progress":
            events.append(self.make(record, "ui.state", "progress", ext=data))
        elif typ in ("started", "completed", "failed", "cancelled") and data.get("agentId"):
            events.append(
                self.make(
                    record,
                    "subagent.spawn" if typ == "started" else "subagent.result",
                    "agent." + typ,
                    attrs={
                        "child_native_id": data["agentId"],
                        "status": "running" if typ == "started" else typ,
                    },
                    ext=data,
                )
            )
        elif typ == "result" and data.get("agentId"):
            # Workflow journal: an agent's final output.
            result = data.get("result")
            events.append(
                self.make(
                    record,
                    "subagent.result",
                    "agent.result",
                    text=result if isinstance(result, str) else None,
                    attrs={"child_native_id": data["agentId"], "status": "completed"},
                    ext=unused(data, ("result",)) if isinstance(result, str) else data,
                )
            )
        elif typ == "result":
            # Print-mode / SDK final summary; usage stays in ext (already counted per call).
            failed = data.get("is_error") or str(data.get("subtype", "")).startswith("error")
            events.append(
                self.make(
                    record,
                    "turn.end",
                    "result",
                    text=data.get("result") if isinstance(data.get("result"), str) else None,
                    attrs={
                        "status": "failed" if failed else "completed",
                        "duration_ms": data.get("duration_ms"),
                    },
                    ext=unused(data, ("result",)),
                )
            )
        elif typ == "relocated":
            events.append(
                self.make(
                    record,
                    "setting.change",
                    "relocated",
                    attrs={"relocated_cwd": data.get("relocatedCwd")},
                    ext=data,
                )
            )
        elif typ == "continued-in" and data.get("continuedInSessionId"):
            target = str(data["continuedInSessionId"])
            events.append(
                self.make(
                    record,
                    "link",
                    "continued-in",
                    attrs={
                        "link_kind": "continued_in",
                        "ref": self.store.identity(record.source_id, target),
                        "continued_in_native_id": target,
                    },
                    ext=data,
                )
            )
        elif typ == "summary":
            events.append(
                self.make(
                    record, "context.compaction", "summary", text=data.get("summary"), ext=data
                )
            )
        else:
            return (
                Mapping(events, "ignored", "non-trajectory UI record")
                if events
                else Mapping(disposition="ignored", reason="non-trajectory UI record")
                if typ in ("last-prompt", "atis-latch", "bridge-session", "frame-link")
                or str(typ).startswith("artifact-")
                else Mapping(events + self.unknown(record).events)
            )
        return Mapping(events, references=usage_references)
