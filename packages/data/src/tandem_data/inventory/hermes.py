"""Hermes profile-local skills, plugin manifests, hooks and durable cron jobs."""

from .adapters import _source_bytes, mcp, rules, skills
from .helpers import array, manifests, task
from .reader import KINDS


def _profile(reader, root):
    path = root / "config.yaml"
    doc = reader.document(path, KINDS)
    mcp(reader, doc, path, "mcp_servers")
    skill_config = reader.mapping(doc, "skills", path, ("skill",))
    disabled_skills = array(reader, skill_config, "disabled", path, ("skill",))
    skills(
        reader,
        root / "skills",
        [{"name": name, "enabled": False} for name in disabled_skills if isinstance(name, str)],
    )
    rules(reader, root, ("AGENTS.md", "SOUL.md"))
    config = reader.mapping(doc, "plugins", path, ("plugin",))
    enabled = array(reader, config, "enabled", path, ("plugin",))
    disabled = array(reader, config, "disabled", path, ("plugin",))
    for path in manifests(
        reader, root / "plugins", ("plugin.yaml", "plugin.yml"), ("plugin", "hook", "skill")
    ):
        manifest = reader.document(path, ("plugin", "hook", "skill"))
        if not manifest:
            continue
        name = str(path.parent.relative_to(root / "plugins"))
        state = (
            False
            if name in disabled or path.parent.name in disabled
            else True
            if name in enabled or path.parent.name in enabled
            else None
        )
        reader.add(
            "plugin", name, path, evidence="file", enabled=state, raw=_source_bytes(manifest)
        )
        for i, event in enumerate(array(reader, manifest, "provides_hooks", path, ("hook",))):
            if isinstance(event, str):
                reader.add(
                    "hook",
                    event,
                    path,
                    f"provides_hooks/{i}",
                    enabled=False if state is False else None,
                    config={"plugin": name},
                    raw=_source_bytes(event),
                )
            else:
                reader.issue(path, ("hook",), "invalid_hook_declaration")
        before = set(reader.items)
        skills(reader, path.parent / "skills")
        for key in set(reader.items) - before:
            reader.items[key]["config"]["plugin"] = name
            if state is False:
                reader.items[key]["enabled"] = 0
    for folder in reader.children(root / "hooks", ("hook",)):
        path = folder / "HOOK.yaml"
        doc = reader.document(path, ("hook",))
        if doc:
            reader.add(
                "hook", doc.get("name", folder.name), path, evidence="file", raw=_source_bytes(doc)
            )
    path = root / "cron/jobs.json"
    doc = reader.document(path, ("scheduled_task",), expected=(dict, list))
    entries = (
        doc if isinstance(doc, list) else array(reader, doc, "jobs", path, ("scheduled_task",))
    )
    for i, entry in enumerate(entries):
        state = entry.get("enabled") if isinstance(entry, dict) else None
        if isinstance(entry, dict) and (
            entry.get("state") in ("paused", "completed", "error") or entry.get("paused_at")
        ):
            state = False
        task(reader, entry, path, f"jobs/{i}", enabled=state)


def hermes(reader, root):
    _profile(reader, root)
    for profile in reader.children(root / "profiles", KINDS):
        _profile(reader, profile)
