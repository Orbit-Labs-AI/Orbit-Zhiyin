"""Shared static declarations. References never authorize new filesystem roots."""

from pathlib import Path
from urllib.parse import urlsplit

from .adapters import _source_bytes, skills


def array(reader, doc, key, path, kinds):
    value = doc.get(key, [])
    if not isinstance(value, list):
        reader.issue(path, kinds, "invalid_" + key)
        return []
    return value


def reference_name(value):
    """Do not publish URL userinfo, queries or fragments as installation names."""
    if "://" in value:
        try:
            return Path(urlsplit(value).path).name or "remote-resource"
        except ValueError:
            return None
    return value


def local_path(reader, value, base, kinds):
    if not isinstance(value, str) or not value or "://" in value or any(c in value for c in "*?[]"):
        reader.issue(base, kinds, "unresolved_reference")
        return None
    try:
        path = Path(value).expanduser()
        path = path if path.is_absolute() else base / path
        reader.safe(path)
    except (ValueError, OSError, RuntimeError):
        reader.issue(base, kinds, "unauthorized_reference")
        return None
    return path


def references(reader, values, path, kind, *, prefix="references"):
    if not isinstance(values, list):
        reader.issue(path, (kind,), "invalid_references")
        return
    for i, value in enumerate(values):
        if not isinstance(value, str):
            reader.issue(path, (kind,), "invalid_reference")
            continue
        # Pi resource selectors use ! for exclusions. Keep the declaration but do
        # not pretend to resolve glob precedence or runtime resource registration.
        negative = value.startswith("!")
        target = value[1:] if negative else value
        name = reference_name(target)
        if name is None:
            reader.issue(path, (kind,), "invalid_reference")
            continue
        reader.add(
            kind,
            name,
            path,
            f"{kind}/{prefix}/{i}",
            enabled=False if negative else None,
            raw=_source_bytes(value),
        )
        if negative:
            continue
        local = local_path(reader, target, path.parent, (kind,))
        if local is None:
            continue
        try:
            if not reader.safe(local).exists():
                reader.issue(local, (kind,), "missing_reference")
            elif kind == "skill" and local.name != "SKILL.md":
                skills(reader, local)
            else:
                reader.file(local, kind)
        except OSError:
            reader.issue(local, (kind,), "unreadable_reference")


def plugins(reader, entries, path, key, *, source_field="source"):
    if not isinstance(entries, list):
        reader.issue(path, ("plugin",), "invalid_" + key)
        return
    for i, entry in enumerate(entries):
        value = (
            entry
            if isinstance(entry, str)
            else entry.get(source_field)
            if isinstance(entry, dict)
            else None
        )
        # OpenCode v1 also supports [package, options].
        if isinstance(entry, list) and entry:
            value = entry[0]
        if not isinstance(value, str):
            reader.issue(path, ("plugin",), "invalid_plugin_reference")
            continue
        name = reference_name(value)
        if name is None:
            reader.issue(path, ("plugin",), "invalid_reference")
            continue
        reader.add("plugin", name, path, f"{key}/{i}", raw=_source_bytes(entry))


def hook_array(reader, entries, path, prefix="hooks"):
    if not isinstance(entries, list):
        reader.issue(path, ("hook",), "invalid_hooks")
        return
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("event"), str):
            reader.issue(path, ("hook",), "invalid_hook")
            continue
        reader.add("hook", entry["event"], path, f"{prefix}/{i}", raw=_source_bytes(entry))


def task(reader, entry, path, locator="", *, name_key="name", enabled=None):
    if not isinstance(entry, dict):
        reader.issue(path, ("scheduled_task",), "invalid_task")
        return
    name = entry.get(name_key) or entry.get("id") or path.stem
    reader.add("scheduled_task", name, path, locator, enabled=enabled, raw=_source_bytes(entry))


def manifests(reader, root, names, kinds, levels=2):
    """Manifest layouts have bounded category depth; never traverse plugin code trees."""
    for folder in reader.children(root, kinds):
        try:
            if not reader.safe(folder).is_dir():
                continue
            found = False
            for name in names:
                path = folder / name
                if reader.safe(path).exists():
                    found = True
                    yield path
            if not found and levels > 1:
                yield from manifests(reader, folder, names, kinds, levels - 1)
        except (OSError, ValueError, RuntimeError):
            reader.issue(folder, kinds, "unsafe_manifest_path")
