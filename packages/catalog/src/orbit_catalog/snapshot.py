"""Offline library seed: a small gzip snapshot of a synced catalog, imported on first start.

A fresh install has no network data, so the library would be empty for minutes. The
snapshot is built on a networked machine before release (``python -m orbit_catalog
snapshot``), checked in as ``data/library-seed.v1.json.gz`` (<= 3 MB) and imported once.

Each original source ``x`` becomes a read-only ``seed-x`` source (kind ``snapshot``,
priority 10). Items keep their real ``item_id``, so a later network sync of ``x`` wins
materialization; :func:`retire_seeds` then removes the ``seed-x`` rows so nothing stale or
duplicated stays listed.
"""

from __future__ import annotations

import gzip
import json
import time
import zlib
from importlib.resources import files

from .contracts import Page, Record, Resource, SourceSpec, canonical_json, digest
from .store import CatalogStore, _ms, get_blob

FORMAT = "orbit-library-seed/1"
SEED_PREFIX = "seed-"
SEED_FILE = "data/library-seed.v1.json.gz"
DEFAULT_PER_KIND = {"skill": 400, "plugin": 250, "subagent": 150, "command": 60, "rule": 60, "hook": 40,
                    "workflow": 20, "mcp_server": 300}
MIN_SOURCES = 3
BODY_LIMIT = 20_000
# Sources available offline anyway (package data / local); never copied into the seed.
OFFLINE_KINDS = {"bundle", "kb", "local", "snapshot"}
SEED_REFRESH = 10 * 365 * 86400


def seed_source_id(source_id: str) -> str:
    return (SEED_PREFIX + source_id)[:80]


def _truncate(text: str, limit: int) -> str:
    data = text.encode()
    return text if len(data) <= limit else data[:limit].decode(errors="ignore")


def _candidates(store: CatalogStore, kinds, include_staged: bool) -> dict[str, list[dict]]:
    """kind -> ranked candidates {item_id, source_id, sort, res, body} (blobs loaded lazily)."""
    found: dict[str, list[dict]] = {kind: [] for kind in kinds}
    with store.connect(True) as conn:
        specs = {r["source_id"]: json.loads(r["spec"]) for r in conn.execute("SELECT source_id,spec FROM catalog_source")}
        rows = conn.execute(
            "SELECT i.item_id,i.type,i.official,i.stars,i.installs,i.risk_level,i.name_key,i.summary,i.license,i.body_len,"
            "i.updated_at,json_extract(i.metadata,'$.metadata.installable') AS installable,"
            "json_extract(i.metadata,'$.metadata.repository_url') AS repo,w.source_id,w.res_sha,w.body_sha FROM catalog_item i "
            "JOIN (SELECT s.item_id,s.source_id,s.res_sha,s.body_sha,row_number() OVER (PARTITION BY s.item_id "
            "ORDER BY c.priority DESC,s.has_path DESC,s.source_id,s.native_id) AS n FROM item_source s "
            "JOIN catalog_source c USING(source_id) WHERE s.status='active' AND c.enabled=1) w "
            "ON w.item_id=i.item_id AND w.n=1 WHERE i.listable=1 AND i.canonical_of IS NULL AND i.status='active' "
            "AND i.type IN (SELECT value FROM json_each(?))", (json.dumps(sorted(kinds)),)).fetchall()
        seen = set()
        for row in rows:
            spec = specs.get(row["source_id"]) or {}
            kind = spec.get("kind")
            origin = (spec.get("config") or {}).get("origin") if kind == "snapshot" else row["source_id"]
            if not origin or (kind in OFFLINE_KINDS and kind != "snapshot"):
                continue
            seen.add(row["item_id"])
            # Popularity first; without it (most MCP servers) prefer documented, licensed, recent items.
            richness = (bool(row["summary"]) + bool(row["license"]) + bool(row["body_len"]) + bool(row["installable"])
                        + bool(row["repo"]))
            found[row["type"]].append({"item_id": row["item_id"], "source_id": origin,
                                       "sort": (-row["official"], -(row["stars"] or 0), -(row["installs"] or 0),
                                                -richness, row["risk_level"], -(row["updated_at"] or 0),
                                                row["item_id"]),
                                       "key": (row["name_key"], row["summary"] or ""),
                                       "res_sha": row["res_sha"], "body_sha": row["body_sha"]})
        if include_staged:
            # An interrupted full scan (e.g. the MCP registry) still holds validated resources in
            # staging; they are not published locally but are good seed material.
            staged = conn.execute(
                "SELECT r.source_id,s.resource FROM sync_stage s JOIN sync_run r USING(run_id) "
                "WHERE r.status IN ('running','paused','failed','ready')").fetchall()
            for row in staged:
                if specs.get(row["source_id"], {}).get("kind") in OFFLINE_KINDS:
                    continue
                doc = json.loads(zlib.decompress(row["resource"]))
                if doc.get("type") not in found or doc.get("status", "active") != "active" or doc["item_id"] in seen:
                    continue
                seen.add(doc["item_id"])
                manifest = doc.get("manifest") or {}
                richness = bool(manifest.get("packages") or manifest.get("remotes")) + bool((manifest.get("repository") or {}).get("url"))
                updated = _ms((doc.get("metadata") or {}).get("source_updated_at")) or 0
                found[doc["type"]].append({"item_id": doc["item_id"], "source_id": row["source_id"],
                                           "sort": (-int(bool(doc.get("official"))), 0, 0, -richness - 1, 0,
                                                    -updated, doc["item_id"]),
                                           "key": (str(doc.get("name") or "").lower(), doc.get("summary") or ""),
                                           "doc": doc})
    for kind, rows in found.items():
        rows.sort(key=lambda r: r["sort"])
        # The same component mirrored by two repositories (same name and summary) is listed once.
        keys: set = set()
        found[kind] = [r for r in rows if not (r["key"] in keys or keys.add(r["key"]))]
    return found


