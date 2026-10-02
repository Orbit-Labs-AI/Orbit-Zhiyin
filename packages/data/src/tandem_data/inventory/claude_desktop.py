"""Claude app and account-synced resources; session observations are not live installs."""

import json
from datetime import datetime

from .adapters import _source_bytes, mcp, skills
from .components import COMPONENT_KINDS, plugin_components
from .helpers import array, local_path


def synced_plugins(reader, directory, configured):
    for bucket in reader.directories(directory, ("plugin", *COMPONENT_KINDS)):
        if bucket.name.startswith("."):
            continue
        for folder in reader.directories(bucket, ("plugin", *COMPONENT_KINDS)):
            if folder.name.startswith("."):
                continue
            path = folder / ".claude-plugin/plugin.json"
            manifest = reader.document(path, ("plugin", *COMPONENT_KINDS), required=True)
            if not manifest:
                continue
            name = manifest.get("name", folder.name)
            enabled = configured.get(str(name) + "@synced")
            reader.add(
                "plugin",
                name,
                path,
                evidence="cached",
                enabled=enabled,
                config={"source_kind": "account_sync"},
                raw=_source_bytes(manifest),
            )
            plugin_components(
                reader, folder, manifest, path, str(name), enabled=enabled, evidence="cached"
            )


def timestamp(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return round(date.timestamp() * 1000) if date.tzinfo else None
        except (ValueError, OverflowError):
            pass
    return None


def session_observations(reader, bucket):
    candidates = []
    for path in reader.children(bucket, ("mcp",)):
        if not path.name.startswith("local_") or path.suffix != ".json":
            continue
        # Large tool schemas are parsed only within the bounded input document;
        # no schema, title, prompt, cwd or account payload is persisted.
        raw = reader.read(path, ("mcp",))
        if raw is None:
            continue
        try:
            doc = json.loads(raw)
            if not isinstance(doc, dict):
                raise ValueError
            servers = doc.get("remoteMcpServersConfig")
            if servers is None:
                continue
            if not isinstance(servers, list):
                raise ValueError
            observed = timestamp(doc.get("lastActivityAt")) or timestamp(doc.get("createdAt"))
            if observed is None:
                reader.issue(path, ("mcp",), "session_observation_time_unknown")
                continue
            selected = []
            for server in servers:
                if not isinstance(server, dict) or not isinstance(server.get("name"), str):
                    raise ValueError
                native_id = server.get("uuid")
                tools = server.get("tools", [])
                selected.append(
                    (
                        server["name"],
                        native_id if isinstance(native_id, str) else server["name"],
                        len(tools) if isinstance(tools, list) else None,
                    )
                )
            candidates.append((observed, str(path), path, selected))
        except (ValueError, UnicodeError, RecursionError):
            reader.issue(path, ("mcp",), "invalid_session_resource_metadata")
    if not candidates:
        return
    observed, _, path, selected = max(candidates, key=lambda row: row[:2])
    # Absence from the newest snapshot must not resurrect a server from older sessions.
    for name, native_id, tool_count in selected:
        reader.add(
            "mcp",
            name,
            path,
            "remoteMcpServersConfig/" + native_id,
            evidence="cached",
            config={
                "source_kind": "latest_readable_account_session",
                "source_observed_at": observed,
                "transport": "remote",
                "tool_count": tool_count,
            },
        )
    reader.issue(path, ("mcp",), "session_snapshot_is_not_live_inventory")


def scheduled_tasks(reader, path):
    doc = reader.document(path, ("scheduled_task",))
    if not doc:
        return
    key = "scheduledTasks" if "scheduledTasks" in doc else "tasks"
    if key not in doc:
        reader.issue(path, ("scheduled_task",), "unsupported_task_layout")
        return
    for i, entry in enumerate(array(reader, doc, key, path, ("scheduled_task",))):
        if not isinstance(entry, dict):
            reader.issue(path, ("scheduled_task",), "invalid_task")
            continue
        reader.add(
            "scheduled_task",
            entry.get("name", entry.get("id", str(i))),
            path,
            f"{key}/{i}",
            enabled=entry.get("enabled"),
            raw=_source_bytes(entry),
        )


def cowork_plugins(reader, directory):
    path = directory / "installed_plugins.json"
    doc = reader.document(path, ("plugin", *COMPONENT_KINDS))
    for name, entries in reader.mapping(doc, "plugins", path, ("plugin",)).items():
        if not isinstance(entries, list):
            reader.issue(path, ("plugin",), "invalid_installed_plugins")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                reader.issue(path, ("plugin",), "invalid_plugin_installation")
                continue
            reader.add(
                "plugin",
                name,
                path,
                f"plugins/{name}/{i}",
                evidence="installed",
                raw=_source_bytes(entry),
            )
            folder = local_path(reader, entry.get("installPath"), directory, COMPONENT_KINDS)
            if folder:
                manifest_path = folder / ".claude-plugin/plugin.json"
                manifest = reader.document(manifest_path, COMPONENT_KINDS, required=True)
                if manifest:
                    plugin_components(
                        reader, folder, manifest, manifest_path, name, evidence="file"
                    )


def _buckets(reader, root, depth=2):
    """Only account/org levels, never session contents, browser caches or transcripts."""
    yield root
    if depth:
        for folder in reader.children(root, ("mcp", "plugin", "skill", "scheduled_task")):
            if folder.name.startswith(".") or folder.name in (
                "skills-plugin",
                "rpm",
                "cowork_plugins",
            ):
                continue
            try:
                if reader.safe(folder).is_dir():
                    yield from _buckets(reader, folder, depth - 1)
            except (OSError, ValueError, RuntimeError):
                reader.issue(
                    folder, ("mcp", "plugin", "skill", "scheduled_task"), "unsafe_account_directory"
                )


def scan_desktop(reader, root):
    path = root / "claude_desktop_config.json"
    mcp(reader, reader.document(path, ("mcp",)), path)
    path = root / "extensions-installations.json"
    doc = reader.document(path, ("plugin", "mcp"))
    for native_id, entry in reader.mapping(doc, "extensions", path, ("plugin",)).items():
        if not isinstance(entry, dict):
            reader.issue(path, ("plugin", "mcp"), "invalid_extension")
            continue
        manifest = entry.get("manifest", {})
        if not isinstance(manifest, dict):
            reader.issue(path, ("plugin", "mcp"), "invalid_extension_manifest")
            continue
        name = manifest.get("name", native_id)
        if not isinstance(name, str):
            reader.issue(path, ("plugin", "mcp"), "invalid_extension_name")
            name = native_id
        reader.add(
            "plugin",
            name,
            path,
            "extensions/" + native_id,
            evidence="installed",
            raw=_source_bytes(entry),
        )
        server = manifest.get("server")
        if isinstance(server, dict):
            reader.add(
                "mcp",
                name,
                path,
                "extensions/" + native_id + "/server",
                evidence="installed",
                config={"source_kind": "desktop_extension", "plugin": name},
                raw=_source_bytes(server),
            )
    roots = [root / name for name in ("claude-code-sessions", "local-agent-mode-sessions")]
    if root.name in ("claude-code-sessions", "local-agent-mode-sessions"):
        roots = [root]
    elif not any(path.exists() for path in roots):
        roots = [root]  # Also supports a directly selected account/session metadata root.
    for session_root in roots:
        for bucket in _buckets(reader, session_root):
            scheduled_tasks(reader, bucket / "scheduled-tasks.json")
            session_observations(reader, bucket)
            cowork_plugins(reader, bucket / "cowork_plugins")
            for folder in reader.directories(bucket / "rpm", ("plugin", *COMPONENT_KINDS)):
                path = folder / ".claude-plugin/plugin.json"
                manifest = reader.document(path, ("plugin", *COMPONENT_KINDS))
                if manifest:
                    name = manifest.get("name", folder.name)
                    reader.add("plugin", name, path, evidence="cached", raw=_source_bytes(manifest))
                    plugin_components(reader, folder, manifest, path, name, evidence="cached")
        for account in reader.directories(session_root / "skills-plugin", ("skill",)):
            for org in reader.directories(account, ("skill",)):
                skills(reader, org / "skills")
