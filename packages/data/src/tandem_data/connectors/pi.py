from pathlib import Path

from tandem_data.connectors.base import BaseMapper, Mapping
from tandem_data.contract import canonical


class PiMapper(BaseMapper):
    def prepare(self, records):
        super().prepare(records)
        self.parent_file_id = None
        self.parent_path = None
        self.parent_entries = set()
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
                self.parent_entries = {
                    record.data.get("id")
                    for record in self.store.iter_file(file["file_id"])
                    if record.data.get("type") != "session"
                }

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
            return Mapping([event])
        if self.session_uid is None:
            raise ValueError("pi session header is required")
        if data.get("id") in self.parent_entries:
            refs = [
                row[0]
                for row in self.store.db.execute(
                    "SELECT event_uid FROM event WHERE native_key=?",
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
            self.model = message.get("model", self.model)
            self.provider = message.get("provider", self.provider)
            self.effort = message.get("thinkingLevel", self.effort)
            events = self.message(record, message)
            for event in events:
                if data.get("parentId"):
                    event.parent_native_key = [
                        record.source_id,
                        record.relative_path,
                        data["parentId"],
                    ]
                event.attrs["time"]["reported"]["message.timestamp"] = message.get("timestamp")
            if message.get("usage"):
                events.append(
                    self.usage(
                        record,
                        message["usage"],
                        "pi",
                        request_id=message.get("responseId"),
                        request_key=[record.source_id, self.session_uid, data["id"]],
                        cost_usd=message["usage"].get("cost", {}).get("total"),
                        cost_source="native_estimate",
                        stop_reason=message.get("stopReason"),
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
            return Mapping(
                [
                    self.usage(
                        record,
                        data.get("usage", {}),
                        "pi",
                        request_key=self.native_key(record),
                        purpose="cache_warmup",
                    )
                ]
            )
        return self.unknown(record)