def _pick(ranked: list[dict], limit: int) -> list[dict]:
    """Top `limit`, but guarantee up to MIN_SOURCES distinct sources when the pool has them."""
    chosen = ranked[:limit]
    sources = {r["source_id"] for r in chosen}
    if len(sources) >= MIN_SOURCES or limit < MIN_SOURCES:
        return chosen
    extra = []
    for row in ranked[limit:]:
        if row["source_id"] not in sources:
            sources.add(row["source_id"])
            extra.append(row)
            if len(sources) >= MIN_SOURCES:
                break
    # Make room by dropping the lowest-ranked items of sources that keep another item.
    counts: dict[str, int] = {}
    for row in chosen:
        counts[row["source_id"]] = counts.get(row["source_id"], 0) + 1
    kept = list(chosen)
    for row in reversed(chosen):
        if len(kept) + len(extra) <= limit:
            break
        if counts[row["source_id"]] > 1:
            counts[row["source_id"]] -= 1
            kept.remove(row)
    return (kept + extra)[:limit]


def _resource(conn, row: dict, body_limit: int, cache: dict) -> dict:
    key = row["item_id"]
    if key not in cache:
        if "doc" in row:
            doc = dict(row["doc"])
            body = doc.pop("body", "") or ""
        else:
            doc = json.loads(get_blob(conn, row["res_sha"]))
            body = get_blob(conn, row["body_sha"]).decode() if row["body_sha"] else ""
        cache[key] = (doc, body)
    doc, body = cache[key]
    doc = {**doc, "body": _truncate(body, body_limit) if doc.get("body_policy") == "licensed" and body_limit else ""}
    # Validate and drop defaults: the seed stores the smallest faithful Resource.
    return Resource.model_validate(doc).model_dump(exclude_defaults=True)


def build_snapshot(store: CatalogStore, *, per_kind: dict[str, int] | None = None, max_bytes: int = 3_000_000,
                   built_at: int | None = None, include_staged: bool = True) -> bytes:
    """Deterministic gzip JSON (``orbit-library-seed/1``) no larger than ``max_bytes``.

    Shrinks in order: README excerpt (20 KB -> 8 KB -> 2 KB -> none), then per-kind counts.
    """
    per_kind = dict(per_kind or DEFAULT_PER_KIND)
    ranked = _candidates(store, set(per_kind), include_staged)
    cache: dict = {}
    built_at = int(time.time() * 1000) if built_at is None else built_at
    scale, body_caps = 1.0, [BODY_LIMIT, 8_000, 2_000, 0]
    with store.connect(True) as conn:
        while True:
            quotas = {kind: max(1, int(n * scale)) for kind, n in per_kind.items()}
            picked = {kind: _pick(ranked[kind], quotas[kind]) for kind in per_kind}
            for cap in body_caps:
                # Fast level-1 trial: never smaller than the level-9 result, so a fit is a fit.
                if len(_encode(conn, picked, cap, cache, built_at, level=1)) <= max_bytes:
                    return _encode(conn, picked, cap, cache, built_at)
            if all(len(rows) <= 1 for rows in picked.values()):
                raise ValueError("snapshot_exceeds_max_bytes")
            scale *= 0.8
            body_caps = [0]


