"""Retain published facts when an indexed original disappears.

Only existing L1/L2 rows are carried through a rebuild. No native payload is
recreated, and retained facts explicitly remain marked as unavailable evidence.
"""

import json
from pathlib import Path

from tandem_data.contract import canonical
from tandem_data.privacy import redact, sanitize
from tandem_data.store import insert


class RetainedProjection:
    def __init__(self, store):
        self.files = {}
        self.events = []
        self.links = []
        self.records = []
        for row in store.db.execute(
            "SELECT f.*,s.root_path FROM source_file f JOIN source s USING(source_id) "
            "WHERE s.source_id IN (SELECT source_id FROM rebuild_scope) AND "
            "(SELECT archive_uid FROM source_revision v WHERE v.file_id=f.file_id ORDER BY revision DESC LIMIT 1) IS NULL"
        ):
            if not (Path(row["root_path"]) / row["relative_path"]).exists():
                self.files[row["file_id"]] = dict(row)
        for file_id in self.files:
            self.events.extend(
                dict(r)
                for r in store.db.execute(
                    "SELECT e.* FROM event e JOIN raw_record r USING(record_uid) WHERE r.file_id=? ORDER BY e.session_uid,e.seq",
                    (file_id,),
                )
            )
            self.records.extend(
                dict(r)
                for r in store.db.execute(
                    "SELECT record_uid,disposition,note FROM raw_record WHERE file_id=?", (file_id,)
                )
            )
            self.links.extend(
                dict(r)
                for r in store.db.execute(
                    "SELECT x.* FROM record_event x JOIN raw_record r USING(record_uid) WHERE r.file_id=?",
                    (file_id,),
                )
            )

    def restore(self, store, sequences, first_by_native):
        for event in self.events:
            event["seq"] = sequences[event["session_uid"]]
            sequences[event["session_uid"]] += 1
            event["turn_uid"] = None
            attrs = json.loads(event["attrs"])
            attrs.update(source_status="missing", preserved_mapper_version=event["mapper_version"])
            event["attrs"] = canonical(sanitize(attrs))
            event["ext"] = canonical(sanitize(json.loads(event["ext"])))
            if event["text"] is not None:
                event["text"] = redact(event["text"])
            insert(store.db, "event", event)
            first_by_native.setdefault(event["native_key"], event["event_uid"])
        for row in self.records:
            store.db.execute(
                "UPDATE raw_record SET disposition=?,note=? WHERE record_uid=?",
                (row["disposition"], row["note"], row["record_uid"]),
            )
        for file_id, info in self.files.items():
            store.db.execute(
                "UPDATE source_file SET status='gone_upstream' WHERE file_id=?", (file_id,)
            )
            store.issue(
                info["source_id"],
                "source_unavailable",
                file_id=file_id,
                detail={"status": "missing", "facts": "previously_published"},
            )

    def finish(self, store, infos):
        for link in self.links:
            if store.db.execute(
                "SELECT 1 FROM event WHERE event_uid=?", (link["event_uid"],)
            ).fetchone():
                store.db.execute(
                    "INSERT OR IGNORE INTO record_event VALUES(?,?,?,?)",
                    tuple(link[k] for k in ("record_uid", "event_uid", "relation", "contribution")),
                )
        # An unavailable secondary representation may no longer have a canonical
        # event after a healthy source rewrite. Keep the gap rather than a broken link.
        for row in self.records:
            relations = {
                r[0]
                for r in store.db.execute(
                    "SELECT relation FROM record_event WHERE record_uid=?", (row["record_uid"],)
                )
            }
            disposition = next(
                (r for r in ("mapped", "folded", "replayed", "duplicate") if r in relations), None
            )
            if disposition:
                store.db.execute(
                    "UPDATE raw_record SET disposition=? WHERE record_uid=?",
                    (disposition, row["record_uid"]),
                )
            elif row["disposition"] not in ("ignored", "unparsed"):
                store.db.execute(
                    "UPDATE raw_record SET disposition='unparsed',note=? WHERE record_uid=?",
                    (
                        canonical(
                            {"reason": "missing source; canonical event no longer available"}
                        ),
                        row["record_uid"],
                    ),
                )
        ranks = {info["file_id"]: index for index, info in enumerate(infos)}
        for session_uid in {event["session_uid"] for event in self.events}:
            events = list(
                store.db.execute(
                    "SELECT e.event_uid,e.seq,r.file_id FROM event e JOIN raw_record r USING(record_uid) WHERE e.session_uid=? ORDER BY e.seq",
                    (session_uid,),
                )
            )
            if not events:
                continue
            # Keep each file's native order, placing cached and live files back in
            # the same dependency order as normal mapping.
            events.sort(key=lambda e: (ranks.get(e["file_id"], len(ranks)), e["seq"]))
            shift = max(e["seq"] for e in events) + len(events) + 1
            store.db.execute("UPDATE event SET seq=seq+? WHERE session_uid=?", (shift, session_uid))
            store.db.executemany(
                "UPDATE event SET seq=? WHERE event_uid=?",
                ((i, e["event_uid"]) for i, e in enumerate(events)),
            )
        store.db.execute(
            "UPDATE event SET parent_uid=NULL WHERE parent_uid IS NOT NULL AND parent_uid NOT IN (SELECT event_uid FROM event)"
        )
