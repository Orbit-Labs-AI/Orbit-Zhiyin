"""Atomic L2 replacement and provenance accounting; L0 never depends on L2."""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tandem_data import MAPPER_VERSION, REDUCER_VERSION, payload
from tandem_data.connectors import MAPPERS
from tandem_data.connectors.base import Mapping
from tandem_data.contract import canonical, now_ms, validate_event
from tandem_data.privacy import REDACTION_VERSION
from tandem_data.source_reader import SourceUnavailable
from tandem_data.store import insert

# Tandem's own headless AI runs (tandem_backend.ai.isolation) start in ``<home>/agent-cwd``
# and put this marker on the first prompt line; they never become canonical sessions.
TANDEM_AI_MARKER = "[tandem-analysis v1"
TANDEM_AI_CWD = "agent-cwd"
TANDEM_AI_MARKER_FILE = ".tandem-ai"
SESSION_TABLES = (
    "model_call",
    "usage_snapshot",
    "session_feature",
    "link",
    "tool_call",
    "turn",
    "session",
    "event",
)


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


def tandem_ai_session_uids(store) -> list[str]:
    """Sessions in the rebuild scope that Tandem's AI runtime started (cwd or marker)."""
    root = store.home / TANDEM_AI_CWD
    found = set()
    for row in store.db.execute(
        "SELECT session_uid, cwd FROM session WHERE source_id IN (SELECT source_id FROM rebuild_scope) "
        "AND cwd IS NOT NULL AND (cwd = ? OR cwd LIKE ? OR cwd LIKE ?)",
        (str(root), f"{root}/%", f"%/{TANDEM_AI_CWD}"),
    ):
        cwd = row["cwd"]
        if cwd == str(root) or cwd.startswith(f"{root}/") or _has_marker(cwd):
            found.add(row["session_uid"])
    found.update(
        row[0]
        for row in store.db.execute(
            "SELECT DISTINCT e.session_uid FROM event e JOIN session_identity i USING(session_uid) "
            "WHERE i.source_id IN (SELECT source_id FROM rebuild_scope) AND e.actor = 'human' "
            "AND substr(ltrim(e.text, ' ' || char(9) || char(10) || char(13)), 1, ?) = ?",
            (len(TANDEM_AI_MARKER), TANDEM_AI_MARKER),
        )
    )
    return sorted(found)


def _has_marker(cwd: str) -> bool:
    try:
        return (Path(cwd) / TANDEM_AI_MARKER_FILE).is_file()
    except OSError:
        return False


def exclude_tandem_ai_sessions(store) -> int:
    """Drop Tandem's own AI sessions from L2/L3; their L1 records stay, marked ignored."""
    uids = tandem_ai_session_uids(store)
    if not uids:
        return 0
    marks = ",".join("?" * len(uids))
    events = f"SELECT event_uid FROM event WHERE session_uid IN ({marks})"
    store.db.execute(
        f"DELETE FROM tool_call_event WHERE call_uid IN (SELECT call_uid FROM tool_call "
        f"WHERE session_uid IN ({marks}))",
        uids,
    )
    records = [
        row[0]
        for row in store.db.execute(
            f"SELECT DISTINCT record_uid FROM record_event WHERE event_uid IN ({events})", uids
        )
    ]
    for table in ("record_event", "event_context"):
        store.db.execute(f"DELETE FROM {table} WHERE event_uid IN ({events})", uids)
    note = canonical({"reason": "tandem_ai_session"})
    store.db.executemany(
        "UPDATE raw_record SET disposition='ignored',note=? WHERE record_uid=? "
        "AND NOT EXISTS(SELECT 1 FROM record_event WHERE record_event.record_uid=raw_record.record_uid)",
        ((note, uid) for uid in records),
    )
    for table in SESSION_TABLES:
        store.db.execute(f"DELETE FROM {table} WHERE session_uid IN ({marks})", uids)
    return len(uids)


@dataclass
class NativeMapped:
    """Writer-independent result of mapping one record (may come from a worker)."""

    result: Mapping | None = None
    error: str | None = None
    session_hint: str | None = None
    prepared: list = field(default_factory=list)
    encoded: list | None = None


