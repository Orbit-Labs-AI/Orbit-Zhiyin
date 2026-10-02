"""Atomic L2 replacement and provenance accounting; L0 never depends on L2."""

import json
from collections import defaultdict

from tandem_data import MAPPER_VERSION, REDUCER_VERSION
from tandem_data.connectors import MAPPERS
from tandem_data.contract import canonical, now_ms, validate_event
from tandem_data.privacy import REDACTION_VERSION
from tandem_data.store import insert


def _merge(old, new):
    result = dict(old)
    for key, value in new.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        elif result.get(key) is None or result.get(key) in ("", "unknown"):
            result[key] = value
        elif key not in result:
            result[key] = value
    return result


def rebuild(store, *, mapper_version=None, source_ids=None):
    from tandem_data.reduce import derive

    mapper_version = mapper_version or MAPPER_VERSION
    sequences = defaultdict(int)
    parent_keys = {}
    first_by_native = {}
    pending = []
    store._kimi_indexes = {}
    with store.transaction():
        store.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS rebuild_scope(source_id TEXT PRIMARY KEY)"
        )
        store.db.execute("DELETE FROM rebuild_scope")
        if source_ids is None:
            store.db.execute("INSERT INTO rebuild_scope SELECT source_id FROM source")
        else:
            store.db.executemany(
                "INSERT INTO rebuild_scope VALUES(?)", ((s,) for s in sorted(set(source_ids)))
            )
        sessions = "SELECT session_uid FROM session_identity WHERE source_id IN (SELECT source_id FROM rebuild_scope)"
        evidence = "SELECT event_uid FROM event WHERE session_uid IN (" + sessions + ")"
        source_files = "SELECT file_id FROM source_file WHERE source_id IN (SELECT source_id FROM rebuild_scope)"
        store.db.execute(
            "DELETE FROM tool_call_event WHERE call_uid IN (SELECT call_uid FROM tool_call WHERE session_uid IN ("
            + sessions
            + "))"
        )
        for table in ("record_event", "event_context"):
            store.db.execute(f"DELETE FROM {table} WHERE event_uid IN ({evidence})")
        for table in (
            "model_call",
            "usage_snapshot",
            "session_feature",
            "link",
            "tool_call",
            "turn",
            "session",
            "event",
        ):
            store.db.execute(f"DELETE FROM {table} WHERE session_uid IN ({sessions})")
        store.db.execute(
            "DELETE FROM ingest_issue WHERE stage IN ('l2','l3') AND source_id IN (SELECT source_id FROM rebuild_scope)"
        )
        store.db.execute(
            "UPDATE raw_record SET disposition='ignored',note=? WHERE file_id IN ("
            + source_files
            + ")",
            (canonical({"reason": "superseded source row version"}),),
        )
        store.db.execute(
            "UPDATE raw_record SET disposition='unparsed',note='{}' WHERE file_id IN ("
            + source_files
            + ") AND record_uid IN (SELECT record_uid FROM file_record)"
        )
        infos = list(
            store.db.execute(
                "SELECT f.*,s.agent FROM source_file f JOIN source s USING(source_id) "
                "WHERE s.source_id IN (SELECT source_id FROM rebuild_scope) ORDER BY s.agent,f.source_id,f.relative_path"
            )
        )
        mappers = {}
        for info in infos:
            if info["role"] == "legacy_transcript":
                store.db.execute(
                    "UPDATE raw_record SET disposition='ignored',note=? WHERE file_id=?",
                    (
                        canonical({"reason": "newer native format generation is canonical"}),
                        info["file_id"],
                    ),
                )
                continue
            if info["agent"] not in MAPPERS:
                store.issue(
                    info["source_id"], "unsupported_connector", stage="l2", file_id=info["file_id"]
                )
                continue
            mapper = MAPPERS[info["agent"]](store, info)
            mapper.prepare(store.iter_file(info["file_id"]))
            mappers[info["file_id"]] = mapper

        store.db.execute(
            "UPDATE raw_record SET disposition='ignored',note=? WHERE native_type='pending_tail'",
            (canonical({"reason": "incomplete_tail_retained_in_L0"}),),
        )
        # Native parent files precede copied child prefixes; metadata snapshots come last.
        by_native = {
            (
                info["source_id"],
                str(
                    mappers[info["file_id"]].header.get(
                        "session_id", mappers[info["file_id"]].header.get("id", "")
                    )
                ),
            ): info["file_id"]
            for info in infos
            if info["file_id"] in mappers
        }
        by_file = {info["file_id"]: info for info in infos}
        ordered, visiting, visited = [], set(), set()

        def visit(info):
            file_id = info["file_id"]
            if file_id in visited or file_id in visiting:
                return
            visiting.add(file_id)
            mapper = mappers.get(file_id)
            header = mapper.header if mapper else {}
            parent_id = header.get(
                "parentSession", header.get("parent_thread_id", header.get("forked_from_id"))
            )
            parent_file = getattr(mapper, "parent_file_id", None) or by_native.get(
                (info["source_id"], str(parent_id))
            )
            if parent_file and parent_file != file_id:
                visit(by_file[parent_file])
            visiting.remove(file_id)
            visited.add(file_id)
            ordered.append(info)

        for info in sorted(
            infos, key=lambda item: item["role"] in ("index_db", "title_index", "import_ledger")
        ):
            visit(info)
        infos = ordered

        def map_record(mapper, record):
            try:
                if record.record_uid in getattr(mapper, "preparation_failures", ()):
                    raise ValueError("native_preparation_error")
                result = mapper.map(record)
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                store.issue(
                    record.source_id,
                    "native_mapping_error",
                    record_uid=record.record_uid,
                    file_id=record.file_id,
                    detail={"exception": type(error).__name__},
                )
                store.db.execute(
                    "UPDATE raw_record SET disposition='unparsed',note=? WHERE record_uid=?",
                    (canonical({"reason": "native_mapping_error"}), record.record_uid),
                )
                return
            # Keep all source fields on one event, with bounded/redacted projection copies.
            # Exact bytes (including media and unknown fields) are always addressed in L0.
            if result.events:
                result.events[0].ext = {"native": record.data, **result.events[0].ext}
            # Contract errors are implementation bugs: abort and retain the previous published projection.
            prepared = [
                (draft, draft.envelope(record.record_uid, 0, mapper_version))
                for draft in result.events
            ]
            for _, envelope in prepared:
                validate_event(envelope)
            relations = []
            for draft, prepared_envelope in prepared:
                existing = store.db.execute(
                    "SELECT * FROM event WHERE event_uid=?", (draft.event_uid,)
                ).fetchone()
                if existing:
                    relation = (
                        "replayed" if existing["session_uid"] != draft.session_uid else "duplicate"
                    )
                    if relation != "replayed":
                        attrs, ext = json.loads(existing["attrs"]), json.loads(existing["ext"])
                        incoming = {**prepared_envelope, "seq": existing["seq"]}
                        merged, merged_ext = (
                            _merge(attrs, incoming["attrs"]),
                            _merge(ext, incoming["ext"]),
                        )
                        stamp = existing["ts"]
                        if (
                            draft.attrs["time"]["semantics"] in ("started", "completed")
                            and draft.ts is not None
                            and attrs["time"]["semantics"] in ("written", "unknown")
                        ):
                            merged["time"], stamp = draft.attrs["time"], draft.ts
                        if draft.kind == "model.usage":
                            for token in (
                                "input_tokens",
                                "output_tokens",
                                "cache_read_tokens",
                                "cache_write_tokens",
                            ):
                                if (
                                    attrs.get(token) is not None
                                    and draft.attrs.get(token) is not None
                                    and attrs[token] != draft.attrs[token]
                                ):
                                    store.issue(
                                        record.source_id,
                                        "conflicting_request_usage",
                                        record_uid=record.record_uid,
                                        file_id=record.file_id,
                                        detail={"field": token},
                                    )
                        if merged != attrs or merged_ext != ext or stamp != existing["ts"]:
                            relation = "folded"
                            store.db.execute(
                                "UPDATE event SET attrs=?,ext=?,ts=? WHERE event_uid=?",
                                (canonical(merged), canonical(merged_ext), stamp, draft.event_uid),
                            )
                    store.db.execute(
                        "INSERT OR IGNORE INTO record_event VALUES(?,?,?,'{}')",
                        (record.record_uid, draft.event_uid, relation),
                    )
                else:
                    envelope = {**prepared_envelope, "seq": sequences[draft.session_uid]}
                    sequences[draft.session_uid] += 1
                    envelope["native_key"] = canonical(envelope["native_key"])
                    envelope["attrs"] = canonical(envelope["attrs"])
                    envelope["ext"] = canonical(envelope["ext"])
                    insert(store.db, "event", envelope)
                    relation = "mapped"
                    store.db.execute(
                        "INSERT INTO record_event VALUES(?,?,?,'{}')",
                        (record.record_uid, draft.event_uid, relation),
                    )
                    key = canonical(draft.native_key)
                    first_by_native.setdefault(key, draft.event_uid)
                    if draft.parent_native_key:
                        parent_keys[draft.event_uid] = canonical(draft.parent_native_key)
                    if draft.kind == "unknown":
                        store.issue(
                            record.source_id,
                            "unknown_native_type",
                            record_uid=record.record_uid,
                            file_id=record.file_id,
                            detail={"native_type": record.native_type},
                        )
                relations.append(relation)
                store.db.execute(
                    "UPDATE raw_record SET session_uid=? WHERE record_uid=?",
                    (draft.session_uid, record.record_uid),
                )
            if result.references:
                pending.append((record, result))
            if relations:
                disposition = next(
                    kind
                    for kind in ("mapped", "folded", "replayed", "duplicate")
                    if kind in relations
                )
            else:
                disposition = result.disposition or "ignored"
            store.db.execute(
                "UPDATE raw_record SET disposition=?,note=? WHERE record_uid=?",
                (
                    disposition,
                    canonical({"reason": result.reason} if result.reason else {}),
                    record.record_uid,
                ),
            )

        for info in infos:
            mapper = mappers.get(info["file_id"])
            if mapper is None:
                continue
            for record in store.iter_file(info["file_id"]):
                if record.native_type == "table:session_model_usage":
                    continue  # All versions, in observation order, are mapped below.
                map_record(mapper, record)
            for record in store.iter_versions(info["file_id"], "table:session_model_usage"):
                map_record(mapper, record)
        for record, result in pending:
            resolved = [
                event_uid
                for event_uid in result.references
                if store.db.execute(
                    "SELECT 1 FROM event WHERE event_uid=?", (event_uid,)
                ).fetchone()
            ]
            if len(resolved) != len(set(result.references)):
                store.db.execute(
                    "UPDATE raw_record SET disposition='unparsed',note=? WHERE record_uid=?",
                    (canonical({"reason": "canonical reference unresolved"}), record.record_uid),
                )
                store.issue(
                    record.source_id,
                    "unresolved_canonical_reference",
                    record_uid=record.record_uid,
                    file_id=record.file_id,
                )
            else:
                for event_uid in resolved:
                    store.db.execute(
                        "INSERT OR IGNORE INTO record_event VALUES(?,?,?,'{}')",
                        (record.record_uid, event_uid, result.disposition or "folded"),
                    )
        for event_uid, native_key in parent_keys.items():
            if native_key in first_by_native and first_by_native[native_key] != event_uid:
                store.db.execute(
                    "UPDATE event SET parent_uid=? WHERE event_uid=?",
                    (first_by_native[native_key], event_uid),
                )
        for row in store.db.execute(
            "SELECT r.*,f.source_id FROM raw_record r JOIN file_record c USING(record_uid) "
            "JOIN source_file f ON f.file_id=r.file_id WHERE r.native_type='invalid'"
        ).fetchall():
            store.issue(
                row["source_id"],
                "invalid_json_record",
                record_uid=row["record_uid"],
                file_id=row["file_id"],
            )
        derive(store, scoped=True)
        for info in infos:
            store.db.execute(
                "UPDATE source_file SET watermark=json_set(watermark,'$.projected_revision',COALESCE(json_extract(watermark,'$.revision'),0),'$.mapper_version',?,'$.reducer_version',?,'$.redaction_version',?) WHERE file_id=?",
                (mapper_version, REDUCER_VERSION, REDACTION_VERSION, info["file_id"]),
            )

        if not store.db.execute(
            "SELECT 1 FROM source_file WHERE COALESCE(json_extract(watermark,'$.mapper_version'),'') <> ? LIMIT 1",
            (mapper_version,),
        ).fetchone():
            store.db.execute("UPDATE schema_manifest SET redaction_version=?", (REDACTION_VERSION,))
        dangling = store.db.execute("PRAGMA foreign_key_check").fetchall()
        if dangling:
            raise ValueError("Projection contains broken foreign keys")
        invalid = store.db.execute(
            "SELECT COUNT(*) FROM v_raw_record_ledger WHERE "
            "(disposition IN ('mapped','folded','replayed','duplicate') AND event_count=0) OR "
            "(disposition IN ('ignored','unparsed') AND event_count>0)"
        ).fetchone()[0]
        if invalid:
            raise ValueError("L1 disposition and provenance links disagree")
        count = store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        store.db.execute(
            "INSERT INTO projection_run(contract_version,mapper_version,reducer_version,completed_at,event_count,l1_revision_count) VALUES(1,?,?,?,?,?)",
            (
                mapper_version,
                REDUCER_VERSION,
                now_ms(),
                count,
                store.db.execute(
                    "SELECT COALESCE(SUM(json_extract(watermark,'$.projected_revision')),0) FROM source_file"
                ).fetchone()[0],
            ),
        )
    return {
        "events": count,
        "sessions": store.db.execute("SELECT COUNT(*) FROM session").fetchone()[0],
        "records": store.db.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0],
        "issues": store.db.execute("SELECT COUNT(*) FROM ingest_issue").fetchone()[0],
    }
