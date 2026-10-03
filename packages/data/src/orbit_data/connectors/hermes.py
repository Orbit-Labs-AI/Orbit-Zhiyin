import re

from orbit_data.connectors.base import (
    BaseMapper,
    Mapping,
    decode_json,
    mcp_server_names,
    split_mcp_name,
)
from orbit_data.contract import time_fields, uid, unused


def sanitize(value: str) -> str:
    """hermes-agent tools/mcp_tool_schema.py ``sanitize_mcp_name_component``."""
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def approval_evidence(content) -> tuple[str, dict] | None:
    """Permission event recorded in a Hermes terminal result, if any.

    tools/terminal_tool.py ``_run_approval_guards``: a refused command returns
    ``_error_json(msg, status="blocked")``; gateway ask mode returns
    ``status="pending_approval"``; an approved flagged command carries the ``approval``
    note "... was approved by the user." or "... auto-approved by smart approval."
    (terminal_tool_result.py). Unflagged commands never prompt and record nothing.
    """
    if not isinstance(content, dict):
        return None
    status, note = content.get("status"), content.get("approval")
    if status == "blocked":
        return "permission.decision", {"decision": "denied", "reason": "blocked"}
    if status == "pending_approval":
        return "permission.request", {"reason": "pending_approval"}
    if isinstance(note, str):
        if "approved by the user" in note:
            return "permission.decision", {"decision": "approved", "reason": "user"}
        if "auto-approved by smart approval" in note:
            return "permission.decision", {"decision": "approved", "reason": "smart_approval"}
    return None


def tool_outcome(content) -> tuple[str, int | None]:
    """Status from the explicit fields Hermes tool handlers return as JSON.

    Mirrors the explicit branches of hermes-agent ``agent/display._detect_tool_failure``:
    terminal results carry ``exit_code`` (0 = success), ``tools/registry.tool_error``
    returns ``{"error": msg}``, and handlers report ``success: true|false``. Plain text
    or JSON without these fields stays ``unknown`` (no substring guessing).
    """
    if not isinstance(content, dict):
        return "unknown", None
    exit_code = content.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return ("completed" if exit_code == 0 else "failed"), exit_code
    if content.get("success") is False or content.get("error"):
        return "failed", None
    if content.get("success") is True:
        return "completed", None
    return "unknown", None