def rebuild_retaining(store, **kwargs):
    """``rebuild`` that tolerates sources rewritten or truncated after capture.

    A live log that only grew is read up to its captured length and never fails. One
    whose captured prefix changed fails its checks: the attempt rolls back and is
    retried with that file's last published facts retained (``source_status='changed'``)
    until the next scan captures the new revision. A session closure cannot carry
    retained facts, so that retry covers the closure's source instead.
    """
    changed = set()
    while True:
        try:
            return rebuild(store, changed=frozenset(changed), **kwargs)
        except SourceUnavailable as error:
            file_id = getattr(error, "file_id", None)
            if file_id is None or file_id in changed:
                raise
            changed.add(file_id)
            store._unavailable_files = set()
            scope = kwargs.pop("scope", None)
            if scope is not None:
                kwargs["source_ids"] = scope.source_ids


def map_native(mapper, record, mapper_version):
    """Pure part of mapping one record: native mapping, envelope and contract checks."""
    if record.record_uid in getattr(mapper, "preparation_failures", set()):
        return None
    try:
        result = mapper.map(record)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return NativeMapped(error=type(error).__name__)
    # Legacy stream imports retain their compatibility payload. Native imports
    # address unrecognized records through L0/L1 instead of copying raw JSON.
    if result.events and json.loads(mapper.info["watermark"]).get("capture") != "source_reference":
        result.events[0].ext = {"native": record.data, **result.events[0].ext}
    else:
        for draft in result.events:
            if draft.kind == "unknown":
                draft.ext = {
                    "native_type": record.native_type,
                    "source_record_uid": record.record_uid,
                }
    # L1 keeps the source locator instead of another copy of every native payload.
    table = record.data.get("table") if mapper.info["format"] == "sqlite_rows" else None
    row = record.data.get("row", {})
    hint = None
    if mapper.session_uid and (
        not table
        or result.events
        or row.get("session_id")
        or table in ("session", "sessions", "threads")
    ):
        hint = mapper.session_uid
    # Contract errors are implementation bugs: abort and retain the previous published projection.
    prepared = [
        (draft, draft.envelope(record.record_uid, 0, mapper_version)) for draft in result.events
    ]
    for _, envelope in prepared:
        validate_event(envelope)
    return NativeMapped(
        Mapping(disposition=result.disposition, reason=result.reason, references=result.references),
        session_hint=hint,
        prepared=prepared,
    )


