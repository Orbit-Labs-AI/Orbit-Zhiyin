import hashlib
from dataclasses import replace

from tandem_data.connectors.base import BaseMapper, Mapping, decode_json, text_content
from tandem_data.contract import canonical, uid


class CodexMapper(BaseMapper):
    def prepare(self, records):
        self.has_calls = False
        self.messages = {}
        self.usage_records = []
        self.matched_messages = set()
        self.cut = None
        self.parent = None
        self.header_record_uid = None
        self.prepare_each(records, self.prepare_record)

    def prepare_record(self, record):
        data, payload = record.data, record.data.get("payload", {})
        if data.get("type") == "session_meta" and not self.header:
            self.header = payload
            self.header_record_uid = record.record_uid
            source = payload.get("source", {})
            subagent = source.get("subagent", {}) if isinstance(source, dict) else {}
            spawn = subagent.get("thread_spawn", {}) if isinstance(subagent, dict) else {}
            self.cut = payload.get("subagent_history_start_ordinal") if spawn else None
            self.parent = payload.get("parent_thread_id", payload.get("forked_from_id"))
            self.parent = self.parent or spawn.get("parent_thread_id")
            self.parent_candidates = {}
            self.parent_cursor = (-1, -1)
        if data.get("type") == "token_usage_record":
            self.has_calls = True
            self.usage_records.append((record.ordinal, payload.get("response_id")))
        if data.get("type") == "event_msg" and payload.get("type") == "item_completed":
            item = payload.get("item", {})
            if item.get("type") in ("UserMessage", "AgentMessage"):
                role = "user" if item["type"] == "UserMessage" else "assistant"
                signature = (
                    role,
                    payload.get("turn_id"),
                    hashlib.sha256(text_content(item.get("content")).encode()).hexdigest(),
                )
                self.messages.setdefault(signature, []).append((record.ordinal, item.get("id")))

    def native_key(self, record):
        payload = record.data.get("payload", {})
        native = payload.get("id")
        return (
            [record.source_id, self.session_uid, native] if native else super().native_key(record)
        )

    @staticmethod
    def record_signature(record):
        return uid("native_payload", record.data.get("type"), record.data.get("payload"))

    def map(self, record):
        reason = getattr(self, "excluded_records", {}).get(record.record_uid)
        if reason:
            return Mapping(disposition="ignored", reason=reason)
        data, typ = record.data, record.data.get("type")
        if self.info["role"] == "import_ledger" and "records" in data:
            events = []
            for index, item in enumerate(data["records"]):
                mapped = self.map(replace(record, data={"type": "import_ledger", "payload": item}))
                for event in mapped.events:
                    event.event_path += f".{index}"
                events.extend(mapped.events)
            return Mapping(events, reason="import ledger snapshot")
        if typ in ("project_index", "project_root"):
            return Mapping(
                disposition="ignored",
                reason="project metadata retained; session cwd/remote defines canonical identity",
            )
        payload = data.get("payload", {})
        if self.info["role"] == "title_index":
            payload, typ = data, "title_index"
        if typ in ("state_index", "title_index", "spawn_edge", "import_ledger"):
            return self._map_index(record, data, typ, payload)
        if self.session_uid is None:
            native = str(self.header.get("id", self.header.get("session_id", record.relative_path)))
            self.session_uid = self.store.identity(record.source_id, native)
            self.model = self.header.get("model")
            self.provider = self.header.get("model_provider")
        # Copied prefix is excluded only with explicit native boundary evidence.
        ordinal = (
            record.ordinal
            if self.header.get("history_mode") == "paginated"
            else data.get("ordinal", record.ordinal)
        )
        if (
            self.cut is not None
            and record.record_uid != self.header_record_uid
            and ordinal < self.cut
        ):
            if data.get("type") == "turn_context":
                self.model = payload.get("model", self.model)
                self.effort = payload.get("effort", self.effort)
            elif data.get("type") == "world_state":
                self.model = payload.get("state", {}).get("model", self.model)
            refs = []
            candidates = self.parent_candidates.get(self.record_signature(record), [])
            for candidate in candidates:
                if candidate[0] <= self.parent_cursor:
                    continue
                refs = [
                    row[0]
                    for row in self.store.db.execute(
                        "SELECT event_uid FROM record_event WHERE record_uid=?", (candidate[1],)
                    )
                ]
                if refs:
                    self.parent_cursor = candidate[0]
                    break
            if not refs and self.header.get("history_mode") == "paginated":
                # Codex serializes forked paginated history with new rollout/item/turn IDs
                # and may replace compacted instructions. The explicit prefix boundary
                # identifies context, not a second execution of the parent's actions.
                item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
                content = text_content(payload.get("content")) or text_content(item.get("content"))
                return Mapping(
                    [
                        self.make(
                            record,
                            "context.inject",
                            "inherited.reconstructed",
                            actor="harness",
                            text=content or None,
                            native_key=[record.source_id, record.record_uid, "inherited_context"],
                            attrs={
                                "origin": "injected",
                                "inherited_prefix": True,
                                "context_type": "inherited_history",
                                "native_turn_id": None,
                                "parent_native_id": self.parent,
                                "native_kind": typ,
                                "parent_event_match": "unavailable_after_native_reconstruction",
                            },
                            ext=payload,
                        )
                    ],
                    reason="native paginated inherited context; not a new action",
                )
            if not refs and (
                typ == "world_state"
                or typ == "response_item"
                and payload.get("role") in ("system", "developer")
            ):
                # A fork may update its injected environment before the inherited cut.
                # Without an identical parent record it is retained as context, never as behavior.
                return Mapping(
                    [
                        self.make(
                            record,
                            "context.inject",
                            "inherited.modified_context",
                            actor="harness",
                            text=text_content(payload.get("content")),
                            attrs={"origin": "injected", "inherited_prefix": True},
                            ext=payload,
                        )
                    ],
                    reason="modified inherited setup; no identical parent record",
                )
            return Mapping(
                disposition="replayed" if refs else "unparsed",
                references=refs,
                reason="inherited prefix"
                if refs
                else "inherited prefix: canonical record not resolved",
            )
        if typ == "session_meta":
            source = payload.get("source", {})
            spawn = (
                source.get("subagent", {}).get("thread_spawn", {})
                if isinstance(source, dict) and isinstance(source.get("subagent"), dict)
                else {}
            )
            parent = payload.get("parent_thread_id", spawn.get("parent_thread_id"))
            kind = "subagent" if parent else "main"
            if isinstance(source, dict) and "guardian" in canonical(source):
                kind = "review"
            event = self.meta(
                record,
                str(payload.get("id", payload.get("session_id"))),
                kind=kind,
                parent_native_id=parent,
                cwd=payload.get("cwd"),
                git_branch=payload.get("git", {}).get("branch"),
                git_sha=payload.get("git", {}).get("commit_hash"),
                git_remote=payload.get("git", {}).get("repository_url"),
                harness_version=payload.get("cli_version"),
                client=payload.get("originator"),
                provider=self.provider,
                forked_from_native=payload.get("forked_from_id"),
                history_base=payload.get("history_base"),
            )
            event.ext = payload
            return Mapping([event])
        if typ == "event_msg" and payload.get("type") == "thread_rolled_back":
            return Mapping(
                [
                    self.make(
                        record, "branch", "rollback", attrs={"num_turns": payload.get("num_turns")}
                    )
                ]
            )
        if typ == "turn_context":
            self.native_turn = payload.get("turn_id", self.native_turn)
            self.model = payload.get("model", self.model)
            self.effort = payload.get("effort", self.effort)
            return Mapping(
                [
                    self.make(
                        record,
                        "setting.change",
                        "turn_context",
                        attrs={
                            "cwd": payload.get("cwd"),
                            "model_raw": self.model,
                            "provider": self.provider,
                            "effort_raw": self.effort,
                            "timezone": payload.get("timezone"),
                            "timezone_source": "reported" if payload.get("timezone") else "unknown",
                        },
                        ext=payload,
                    )
                ]
            )
        if typ == "token_usage_record":
            return Mapping(
                [
                    self.usage(
                        record,
                        payload.get("usage", {}),
                        "codex",
                        request_id=payload.get("response_id"),
                        native_turn_id=payload.get("turn_id", self.native_turn),
                    )
                ]
            )
        if typ == "response_item":
            return self._map_response(record, data, typ, payload)
        if typ == "event_msg":
            return self._map_event(record, data, typ, payload)
        if typ in ("compacted", "compaction", "world_state"):
            return Mapping(
                [
                    self.make(
                        record,
                        "context.inject" if typ == "world_state" else "context.compaction",
                        typ,
                        ext=payload,
                    )
                ]
            )
        if typ == "inter_agent_communication_metadata":
            return Mapping(
                [
                    self.make(
                        record,
                        "context.inject",
                        "peer.metadata",
                        attrs={"origin": "peer"},
                        ext=payload,
                    )
                ]
            )
        return self.unknown(record)

    def _map_index(self, record, data, typ, payload):
        """Apply allowlisted index metadata to its native session identity."""
        native = (
            payload.get("imported_thread_id")
            if typ == "import_ledger"
            else payload.get("child_thread_id")
            if typ == "spawn_edge"
            else payload.get("id", payload.get("thread_id"))
        )
        if not native:
            return Mapping(disposition="unparsed", reason="metadata lacks thread identity")
        self.session_uid = self.store.identity(record.source_id, str(native))
        if typ == "title_index":
            return Mapping(
                [
                    self.make(
                        record,
                        "session.title",
                        "index.title",
                        text=payload.get("thread_name", payload.get("name", payload.get("title"))),
                        attrs={"title_source": "native"},
                    )
                ]
            )
        attrs = {}
        if typ in ("import_ledger", "spawn_edge"):
            attrs["kind"] = "import" if typ == "import_ledger" else "subagent"
        if typ == "spawn_edge" and payload.get("parent_thread_id"):
            attrs["parent_uid"] = self.store.identity(record.source_id, payload["parent_thread_id"])
        if typ == "state_index":
            attrs.update(
                title=payload.get("name") or payload.get("title") or payload.get("preview"),
                title_source="custom" if payload.get("name") else "native",
                cwd=payload.get("cwd"),
                git_remote=payload.get("git_origin_url"),
                client=payload.get("originator"),
                harness_version=payload.get("cli_version"),
                current_index=payload,
            )
        return Mapping(
            [
                self.make(
                    record,
                    "session.meta",
                    "index.meta",
                    attrs=attrs,
                    native_key=[record.source_id, record.record_uid, typ],
                    ext=payload,
                )
            ]
        )

    def _map_response(self, record, data, typ, payload):
        """Map a Responses item while keeping injected content separate from human input."""
        item_type = payload.get("type")
        turn = payload.get("internal_chat_message_metadata_passthrough", {}).get(
            "turn_id", self.native_turn
        )
        if item_type == "message":
            role = payload.get("role")
            signature = (
                role,
                turn,
                hashlib.sha256(text_content(payload.get("content")).encode()).hexdigest(),
            )
            candidates = self.messages.get(signature, [])
            matching = [
                (ordinal, native) for ordinal, native in candidates if native == payload.get("id")
            ]
            if not matching:
                matching = [
                    (ordinal, native)
                    for ordinal, native in candidates
                    if abs(ordinal - record.ordinal) <= 2 and native not in self.matched_messages
                ]
            pair = (
                min(matching, key=lambda item: abs(item[0] - record.ordinal)) if matching else None
            )
            key_id = pair[1] if pair else payload.get("id")
            if pair:
                self.matched_messages.add(key_id)
            key = (
                [record.source_id, self.session_uid, key_id] if key_id else self.native_key(record)
            )
            origin = (
                "human"
                if role == "user"
                and (pair or data.get("metadata", {}).get("user_input_order") is not None)
                else "unknown"
                if role == "assistant"
                else "injected"
            )
            return Mapping(
                self.message(record, payload, origin=origin, key=key, native_turn_id=turn)
            )
        if item_type in ("function_call", "custom_tool_call"):
            call_id = str(payload.get("call_id", payload.get("id", record.record_uid)))
            key = [record.source_id, self.session_uid, "tool", call_id]
            return Mapping(
                [
                    self.make(
                        record,
                        "tool.call",
                        "tool.call",
                        actor="assistant",
                        call_id=call_id,
                        native_key=key,
                        attrs={
                            "name": payload.get("name", "unknown"),
                            "input": decode_json(payload.get("arguments", payload.get("input"))),
                            "native_turn_id": turn,
                        },
                        ext=payload,
                    )
                ]
            )
        if item_type in ("function_call_output", "custom_tool_call_output"):
            call_id = str(payload.get("call_id", record.record_uid))
            return Mapping(
                [
                    self.make(
                        record,
                        "tool.result",
                        "tool.result",
                        actor="tool",
                        call_id=call_id,
                        native_key=[record.source_id, self.session_uid, "tool", call_id],
                        text=text_content(payload.get("output")),
                        attrs={"status": "unknown", "native_turn_id": turn},
                        ext={key: value for key, value in payload.items() if key != "output"},
                    )
                ]
            )
        if item_type == "reasoning":
            return Mapping(
                [
                    self.make(
                        record,
                        "reasoning",
                        "reasoning",
                        actor="assistant",
                        text=text_content(payload.get("summary")),
                        ext={key: value for key, value in payload.items() if key != "summary"},
                    )
                ]
            )
        if item_type == "agent_message":
            return Mapping(
                [
                    self.make(
                        record,
                        "message.user",
                        "peer.message",
                        actor="subagent",
                        text=text_content(payload.get("content")) or None,
                        attrs={"origin": "peer", "input_format": None},
                        ext=payload,
                    )
                ]
            )
        return self.unknown(record)

    def _map_event(self, record, data, typ, payload):
        """Map native UI lifecycle, tool completion and usage observations."""
        etype = payload.get("type")
        self.native_turn = payload.get("turn_id", self.native_turn)
        if etype == "thread_settings_applied":
            settings = payload.get("thread_settings", {})
            self.model = settings.get("model", self.model)
            self.effort = settings.get("reasoning_effort", self.effort)
            self.provider = settings.get("model_provider", self.provider)
            return Mapping(
                [
                    self.make(
                        record,
                        "setting.change",
                        "thread_settings",
                        attrs={
                            "model_raw": self.model,
                            "provider": self.provider,
                            "effort_raw": self.effort,
                        },
                        ext=settings,
                    )
                ]
            )
        if etype in ("task_started", "task_complete", "turn_aborted"):
            started = etype == "task_started"
            field = "started_at" if started else "completed_at"
            return Mapping(
                [
                    self.make(
                        record,
                        "turn.start" if started else "turn.end",
                        etype,
                        attrs={
                            "status": "active"
                            if started
                            else "interrupted"
                            if etype == "turn_aborted"
                            else "failed"
                            if payload.get("error")
                            else "completed",
                            "duration_ms": payload.get("duration_ms"),
                        },
                        ext=payload,
                        ts_value=payload.get(field),
                        ts_field="payload." + field,
                        ts_unit="seconds",
                        semantics="started" if started else "completed",
                    )
                ]
            )
        if etype == "token_count":
            info = payload.get("info") or {}
            events = []
            if info.get("total_token_usage"):
                events.append(
                    self.usage(
                        record,
                        info["total_token_usage"],
                        "codex",
                        scope="session_snapshot",
                        path="info.total_token_usage",
                    )
                )
            if info.get("last_token_usage") and not self.has_calls:
                # Legacy logs lack response identity. Only changed cumulative observations identify a new call.
                total = canonical(info.get("total_token_usage"))
                if total != getattr(self, "last_total", None):
                    events.append(
                        self.usage(
                            record,
                            info["last_token_usage"],
                            "codex",
                            request_key=[record.source_id, self.session_uid, record.record_uid],
                            path="info.last_token_usage",
                            boundary_evidence="changed_cumulative_usage",
                        )
                    )
                self.last_total = total
            return (
                Mapping(events)
                if events
                else Mapping(disposition="ignored", reason="rate-limit observation without usage")
            )
        if etype == "user_message":
            return Mapping(
                self.message(
                    record,
                    {"role": "user", "content": payload.get("message", "")},
                    origin="human",
                )
            )
        if etype == "item_completed":
            item = payload.get("item", {})
            itype, native = item.get("type"), item.get("id")
            key = (
                [record.source_id, self.session_uid, native] if native else self.native_key(record)
            )
            if itype in ("UserMessage", "AgentMessage"):
                events = self.message(
                    record,
                    {"role": "user" if itype == "UserMessage" else "assistant", **item},
                    key=key,
                )
                for event in events:
                    event.attrs["native_turn_id"] = payload.get("turn_id")
                return Mapping(events)
            if itype == "Reasoning":
                return Mapping(
                    [
                        self.make(
                            record,
                            "reasoning",
                            "reasoning",
                            actor="assistant",
                            native_key=key,
                            text="\n".join(item.get("summary_text", [])),
                            ext=item,
                        )
                    ]
                )
            if (
                itype
                in (
                    "CommandExecution",
                    "McpToolCall",
                    "FileChange",
                    "WebSearch",
                    "CollabAgentToolCall",
                )
                or itype == "Extension"
                and item.get("kind") == "web.search"
            ):
                call_id = str(native or record.record_uid)
                key = [record.source_id, self.session_uid, "tool", call_id]
                name = {
                    "CommandExecution": "exec_command",
                    "McpToolCall": f"mcp__{item.get('server')}__{item.get('tool')}",
                    "FileChange": "apply_patch",
                    "WebSearch": "web.search",
                    "CollabAgentToolCall": item.get("tool", "subagent"),
                    "Extension": "web.search",
                }[itype]
                args = item.get(
                    "arguments",
                    {"command": " ".join(item.get("command", []))}
                    if itype == "CommandExecution"
                    else {"action": item.get("action"), "query": item.get("query")}
                    if itype in ("WebSearch", "Extension")
                    else item.get("changes"),
                )
                call = self.make(
                    record,
                    "tool.call",
                    "tool.call",
                    actor="assistant",
                    call_id=call_id,
                    native_key=key,
                    attrs={
                        "name": name,
                        "input": args,
                        "category": "subagent" if itype == "CollabAgentToolCall" else None,
                        "duration_ms": item.get("duration_ms"),
                        "native_turn_id": self.native_turn,
                    },
                    ts_value=payload.get("started_at_ms"),
                    ts_field="payload.started_at_ms",
                    ts_unit="milliseconds",
                    semantics="started",
                )
                result = self.make(
                    record,
                    "tool.result",
                    "tool.result",
                    actor="tool",
                    call_id=call_id,
                    native_key=key,
                    text=item.get(
                        "aggregated_output",
                        text_content(item.get("result", {}).get("content"))
                        if isinstance(item.get("result"), dict)
                        else None,
                    ),
                    attrs={
                        "status": item.get("status", "unknown").lower(),
                        "status_scope": "direct_command"
                        if itype == "CommandExecution"
                        else "tool_protocol",
                        "exit_code": item.get("exit_code"),
                        "duration_ms": item.get("duration_ms"),
                        "native_turn_id": self.native_turn,
                    },
                    ts_value=payload.get("completed_at_ms"),
                    ts_field="payload.completed_at_ms",
                    ts_unit="milliseconds",
                    semantics="completed",
                    ext={
                        k: v
                        for k, v in item.items()
                        if k not in ("aggregated_output", "stdout", "stderr", "result")
                    },
                )
                return Mapping([call, result])
            return Mapping(
                [
                    self.make(
                        record,
                        "context.compaction"
                        if itype == "ContextCompaction"
                        else "subagent.spawn"
                        if "SubAgent" in str(itype)
                        else "unknown",
                        "item",
                        ext=item,
                    )
                ]
            )
        return Mapping([self.make(record, "unknown", "event_msg", ext=payload)])
