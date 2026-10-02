"""Read DSH Cordis declarations without evaluating !!js or booting plugins."""

from .adapters import _source_bytes, hooks, mcp, rules, skills
from .helpers import array, local_path, reference_name, references, task
from .reader import KINDS


def _entries(reader, entries, path, prefix="", depth=0):
    if depth > 8 or not isinstance(entries, list):
        reader.issue(path, KINDS, "invalid_or_deep_cordis_tree")
        return
    for i, entry in enumerate(entries):
        locator = f"{prefix}/{i}"
        if not isinstance(entry, dict):
            reader.issue(path, KINDS, "invalid_cordis_entry")
            continue
        if "insert" in entry:
            _entries(reader, entry["insert"], path, locator + "/insert", depth + 1)
        if "group" in entry:
            _entries(reader, entry["group"], path, locator + "/group", depth + 1)
        name = entry.get("name", entry.get("id"))
        if not isinstance(name, str):
            if "insert" not in entry and "group" not in entry:
                reader.issue(path, KINDS, "unresolved_cordis_entry")
            continue
        state = not entry["disabled"] if isinstance(entry.get("disabled"), bool) else None
        reader.add(
            "plugin", reference_name(name), path, locator, enabled=state, raw=_source_bytes(entry)
        )
        config = entry.get("config", {})
        if not isinstance(config, dict):
            reader.issue(path, KINDS, "invalid_cordis_config")
            continue
        short = name.removeprefix("@deepseek-ai/dsh-")
        if short == "mcp-client":
            server = config.get("serverName", entry.get("id"))
            if isinstance(server, str):
                mcp(
                    reader,
                    {"mcpServers": {server: {**config, "enabled": state}}},
                    path,
                    prefix=locator + "/",
                )
            else:
                reader.issue(path, ("mcp",), "invalid_server_name")
        elif short in ("hooks-claude-code", "hooks-codex"):
            target = config.get("configPath")
            # Upstream resolves relative configPath against launch cwd, which is
            # unavailable in an offline installation scan. Never guess that cwd.
            if isinstance(target, str) and target.startswith("/"):
                local = local_path(reader, target, path.parent, ("hook",))
                if local:
                    doc = reader.document(local, ("hook",), required=True)
                    hooks(
                        reader,
                        doc if "hooks" in doc else {"hooks": doc},
                        local,
                        disabled=state is False,
                    )
            else:
                reader.issue(path, ("hook",), "hook_launch_cwd_unknown")
        elif short == "skill-filesystem":
            references(reader, config.get("customSkillDirs", []), path, "skill")
        elif short == "storage-domain" and config.get("backend", "json") != "json":
            reader.issue(path, ("scheduled_task",), "unsupported_schedule_backend")
        elif short == "storage-json" and "root" in config:
            # An explicit alternate storage root must be independently authorized.
            target = config["root"]
            if isinstance(target, str) and target.startswith("/"):
                local = local_path(reader, target, path.parent, ("scheduled_task",))
                if local:
                    _schedule(reader, local)
            else:
                reader.issue(path, ("scheduled_task",), "storage_root_unresolved")


def _bundle(reader, root, name, seen, depth=0):
    if depth > 5:
        reader.issue(root, KINDS, "bundle_depth_limit")
        return
    folder = local_path(reader, name, root / "node_modules", KINDS)
    if folder is None or folder in seen:
        return
    seen.add(folder)
    path = folder / "package.json"
    doc = reader.document(path, KINDS)
    if not doc:
        reader.issue(path, KINDS, "bundle_manifest_unavailable")
        return
    reader.add("plugin", name, path, evidence="installed", raw=_source_bytes(doc))
    dsh = reader.mapping(doc, "dsh", path, KINDS)
    bundle = reader.mapping(dsh, "bundle", path, KINDS)
    if "patch" in bundle:
        patch = local_path(reader, bundle["patch"], folder, KINDS)
        if patch:
            _entries(reader, reader.document(patch, KINDS, expected=list, required=True), patch)
    skills(reader, folder / "skills")


def _profile(reader, root):
    path = root / "package.json"
    doc = reader.document(path, ("plugin",))
    dsh = reader.mapping(doc, "dsh", path, ("plugin",))
    profile = reader.mapping(dsh, "profile", path, ("plugin",))
    seen = set()
    for i, name in enumerate(array(reader, profile, "bundles", path, ("plugin",))):
        if isinstance(name, str):
            reader.add(
                "plugin",
                reference_name(name),
                path,
                f"bundles/{i}",
                raw=_source_bytes(name),
            )
            _bundle(reader, root, name, seen)
        else:
            reader.issue(path, ("plugin",), "invalid_bundle")
    for filename in ("cordis.yml", "cordis.patch.yml"):
        path = root / filename
        _entries(reader, reader.document(path, KINDS, expected=list), path)
    skills(reader, root / "skills")
    rules(reader, root, ("AGENTS.md",))


def _schedule(reader, root):
    path = root / "schedule.json"
    doc = reader.document(path, ("scheduled_task",))
    if doc:
        unit = doc.get("unit")
        if not isinstance(unit, dict) or unit.get("name") != "schedule" or unit.get("version") != 1:
            reader.issue(path, ("scheduled_task",), "unsupported_schedule_version")
            return
        tables = reader.mapping(doc, "tables", path, ("scheduled_task",))
        for key, entry in reader.mapping(tables, "tasks", path, ("scheduled_task",)).items():
            if not isinstance(entry, dict) or not isinstance(entry.get("record"), dict):
                reader.issue(path, ("scheduled_task",), "invalid_schedule_task")
                continue
            status = entry.get("status")
            task(
                reader,
                entry["record"],
                path,
                "tasks/" + key,
                name_key="title",
                enabled=True if status == "active" else False if status == "inactive" else None,
            )


def dsh(reader, root):
    path = root / "settings.yaml"
    legacy = reader.document(path, KINDS)
    _entries(
        reader, [{"id": key, "config": value} for key, value in legacy.items()], path, "legacy"
    )
    _profile(reader, root)
    for profile in reader.children(root / "profiles", KINDS):
        _profile(reader, profile)
    _schedule(reader, root / "storages")