def rebuild(
    store,
    *,
    mapper_version=None,
    source_ids=None,
    progress=None,
    workers=1,
    scope=None,
    pool=None,
    changed=frozenset(),
):
    """Replace L2/L3 for whole sources, or for a session closure when ``scope`` is set.

    ``workers=1`` without a scope is the original serial path. Otherwise independent
    files are mapped by worker processes and applied in the same topological order.

    ``changed`` lists indexed files whose live source no longer starts with their
    captured revision; they keep their previously published facts (see
    ``rebuild_retaining``). Only whole-source rebuilds carry retained facts.
    """
    from tandem_data.reduce import derive

    progress = progress or (lambda _: None)
    progress({"stage": "reset_projection"})
    mapper_version = mapper_version or MAPPER_VERSION
    sequences = defaultdict(int)
    parent_keys = {}
    first_by_native = {}
    pending = []
    store._kimi_indexes = {}
    plan = None
    if scope is not None:
        source_ids = scope.source_ids
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
        if scope is not None:
            # A session closure replaces only its sessions and the files that feed them.
            sessions, source_files = scope.install(store.db)
            evidence = "SELECT event_uid FROM event WHERE session_uid IN (" + sessions + ")"
        from tandem_data.retained import RetainedProjection

        retained = RetainedProjection(store, changed) if scope is None else scope.retained()
        store._unavailable_files = set(retained.files)
        store.db.execute(
            "DELETE FROM tool_call_event WHERE call_uid IN (SELECT call_uid FROM tool_call WHERE session_uid IN ("
            + sessions
            + "))"
        )
        for table in ("record_event", "event_context"):
            store.db.execute(f"DELETE FROM {table} WHERE event_uid IN ({evidence})")
        for table in SESSION_TABLES:
            store.db.execute(f"DELETE FROM {table} WHERE session_uid IN ({sessions})")
        if scope is None:
            store.db.execute(
                "DELETE FROM ingest_issue WHERE stage IN ('l2','l3') AND source_id IN (SELECT source_id FROM rebuild_scope)"
            )
        else:
            scope.delete_issues(store.db)
        # Walk file-local rows once. Two passes (including a global UID IN-list)
        # rewrote every current record twice and caused random primary-key IO.
        current = "EXISTS(SELECT 1 FROM file_record f WHERE f.record_uid=raw_record.record_uid)"
        store.db.execute(
            f"UPDATE raw_record SET disposition=CASE WHEN {current} THEN 'unparsed' ELSE 'ignored' END,"
            f"note=CASE WHEN {current} THEN '{{}}' ELSE ? END WHERE file_id IN ({source_files})",
            (canonical({"reason": "superseded source row version"}),),
        )
        deferred = None
        if scope is None:
            from tandem_data.bulkload import DeferredIndexes

            # Bulk-load mode (e.g. first import): sorted index builds after the writes.
            deferred = DeferredIndexes.start(
                store.db,
                incoming=store.db.execute(
                    f"SELECT COUNT(*) FROM raw_record WHERE file_id IN ({source_files})"
                ).fetchone()[0],
            )
        infos = list(
            store.db.execute(
                "SELECT f.*,s.agent FROM source_file f JOIN source s USING(source_id) "
                "WHERE s.source_id IN (SELECT source_id FROM rebuild_scope)"
                + (f" AND f.file_id IN ({source_files})" if scope is not None else "")
                + " ORDER BY s.agent,f.source_id,f.relative_path"
            )
        )
        mappers = {}
        retained.restore(store, sequences, first_by_native)
        if workers != 1 or scope is not None:
            from tandem_data.parallel import MapPlan

            plan = MapPlan(store, infos, retained.files, mapper_version, pool, workers, scope)
        progress({"stage": "prepare", "completed": 0, "total": len(infos)})
        for index, info in enumerate(infos):
            progress({"stage": "prepare", "completed": index, "total": len(infos)})
            if info["file_id"] in retained.files:
                continue
            if plan is not None and plan.prepared(info, mappers):
                continue  # Prepared by a worker; its side effects were applied in order.
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
            try:
                mapper.prepare(store.iter_file(info["file_id"]))
            except SourceUnavailable:
                raise  # Roll back; Store.rebuild retries with this file retained.
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                store.issue(
                    info["source_id"],
                    "file_preparation_error",
                    file_id=info["file_id"],
                    detail={"exception": type(error).__name__},
                )
                continue
            mappers[info["file_id"]] = mapper

        from tandem_data.connectors.codex import select_history

        select_history(store, mappers)

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
                        "id", mappers[info["file_id"]].header.get("session_id", "")
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
            ) or getattr(mapper, "parent", None)  # Codex thread_spawn.parent_thread_id
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
            if plan is not None and plan.owns(mapper):
                plan.apply(
                    mapper, record, apply_mapped, sequences, first_by_native, parent_keys, pending
                )
            else:
                apply_mapped(mapper, record, map_native(mapper, record, mapper_version))

        def apply_mapped(mapper, record, mapped):
            if mapped is None:
                return
            if mapped.error:
                store.issue(
                    record.source_id,
                    "native_mapping_error",
                    record_uid=record.record_uid,
                    file_id=record.file_id,
                    detail={"exception": mapped.error},
                )
                store.db.execute(
                    "UPDATE raw_record SET disposition='unparsed',note=? WHERE record_uid=?",
                    (canonical({"reason": "native_mapping_error"}), record.record_uid),
                )
                return
            result = mapped.result
            if mapped.session_hint:
                store.db.execute(
                    "UPDATE raw_record SET session_uid=? WHERE record_uid=?",
                    (mapped.session_hint, record.record_uid),
                )
            prepared = mapped.prepared
            relations = []
            for draft, prepared_envelope in prepared:
                existing = store.db.execute(
                    "SELECT * FROM event WHERE event_uid=?", (draft.event_uid,)
                ).fetchone()
                if existing and plan is not None:
                    plan.check_existing(existing)  # A closure must own every event it touches.
                if existing:
                    existing = payload.restore_row(store.db, existing)
                    relation = (
                        "replayed" if existing["session_uid"] != draft.session_uid else "duplicate"
                    )
                    if relation != "replayed":
                        attrs, ext = json.loads(existing["attrs"]), json.loads(existing["ext"])
                        incoming = {**prepared_envelope, "seq": existing["seq"]}
                        if attrs.get("source_status") in ("missing", "changed"):
                            # A live representation wins over a preserved one with
                            # the same native identity, including shorter corrected text.
                            replacement = dict(incoming)
                            for field in ("attrs", "ext", "native_key"):
                                replacement[field] = canonical(replacement[field])
                            replacement["text"] = payload.pack_text(
                                store.db, replacement["kind"], replacement["text"]
                            )
                            fields = [field for field in replacement if field != "event_uid"]
                            store.db.execute(
                                "UPDATE event SET "
                                + ",".join(f"{field}=?" for field in fields)
                                + " WHERE event_uid=?",
                                [replacement[field] for field in fields] + [draft.event_uid],
                            )
                            existing = payload.restore_row(
                                store.db,
                                store.db.execute(
                                    "SELECT * FROM event WHERE event_uid=?", (draft.event_uid,)
                                ).fetchone(),
                            )
                            attrs, ext = json.loads(existing["attrs"]), json.loads(existing["ext"])
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
                        text = existing["text"]
                        if incoming["text"] and (not text or incoming["text"].startswith(text)):
                            text = incoming["text"]
                            for field in (
                                "original_chars",
                                "message_digest",
                                "writing_measurements",
                            ):
                                if field in incoming["attrs"]:
                                    merged[field] = incoming["attrs"][field]
                        if (
                            merged != attrs
                            or merged_ext != ext
                            or stamp != existing["ts"]
                            or text != existing["text"]
                        ):
                            relation = "folded"
                            store.db.execute(
                                "UPDATE event SET attrs=?,ext=?,ts=?,text=? WHERE event_uid=?",
                                (
                                    canonical(merged),
                                    canonical(merged_ext),
                                    stamp,
                                    payload.pack_text(store.db, existing["kind"], text),
                                    draft.event_uid,
                                ),
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

        mapped_records = 0
        progress({"stage": "map", "completed": 0, "total": len(infos), "records": 0})
        for index, info in enumerate(infos):
            mapper = mappers.get(info["file_id"])
            if mapper is None:
                continue
            if info["agent"] == "codex" and mapper.cut is not None and mapper.parent:
                parent_file = by_native.get((info["source_id"], str(mapper.parent)))
                mapper.parent_candidates = defaultdict(list)
                # A parent that is itself a fork replays its prefix; those links are
                # written after mapping, so hand the child the pending references.
                mapper.replayed_refs = {
                    item.record_uid: result.references
                    for item, result in pending
                    if item.file_id == parent_file
                }
                if parent_file:
                    for parent_record in store.iter_file(parent_file):
                        for signature in mapper.parent_signatures(parent_record):
                            mapper.parent_candidates[signature].append(
                                (parent_record.ordinal, parent_record.record_uid)
                            )
            owned = plan is not None and plan.owns(mapper)
            for record in plan.records(mapper) if owned else store.iter_file(info["file_id"]):
                if record.native_type == "table:session_model_usage":
                    continue  # All versions, in observation order, are mapped below.
                map_record(mapper, record)
                mapped_records += 1
                if mapped_records % 500 == 0:
                    progress(
                        {
                            "stage": "map",
                            "completed": index,
                            "total": len(infos),
                            "records": mapped_records,
                        }
                    )
            if plan is not None:
                plan.flush()  # Later files and link resolution read these events.
            progress(
                {
                    "stage": "map",
                    "completed": index + 1,
                    "total": len(infos),
                    "records": mapped_records,
                }
            )
            # Usage rows exist only for SQLite sources; worker-owned files are line formats.
            for record in (
                () if owned else store.iter_versions(info["file_id"], "table:session_model_usage")
            ):
                map_record(mapper, record)
        # Lower DSH generations remain browsable in the same trajectory, although
        # only the highest generation contributes canonical facts.
        from pathlib import PurePosixPath

        dsh_sessions = {
            (m.info["source_id"], str(PurePosixPath(m.info["relative_path"]).parent)): m.session_uid
            for m in mappers.values()
            if m.info["agent"] == "dsh" and m.session_uid
        }
        for info in infos:
            if info["role"] == "legacy_transcript":
                session_uid = dsh_sessions.get(
                    (info["source_id"], str(PurePosixPath(info["relative_path"]).parent))
                )
                if session_uid:
                    store.db.execute(
                        "UPDATE raw_record SET session_uid=? WHERE file_id=?",
                        (session_uid, info["file_id"]),
                    )
        if deferred is not None:
            from tandem_data.bulkload import AFTER_MAP

            deferred.restore(AFTER_MAP)
        retained.finish(store, infos)
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
        parent_updates = []
        for event_uid, native_key in parent_keys.items():
            if native_key in first_by_native and first_by_native[native_key] != event_uid:
                parent_updates.append((first_by_native[native_key], event_uid))
            elif plan is not None and native_key not in first_by_native:
                plan.unresolved_parent(native_key)
        # One statement for every parent link (same rows and order as row-by-row).
        store.db.executemany("UPDATE event SET parent_uid=? WHERE event_uid=?", parent_updates)
        # Only rebuilt files can gain or lose an invalid-record issue; other sources keep
        # theirs (their L2 issues are not deleted), so scanning every raw_record of the
        # library on each source rebuild only rewrote identical rows.
        for row in store.db.execute(
            "SELECT r.*,f.source_id FROM raw_record r JOIN file_record c USING(record_uid) "
            "JOIN source_file f ON f.file_id=r.file_id WHERE r.native_type='invalid' "
            f"AND r.file_id IN ({source_files})"
        ).fetchall():
            store.issue(
                row["source_id"],
                "invalid_json_record",
                record_uid=row["record_uid"],
                file_id=row["file_id"],
            )
        if plan is not None:
            plan.finish_mapping()  # Bulk-indexes deferred search rows before derivation.
        progress({"stage": "derive"})
        if scope is not None:
            scope.before_derive(store.db)  # Escalates if the closure was incomplete.
        derive(
            store,
            scoped=True,
            progress=progress,
            sessions=None if scope is None else scope.sessions_sql,
        )
        if deferred is not None:
            deferred.restore()  # Before validation and publication.
        exclude_tandem_ai_sessions(store)
        # Changed files are not projected: the next import rebuilds them from a fresh capture.
        store.db.executemany(
            "UPDATE source_file SET watermark=json_set(watermark,'$.projected_revision',COALESCE(json_extract(watermark,'$.revision'),0),'$.mapper_version',?,'$.reducer_version',?,'$.redaction_version',?) WHERE file_id=?",
            [
                (mapper_version, REDUCER_VERSION, REDACTION_VERSION, info["file_id"])
                for info in infos
                if info["file_id"] not in changed
            ],
        )

        if not store.db.execute(
            "SELECT 1 FROM source_file WHERE COALESCE(json_extract(watermark,'$.mapper_version'),'') <> ? LIMIT 1",
            (mapper_version,),
        ).fetchone():
            store.db.execute("UPDATE schema_manifest SET redaction_version=?", (REDACTION_VERSION,))
        progress({"stage": "validate_projection"})
        if plan is not None:
            plan.validate(source_files, sessions)  # Same checks, limited to rebuilt rows.
        else:
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
    progress({"stage": "published", "completed": len(infos), "total": len(infos)})
    return {
        "events": count,
        "sessions": store.db.execute("SELECT COUNT(*) FROM session").fetchone()[0],
        "records": store.db.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0],
        "issues": store.db.execute("SELECT COUNT(*) FROM ingest_issue").fetchone()[0],
        "skipped_files": len(changed),
    }
