"""Explicit source layouts. A cache entry is never proof of enabled installation."""

import json
from pathlib import Path

import yaml

from .reader import KINDS, ScanReader

SUPPORTED = {
    "codex": KINDS,
    "dsh": KINDS,
    "hermes": KINDS,
    "kimi": KINDS,
    "pi": ("skill", "mcp", "plugin", "rule"),
    "opencode": ("skill", "mcp", "plugin", "rule"),
    "claude_code": ("skill", "mcp", "hook", "plugin", "rule"),
    "common": ("skill", "rule"),
    "project": KINDS,
    "claude_desktop": KINDS,
}


def _source_bytes(value) -> bytes:
    # TOML allows datetime and non-finite floats. Only hash these source values;
    # none of them bypasses the persisted metadata allowlist.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()


def mcp(reader, doc, path, key="mcpServers", prefix="", project_path=None):
    for name, value in reader.mapping(doc, key, path, ("mcp",)).items():
        if not isinstance(value, dict):
            reader.issue(path, ("mcp",), "invalid_mcp_entry")
            continue
        enabled = value.get("enabled")
        if isinstance(value.get("disabled"), bool):
            enabled = not value["disabled"]
        reader.add(
            "mcp",
            name,
            path,
            prefix + key + "/" + name,
            enabled=enabled,
            raw=_source_bytes(value),
            config={
                "transport": "remote"
                if "url" in value
                else "stdio"
                if "command" in value
                else "unknown",
                **({"project_path": project_path} if project_path is not None else {}),
            },
        )


def hooks(reader, doc, path, *, disabled=False, prefix=""):
    for event, groups in reader.mapping(doc, "hooks", path, ("hook",)).items():
        if not isinstance(groups, list):
            reader.issue(path, ("hook",), "invalid_hook_event")
            continue
        for i, group in enumerate(groups):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                reader.issue(path, ("hook",), "invalid_hook_group")
                continue
            for j, hook in enumerate(group["hooks"]):
                if not isinstance(hook, dict):
                    reader.issue(path, ("hook",), "invalid_hook")
                    continue
                reader.add(
                    "hook",
                    event,
                    path,
                    f"{prefix}hooks/{event}/{i}/{j}",
                    enabled=False if disabled else hook.get("enabled"),
                    raw=_source_bytes(hook),
                    config={
                        "event": event,
                        "type": hook.get("type")
                        if hook.get("type") in ("command", "prompt", "agent", "http")
                        else "unknown",
                    },
                )


def skills(reader, directory, overrides=()):
    for path in reader.skill_documents(directory):
        raw = reader.read(path, ("skill",))
        if raw is None:
            continue
        name = path.parent.name
        try:
            text = raw.decode("utf-8-sig")
            if text.startswith("---\n") and "\n---" in text[4:]:
                header = text[4:].split("\n---", 1)[0]
                if len(header) > 16384 or any(
                    isinstance(e, yaml.AliasEvent) for e in yaml.parse(header)
                ):
                    raise ValueError
                meta = yaml.safe_load(header)
                if isinstance(meta, dict) and "name" in meta:
                    if not isinstance(meta["name"], str) or not meta["name"].strip():
                        raise ValueError
                    name = meta["name"].strip()
        except (ValueError, UnicodeError, yaml.YAMLError, RecursionError):
            reader.issue(path, ("skill",), "invalid_skill_frontmatter")
        enabled = None
        for rule in overrides:
            try:
                selector = rule.get("path")
                selected = Path(selector).expanduser() if isinstance(selector, str) else None
                if selected is not None and not selected.is_absolute():
                    selected = reader.root / selected
                if rule.get("name") == name or selected in (path, path.parent):
                    enabled = rule.get("enabled")
            except (OSError, ValueError, RuntimeError):
                reader.issue(path, ("skill",), "invalid_skill_selector")
        reader.add("skill", name, path, enabled=enabled, evidence="file", raw=raw)