def _encode(conn, picked: dict[str, list[dict]], body_cap: int, cache: dict, built_at: int, level: int = 9) -> bytes:
    sources: dict[str, list[dict]] = {}
    stats = {}
    for kind, rows in sorted(picked.items()):
        stats[kind] = len(rows)
        for row in rows:
            sources.setdefault(row["source_id"], []).append(_resource(conn, row, body_cap, cache))
    payload = {"format": FORMAT, "built_at": built_at, "stats": stats,
               "sources": {sid: {"revision": digest(items), "items": sorted(items, key=lambda r: r["item_id"])}
                           for sid, items in sorted(sources.items())}}
    return gzip.compress(canonical_json(payload).encode(), compresslevel=level, mtime=0)


def load_seed(data: bytes | dict) -> dict:
    doc = json.loads(gzip.decompress(data)) if isinstance(data, (bytes, bytearray)) else data
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("sources"), dict):
        raise ValueError("invalid_library_seed")
    return doc


def bundled_seed() -> bytes | None:
    resource = files("orbit_catalog").joinpath(SEED_FILE)
    return resource.read_bytes() if resource.is_file() else None


def import_snapshot(store: CatalogStore, data: bytes | dict, *, skip_synced: bool = True) -> dict:
    """Publish each snapshot source as ``seed-<source_id>``; idempotent and offline.

    Sources whose real counterpart already completed a sync are skipped (the network copy is
    newer and the seed would only be retired again).
    """
    doc = load_seed(data)
    existing = {s["source_id"]: s for s in store.sources()}
    plan, skipped = [], []
    for source_id, source in sorted(doc["sources"].items()):
        if skip_synced and (existing.get(source_id) or {}).get("completed_at"):
            skipped.append(source_id)
            continue
        records = [Record(native_id=r["item_id"], resource=Resource.model_validate(r)) for r in source.get("items", [])]
        spec = SourceSpec(source_id=seed_source_id(source_id), kind="snapshot", url="bundled:" + SEED_FILE, priority=10,
                          refresh_seconds=SEED_REFRESH, config={"origin": source_id})
        plan.append((spec, records, source.get("revision") or digest(source.get("items", []))))
    if plan:
        store.register([spec for spec, _, _ in plan])
    imported, by_kind = {}, {}
    with store.writer():
        for spec, records, revision in plan:
            run = store.begin_run(spec.source_id)
            if run["status"] != "ready":
                store.stage(run["run_id"], Page(records=records, complete=True, mode="full", revision=revision))
            result = store.publish(run["run_id"])
            imported[spec.source_id] = {"seen": result["seen"], "changed": result["changed"]}
            for record in records:
                by_kind[record.resource.type] = by_kind.get(record.resource.type, 0) + 1
    return {"format": doc["format"], "built_at": doc.get("built_at"), "sources": imported, "skipped": skipped,
            "items": sum(by_kind.values()), "by_kind": by_kind}


def retire_seeds(store: CatalogStore, source_ids) -> int:
    """After ``x`` published from the network, drop ``seed-x`` rows; returns rows retired."""
    from .store import _now

    seeds = {seed_source_id(s) for s in source_ids if not s.startswith(SEED_PREFIX)}
    if not seeds:
        return 0
    known = {s["source_id"] for s in store.sources() if s["spec"].get("kind") == "snapshot"}
    seeds &= known
    if not seeds:
        return 0
    with store.writer(), store.connect() as conn:
        ids = set()
        for source_id in sorted(seeds):
            ids.update(r[0] for r in conn.execute(
                "UPDATE item_source SET status='removed' WHERE source_id=? AND status='active' RETURNING item_id",
                (source_id,)).fetchall())
        if ids:
            store._materialize_many(conn, ids, _now())
            store._bump(conn)
    return len(ids)
