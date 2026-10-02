"""Pi and OpenCode configuration; extension code is inventoried, never imported."""

from .adapters import mcp, rules, skills
from .helpers import plugins, references


def pi(reader, root):
    path = root / "settings.json"
    doc = reader.document(path, ("skill", "plugin"))
    plugins(reader, doc.get("packages", []), path, "packages")
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


def opencode(reader, root):
    # This is XDG_CONFIG_HOME/opencode, NOT XDG_DATA_HOME/opencode (session DB).
    if (root / "opencode.db").exists() and not any(
        (root / name).exists() for name in ("opencode.json", "opencode.jsonc", "config.json")
    ):
        reader.issue(root, ("skill", "mcp", "plugin", "rule"), "expected_opencode_config_root")
    for filename in ("opencode.json", "opencode.jsonc", "config.json"):
        path = root / filename
        doc = reader.document(path, ("skill", "mcp", "plugin", "rule"))
        servers = reader.mapping(doc, "mcp", path, ("mcp",))
        # v1 mcp.<name>; v2 mcp.servers.<name>, with timeout as metadata.
        if "servers" in servers:
            mcp(reader, servers, path, "servers")
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
    skills(reader, root / "skills")
    skills(reader, root / "skill")
    rules(reader, root, ("AGENTS.md",))
    for directory in ("plugins", "plugin"):
        for path in reader.children(root / directory, ("plugin",)):
            if path.suffix in (".ts", ".js"):
                reader.file(path, "plugin")