def rules(reader, root, names, directory="rules"):
    for name in names:
        reader.file(root / name, "rule", name=name)
    for path in reader.walk(root / directory, ("rule",)):
        if path.suffix in (".md", ".mdc", ".rules", ".txt"):
            reader.file(path, "rule", name=str(path.relative_to(root)))


def plugin_cache(reader, root, configured):
    components = ("plugin", "skill", "mcp", "hook")
    for market in reader.directories(root / "plugins/cache", components):
        for plugin in reader.directories(market, components):
            for version in reader.directories(plugin, components):
                manifest = version / ".codex-plugin/plugin.json"
                doc = reader.document(manifest, components)
                if not doc:
                    manifest = version / ".claude-plugin/plugin.json"
                    doc = reader.document(manifest, components)
                if not doc:
                    reader.issue(version, components, "missing_plugin_manifest")
                    continue
                key = plugin.name + "@" + market.name
                entry = configured.get(key, {})
                enabled = entry.get("enabled") if isinstance(entry, dict) else entry
                reader.add(
                    "plugin",
                    key,
                    manifest,
                    evidence="cached",
                    enabled=enabled,
                    config={"version": version.name},
                    raw=_source_bytes(doc),
                )
                from .components import plugin_components

                plugin_components(
                    reader, version, doc, manifest, key, enabled=enabled, evidence="cached"
                )


def codex(reader: ScanReader, root: Path):
    path = root / "config.toml"
    doc = reader.document(path, KINDS)
    mcp(reader, doc, path, "mcp_servers")
    config = reader.mapping(doc, "skills", path, ("skill",)).get("config", [])
    if not isinstance(config, list) or any(not isinstance(row, dict) for row in config):
        reader.issue(path, ("skill",), "invalid_skill_config")
        config = []
    skills(reader, root / "skills", config)
    for i, rule in enumerate(config):
        if not isinstance(rule.get("name", rule.get("path")), str):
            reader.issue(path, ("skill",), "invalid_skill_selector")
            continue
        reader.add(
            "skill",
            rule.get("name")
            or (
                Path(str(rule.get("path", "unknown"))).parent.name
                if Path(str(rule.get("path", ""))).name == "SKILL.md"
                else Path(str(rule.get("path", "unknown"))).name
            ),
            path,
            f"skills/config/{i}",
            enabled=rule.get("enabled"),
            raw=_source_bytes(rule),
        )
    from .helpers import local_path

    for rule in config:
        if isinstance(rule.get("path"), str):
            target = local_path(reader, rule["path"], root, ("skill",))
            if target:
                if target.exists():
                    skills(reader, target.parent if target.name == "SKILL.md" else target, config)
                else:
                    reader.issue(path, ("skill",), "missing_reference")
    rules(reader, root, ("AGENTS.md", "AGENTS.override.md"))
    plugins = reader.mapping(doc, "plugins", path, ("plugin",))
    for name, value in plugins.items():
        if not isinstance(value, dict):
            reader.issue(path, ("plugin",), "invalid_plugin_config")
            continue
        reader.add(
            "plugin",
            name,
            path,
            "plugins/" + name,
            enabled=value.get("enabled"),
            raw=_source_bytes(value),
        )
    plugin_cache(reader, root, plugins)
    hook_path = root / "hooks.json"
    hooks(reader, reader.document(hook_path, ("hook",)), hook_path)
    hooks(reader, doc, path)
    for task in reader.directories(root / "automations", ("scheduled_task",)):
        task_path = task / "automation.toml"
        task_doc = reader.document(task_path, ("scheduled_task",))
        if task_doc:
            status = task_doc.get("status")
            if not isinstance(status, str):
                status = None
            reader.add(
                "scheduled_task",
                task_doc.get("name", task.name),
                task_path,
                enabled={"ACTIVE": True, "PAUSED": False}.get(status),
                raw=_source_bytes(task_doc),
                config={"status": status if status in ("ACTIVE", "PAUSED") else "unknown"},
            )
        else:
            reader.issue(task_path, ("scheduled_task",), "missing_task_definition")


