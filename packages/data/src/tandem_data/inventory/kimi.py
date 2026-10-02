"""Kimi Code registry and both legacy-file and durable-wire cron observations."""

import json

from .adapters import _source_bytes, mcp, rules, skills
from .helpers import array, hook_array, local_path, references, task

COMPONENTS = ("plugin", "skill", "mcp", "hook", "rule")


def _plugins(reader, root):
    path = root / "plugins/installed.json"
    doc = reader.document(path, COMPONENTS)
    if doc and doc.get("version") != 1:
        reader.issue(path, COMPONENTS, "unsupported_plugin_registry_version")
        return
    for i, entry in enumerate(array(reader, doc, "plugins", path, COMPONENTS)):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            reader.issue(path, COMPONENTS, "invalid_plugin_registration")
            continue
        name, state = entry["id"], entry.get("enabled")
        reader.add(
            "plugin",
            name,
            path,
            f"plugins/{i}",
            enabled=state,
            evidence="installed",
            raw=_source_bytes(entry),
        )
        folder = local_path(reader, entry.get("root"), root, COMPONENTS)
        if folder is None:
            continue
        manifest_path = folder / "kimi.plugin.json"
        manifest = reader.document(manifest_path, COMPONENTS)
        if not manifest:
            reader.issue(manifest_path, COMPONENTS, "missing_plugin_manifest")
            continue
        before = set(reader.items)
        mcp(reader, manifest, manifest_path)
        hook_array(reader, manifest.get("hooks", []), manifest_path)
        if "skills" in manifest:
            values = manifest["skills"]
            references(
                reader, [values] if isinstance(values, str) else values, manifest_path, "skill"
            )
        else:
            reader.file(folder / "SKILL.md", "skill", name=name)
        if "systemPrompt" in manifest:
            reader.add(
                "rule",
                name + ":systemPrompt",
                manifest_path,
                "systemPrompt",
                raw=_source_bytes(manifest["systemPrompt"]),
            )
        if "systemPromptPath" in manifest:
            references(reader, [manifest["systemPromptPath"]], manifest_path, "rule")
        capabilities = reader.mapping(entry, "capabilities", path, ("mcp",))
        servers = reader.mapping(capabilities, "mcpServers", path, ("mcp",))
        for key in set(reader.items) - before:
            item = reader.items[key]
            item["config"]["plugin"] = name
            if state is False:
                item["enabled"] = 0
            elif item["type"] == "mcp":
                server_state = servers.get(item["name"], {})
                if isinstance(server_state, dict) and isinstance(server_state.get("enabled"), bool):
                    item["enabled"] = int(server_state["enabled"])


def _cron(reader, agent):
    observed = {}
    for path in reader.children(agent / "cron", ("scheduled_task",)):
        if path.suffix != ".json":
            continue
        doc = reader.document(path, ("scheduled_task",))
        if isinstance(doc.get("id"), str):
            observed[doc["id"]] = (doc, path, "")
        else:
            reader.issue(path, ("scheduled_task",), "invalid_cron_task")
    path = agent / "wire.jsonl"
    raw = reader.read(path, ("scheduled_task",))
    if raw is not None:
        for i, line in enumerate(raw.splitlines()):
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError
                kind = event.get("type")
                if kind == "cron.add":
                    entry = event.get("task")
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        raise ValueError
                    observed[entry["id"]] = (entry, path, f"line/{i + 1}")
                elif kind == "cron.delete":
                    ids = event.get("ids")
                    if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
                        raise ValueError
                    for key in ids:
                        observed.pop(key, None)
                elif isinstance(kind, str) and kind.startswith("cron.") and kind != "cron.cursor":
                    reader.issue(path, ("scheduled_task",), "unknown_cron_record")
            except (ValueError, UnicodeError, RecursionError):
                reader.issue(path, ("scheduled_task",), "invalid_cron_journal")
    for entry, path, locator in observed.values():
        # Session resumption controls activation; persistence alone does not mean running.
        task(reader, entry, path, locator)


def kimi(reader, root):
    path = root / "config.toml"
    doc = reader.document(path, ("skill", "hook"))
    references(reader, doc.get("extra_skill_dirs", []), path, "skill")
    hook_array(reader, doc.get("hooks", []), path)
    skills(reader, root / "skills")
    rules(reader, root, ("AGENTS.md",))
    path = root / "mcp.json"
    mcp(reader, reader.document(path, ("mcp",)), path)
    _plugins(reader, root)
    # Enumerate only native directory levels. Never open task output or message bodies
    # except the bounded wire needed to fold authoritative cron additions/deletions.
    for workdir in reader.children(root / "sessions", ("scheduled_task",)):
        for session in reader.children(workdir, ("scheduled_task",)):
            for agent in reader.children(session / "agents", ("scheduled_task",)):
                _cron(reader, agent)
