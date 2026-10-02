import shlex

from tandem_data.connectors.base import BaseMapper, Mapping, decode_json, text_content
from tandem_data.contract import canonical, uid
from tandem_data.duration import native_duration_ms


def select_history(store, mappers):
    """Match native history_base file identities; excluded branches remain in L1."""
    import re
    from collections import defaultdict
    from pathlib import Path

    groups = defaultdict(list)
    active_paths = {}
    for mapper in mappers.values():
        if not isinstance(mapper, CodexMapper):
            continue
        if mapper.info["role"] == "state_index":
            for record in store.iter_file(mapper.info["file_id"]):
                if record.data.get("table") == "threads":
                    row = record.data["row"]
                    active_paths[(record.source_id, str(row.get("id")))] = row.get("rollout_path")
        if mapper.header.get("id"):
            groups[(mapper.info["source_id"], str(mapper.header["id"]))].append(mapper)
    for identity, members in groups.items():
        if len(members) < 2 or not any(m.header.get("history_base") for m in members):
            continue
        aliases = {}
        for mapper in members:
            stem = (
                Path(mapper.info["relative_path"]).name.removesuffix(".zst").removesuffix(".jsonl")
            )
            ids = re.findall(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", stem)
            aliases[ids[-1] if ids else stem.removeprefix("rollout-")] = mapper
        parents = {}
        for mapper in members:
            base = mapper.header.get("history_base") or {}
            parent = aliases.get(base.get("thread_id"))
            if parent is not None and parent is not mapper:
                parents[mapper] = parent
        current_path = active_paths.get(identity)
        active = next(
            (
                m
                for m in members
                if current_path
                and Path(m.info["relative_path"]).name.removesuffix(".zst")
                == Path(current_path).name.removesuffix(".zst")
            ),
            None,
        )
        if active is None:
            sinks = [m for m in members if m not in parents.values()]
            if len(sinks) != 1:
                store.issue(
                    identity[0], "ambiguous_active_history", detail={"branches": len(sinks)}
                )
                continue  # Keep evidence; do not silently choose an arbitrary branch.
            active = sinks[0]
        for mapper in members:
            mapper.history_excluded = True
        bound, seen = float("inf"), set()
        while active is not None and active not in seen:
            seen.add(active)
            active.history_excluded = False
            active.history_end = bound
            cutoff = (active.header.get("history_base") or {}).get("end_ordinal_exclusive")
            if isinstance(cutoff, int):
                bound = min(bound, cutoff)
            active = parents.get(active)


class CodexMapper(BaseMapper):
    def subagent_events(self, record, kind, payload, path):
        """Native child identity is required; UI item ids are not child sessions."""
        children = []
        for key in ("agent_thread_id", "receiver_thread_id", "new_thread_id", "agent_id"):
            if isinstance(payload.get(key), str) and payload[key]:
                children.append(payload[key])
        for key in ("receiver_thread_ids", "agent_thread_ids"):
            if isinstance(payload.get(key), list):
                children.extend(c for c in payload[key] if isinstance(c, str) and c)
        statuses = payload.get("agent_statuses") or payload.get("statuses")
        if isinstance(statuses, dict):
            children.extend(c for c in statuses if isinstance(c, str) and c)
        result = []
        for child in sorted(set(children)) or [None]:
            attrs = {
                "parent_session_uid": self.session_uid,
                "lifecycle_phase": payload.get("kind", payload.get("type")),
                "status": payload.get("status") or "completed"
                if kind == "subagent.result"
                else "unknown",
            }
            if child:
                attrs["child_session_uid"] = self.store.identity(record.source_id, child)
                attrs["child_native_id"] = child
            else:
                attrs["relation_missing_reason"] = "native_child_identity_missing"
            result.append(
                self.make(
                    record,
                    kind,
                    path + ("." + child if child else ""),
                    actor="subagent",
                    attrs=attrs,
                    ext=payload,
                )
            )
        return result

    def prepare(self, records):
        self.has_calls = False
        self.messages = {}
        self.usage_records = []
        self.matched_messages = set()
        self.cut = None
        self.parent = None
        self.prepared_turn = None
        self.ui_keys = {}
        self.ui_messages = {}
        self.rollback_ranges = []
        self.human_starts = []
        self.last_human_turn = None
        self.prepare_each(records, self.prepare_record)

    def prepare_record(self, record):
        data, payload = record.data, record.data.get("payload", {})
        if data.get("type") in ("turn_context", "event_msg"):
            self.prepared_turn = payload.get("turn_id", self.prepared_turn)
        if data.get("type") == "event_msg":
            is_human = payload.get("type") == "user_message" or (
                payload.get("type") == "item_completed"
                and payload.get("item", {}).get("type") == "UserMessage"
            )
            if is_human and (
                self.prepared_turn is None or self.prepared_turn != self.last_human_turn
            ):
                self.human_starts.append(record.ordinal)
                self.last_human_turn = self.prepared_turn
            if payload.get("type") == "thread_rolled_back":
                count = payload.get("num_turns")
                if isinstance(count, int) and count > 0 and self.human_starts:
                    start = self.human_starts[max(0, len(self.human_starts) - count)]
                    self.rollback_ranges.append((start, record.ordinal))
                    self.human_starts = [x for x in self.human_starts if x < start]
                    self.last_human_turn = None
        if data.get("type") == "session_meta" and not self.header:
            self.header = payload
            source = payload.get("source", {})
            subagent = source.get("subagent", {}) if isinstance(source, dict) else {}
            spawn = subagent.get("thread_spawn", {}) if isinstance(subagent, dict) else {}
            self.cut = payload.get("subagent_history_start_ordinal") if spawn else None
            self.parent = payload.get("parent_thread_id", payload.get("forked_from_id"))
            self.parent = self.parent or spawn.get("parent_thread_id")
            self.parent_candidates = {}
            self.parent_cursor = -1
        if data.get("type") == "token_usage_record":
            self.has_calls = True
            self.usage_records.append((record.ordinal, payload.get("response_id")))
        if data.get("type") == "event_msg" and payload.get("type") == "item_completed":
            item = payload.get("item", {})
            if item.get("type") in ("UserMessage", "AgentMessage"):
                role = "user" if item["type"] == "UserMessage" else "assistant"
                signature = (role, self.prepared_turn, text_content(item.get("content")))
                native = item.get("id") or "ui:" + record.record_uid
                self.ui_keys[record.record_uid] = native
                self.ui_messages[native] = {**item, "role": role}
                self.messages.setdefault(signature, []).append((record.ordinal, native))
        if data.get("type") == "event_msg" and payload.get("type") in (
            "user_message",
            "agent_message",
        ):
            role = "user" if payload["type"] == "user_message" else "assistant"
            signature = (
                role,
                self.prepared_turn,
                text_content(payload.get("message", payload.get("content"))),
            )
            native = payload.get("id") or "ui:" + record.record_uid
            self.ui_keys[record.record_uid] = native
            self.ui_messages[native] = {
                "role": role,
                "content": payload.get("message", payload.get("content")),
                "phase": payload.get("phase"),
            }
            self.messages.setdefault(signature, []).append((record.ordinal, native))

    def native_key(self, record):
        payload = record.data.get("payload", {})
        native = payload.get("id") if isinstance(payload, dict) else None
        return (
            [record.source_id, self.session_uid, native] if native else super().native_key(record)
        )

    @staticmethod
    def record_signature(record):
        return uid("native_payload", record.data.get("type"), record.data.get("payload"))

    def map(self, record):
        data, typ = record.data, record.data.get("type")
        payload = data.get("payload", {})
        if data.get("table") in ("threads", "thread_spawn_edges"):
            typ = "state_index" if data["table"] == "threads" else "spawn_edge"
            payload = data["row"]
        if self.info["role"] == "title_index":
            payload, typ = data, "title_index"
        if self.info["role"] == "import_ledger" and "records" in data:
            entries = data["records"]
            entries = list(entries.values()) if isinstance(entries, dict) else entries
            events = []
            for index, item in enumerate(entries or []):
                native = item.get("imported_thread_id")
                if native:
                    self.session_uid = self.store.identity(record.source_id, str(native))
                    events.append(
                        self.make(
                            record,
                            "session.meta",
                            f"imports[{index}]",
                            attrs={"kind": "import"},
                            ext=item,
                        )
                    )
            return Mapping(
                events, disposition=None if events else "ignored", reason="import ledger"
            )
        if typ in ("state_index", "title_index", "spawn_edge", "import_ledger"):
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
                            text=payload.get(
                                "thread_name", payload.get("name", payload.get("title"))
                            ),
                            attrs={"title_source": "native"},
                        )
                    ]
                )
            attrs = {}
            if typ in ("import_ledger", "spawn_edge"):
                attrs["kind"] = "import" if typ == "import_ledger" else "subagent"
            if typ == "spawn_edge" and payload.get("parent_thread_id"):
                attrs["parent_uid"] = self.store.identity(
                    record.source_id, payload["parent_thread_id"]
                )
            if typ == "state_index":
                attrs.update(
                    title=payload.get("name", payload.get("title")),
                    title_source="native",
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
        if self.session_uid is None:
            native = str(self.header.get("id", self.header.get("session_id", record.relative_path)))
            self.session_uid = self.store.identity(record.source_id, native)
            self.model = self.header.get("model")
            self.provider = self.header.get("model_provider")
        # Copied prefix is excluded only with explicit native boundary evidence.
        ordinal = data.get("ordinal", record.ordinal)
        if (
            getattr(self, "history_excluded", False)
            or ordinal >= getattr(self, "history_end", float("inf"))
            or any(start <= record.ordinal < end for start, end in self.rollback_ranges)
        ):
            return Mapping(
                disposition="ignored",
                reason="superseded native branch; retained in source trajectory",
            )
        if self.cut is not None and ordinal > 0 and ordinal < self.cut:
            if data.get("type") == "turn_context":
                self.model = payload.get("model", self.model)
                self.effort = payload.get("effort", self.effort)
            elif data.get("type") == "world_state":
                self.model = payload.get("state", {}).get("model", self.model)
            refs = []
            candidates = self.parent_candidates.get(self.record_signature(record), [])
            candidate = next((item for item in candidates if item[0] > self.parent_cursor), None)
            if candidate:
                self.parent_cursor = candidate[0]
                refs = [
                    row[0]
                    for row in self.store.db.execute(
                        "SELECT event_uid FROM record_event WHERE record_uid=?",
                        (candidate[1],),
                    )
                ]
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
            if refs:
                return Mapping(disposition="replayed", references=refs, reason="inherited prefix")
            # The native cutoff proves this is supplied history, not new child behavior.
            # Parent history may have been compacted/replaced since the fork. Preserve
            # the child's actual evidence as context, without inventing a parent link.
            self.store.issue(
                record.source_id,
                "inherited_parent_evidence_unavailable",
                file_id=record.file_id,
                record_uid=record.record_uid,
                detail={"native_type": record.native_type, "parent_native_id": self.parent},
            )
            return Mapping(
                [
                    self.make(
                        record,
                        "context.inject",
                        "inherited.unresolved_context",
                        actor="harness",
                        attrs={
                            "origin": "injected",
                            "inherited_prefix": True,
                            "parent_evidence": "unavailable",
                            "native_type": record.native_type,
                        },
                        native_key=[
                            record.source_id,
                            self.session_uid,
                            record.record_uid,
                            "inherited",
                        ],
                    )
                ],
                reason="native inherited prefix retained; parent evidence unavailable",
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
            item_type = payload.get("type")
            turn = payload.get("internal_chat_message_metadata_passthrough", {}).get(
                "turn_id", self.native_turn
            )
            if item_type == "message":
                role = payload.get("role")
                signature = (role, turn, text_content(payload.get("content")))
                candidates = self.messages.get(signature, [])
                matching = [
                    (ordinal, native)
                    for ordinal, native in candidates
                    if native == payload.get("id")
                ]
                if not matching:
                    matching = [
                        (ordinal, native)
                        for ordinal, native in candidates
                        if (turn is not None or abs(ordinal - record.ordinal) <= 2)
                        and native not in self.matched_messages
                        and (
                            not payload.get("phase")
                            or not self.ui_messages[native].get("phase")
                            or payload["phase"] == self.ui_messages[native]["phase"]
                        )
                    ]
                pair = (
                    min(matching, key=lambda item: abs(item[0] - record.ordinal))
                    if matching
                    else None
                )
                key_id = pair[1] if pair else payload.get("id")
                if pair:
                    self.matched_messages.add(key_id)
                key = (
                    [record.source_id, self.session_uid, key_id]
                    if key_id
                    else self.native_key(record)
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
                    self.message(
                        record,
                        {
                            **payload,
                            **self.ui_messages[key_id],
                            "phase": self.ui_messages[key_id].get("phase") or payload.get("phase"),
                        }
                        if pair
                        else payload,
                        origin=origin,
                        key=key,
                        native_turn_id=turn,
                    )
                )
            if item_type in (
                "function_call",
                "custom_tool_call",
                "local_shell_call",
                "tool_search_call",
                "web_search_call",
                "image_generation_call",
            ):
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
                                "name": payload.get(
                                    "name",
                                    "tool_search" if item_type == "tool_search_call" else item_type,
                                ),
                                "input": decode_json(
                                    payload.get(
                                        "arguments", payload.get("input", payload.get("action"))
                                    )
                                ),
                                "native_turn_id": turn,
                            },
                            ext=payload,
                        )
                    ]
                )
            if item_type in (
                "function_call_output",
                "custom_tool_call_output",
                "tool_search_output",
            ):
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
                            text=text_content(payload.get("output", payload.get("tools"))),
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
                            text=text_content(payload.get("summary"))
                            or text_content(payload.get("content")),
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
            if item_type in ("compaction", "compaction_summary", "context_compaction"):
                return Mapping(
                    [
                        self.make(
                            record,
                            "context.compaction",
                            item_type,
                            text=text_content(payload.get("summary", payload.get("content"))),
                            ext=payload,
                        )
                    ]
                )
            return self.unknown(record)
        if typ == "event_msg":
            etype = payload.get("type")
            self.native_turn = payload.get("turn_id", self.native_turn)
            if etype == "thread_goal_updated":
                return Mapping(
                    [self.make(record, "plan.update", "thread.goal", actor="harness", ext=payload)]
                )
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
            if etype in (
                "task_started",
                "turn_started",
                "task_complete",
                "turn_complete",
                "turn_aborted",
            ):
                started = etype in ("task_started", "turn_started")
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
                    else Mapping(
                        disposition="ignored", reason="rate-limit observation without usage"
                    )
                )
            if etype in ("user_message", "agent_message"):
                return Mapping(
                    self.message(
                        record,
                        {
                            "role": "user" if etype == "user_message" else "assistant",
                            "content": payload.get("message", payload.get("content", "")),
                            "phase": payload.get("phase"),
                        },
                        origin="human",
                        key=[record.source_id, self.session_uid, self.ui_keys[record.record_uid]],
                    )
                )
            if etype in ("agent_reasoning", "agent_reasoning_raw_content"):
                return Mapping(
                    [
                        self.make(
                            record,
                            "reasoning",
                            etype,
                            actor="assistant",
                            text=text_content(payload.get("text", payload.get("content"))),
                            ext=payload,
                        )
                    ]
                )
            if etype in (
                "exec_command_begin",
                "exec_command_end",
                "mcp_tool_call_begin",
                "mcp_tool_call_end",
                "patch_apply_begin",
                "patch_apply_end",
                "dynamic_tool_call_request",
                "dynamic_tool_call_response",
            ):
                return self.legacy_tool(record, payload)
            if etype == "item_completed":
                item = payload.get("item", {})
                itype, native = item.get("type"), item.get("id")
                native = native or self.ui_keys.get(record.record_uid)
                key = (
                    [record.source_id, self.session_uid, native]
                    if native
                    else self.native_key(record)
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
                                text="\n".join(item.get("summary_text", []))
                                or "\n".join(item.get("raw_content", [])),
                                ext=item,
                            )
                        ]
                    )
                if itype == "FunctionCallOutput":
                    call_id = str(native or record.record_uid)
                    return Mapping(
                        [
                            self.make(
                                record,
                                "tool.result",
                                "tool.result",
                                actor="tool",
                                call_id=call_id,
                                native_key=[record.source_id, self.session_uid, "tool", call_id],
                                text=text_content(item.get("output")),
                                attrs={"status": "unknown", "native_turn_id": self.native_turn},
                                ext=item,
                            )
                        ]
                    )
                if itype == "SubAgentActivity":
                    kind = {"started": "subagent.spawn", "completed": "subagent.result"}.get(
                        item.get("kind"), "subagent.activity"
                    )
                    return Mapping(self.subagent_events(record, kind, item, "subagent.activity"))
                if (
                    itype
                    in (
                        "CommandExecution",
                        "McpToolCall",
                        "FileChange",
                        "WebSearch",
                        "CollabAgentToolCall",
                        "ImageView",
                    )
                    or itype == "Extension"
                    and item.get("kind") in ("web.search", "clock.sleep", "image_gen.generation")
                ):
                    call_id = str(native or record.record_uid)
                    key = [record.source_id, self.session_uid, "tool", call_id]
                    name = {
                        "CommandExecution": "exec_command",
                        "McpToolCall": f"mcp__{item.get('server')}__{item.get('tool')}",
                        "FileChange": "apply_patch",
                        "WebSearch": "web.search",
                        "CollabAgentToolCall": item.get("tool", "subagent"),
                        "ImageView": "view_image",
                        "Extension": item.get("kind"),
                    }[itype]
                    args = item.get(
                        "arguments",
                        {
                            "command": shlex.join(item.get("command", []))
                            if isinstance(item.get("command"), list)
                            else item.get("command")
                        }
                        if itype == "CommandExecution"
                        else {"action": item.get("action"), "query": item.get("query")}
                        if itype in ("WebSearch", "Extension")
                        else item.get("changes"),
                    )
                    if itype == "ImageView":
                        args = {"path": item.get("path")}
                    elif itype == "Extension" and item.get("kind") == "clock.sleep":
                        args = {"duration_ms": item.get("durationMs")}
                    elif itype == "Extension" and item.get("kind") == "image_gen.generation":
                        # revisedPrompt is the completed tool's rewrite, not the original user input.
                        args = item.get("arguments")
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
                            "duration_ms": native_duration_ms(item),
                            "native_execution_ms": native_duration_ms(item)
                            if itype == "CommandExecution"
                            else None,
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
                            "status": str(item.get("status") or "unknown").lower(),
                            "status_scope": "direct_command"
                            if itype == "CommandExecution"
                            else "tool_protocol",
                            "exit_code": item.get("exit_code"),
                            "duration_ms": native_duration_ms(item),
                            "native_execution_ms": native_duration_ms(item)
                            if itype == "CommandExecution"
                            else None,
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
                            else "plan.update"
                            if itype == "Plan"
                            else "hook.run"
                            if itype == "HookPrompt"
                            else "unknown",
                            "item",
                            ext=item,
                        )
                    ]
                )
            kind = {
                "thread_rolled_back": "branch",
                "undo_started": "branch",
                "undo_completed": "branch",
                "request_user_input": "permission.request",
                "request_permissions": "permission.request",
                "exec_approval_request": "permission.request",
                "apply_patch_approval_request": "permission.request",
                "elicitation_request": "permission.request",
                "elicitation_response": "permission.decision",
                "request_user_input_response": "permission.decision",
                "exec_approval_response": "permission.decision",
                "apply_patch_approval_response": "permission.decision",
                "plan_update": "plan.update",
                "error": "error",
                "warning": "error",
                "context_compacted": "context.compaction",
                "session_configured": "setting.change",
                "item_started": "ui.state",
                "agent_message_delta": "ui.state",
                "agent_reasoning_delta": "ui.state",
                "exec_command_output_delta": "ui.state",
                "collab_agent_spawn_begin": "subagent.activity",
                "collab_agent_spawn_end": "subagent.spawn",
                "collab_agent_interaction_begin": "subagent.message",
                "collab_agent_interaction_end": "subagent.message",
                "collab_waiting_begin": "subagent.wait",
                "collab_waiting_end": "subagent.wait",
                "collab_close_begin": "subagent.close",
                "collab_close_end": "subagent.close",
            }.get(etype, "unknown")
            if kind.startswith("subagent."):
                return Mapping(
                    self.subagent_events(record, kind, payload, "event_msg." + str(etype))
                )
            return Mapping(
                [
                    self.make(
                        record,
                        kind,
                        "event_msg." + str(etype),
                        text=text_content(payload.get("message", payload.get("text"))) or None,
                        ext=payload,
                    )
                ]
            )
        if typ in ("compacted", "compaction", "world_state"):
            return Mapping(
                [
                    self.make(
                        record,
                        "context.inject" if typ == "world_state" else "context.compaction",
                        typ,
                        text=text_content(payload.get("message", payload.get("summary"))) or None,
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

    def legacy_tool(self, record, payload):
        typ = payload["type"]
        call_id = str(payload.get("call_id", payload.get("id", record.record_uid)))
        started = typ.endswith(("_begin", "_request"))
        invocation = payload.get("invocation") or {}
        name = (
            "exec_command"
            if typ.startswith("exec_")
            else "apply_patch"
            if typ.startswith("patch_")
            else "mcp__"
            + str(invocation.get("server", "unknown"))
            + "__"
            + str(invocation.get("tool", "unknown"))
            if typ.startswith("mcp_")
            else payload.get("tool", "unknown")
        )
        attrs = {"name": name, "native_turn_id": self.native_turn}
        if started:
            attrs["input"] = payload.get(
                "arguments",
                invocation.get("arguments", payload.get("command", payload.get("changes"))),
            )
        else:
            attrs.update(
                status=payload.get("status")
                or (
                    "failed"
                    if payload.get("error")
                    or payload.get("exit_code") not in (None, 0)
                    or payload.get("success") is False
                    else "completed"
                    if payload.get("exit_code") == 0 or payload.get("success") is True
                    else "unknown"
                ),
                exit_code=payload.get("exit_code"),
                duration_ms=payload.get("duration_ms"),
            )
        return Mapping(
            [
                self.make(
                    record,
                    "tool.call" if started else "tool.result",
                    "tool.call" if started else "tool.result",
                    actor="assistant" if started else "tool",
                    call_id=call_id,
                    native_key=[record.source_id, self.session_uid, "tool", call_id],
                    text=None
                    if started
                    else text_content(
                        payload.get(
                            "aggregated_output", payload.get("output", payload.get("result"))
                        )
                    ),
                    attrs=attrs,
                    ext=payload,
                )
            ]
        )
