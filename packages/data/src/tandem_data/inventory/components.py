"""Static plugin components with plugin-local containment and source provenance."""

from pathlib import Path

from .adapters import hooks, mcp, skills
from .helpers import local_path

COMPONENT_KINDS = ("skill", "mcp", "hook")


def component_path(reader, folder, value, kind):
    path = local_path(reader, value, folder, (kind,))
    if path is None:
        return None
    try:
        if not path.resolve().is_relative_to(folder.resolve()):
            reader.issue(folder, (kind,), "component_outside_plugin")
            return None
        if not reader.safe(path).exists():
            reader.issue(path, (kind,), "missing_reference")
            return None
    except (OSError, ValueError, RuntimeError):
        reader.issue(folder, (kind,), "unsafe_component_path")
        return None
    return path


def mcp_document(reader, doc, path, prefix=""):
    """Plugin MCP files may contain a wrapper or a bare server map."""
    mcp(
        reader,
        doc
        if "mcpServers" in doc
        else {"mcpServers": {key: value for key, value in doc.items() if key != "$schema"}},
        path,
        prefix=prefix,
    )


def plugin_components(
    reader, folder, manifest, manifest_path, name, *, enabled=None, evidence="file"
):
    if not isinstance(name, str):
        reader.issue(manifest_path, COMPONENT_KINDS, "invalid_plugin_name")
        name = folder.name
    before = set(reader.items)
    skills(reader, folder / "skills")
    if (folder / "SKILL.md").exists() and "skills" not in manifest:
        skills(reader, folder)
    paths = manifest.get("skills", [])
    paths = [paths] if isinstance(paths, str) else paths
    if not isinstance(paths, list):
        reader.issue(manifest_path, ("skill",), "invalid_plugin_skills")
    else:
        for value in paths:
            path = component_path(reader, folder, value, "skill")
            if path:
                skills(reader, path.parent if path.name == "SKILL.md" else path)
    for kind, key, default in (
        ("mcp", "mcpServers", ".mcp.json"),
        ("hook", "hooks", "hooks/hooks.json"),
    ):
        path = folder / default
        doc = reader.document(path, (kind,))
        if kind == "mcp":
            mcp_document(reader, doc, path)
        else:
            hooks(reader, doc, path, disabled=enabled is False)
        declared = manifest.get(key, [])
        entries = declared if isinstance(declared, list) else [declared]
        for i, entry in enumerate(entries):
            path = manifest_path
            prefix = f"manifest/{key}/{i}/"
            if isinstance(entry, str):
                if Path(entry).suffix in (".mcpb", ".dxt"):
                    reader.issue(manifest_path, (kind,), "bundle_format_not_scanned")
                    continue
                path = component_path(reader, folder, entry, kind)
                if path is None:
                    continue
                entry = reader.document(path, (kind,), required=True)
                prefix = ""  # Same referenced file is one observation, even if declared twice.
            if not isinstance(entry, dict):
                reader.issue(manifest_path, (kind,), "invalid_plugin_component")
                continue
            if kind == "mcp":
                mcp_document(reader, entry, path, prefix=prefix)
            else:
                hooks(
                    reader,
                    entry if "hooks" in entry else {"hooks": entry},
                    path,
                    disabled=enabled is False,
                    prefix=prefix,
                )
    for inv_id in set(reader.items) - before:
        item = reader.items[inv_id]
        item["evidence"] = evidence
        item["config"]["plugin"] = name
        if enabled is False:
            item["enabled"] = 0
