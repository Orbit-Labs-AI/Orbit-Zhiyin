"""Local installation observations, separate from session ingestion and usage evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orbit_data.contract import canonical, now_ms, uid
from orbit_data.coverage import dataset_coverage
from orbit_data.store import Store, insert, readonly_connection

from .adapters import SUPPORTED, mcp, scan_layout
from .reader import KINDS, ScanReader

SCANNER_VERSION = "1.4.3"
# Connectors that split ``<server>_<tool>`` tool names only with inventoried MCP server
# names (connectors.base.split_mcp_name); their mapping depends on the inventory.
MCP_NAME_MAPPED = frozenset({"opencode", "hermes"})


def _mcp_names(db, agent: str) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT DISTINCT i.name FROM inventory_item i JOIN inventory_scan s USING(scan_id) "
            "WHERE i.type='mcp' AND s.agent=?",
            (agent,),
        )
        if isinstance(row[0], str) and row[0]
    }


@dataclass(frozen=True)
class InventoryRequest:
    agent: str
    root: Path
    project_id: str | None = None
    allowed_roots: tuple[Path, ...] = ()
    claude_config: Path | None = None
    skill_roots: tuple[Path, ...] = ()


def scan_inventory(store: Store, request: InventoryRequest) -> dict:
    """Scan only explicitly enabled inputs and atomically publish an immutable snapshot.

    Errors publish partial observations, never a complete empty installation list.
    A later snapshot replaces the visible set, including deletions, without losing history.
    """
    from orbit_data.service import ImportService

    if request.agent not in SUPPORTED:
        raise ValueError(f"Unsupported inventory agent: {request.agent}")
    if request.claude_config and request.agent != "claude_code":
        raise ValueError("claude_config requires claude_code")
    root = request.root.expanduser().resolve()
    allowed = tuple(
        path.expanduser().resolve(strict=True)
        for path in (*request.allowed_roots, *request.skill_roots)
    )
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
        if request.skill_roots:
            from .adapters import skills

            for skill_root in request.skill_roots:
                skills(reader, skill_root.expanduser().resolve())
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
        if request.agent == "claude_code" and not request.claude_config:
            # User and local-scope MCP servers live in ~/.claude.json, which is only read
            # when passed explicitly; the rows here cover settings files and plugins only.
            coverage["mcp"]["reason"] = "user_scope_not_scanned"
        remap_files = 0
        with store.transaction():
            before = (
                _mcp_names(store.db, request.agent) if request.agent in MCP_NAME_MAPPED else set()
            )
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
            if request.agent in MCP_NAME_MAPPED and _mcp_names(store.db, request.agent) - before:
                # Sessions imported before this scan mapped these tool names without the
                # server list; mark their files stale so the next projection resolves
                # mcp_server/mcp_tool instead of leaving them unknown for good.
                remap_files = store.db.execute(
                    "UPDATE source_file SET watermark=json_set(watermark,'$.mapper_version','') "
                    "WHERE source_id IN (SELECT source_id FROM source WHERE agent=?) "
                    "AND json_extract(watermark,'$.mapper_version') IS NOT NULL",
                    (request.agent,),
                ).rowcount
        if getattr(store, "_mcp_server_names", None):
            store._mcp_server_names.pop(request.agent, None)
    return {
        "scan_id": scan_id,
        "items": len(reader.items),
        "coverage": coverage,
        "diagnostics": reader.diagnostics,
        "status": "partial" if reader.failed else "available",
        "remap_files": remap_files,
    }


def read_inventory_connection(connection, *, until_ts=None, project_ids=None) -> dict:
    """Latest observation per selected source, strictly before a historical cutoff.

    Coverage describes approved layouts only. A snapshot is not proof of effective
    runtime configuration, historical installation, invocation or recommendation value.
    """
    empty = {
        "items": None,
        "scans": [],
        "coverage": {
            **dataset_coverage(None, reasons=["no_inventory_scan"]),
            "reason": "no_inventory_scan",
        },
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
    incomplete_layouts = sum(
        s["status"] != "available" for scan in scans for s in scan["coverage"].values()
    )
    return {
        "items": items,
        "scans": scans,
        "coverage": {
            **dataset_coverage(
                len(items), reason_counts={"inventory_layout_incomplete": incomplete_layouts}
            ),
            "boundary": "explicit_roots_only",
            "semantics": "observed_configuration_not_usage",
            "scan_ids": [scan["scan_id"] for scan in scans],
        },
    }


def read_inventory(home: str | Path, *, until_ts=None, project_ids=None) -> dict:
    with readonly_connection(Path(home) / "orbit.db") as connection:
        connection.execute("BEGIN")
        return read_inventory_connection(connection, until_ts=until_ts, project_ids=project_ids)
