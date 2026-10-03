from pathlib import Path

from orbit_data.connectors.base import NATIVE_KEY_MATCH, BaseMapper, Mapping
from orbit_data.contract import canonical, time_fields


def reported_cost(usage) -> float | None:
    """pi writes usage.cost as an object; tolerate null or a bare number."""
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if isinstance(cost, dict):
        cost = cost.get("total")
    return cost if isinstance(cost, int | float) and not isinstance(cost, bool) else None


class PiMapper(BaseMapper):
    def prepare(self, records):
        super().prepare(records)
        self.parent_file_id = None
        self.parent_path = None
        self.parent_entries = {}
        self.parent_identity = None
        parent = self.header.get("parentSession")
        if parent:
            root = self.store.db.execute(
                "SELECT root_path FROM source WHERE source_id=?", (self.info["source_id"],)
            ).fetchone()[0]
            path = Path(parent)
            if path.is_absolute() and path.is_relative_to(root):
                parent = str(path.relative_to(root))
            for file in self.store.db.execute(
                "SELECT * FROM source_file WHERE source_id=? AND relative_path=?",
                (self.info["source_id"], parent),
            ):
                self.parent_file_id, self.parent_path = file["file_id"], file["relative_path"]
                for parent_record in self.store.iter_file(file["file_id"]):
                    if parent_record.data.get("type") == "session":
                        self.parent_identity = self.store.identity(
                            self.info["source_id"], str(parent_record.data["id"]), self.parent_path
                        )
                    elif parent_record.data.get("id"):
                        self.parent_entries[parent_record.data["id"]] = canonical(
                            parent_record.data
                        )

    def map(self, record):
        data, typ = record.data, record.data.get("type")
        if typ == "session":
            event = self.meta(
                record,
                str(data["id"]),
                file_scope=record.relative_path,
                cwd=data.get("cwd"),
                harness_version=str(data.get("version")),
                fork_parent_path=data.get("parentSession"),
            )
            if self.parent_identity:
                event.attrs["forked_from_uid"] = self.parent_identity
            return Mapping([event])
        if self.session_uid is None:
            raise ValueError("pi session header is required")
        if self.parent_entries.get(data.get("id")) == canonical(data):
            refs = [
                row[0]
                for row in self.store.db.execute(
                    "SELECT event_uid FROM event WHERE " + NATIVE_KEY_MATCH,
                    (canonical([record.source_id, self.parent_path, data["id"]]),),
                )
            ]
            return Mapping(
                disposition="replayed" if refs else "unparsed",
                references=refs,
                reason="verified fork entry copied from parent",
            )
        if typ == "model_change":
            self.model, self.provider = data.get("modelId"), data.get("provider")
            return Mapping(
                [
                    self.make(
                        record,
                        "setting.change",
                        "model",
                        attrs={"model_raw": self.model, "provider": self.provider},
                    )
                ]
            )
        if typ == "thinking_level_change":
            self.effort = data.get("thinkingLevel")
            return Mapping(
                [self.make(record, "setting.change", "effort", attrs={"effort_raw": self.effort})]
            )
        if typ == "message":
            message = data.get("message", {})
            if message.get("role") == "bashExecution":
                call_id = str(data.get("id", record.record_uid))
                call = self.make(
                    record,
                    "tool.call",
                    "bash.call",
                    actor="human",
                    call_id=call_id,
                    attrs={"name": "bash", "input": {"command": message.get("command")}},
                )
                result = self.make(
                    record,
                    "tool.result",
                    "bash.result",
                    actor="tool",
                    call_id=call_id,
                    text=message.get("output"),
                    attrs={
                        "name": "bash",
                        "exit_code": message.get("exitCode"),
                        "status": "interrupted"
                        if message.get("cancelled")
                        else "completed"
                        if message.get("exitCode") == 0
                        else "failed"
                        if message.get("exitCode") is not None
                        else "unknown",
                        "status_scope": "direct_command",
                    },
                )
                return Mapping([call, result])
            if message.get("role") in ("branchSummary", "compactionSummary"):
                return Mapping(
                    [
                        self.make(
                            record,
                            "branch"
                            if message["role"] == "branchSummary"
                            else "context.compaction",
                            "message.summary",
                            text=message.get("summary"),
                            ext=message,
                        )
                    ]
                )
            self.model = message.get("model", self.model)
            self.provider = message.get("provider", self.provider)
            self.effort = message.get("thinkingLevel", self.effort)
            origin = (
                "injected"
                if message.get("role") in ("custom", "hookMessage", "system", "developer")
                else "human"
            )
            events = self.message(record, message, origin=origin)
            if not events:
                events = [self.make(record, "context.inject", "message.metadata", ext=message)]
            for event in events:
                if data.get("parentId"):
                    event.parent_native_key = [
                        record.source_id,
                        record.relative_path,
                        data["parentId"],
                    ]
                event.attrs["time"]["reported"]["message.timestamp"] = message.get("timestamp")
                if event.ts is None and message.get("timestamp") is not None:
                    event.ts, event.attrs["time"] = time_fields(
                        message["timestamp"],
                        "message.timestamp",
                        "milliseconds",
                        "request_start" if message.get("role") == "assistant" else "created",
                    )
            if message.get("usage"):
                events.append(
                    self.usage(
                        record,
                        message["usage"],
                        "pi",
                        request_id=message.get("responseId"),
                        request_key=[
                            record.source_id,
                            self.session_uid,
                            data.get("id", record.ordinal),
                        ],
                        cost_usd=reported_cost(message["usage"]),
                        cost_source="native_estimate",
                        stop_reason=message.get("stopReason"),
                    )
                )
            # pi ends the agent loop on stopReason error/aborted and records the
            # reason in errorMessage (pi-ai StopReason: stop|length|toolUse|error|aborted).
            stop = message.get("stopReason")
            if message.get("role") == "assistant" and stop in ("error", "aborted"):
                reason = message.get("errorMessage")
                reason = reason if isinstance(reason, str) else None
                if stop == "error":
                    events.append(
                        self.make(
                            record,
                            "error",
                            "message.error",
                            text=reason,
                            attrs={"error_class": "provider_error"},
                        )
                    )
                events.append(
                    self.make(
                        record,
                        "turn.end",
                        "message.stop",
                        attrs={
                            "status": "failed" if stop == "error" else "interrupted",
                            "reason": reason,
                        },
                    )
                )
            return Mapping(events)
        kinds = {
            "compaction": "context.compaction",
            "branch_summary": "branch",
            "session_info": "session.title",
            "custom": "context.inject",
            "context_edit": "branch",
            "label": "branch",
        }
        if typ in kinds:
            return Mapping(
                [
                    self.make(
                        record,
                        kinds[typ],
                        typ,
                        text=data.get("summary", data.get("name")),
                        ext=data,
                    )
                ]
            )
        if typ == "usage":
            self.model, self.provider = (
                data.get("model", self.model),
                data.get("provider", self.provider),
            )
            return Mapping(
                [
                    self.usage(
                        record,
                        data.get("usage", {}),
                        "pi",
                        request_key=self.native_key(record),
                        purpose=data.get("kind", "auxiliary"),
                        cost_usd=reported_cost(data.get("usage")),
                        cost_source="native_estimate",
                    )
                ]
            )
        return self.unknown(record)