class HermesMapper(BaseMapper):
    def prepare(self, records):
        self.active_uids = set()
        self.parents = {}
        self.settings = {}
        self.prompt_sessions = {}
        self.mcp_servers = mcp_server_names(self.store, "hermes")

        def inspect(record):
            table, row = record.data.get("table"), record.data.get("row", {})
            if table == "messages" and row.get("active", 1) and row.get("message_uid"):
                self.active_uids.add((row.get("session_id"), row["message_uid"]))
            if table == "sessions":
                self.parents[row["id"]] = row.get("parent_session_id")
                self.settings[row["id"]] = (row.get("model"), row.get("billing_provider"))
                if row.get("system_prompt_hash"):
                    self.prompt_sessions.setdefault(row["system_prompt_hash"], []).append(row["id"])

        self.prepare_each(records, inspect)

    def make(self, record, *args, **kwargs):
        row = record.data.get("row", {})
        kwargs.setdefault("ts_value", row.get("timestamp"))
        kwargs.setdefault("ts_field", "row.timestamp")
        kwargs.setdefault("ts_unit", "seconds")
        return super().make(record, *args, **kwargs)

    def map(self, record):
        table, row = record.data.get("table"), record.data.get("row", {})
        native = row.get("session_id", row.get("id") if table == "sessions" else None)
        if native:
            self.session_uid = self.store.identity(record.source_id, str(native))
            self.model, self.provider = self.settings.get(native, (None, None))
        if table == "sessions":
            origin = decode_json(row.get("origin_json"), {}) or {}
            kind = (
                "subagent"
                if origin.get("_delegate_from") or row.get("source") == "subagent"
                else "import"
                if origin.get("_imported_from")
                else "main"
            )
            meta = self.meta(
                record,
                str(row["id"]),
                kind=kind,
                parent_native_id=row.get("parent_session_id") if kind == "subagent" else None,
                forked_from_native=row.get("parent_session_id") if kind == "main" else None,
                cwd=row.get("cwd"),
                git_branch=row.get("git_branch"),
                git_root=row.get("git_repo_root"),
                title=row.get("title"),
                title_source=row.get("title_source"),
                model_raw=row.get("model"),
                provider=row.get("billing_provider"),
            )
            meta.ext = unused(
                row,
                (
                    "id",
                    "cwd",
                    "git_branch",
                    "git_repo_root",
                    "title",
                    "title_source",
                    "model",
                    "billing_provider",
                ),
            )
            meta.ts, meta.attrs["time"] = time_fields(
                row.get("started_at"), "row.started_at", "seconds", "created"
            )
            return Mapping([meta])
        if table == "messages":
            if (
                not row.get("active", 1)
                and not row.get("compacted", 0)
                and (row.get("session_id"), row.get("message_uid")) not in self.active_uids
            ):
                return Mapping(
                    [
                        self.make(
                            record,
                            "branch",
                            "rewound.message",
                            ext=row,
                            attrs={"operation": "rewind", "active": False},
                        )
                    ]
                )
            key = (
                [record.source_id, row["message_uid"]]
                if row.get("message_uid")
                else [record.source_id, self.session_uid, row.get("id")]
            )
            role = row.get("role")
            message = {
                "role": role,
                "content": decode_json(row.get("content"), row.get("content")),
                "tool_call_id": row.get("tool_call_uid") or row.get("tool_call_id"),
                "tool_name": row.get("tool_name"),
            }
            if message["content"] is None:
                message["content"] = ""
            display = decode_json(row.get("display_metadata"), {}) or {}
            origin = (
                "injected"
                if display.get("origin") in ("injected", "system") or row.get("_compressed_summary")
                else "human"
            )
            events = self.message(
                record,
                message,
                key=key,
                origin=origin,
                active=bool(row.get("active", 1)),
                compacted=bool(row.get("compacted", 0)),
            )
            permission = []
            for event in events:
                if event.kind == "tool.result":
                    event.attrs["status_scope"] = "tool_protocol"
                    event.attrs["effect_disposition"] = row.get("effect_disposition")
                    if display.get("interrupted"):
                        event.attrs["status"] = "interrupted"
                    elif row.get("effect_disposition") == "none":
                        # Synthesized result for a call that never ran.
                        event.attrs["status"] = "unknown"
                    else:
                        content = message["content"]
                        status, exit_code = tool_outcome(content)
                        event.attrs["status"] = status
                        if exit_code is not None:
                            event.attrs["exit_code"] = exit_code
                        approval = approval_evidence(content)
                        if (
                            status == "failed"
                            and isinstance(content, dict)
                            and content.get("error")
                        ):
                            # tools/registry.tool_error / terminal _error_json envelope.
                            event.attrs["error_class"] = (
                                "permission_refused"
                                if approval and approval[1].get("decision") == "denied"
                                else "tool_error"
                            )
                        if approval:
                            permission.append((event.call_id, approval))
            if row.get("_compressed_summary"):
                for event in events:
                    event.kind = "context.compaction"
            # Decisions precede the result so the reducer attaches them to the open call.
            events[:0] = [
                self.make(
                    record,
                    kind,
                    "approval",
                    call_id=str(call_id),
                    native_key=[*key, "approval", str(call_id)],
                    attrs=attrs,
                )
                for call_id, (kind, attrs) in permission
            ]
            for i, tool in enumerate(decode_json(row.get("tool_calls"), []) or []):
                function = tool.get("function", {})
                uids = decode_json(row.get("tool_call_uids"), []) or []
                call_id = uids[i] if i < len(uids) else tool.get("id")
                if call_id and function.get("name"):
                    events.append(
                        self.make(
                            record,
                            "tool.call",
                            f"tool_calls[{i}]",
                            actor="assistant",
                            call_id=str(call_id),
                            native_key=key,
                            attrs={
                                "name": function["name"],
                                "input": decode_json(function.get("arguments")),
                                "native_call_id": tool.get("id"),
                                **self._mcp(function["name"]),
                            },
                        )
                    )
            for field in (
                "reasoning",
                "reasoning_content",
                "reasoning_details",
                "codex_reasoning_items",
            ):
                if row.get(field) and (
                    field != "reasoning" or row.get("reasoning") != row.get("reasoning_content")
                ):
                    events.append(
                        self.make(
                            record,
                            "reasoning",
                            field,
                            actor="assistant",
                            native_key=key,
                            text=row[field] if isinstance(row[field], str) else None,
                            ext={field: row[field]},
                        )
                    )
            if events:
                events[0].ext["row"] = unused(
                    row,
                    (
                        "id",
                        "session_id",
                        "message_uid",
                        "role",
                        "content",
                        "timestamp",
                        "tool_calls",
                        "tool_call_uid",
                        "tool_call_id",
                        "tool_call_uids",
                        "tool_name",
                        "reasoning",
                        "reasoning_content",
                        "reasoning_details",
                        "codex_reasoning_items",
                    ),
                )
            if (
                not row.get("active", 1)
                and (row.get("session_id"), row.get("message_uid")) in self.active_uids
            ):
                return Mapping(
                    disposition="duplicate",
                    references=[e.event_uid for e in events],
                    reason="inactive carried copy",
                )
            return Mapping(events)
        if table == "session_model_usage":
            self.model, self.provider = row.get("model"), row.get("billing_provider")
            usage = self.usage(
                record,
                row,
                "hermes",
                scope="session_model_snapshot",
                purpose=row.get("task") or "main",
                snapshot_key=uid(
                    "snapshot_key", record.source_id, self.session_uid, record.data.get("key")
                ),
                cost_usd=row.get("actual_cost_usd")
                if row.get("cost_status") == "actual"
                else row.get("estimated_cost_usd"),
                cost_source=row.get("cost_source", "native_estimate"),
            )
            # Observation time and cumulative update time are distinct.
            usage.ts, usage.attrs["time"] = time_fields(
                row.get("last_seen"), "row.last_seen", "seconds", "written"
            )
            return Mapping([usage])
        if table == "system_prompts":
            events = []
            for native in self.prompt_sessions.get(row.get("hash"), []):
                self.session_uid = self.store.identity(record.source_id, str(native))
                events.append(
                    self.make(
                        record,
                        "context.inject",
                        "system_prompt",
                        text=row.get("prompt"),
                        native_key=[
                            record.source_id,
                            self.session_uid,
                            "system_prompt",
                            row["hash"],
                        ],
                        attrs={"origin": "injected", "context_type": "system_prompt"},
                    )
                )
            if events:
                return Mapping(events)
            return Mapping(
                disposition="ignored",
                reason="deduplicated prompt retained in L0; session rows carry prompt hash",
            )
        return self.unknown(record)

    def _mcp(self, name) -> dict:
        """Legacy ``mcp_<server>_<tool>`` names (before hermes-agent #33533 switched to
        ``mcp__<server>__<tool>``, which the reducer splits itself)."""
        if not isinstance(name, str) or name.startswith("mcp__"):
            return {}
        split = split_mcp_name(name, "mcp_", self.mcp_servers, sanitize)
        return {"mcp_server": split[0], "mcp_tool": split[1]} if split else {}
