"""Pi and OpenCode configuration; extension code is inventoried, never imported."""

import re
from urllib.parse import urlsplit

from .adapters import _source_bytes, mcp, rules, skills
from .helpers import local_path, plugins, references


def pi(reader, root):
    path = root / "settings.json"
    doc = reader.document(path, ("skill", "plugin"))
    plugins(reader, doc.get("packages", []), path, "packages")
    _pi_packages(reader, root, doc.get("packages", []), path)
    plugins(reader, doc.get("extensions", []), path, "extensions")
    references(reader, doc.get("skills", []), path, "skill")
    skills(reader, root / "skills")
    rules(reader, root, ("AGENTS.md",))
    path = root / "mcp.json"
    mcp(reader, reader.document(path, ("mcp",)), path)
    for path in reader.walk(root / "extensions", ("plugin",), depth=1):
        if path.suffix in (".ts", ".js") and (
            path.parent == root / "extensions" or path.name in ("index.ts", "index.js")
        ):
            reader.file(path, "plugin")


def opencode(reader, root, *, config_only=False):
    # This is XDG_CONFIG_HOME/opencode, NOT XDG_DATA_HOME/opencode (session DB).
    if (root / "opencode.db").exists() and not any(
        (root / name).exists() for name in ("opencode.json", "opencode.jsonc", "config.json")
    ):
        reader.issue(root, ("skill", "mcp", "plugin", "rule"), "expected_opencode_config_root")
    filenames = (
        ("opencode.json", "opencode.jsonc")
        if config_only
        else ("opencode.json", "opencode.jsonc", "config.json")
    )
    for filename in filenames:
        path = root / filename
        doc = reader.document(path, ("skill", "mcp", "plugin", "rule"))
        servers = reader.mapping(doc, "mcp", path, ("mcp",))
        # v1 mcp.<name>; v2 mcp.servers.<name>, with timeout as metadata.
        container = servers.get("servers")
        if isinstance(container, dict) and not any(
            key in container for key in ("type", "command", "url", "enabled", "disabled")
        ):
            mcp(reader, servers, path, "servers")
        elif (
            set(servers) == {"timeout"}
            and isinstance(servers["timeout"], dict)
            and set(servers["timeout"]) <= {"startup", "request"}
        ):
            pass  # v2 timeout metadata without any server declarations
        else:
            mcp(reader, doc, path, "mcp")
        plugins(reader, doc.get("plugin", []), path, "plugin")
        plugins(reader, doc.get("plugins", []), path, "plugins", source_field="package")
        paths = doc.get("skills", [])
        if isinstance(paths, dict):
            references(reader, paths.get("urls", []), path, "skill", prefix="urls")
            paths = paths.get("paths", [])
        references(reader, paths, path, "skill")
        references(reader, doc.get("instructions", []), path, "rule")
    if config_only:
        return
    skills(reader, root / "skills")
    skills(reader, root / "skill")
    rules(reader, root, ("AGENTS.md",))
    opencode_markdown_components(reader, root)
    for directory in ("plugins", "plugin"):
        for path in reader.children(root / directory, ("plugin",)):
            if path.suffix in (".ts", ".js"):
                reader.file(path, "plugin")


def opencode_markdown_components(reader, root):
    """OpenCode slash commands ``{command,commands}/**/*.md`` and agents ``{agent,agents}/**/*.md``.

    Names follow upstream config/command.ts, agent.ts and entry-name.ts: the path relative to
    the config dir with the folder prefix and extension removed (``git/commit`` for
    ``command/git/commit.md``); the frontmatter does not rename them.
    """
    from pathlib import Path

    for component, directories in (
        ("command", ("command", "commands")),
        ("agent", ("agent", "agents")),
    ):
        for directory in directories:
            base = root / directory
            for path in reader.walk(base, (component,)):
                if path.suffix != ".md":
                    continue
                raw = reader.read(path, (component,))
                if raw is None:
                    continue
                name = path.relative_to(base).with_suffix("").as_posix()
                reader.add(
                    component,
                    name,
                    path,
                    Path(directory, name).as_posix(),
                    evidence="file",
                    raw=raw,
                    config={"component": component},
                )


def _pi_packages(reader, root, entries, settings_path):
    if not isinstance(entries, list):
        return
    for entry in entries:
        source = (
            entry
            if isinstance(entry, str)
            else entry.get("source")
            if isinstance(entry, dict)
            else None
        )
        if not isinstance(source, str):
            continue
        if source.startswith("npm:"):
            match = re.fullmatch(r"npm:(@[^/]+/[^@]+|[^@]+)(?:@.+)?", source)
            folder = local_path(
                reader, match[1] if match else None, root / "npm/node_modules", ("skill", "plugin")
            )
        elif source.startswith(("https://", "git:https://")):
            try:
                parsed = urlsplit(source.removeprefix("git:"))
                value = (parsed.hostname or "") + "/" + parsed.path.lstrip("/").removesuffix(".git")
                folder = local_path(reader, value, root / "git", ("skill", "plugin"))
            except ValueError:
                folder = None
                reader.issue(settings_path, ("skill", "plugin"), "invalid_package_reference")
        elif source.startswith("git:"):
            folder = local_path(
                reader, source[4:].removesuffix(".git"), root / "git", ("skill", "plugin")
            )
        else:
            folder = local_path(reader, source, settings_path.parent, ("skill", "plugin"))
        if folder is None:
            continue
        path = folder / "package.json"
        package = reader.document(path, ("skill", "plugin"), required=True)
        if not package:
            continue
        reader.add(
            "plugin",
            package.get("name", folder.name),
            path,
            evidence="installed",
            raw=_source_bytes(package),
        )
        pi_manifest = reader.mapping(package, "pi", path, ("skill", "plugin"))
        before = set(reader.items)
        if "skills" in pi_manifest:
            references(reader, pi_manifest["skills"], path, "skill", container=folder)
        else:
            skills(reader, folder / "skills")
        # Resource filtering affects runtime selection. Preserve known explicit
        # disable-all; more elaborate selectors remain unknown rather than true.
        for key in set(reader.items) - before:
            item = reader.items[key]
            item["config"]["plugin"] = package.get("name", folder.name)
            if isinstance(entry, dict) and (
                entry.get("skills") == [] or entry.get("autoload") is False
            ):
                item["enabled"] = 0 if entry.get("skills", []) == [] else None
        if "extensions" in pi_manifest:
            plugins(reader, pi_manifest["extensions"], path, "extensions")
