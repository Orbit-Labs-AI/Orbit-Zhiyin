"""Pinned Git trees, marketplace pointers and licensed component documents."""

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath
from urllib.parse import quote

import yaml

from ..contracts import Feature, Page, Record, Resource, digest
from .structured import safe_path

PAGE_FILES = 60
WORKERS = 12
PERMISSIVE = {"MIT", "Apache-2.0", "CC0-1.0", "CC-BY-4.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}


def file_kind(path: str) -> str | None:
    name = PurePosixPath(path).name
    parts = path.split("/")
    if name == "SKILL.md":
        return "skill"
    if name == "plugin.json" and any(p.endswith("-plugin") or p == "plugin" for p in parts[:-1]):
        return "plugin"
    if name.endswith(".json") and (name == "hooks.json" or "hooks" in parts):
        return "hook"
    if name.endswith((".md", ".mdc")):
        if "agents" in parts or name.endswith(".agent.md"):
            return "subagent"
        if "commands" in parts or "prompts" in parts or name.endswith(".prompt.md"):
            return "command"
        if "instructions" in parts or "rules" in parts or name.endswith(".instructions.md"):
            return "rule"
        if "workflows" in parts:
            return "workflow"
    return None


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
        plan = [(path, file_kind(path)) for path in sorted(blobs) if file_kind(path)]
        if self.source.config.get("root_type") in ("workflow", "guide") and "README.md" in blobs:
            plan.append(("README.md", self.source.config["root_type"]))
        offset = checkpoint["offset"]
        records = []
        known = state.get("known") or {}
        if offset == 0 and self.source.config.get("marketplace"):
            records.extend(self._marketplace(checkpoint, blobs, known))
        batch = plan[offset:offset + PAGE_FILES]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            records.extend(pool.map(lambda entry: self._document(entry, checkpoint, blobs, known), batch))
        next_offset = offset + len(batch)
        return Page(records=records, complete=next_offset >= len(plan), revision=sha,
                    checkpoint={**checkpoint, "offset": next_offset})

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
                if candidate not in self._texts:
                    self._texts[candidate] = self._read(candidate, checkpoint, blobs)
                text = self._texts[candidate].lstrip()[:400]
                if explicit and not re.search(r"(?:terms|license\.)", explicit, re.I):
                    return explicit
                if re.match(r"(?:#\s*)?MIT License", text, re.I):
                    return "MIT"
                if re.match(r"(?:#\s*)?Apache License\s+Version 2\.0", text, re.I):
                    return "Apache-2.0"
                return str(explicit or "repository_specific")
        return str(explicit) if explicit else checkpoint.get("license")

    def _item_id(self, kind, path, checkpoint):
        if kind == "plugin":
            path = str(PurePosixPath(path).parent.parent)
        return f"{kind}:github.com:{checkpoint['repo_id']}:{path}"

    def _extra(self, checkpoint, blob_sha) -> dict:
        return {"blob_sha": blob_sha, "author": self.repo.split("/")[0], "source_updated_at": checkpoint.get("updated_at")}

    def _popularity(self, checkpoint) -> dict:
        return {"stars": checkpoint["stars"]} if checkpoint.get("stars") is not None else {}

    def _components(self, path, checkpoint, blobs) -> list[str]:
        parent = str(PurePosixPath(path).parent.parent)
        return [self._item_id(file_kind(child), child, checkpoint) for child in sorted(blobs)
                if file_kind(child) and file_kind(child) != "plugin" and (parent == "." or child.startswith(parent + "/"))][:1000]

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

    def _document(self, entry, checkpoint, blobs, known=None):
        import json
        path, kind = entry
        reused = self._reuse(entry, checkpoint, blobs, known or {})
        if reused:
            return reused
        if blobs[path].get("size", 0) > 250000:
            # One oversized document must not make the entire source unrefreshable.
            resource = Resource(item_id=self._item_id(kind, path, checkpoint), type=kind,
                                name=PurePosixPath(path).parent.name if kind == "skill" else PurePosixPath(path).stem,
                                url=f"https://github.com/{self.repo}/blob/{checkpoint['sha']}/{quote(path, safe='/')}",
                                repo_id=checkpoint["repo_id"], repo_path=path, commit_sha=checkpoint["sha"],
                                agents=self.source.config.get("agents", []),
                                popularity=self._popularity(checkpoint),
                                metadata={"content_status": "oversize_metadata_only", "source_blob_sha": blobs[path]["sha"],
                                          "source_bytes": blobs[path]["size"], "verification": "tree_metadata_only",
                                          **self._extra(checkpoint, blobs[path]["sha"])})
            return Record(native_id=path, resource=resource, raw={"path": path, **blobs[path]})
        text = self._read(path, checkpoint, blobs)
        if path.endswith(".json"):
            metadata, body = json.loads(text), text
            if not isinstance(metadata, dict):
                raise ValueError("manifest_not_object")
        else:
            metadata, body = frontmatter(text)
        name = str(metadata.get("name") or (PurePosixPath(path).parent.name if kind == "skill" else PurePosixPath(path).stem))[:300]
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
                     agents=self.source.config.get("agents", []), commit_sha=checkpoint["sha"], repo_id=checkpoint["repo_id"], repo_path=path,
                     official=bool(self.source.config.get("official")) and not path.startswith("external_plugins/"), manifest=metadata,
                     metadata={"repository": self.repo, "source_body_hash": digest(text), "source_blob_sha": blobs[path]["sha"],
                               "verification": "repository_and_source_read", "parse_error": metadata.get("parse_error"),
                               **self._extra(checkpoint, blobs[path]["sha"])},
                     popularity=self._popularity(checkpoint),
                     version=str(metadata["version"]) if metadata.get("version") else None,
                     components=components, features=features, risk=risk)
        return Record(native_id=path, resource=r, raw={"path": path, "blob_sha": blobs[path]["sha"], "frontmatter": metadata})

    def _marketplace(self, checkpoint, blobs, known=None):
        import json
        path = safe_path(self.source.config["marketplace"])
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
        manifest = json.loads(self._read(path, checkpoint, blobs))
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
