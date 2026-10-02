"""Local installation observations, separate from session ingestion and usage evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tandem_data.contract import canonical, now_ms, uid
from tandem_data.store import Store, insert, readonly_connection

from .adapters import SUPPORTED, mcp, scan_layout
from .reader import KINDS, ScanReader

SCANNER_VERSION = "1.1.0"


@dataclass(frozen=True)
class InventoryRequest:
    agent: str
    root: Path
    project_id: str | None = None
    allowed_roots: tuple[Path, ...] = ()
    claude_config: Path | None = None


def scan_inventory(store: Store, request: InventoryRequest) -> dict:
    """Scan only explicitly enabled inputs and atomically publish an immutable snapshot.

    Errors publish partial observations, never a complete empty installation list.
    A later snapshot replaces the visible set, including deletions, without losing history.
    """
    from tandem_data.service import ImportService

    if request.agent not in SUPPORTED:
        raise ValueError(f"Unsupported inventory agent: {request.agent}")
    if request.claude_config and request.agent != "claude_code":
        raise ValueError("claude_config requires claude_code")
    root = request.root.expanduser().resolve()
    allowed = tuple(path.expanduser().resolve(strict=True) for path in request.allowed_roots)
    if any(store.home.is_relative_to(path) for path in (root, *allowed)):
        raise ValueError("Data home must be outside all inventory source roots")
    source_key = uid("inventory_source", request.agent, str(root), request.project_id)
    reader = ScanReader(root, source_key, allowed)
    with ImportService(store).writer():
        if (
            request.project_id
            and not store.db.execute(
                "SELECT 1 FROM project WHERE project_id=?", (request.project_id,)
            ).fetchone()
        ):
            raise ValueError("Unknown project_id")
        try:
            if not root.is_dir():
                reader.issue(root, SUPPORTED[request.agent], "root_unavailable")
            else:
                scan_layout(reader, request.agent)
        except OSError as error:
            reader.issue(root, SUPPORTED[request.agent], type(error).__name__)
        if request.claude_config:
            path = request.claude_config.expanduser().absolute()
            # Authorize this exact file, not its parent directory or account siblings.
            reader.allowed += (path,)
            doc = reader.document(path, ("mcp",))
            mcp(reader, doc, path)
            for project_path, value in reader.mapping(doc, "projects", path, ("mcp",)).items():
                if isinstance(value, dict):
                    mcp(
                        reader,
                        value,
                        path,
                        prefix="projects/" + project_path + "/",
                        project_path=project_path,
                    )
                else:
                    reader.issue(path, ("mcp",), "invalid_project_mcp")
        coverage = {}
        for kind in KINDS:
            count = sum(item["type"] == kind for item in reader.items.values())
            supported = kind in SUPPORTED[request.agent]
            coverage[kind] = {
                "status": "partial"
                if kind in reader.failed
                else "available"
                if supported
                else "unavailable",
                "rows": count if supported else None,
                "reason": None if supported else "unsupported_by_layout",
            }
        with store.transaction():
            cursor = store.db.execute(
                "INSERT INTO inventory_scan(source_key,agent,root_path,scope,project_id,observed_at,scanner_version,coverage,diagnostics) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    source_key,
                    request.agent,
                    str(root),
                    "project" if request.agent == "project" or request.project_id else "global",
                    request.project_id,
                    now_ms(),
                    SCANNER_VERSION,
                    canonical(coverage),
                    canonical(reader.diagnostics),
                ),
            )
            scan_id = cursor.lastrowid
            for item in reader.items.values():
                insert(
                    store.db,
                    "inventory_item",
                    {**item, "scan_id": scan_id, "config": canonical(item["config"])},
                )
    return {
        "scan_id": scan_id,
        "items": len(reader.items),
        "coverage": coverage,
        "diagnostics": reader.diagnostics,
        "status": "partial" if reader.failed else "available",
    }


def read_inventory_connection(connection, *, until_ts=None, project_ids=None) -> dict:
    """Latest observation per selected source, strictly before a historical cutoff.

    Coverage describes approved layouts only. A snapshot is not proof of effective
    runtime configuration, historical installation, invocation or recommendation value.
    """
    empty = {
        "items": None,
        "scans": [],
        "coverage": {"status": "unavailable", "rows": None, "reason": "no_inventory_scan"},
    }
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='inventory_scan'").fetchone():
        return empty
    params = {
        "until": until_ts,
        "projects": canonical(project_ids) if project_ids is not None else None,
    }
    scans = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM inventory_scan WHERE scan_id IN (SELECT MAX(scan_id) FROM inventory_scan "
            "WHERE (:until IS NULL OR observed_at < :until) AND "
            "(:projects IS NULL OR scope='global' OR project_id IN (SELECT value FROM json_each(:projects))) "
            "GROUP BY source_key) ORDER BY scan_id",
            params,
        )
    ]
    if not scans:
        return empty
    project_paths = {}
    for project in connection.execute("SELECT project_id,key_type,key,paths FROM project"):
        for path in json.loads(project["paths"]):
            project_paths[path] = project["project_id"]
        if project["key_type"] == "path":
            project_paths[project["key"]] = project["project_id"]
    items = []
    for scan in scans:
        for name in ("coverage", "diagnostics"):
            scan[name] = json.loads(scan[name])
        for row in connection.execute(
            "SELECT * FROM inventory_item WHERE scan_id=? ORDER BY type,name,inv_id",
            (scan["scan_id"],),
        ):
            item = dict(row)
            item["config"] = json.loads(item["config"])
            item.update({key: scan[key] for key in ("agent", "scope", "project_id", "observed_at")})
            project_path = item["config"].get("project_path")
            if project_path is not None or item["config"].get("scope") in ("project", "local"):
                item["scope"] = "project"
                item["project_id"] = project_paths.get(project_path)
            if (
                project_ids is not None
                and item["scope"] == "project"
                and item["project_id"] not in project_ids
            ):
                continue
            items.append(item)
    status = (
        "partial"
        if any(s["status"] != "available" for scan in scans for s in scan["coverage"].values())
        else "available"
    )
    return {
        "items": items,
        "scans": scans,
        "coverage": {
            "status": status,
            "rows": len(items),
            "boundary": "explicit_roots_only",
            "semantics": "observed_configuration_not_usage",
            "scan_ids": [scan["scan_id"] for scan in scans],
        },
    }


def read_inventory(home: str | Path, *, until_ts=None, project_ids=None) -> dict:
    with readonly_connection(Path(home) / "tandem.db") as connection:
        connection.execute("BEGIN")
        return read_inventory_connection(connection, until_ts=until_ts, project_ids=project_ids)
