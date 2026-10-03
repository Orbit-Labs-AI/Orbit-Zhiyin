"""Pinned Git trees, marketplace pointers and licensed component documents."""

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath
from urllib.parse import quote

import yaml

from ..contracts import Feature, Page, Record, Resource, digest, normalize_license
from .structured import SKILL_AGENTS, mcp_config_install, safe_path

PAGE_FILES = 60
WORKERS = 12
PERMISSIVE = {"MIT", "Apache-2.0", "CC0-1.0", "CC-BY-4.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}


MARKETPLACES = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json", ".github/plugin/marketplace.json")
SKILL_INTERNAL = {"subagent", "command", "rule", "workflow"}
RULE_TYPES = {"skill", "plugin", "mcp_server", "hook", "subagent", "command", "rule", "workflow", "guide", "output_style"}


def _plugin_manifest(path: str) -> bool:
    parts = path.split("/")
    return parts[-1] == "plugin.json" and any(p.endswith("-plugin") or p == "plugin" for p in parts[:-1])


def plugin_root(path: str) -> str:
    """`plugins/x/.claude-plugin/plugin.json` → `plugins/x`; the repository root is `.`."""
    return str(PurePosixPath(path).parent.parent)


def file_kind(path: str, skill_dirs=frozenset(), rules=(), plugin_dirs=None) -> str | None:
    """Resource type of one repository file, or None.

    `skill_dirs`: directories holding a SKILL.md; markdown under them (agents/, rules/, references/...)
    belongs to that skill and is not a standalone subagent/rule/command. `rules`: `[{glob, type}]`
    from `SourceSpec.config.kind_rules`, checked first. `plugin_dirs`: plugin roots; when given, a
    `.mcp.json` only counts inside one (a repository's own dev config is not a catalog item).
    """
    pure = PurePosixPath(path)
    name = pure.name
    parts = path.split("/")
    if name == "SKILL.md":
        return "skill"
    internal = any(str(parent) in skill_dirs for parent in pure.parents)
    for rule in rules:
        if (isinstance(rule, dict) and rule.get("type") in RULE_TYPES and isinstance(rule.get("glob"), str)
                and name.lower() != "readme.md" and pure.full_match(rule["glob"])):
            return None if internal and rule["type"] in SKILL_INTERNAL else rule["type"]
    if _plugin_manifest(path):
        return "plugin"
    if name == ".mcp.json":
        root = str(pure.parent)
        return "mcp_server" if plugin_dirs is None or root in plugin_dirs else None
    if (name == "hooks.json" and len(parts) == 1) or (
            "hooks" in parts and (name == "hooks.json" or name.endswith("-hooks.json"))):
        return "hook"
    if name.endswith((".md", ".mdc")):
        kind = None
        if "agents" in parts or name.endswith(".agent.md"):
            kind = "subagent"
        elif "commands" in parts or "prompts" in parts or name.endswith(".prompt.md"):
            kind = "command"
        elif "instructions" in parts or "rules" in parts or name.endswith(".instructions.md"):
            kind = "rule"
        elif "workflows" in parts:
            kind = "workflow"
        return None if internal and kind in SKILL_INTERNAL else kind
    return None


def hook_name(path: str, repo: str) -> str:
    """`plugins/hookify/hooks/hooks.json` → `hookify`; `x/hooks.json` → `x`; root → repository name."""
    parent = PurePosixPath(path).parent
    if parent.name == "hooks":
        parent = parent.parent
    return parent.name or repo.split("/")[-1]


def hook_bindings(manifest: dict) -> list[dict]:
    """Claude Code hooks JSON `{hooks: {Event: [{matcher, hooks: [{type:'command', command}]}]}}` →
    one `{event, matcher, command, timeout}` per command hook (first command per event/matcher)."""
    events = manifest.get("hooks") if isinstance(manifest.get("hooks"), dict) else None
    out = []
    for event, groups in (events or {}).items():
        if not isinstance(event, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", event) or not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks") or []:
                if isinstance(hook, dict) and hook.get("type", "command") == "command" and isinstance(hook.get("command"), str):
                    binding = {"event": event, "command": hook["command"][:4000]}
                    if isinstance(group.get("matcher"), str) and group["matcher"]:
                        binding["matcher"] = group["matcher"][:500]
                    if isinstance(hook.get("timeout"), (int, float)) and not isinstance(hook.get("timeout"), bool):
                        binding["timeout"] = int(hook["timeout"])
                    out.append(binding)
    return out


def mcp_servers(manifest: dict) -> dict:
    """`.mcp.json` is `{mcpServers: {name: cfg}}`, or the bare `{name: cfg}` map plugins also use."""
    servers = manifest.get("mcpServers") if isinstance(manifest.get("mcpServers"), dict) else manifest
    return {str(k): v for k, v in servers.items() if isinstance(v, dict) and (v.get("command") or v.get("url"))}


def frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        return {"parse_error": "unterminated_frontmatter"}, text
    try:
        metadata = yaml.safe_load(parts[0][4:]) or {}
        if not isinstance(metadata, dict):
            raise ValueError("frontmatter_not_mapping")
        # Reject aliases/cycles and non-JSON YAML values at the boundary.
        import json
        metadata = json.loads(json.dumps(metadata, allow_nan=False))
        return metadata, parts[1].lstrip("\n")
    except (yaml.YAMLError, TypeError, ValueError, RecursionError):
        return {"parse_error": "invalid_frontmatter"}, parts[1].lstrip("\n")


class GitHubConnector:
    def __init__(self, source, http):
        self.source, self.http = source, http
        self._texts: dict[str, str] = {}  # LICENSE reads shared by documents of one connector run
        self._skill_dirs: set[str] = set()
        self._plugin_dirs: set[str] = set()
        self._rules = [r for r in source.config.get("kind_rules") or [] if isinstance(r, dict)]
        self.repo = source.config["repo"]
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", self.repo):
            raise ValueError("invalid_github_repository")

    def fetch_page(self, checkpoint: dict, state: dict) -> Page:
        if not checkpoint:
            info = self.http.json(f"https://api.github.com/repos/{self.repo}")
            branch = quote(info["default_branch"], safe="")
            commit = self.http.json(f"https://api.github.com/repos/{self.repo}/branches/{branch}")["commit"]
            head = commit["sha"]
            if head == state.get("revision"):
                return Page(records=[], complete=True, mode="incremental", revision=head)
            committed = ((commit.get("commit") or {}).get("committer") or {}).get("date")
            checkpoint = {"sha": head, "offset": 0, "repo_id": str(info["id"]),
                          "license": (info.get("license") or {}).get("spdx_id"),
                          "stars": info.get("stargazers_count"), "updated_at": committed}
        sha = checkpoint["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("invalid_git_revision")
        tree = self.http.json(f"https://api.github.com/repos/{self.repo}/git/trees/{sha}?recursive=1", immutable=True)
        if tree.get("truncated") or not isinstance(tree.get("tree"), list):
            raise ValueError("incomplete_git_tree")
        blobs = {entry["path"]: entry for entry in tree["tree"] if entry["type"] == "blob"}
        self._skill_dirs = {str(PurePosixPath(p).parent) for p in blobs if PurePosixPath(p).name == "SKILL.md"}
        self._plugin_dirs = {plugin_root(p) for p in blobs if _plugin_manifest(p)}
        plan = [(path, kind) for path in sorted(blobs) if (kind := self._kind(path))]
        if self.source.config.get("root_type") in ("workflow", "guide") and "README.md" in blobs:
            plan.append(("README.md", self.source.config["root_type"]))
        offset = checkpoint["offset"]
        records = []
        known = state.get("known") or {}
        market = self._marketplace_path(blobs)
        if offset == 0 and market:
            explicit = bool(self.source.config.get("marketplace"))
            try:
                checkpoint = {**checkpoint, "marketplace": self._marketplace_index(market, checkpoint, blobs)}
                records.extend(self._marketplace(checkpoint, blobs, known, market))
            except (ValueError, KeyError, TypeError):
                if explicit:
                    raise
                checkpoint = {**checkpoint, "marketplace": None}  # Auto-detected and malformed: skip it.
        batch = plan[offset:offset + PAGE_FILES]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for rows in pool.map(lambda entry: self._documents(entry, checkpoint, blobs, known), batch):
                records.extend(rows)
        next_offset = offset + len(batch)
        return Page(records=records, complete=next_offset >= len(plan), revision=sha,
                    checkpoint={**checkpoint, "offset": next_offset})

    def _kind(self, path: str) -> str | None:
        return file_kind(path, self._skill_dirs, self._rules, self._plugin_dirs)

    def _marketplace_path(self, blobs) -> str | None:
        configured = self.source.config.get("marketplace")
        if configured:
            return configured
        if self.source.config.get("auto_marketplace", True):
            return next((p for p in MARKETPLACES if p in blobs), None)
        return None

    def _marketplace_index(self, path, checkpoint, blobs) -> dict:
        """`{name, dirs: {plugin directory: marketplace entry name}}` so `plugin.json` items can be installed."""
        import json
        manifest = json.loads(self._cached_read(safe_path(path), checkpoint, blobs))
        plugins = manifest.get("plugins") if isinstance(manifest, dict) else None
        if not isinstance(plugins, list):
            raise ValueError("invalid_marketplace_manifest")
        dirs = {}
        for plugin in plugins:
            source = plugin.get("source") if isinstance(plugin, dict) else None
            if isinstance(source, str) and source.startswith("./") and plugin.get("name"):
                directory = safe_path(source).rstrip("/") or "."
                dirs[directory] = str(plugin["name"])
        return {"name": manifest.get("name"), "dirs": dirs}

    def _cached_read(self, path, checkpoint, blobs) -> str:
        if path not in self._texts:
            self._texts[path] = self._read(path, checkpoint, blobs)
        return self._texts[path]

    def _read(self, path, checkpoint, blobs) -> str:
        path = safe_path(path)
        entry = blobs.get(path)
        if not entry or entry.get("size", 0) > 250000:
            raise ValueError("missing_or_oversize_source_file")
        raw = self.http.get(f"https://raw.githubusercontent.com/{self.repo}/{checkpoint['sha']}/{quote(path, safe='/')}", immutable=True)
        expected = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if expected != entry["sha"]:
            raise ValueError("git_blob_hash_mismatch")
        return raw.decode("utf-8").replace("\r\n", "\n")

    def _license(self, path, metadata, checkpoint, blobs):
        explicit = metadata.get("license")
        if isinstance(explicit, str):
            explicit = normalize_license(explicit)
        if isinstance(explicit, str) and explicit in PERMISSIVE:
            return explicit
        if explicit and not isinstance(explicit, str):
            return "unrecognized_component_license"
        # A component license takes precedence over the repository license.
        parent = PurePosixPath(path).parent
        for directory in [parent, *parent.parents]:
            if explicit and directory != parent:
                return explicit  # A restrictive component declaration overrides root MIT.
            for name in ("LICENSE", "LICENSE.txt", "LICENSE.md"):
                candidate = str(directory / name)
                if candidate not in blobs:
                    continue
                text = self._cached_read(candidate, checkpoint, blobs).lstrip()[:400]
                if explicit and not re.search(r"(?:terms|license\.)", explicit, re.I):
                    return explicit
                if re.match(r"(?:#\s*)?MIT License", text, re.I):
                    return "MIT"
                if re.match(r"(?:#\s*)?Apache License\s+Version 2\.0", text, re.I):
                    return "Apache-2.0"
                return str(explicit or "repository_specific")
        return str(explicit) if explicit else checkpoint.get("license")

    def _item_id(self, kind, path, checkpoint, part: str | None = None):
        if kind == "plugin":
            path = plugin_root(path)
        return f"{kind}:github.com:{checkpoint['repo_id']}:{path}" + (f"#{part}" if part else "")

    def _extra(self, checkpoint, blob_sha) -> dict:
        # Stars and dates come from the repository, not the component: say so.
        return {"blob_sha": blob_sha, "author": self.repo.split("/")[0], "source_updated_at": checkpoint.get("updated_at"),
                "updated_scope": "repo", "stars_scope": "repo"}

    def _agents(self, kind) -> list[str]:
        configured = list(self.source.config.get("agents", []))
        if kind == "skill" and self.source.config.get("agents_infer", True):
            return list(dict.fromkeys(configured + SKILL_AGENTS))
        return configured

    def _parts(self, path, kind, checkpoint, blobs) -> list[str | None]:
        """Item suffixes of a split file (hook events, MCP servers); `[None]` when not split/unreadable."""
        import json
        if kind not in ("hook", "mcp_server") or blobs[path].get("size", 0) > 250000:
            return [None]
        try:
            manifest = json.loads(self._cached_read(path, checkpoint, blobs))
        except (ValueError, KeyError, TypeError, UnicodeError):
            return [None]
        if not isinstance(manifest, dict):
            return [None]
        if kind == "hook":
            events = list(dict.fromkeys(b["event"] for b in hook_bindings(manifest)))
            return events or [None]
        return list(mcp_servers(manifest)) or [None]

    def _popularity(self, checkpoint) -> dict:
        return {"stars": checkpoint["stars"]} if checkpoint.get("stars") is not None else {}

    def _components(self, path, checkpoint, blobs) -> list[str]:
        parent = plugin_root(path)
        ids = []
        for child in sorted(blobs):
            kind = self._kind(child)
            if kind and kind != "plugin" and (parent == "." or child.startswith(parent + "/")):
                ids.extend(self._item_id(kind, child, checkpoint, part) for part in self._parts(child, kind, checkpoint, blobs))
        return ids[:1000]

    def _reuse(self, entry, checkpoint, blobs, known) -> Record | None:
        """Unchanged git blob: reuse the stored Resource/raw instead of downloading it again."""
        path, kind = entry
        hit = known.get(path)
        if not hit:
            return None
        if isinstance(hit, dict):
            stored_sha, resource, raw = hit.get("blob_sha"), hit.get("resource"), hit.get("raw")
        else:
            stored_sha, resource, raw = hit
        if resource is None:
            return None
        resource = resource if isinstance(resource, Resource) else Resource.model_validate(resource)
        if (stored_sha or resource.metadata.get("blob_sha")) != blobs[path]["sha"]:
            return None
        update = {"popularity": {**resource.popularity, **self._popularity(checkpoint)}}
        if kind == "plugin":
            update["components"] = self._components(path, checkpoint, blobs)  # Sibling files may have changed.
        return Record(native_id=path, resource=resource.model_copy(update=update), raw=raw or {})

    def _document(self, entry, checkpoint, blobs, known=None) -> Record:
        """First record of `_documents` (single-item files)."""
        return self._documents(entry, checkpoint, blobs, known)[0]

    def _documents(self, entry, checkpoint, blobs, known=None) -> list[Record]:
        import json
        path, kind = entry
        reused = self._reuse(entry, checkpoint, blobs, known or {})
        if reused:
            return [reused]
        if blobs[path].get("size", 0) > 250000:
            # One oversized document must not make the entire source unrefreshable.
            resource = Resource(item_id=self._item_id(kind, path, checkpoint), type=kind,
                                name=self._default_name(kind, path),
                                url=f"https://github.com/{self.repo}/blob/{checkpoint['sha']}/{quote(path, safe='/')}",
                                repo_id=checkpoint["repo_id"], repo_path=path, commit_sha=checkpoint["sha"],
                                agents=self._agents(kind),
                                popularity=self._popularity(checkpoint),
                                metadata={"content_status": "oversize_metadata_only", "source_blob_sha": blobs[path]["sha"],
                                          "source_bytes": blobs[path]["size"], "verification": "tree_metadata_only",
                                          **self._extra(checkpoint, blobs[path]["sha"])})
            return [Record(native_id=path, resource=resource, raw={"path": path, **blobs[path]})]
        text = self._cached_read(path, checkpoint, blobs) if kind in ("hook", "mcp_server") else self._read(path, checkpoint, blobs)
        if path.endswith(".json"):
            metadata, body = json.loads(text), text
            if not isinstance(metadata, dict):
                raise ValueError("manifest_not_object")
        else:
            metadata, body = frontmatter(text)
        name = str(metadata.get("name") or self._default_name(kind, path))[:300]
        if kind in ("hook", "mcp_server"):
            name = self._default_name(kind, path)  # hooks.json / .mcp.json `name` fields are not item names
        description = metadata.get("description")
        summary = str(description)[:12000] if description else ""
        license_id = self._license(path, metadata, checkpoint, blobs)
        allowed = license_id in PERMISSIVE
        item_id = self._item_id(kind, path, checkpoint)
        components = self._components(path, checkpoint, blobs) if kind == "plugin" else []
        features = []
        tools = metadata.get("allowed-tools", metadata.get("tools", []))
        if isinstance(tools, str):
            tools = re.split(r"[,\s]+", tools)
        if isinstance(tools, list):
            features.extend(Feature(feature="tool_kind", value=str(tool)[:256], origin="declared", evidence="frontmatter tools") for tool in tools[:50] if tool)
        risk = ["runs_command"] if kind == "hook" else []
        r = Resource(item_id=item_id, type=kind, name=name or path[:300], summary=summary,
                     url=f"https://github.com/{self.repo}/blob/{checkpoint['sha']}/{quote(path, safe='/')}",
                     body=body if allowed else "", body_policy="licensed" if allowed else "metadata", license=license_id,
                     agents=self._agents(kind), commit_sha=checkpoint["sha"], repo_id=checkpoint["repo_id"], repo_path=path,
                     official=bool(self.source.config.get("official")) and not path.startswith("external_plugins/"), manifest=metadata,
                     metadata={"repository": self.repo, "source_body_hash": digest(text), "source_blob_sha": blobs[path]["sha"],
                               "verification": "repository_and_source_read", "parse_error": metadata.get("parse_error"),
                               **self._extra(checkpoint, blobs[path]["sha"])},
                     popularity=self._popularity(checkpoint),
                     version=str(metadata["version"]) if metadata.get("version") else None,
                     components=components, features=features, risk=risk)
        raw = {"path": path, "blob_sha": blobs[path]["sha"], "frontmatter": metadata}
        if kind == "hook":
            return self._hook_records(r, metadata, raw)
        if kind == "mcp_server":
            return self._mcp_records(r, metadata, raw)
        if kind == "plugin":
            r = self._plugin_fields(r, path, metadata, checkpoint)
        return [Record(native_id=path, resource=r, raw=raw)]

    def _default_name(self, kind, path) -> str:
        pure = PurePosixPath(path)
        if kind == "skill":
            return pure.parent.name or self.repo.split("/")[-1]
        if kind == "hook":
            return hook_name(path, self.repo)
        if kind in ("mcp_server", "plugin"):
            root = pure.parent if kind == "mcp_server" else PurePosixPath(plugin_root(path))
            return root.name or self.repo.split("/")[-1]
        return pure.stem

    def _plugin_fields(self, r: Resource, path, metadata, checkpoint) -> Resource:
        """`plugin.json`: install via the same repository's marketplace, plus declared provenance fields."""
        market = checkpoint.get("marketplace") or {}
        entry = (market.get("dirs") or {}).get(plugin_root(path))
        install = {"marketplace": market["name"], "name": entry} if entry and market.get("name") else {}
        author = metadata.get("author")
        author = author.get("name") if isinstance(author, dict) else author
        extra = {key: str(metadata[key])[:2000] for key in ("homepage", "repository") if isinstance(metadata.get(key), str)}
        if isinstance(author, str) and author.strip():
            extra["author"] = author.strip()[:300]
            extra["declared_author"] = True
        return r.model_copy(update={"install": install, "metadata": {**r.metadata, **extra, "installable": bool(install)}})

    def _hook_records(self, r: Resource, manifest, raw) -> list[Record]:
        """One item per hook event; the first command hook of the event becomes `install.hook`."""
        bindings = hook_bindings(manifest) if isinstance(manifest, dict) else []
        if not bindings:
            return [Record(native_id=r.repo_path, resource=r.model_copy(update={"metadata": {**r.metadata, "installable": False}}), raw=raw)]
        by_event: dict[str, list[dict]] = {}
        for binding in bindings:
            by_event.setdefault(binding["event"], []).append(binding)
        out = []
        for event, group in by_event.items():
            first = group[0]
            install = {"hook": {k: first[k] for k in ("event", "matcher", "command", "timeout") if k in first}}
            features = [*r.features, Feature(feature="hook_event", value=event, origin="declared", evidence="hooks.json")]
            if first.get("matcher"):
                features.append(Feature(feature="hook_matcher", value=first["matcher"][:256], origin="declared", evidence="hooks.json"))
            name = r.name if len(by_event) == 1 else f"{r.name} · {event}"
            meta = {**r.metadata, "hook_event": event, "hook_commands": len(group), "installable": True,
                    "plugin_relative": "${CLAUDE_PLUGIN_ROOT}" in first["command"]}
            item = r.model_copy(update={"item_id": r.item_id + "#" + event, "name": name[:300], "install": install,
                                        "features": features, "metadata": meta})
            out.append(Record(native_id=f"{r.repo_path}#{event}", resource=item, raw=raw))
        return out

    def _mcp_records(self, r: Resource, manifest, raw) -> list[Record]:
        servers = mcp_servers(manifest) if isinstance(manifest, dict) else {}
        out = []
        plugin = str(PurePosixPath(r.repo_path).parent)
        for name, server in servers.items():
            install = mcp_config_install(name, server)
            env = sorted(str(k)[:256] for k in (server.get("env") or {}) if k)[:20]
            features = [Feature(feature="tool_kind", value="mcp", origin="declared", evidence=".mcp.json"),
                        Feature(feature="transport", value="remote" if server.get("url") else "stdio", origin="declared", evidence=".mcp.json"),
                        *(Feature(feature="env_required", value=k, origin="declared", evidence=".mcp.json env") for k in env)]
            meta = {**r.metadata, "plugin_path": plugin, "installable": bool(install),
                    "plugin_relative": "${CLAUDE_PLUGIN_ROOT}" in str(server)}
            item = r.model_copy(update={"item_id": r.item_id + "#" + name, "name": name[:300], "install": {"mcp": install} if install else {},
                                        "features": features, "metadata": meta, "risk": ["external_tools"],
                                        "agents": r.agents or ["claude_code"]})
            out.append(Record(native_id=f"{r.repo_path}#{name}", resource=item, raw=raw))
        return out or [Record(native_id=r.repo_path, resource=r, raw=raw)]

    def _marketplace(self, checkpoint, blobs, known=None, path=None):
        import json
        path = safe_path(path or self.source.config["marketplace"])
        blob_sha = (blobs.get(path) or {}).get("sha")
        stored = {k: v for k, v in (known or {}).items() if k.startswith("marketplace:")}
        if blob_sha and stored:
            reused = []
            for native_id, hit in stored.items():
                resource = hit.get("resource") if isinstance(hit, dict) else hit[1]
                resource = resource if isinstance(resource, Resource) else Resource.model_validate(resource)
                raw = (hit.get("raw") if isinstance(hit, dict) else hit[2]) or {}
                reused.append(Record(native_id=native_id, resource=resource, raw=raw))
            if all(r.resource.metadata.get("marketplace_blob_sha") == blob_sha for r in reused):
                yield from reused
                return
        manifest = json.loads(self._cached_read(path, checkpoint, blobs))
        plugins = manifest.get("plugins")
        if not isinstance(plugins, list):
            raise ValueError("invalid_marketplace_manifest")
        for plugin in plugins:
            name = plugin["name"]
            source = plugin.get("source")
            metadata = {"marketplace": manifest.get("name"), "source": source, "resolution": "pointer_only",
                        "marketplace_blob_sha": blob_sha, "author": self.repo.split("/")[0],
                        "source_updated_at": checkpoint.get("updated_at")}
            item_id = f"plugin:marketplace:{checkpoint['repo_id']}:{name}"
            url = plugin.get("homepage") or self.source.url
            if isinstance(source, str) and source.startswith("./"):
                directory = safe_path(source)
                item_id = f"plugin:github.com:{checkpoint['repo_id']}:{directory}"
                metadata["resolution"] = "repository_path"
                url = f"https://github.com/{self.repo}/tree/{checkpoint['sha']}/{directory}"
            # Pointers to external repositories/packages remain explicit pointers. We do not
            # execute install commands or recursively crawl arbitrary manifest URLs.
            r = Resource(item_id=item_id, type="plugin", name=name[:300], summary=str(plugin.get("description") or "")[:12000],
                         url=url, agents=self.source.config.get("agents", []), manifest=plugin, metadata=metadata,
                         repo_id=checkpoint["repo_id"], commit_sha=checkpoint["sha"],
                         install={"marketplace": manifest.get("name"), "name": name})
            yield Record(native_id="marketplace:" + name, resource=r, raw=plugin)