def claude(reader: ScanReader, root: Path):
    plugins = {}
    for filename in ("settings.json", "settings.local.json"):
        path = root / filename
        doc = reader.document(path, ("mcp", "hook", "plugin"))
        mcp(reader, doc, path)
        hooks(reader, doc, path, disabled=doc.get("disableAllHooks") is True)
        for name, enabled in reader.mapping(doc, "enabledPlugins", path, ("plugin",)).items():
            plugins[name] = enabled
            reader.add(
                "plugin",
                name,
                path,
                "enabledPlugins/" + name,
                enabled=enabled,
                raw=_source_bytes(enabled),
            )
    skills(reader, root / "skills")
    rules(reader, root, ("CLAUDE.md",))
    path = root / "plugins/installed_plugins.json"
    doc = reader.document(path, ("plugin",))
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
                enabled=plugins.get(name),
                evidence="installed",
                raw=_source_bytes(entry),
                config={
                    "scope": entry.get("scope")
                    if entry.get("scope") in ("user", "project", "local")
                    else "unknown",
                    **(
                        {"project_path": entry["projectPath"]}
                        if isinstance(entry.get("projectPath"), str)
                        else {}
                    ),
                },
            )
    from .components import COMPONENT_KINDS, plugin_components
    from .helpers import local_path

    for name, entries in reader.mapping(doc, "plugins", path, ("plugin",)).items():
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or "installPath" not in entry:
                continue
            folder = local_path(reader, entry["installPath"], root, COMPONENT_KINDS)
            if folder and not folder.is_relative_to(root / "plugins/cache"):
                manifest_path = folder / ".claude-plugin/plugin.json"
                manifest = reader.document(manifest_path, COMPONENT_KINDS, required=True)
                if manifest:
                    plugin_components(
                        reader, folder, manifest, manifest_path, name, enabled=plugins.get(name)
                    )
    plugin_cache(reader, root, plugins)
    from .claude_desktop import synced_plugins

    synced_plugins(reader, root / "plugins/synced", plugins)
    # The account-bearing ~/.claude.json is NOT implicitly read beside an approved root.
    path = root / ".mcp.json"
    mcp(reader, reader.document(path, ("mcp",)), path)


def project(reader: ScanReader, root: Path):
    from .dsh import dsh
    from .kimi import kimi
    from .native import opencode, pi

    opencode(reader, root, config_only=True)
    for directory, adapter in (
        (".pi", pi),
        (".opencode", opencode),
        (".kimi-code", kimi),
        (".dsh", dsh),
    ):
        path = root / directory
        try:
            if reader.safe(path).is_dir():
                adapter(reader, path)
        except (OSError, ValueError, RuntimeError):
            reader.issue(path, KINDS, "unsafe_project_config_root")
    claude(reader, root / ".claude")
    codex_root = root / ".codex"
    path = codex_root / "config.toml"
    mcp(reader, reader.document(path, ("mcp",)), path, "mcp_servers")
    skills(reader, root / ".agents/skills")
    skills(reader, codex_root / "skills")
    rules(
        reader,
        root,
        (
            "AGENTS.md",
            "AGENTS.override.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
        ),
        ".cursor/rules",
    )
    rules(reader, codex_root, ())
    path = root / ".mcp.json"
    mcp(reader, reader.document(path, ("mcp",)), path)


def desktop(reader: ScanReader, root: Path):
    from .claude_desktop import scan_desktop

    scan_desktop(reader, root)


def scan_layout(reader: ScanReader, agent: str):
    if agent == "common":
        skills(reader, reader.root / "skills")
        rules(reader, reader.root, ("AGENTS.md",))
    elif agent in ("dsh", "hermes", "kimi", "pi", "opencode"):
        from .dsh import dsh
        from .hermes import hermes
        from .kimi import kimi
        from .native import opencode, pi

        {"dsh": dsh, "hermes": hermes, "kimi": kimi, "pi": pi, "opencode": opencode}[agent](
            reader, reader.root
        )
    else:
        {"codex": codex, "claude_code": claude, "project": project, "claude_desktop": desktop}[
            agent
        ](reader, reader.root)
