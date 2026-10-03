"""Bounded, allowlisted configuration reads. Never archive configuration plaintext."""

from __future__ import annotations

import hashlib
import json
import stat
import tomllib
from pathlib import Path

import json5
import yaml

from orbit_data.contract import canonical, uid
from orbit_data.privacy import redact

KINDS = ("skill", "mcp", "hook", "plugin", "rule", "scheduled_task")
MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 10000
EXCLUDED_DIRECTORIES = {".trash", ".git", "node_modules", "__pycache__"}


class ScanReader:
    def __init__(self, root: Path, source_key: str, allowed_roots: tuple[Path, ...]):
        self.root = root
        self.source_key = source_key
        self.allowed = (root, *allowed_roots)
        self.items: dict[str, dict] = {}
        self.diagnostics: list[dict] = []
        self.failed: set[str] = set()
        self.visited = 0

    def issue(self, path: Path, kinds, code: str):
        self.failed.update(kinds)
        self.diagnostics.append({"path": str(path), "types": list(kinds), "code": code})

    def safe(self, path: Path) -> Path:
        target = path.resolve()
        if ".trash" in path.parts or ".trash" in target.parts:
            raise ValueError("excluded_trash")
        if not any(target.is_relative_to(root) for root in self.allowed):
            raise ValueError("outside_allowed_roots")
        # Even explicitly allowed directories do not authorize credential inputs.
        if any(
            part in ("backups", ".env", "credentials") or part.startswith((".credentials", ".env."))
            for part in target.parts
        ):
            raise ValueError("credential_path")
        if (
            target.name in ("auth.json", "mcp-auth.json")
            or target.suffix == ".key"
            or ("oauth" in target.name.lower() and target.suffix in (".json", ".yaml", ".toml"))
        ):
            raise ValueError("credential_path")
        return target

    def read(self, path: Path, kinds, *, required=False) -> bytes | None:
        try:
            target = self.safe(path)
            info = target.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("not_regular_file")
            with target.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("file_too_large")
            return raw
        except FileNotFoundError:
            if required:
                self.issue(path, kinds, "missing_reference")
            elif path.is_symlink():
                self.issue(path, kinds, "broken_symlink")
        except (OSError, ValueError, RuntimeError) as error:
            self.issue(
                path, kinds, str(error) if isinstance(error, ValueError) else type(error).__name__
            )
        return None

    def document(self, path: Path, kinds, *, expected=dict, required=False):
        raw = self.read(path, kinds, required=required)
        empty = [] if expected is list else {}
        if raw is None:
            return empty
        try:
            text = raw.decode("utf-8-sig")
            if path.suffix in (".yaml", ".yml"):
                # Reject aliases before construction: cycles and exponential alias
                # expansion must not reach hashing or traversal. Never execute tags.
                if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)):
                    raise ValueError("yaml_alias")

                class StaticLoader(yaml.SafeLoader):
                    pass

                def expression(loader, node):
                    self.issue(path, kinds, "dynamic_yaml_expression")
                    return {"$expression": loader.construct_scalar(node)}

                StaticLoader.add_constructor("tag:yaml.org,2002:js", expression)
                value = yaml.load(text, Loader=StaticLoader)
                if value is None:
                    value = empty
            elif path.suffix == ".toml":
                value = tomllib.loads(text)
            elif path.suffix == ".jsonc":
                value = json5.loads(text)
            else:
                value = json.loads(text)
            if not isinstance(value, expected):
                raise ValueError
            pending = [(value, 0)]
            nodes = 0
            while pending:
                node, depth = pending.pop()
                nodes += 1
                if depth > 64 or nodes > MAX_ENTRIES * 4:
                    raise ValueError
                if isinstance(node, dict):
                    if any(not isinstance(key, str) for key in node):
                        raise ValueError
                    pending.extend((child, depth + 1) for child in node.values())
                elif isinstance(node, list):
                    pending.extend((child, depth + 1) for child in node)
            return value
        except (ValueError, UnicodeError, yaml.YAMLError, RecursionError):
            self.issue(path, kinds, "invalid_document")
            return empty

    def children(self, path: Path, kinds) -> list[Path]:
        try:
            target = self.safe(path)
            children = []
            # Bound traversal even for unexpectedly large cache directories.
            for child in target.iterdir():
                self.visited += 1
                if self.visited > MAX_ENTRIES:
                    self.issue(path, kinds, "entry_limit")
                    break
                children.append(path / child.name)
            return sorted(children)
        except FileNotFoundError:
            if path.is_symlink():
                self.issue(path, kinds, "broken_symlink")
        except (OSError, ValueError, RuntimeError) as error:
            self.issue(
                path, kinds, str(error) if isinstance(error, ValueError) else type(error).__name__
            )
        return []

    def directories(self, path: Path, kinds):
        """Directory-only layouts must not reinterpret sidecar files as packages."""
        for child in self.children(path, kinds):
            if child.name.startswith("."):
                continue
            try:
                if self.safe(child).is_dir():
                    yield child
                elif child.is_symlink():
                    self.issue(child, kinds, "broken_directory_link")
            except (OSError, ValueError, RuntimeError):
                self.issue(child, kinds, "unsafe_directory_path")

    def walk(self, path: Path, kinds, depth=5, ancestors=frozenset()):
        """No unrestricted home traversal; follow links only inside authorized roots."""
        try:
            target = self.safe(path)
            if target in ancestors:
                self.issue(path, kinds, "symlink_cycle")
                return
            if not target.is_dir():
                if path.is_symlink():
                    self.issue(path, kinds, "broken_or_non_directory_symlink")
                return
            for child in self.children(path, kinds):
                if child.name in EXCLUDED_DIRECTORIES:
                    continue
                try:
                    resolved = self.safe(child)
                    if resolved.is_dir():
                        if depth:
                            yield from self.walk(child, kinds, depth - 1, ancestors | {target})
                        else:
                            self.issue(child, kinds, "depth_limit")
                    else:
                        yield child
                except (OSError, ValueError, RuntimeError):
                    self.issue(child, kinds, "unsafe_path")
        except (OSError, ValueError, RuntimeError):
            self.issue(path, kinds, "unsafe_path")

    def skill_documents(self, path: Path, depth=5, ancestors=frozenset()):
        """A SKILL.md marks a resource boundary, not a subtree to search for more skills."""
        try:
            target = self.safe(path)
            if target in ancestors:
                self.issue(path, ("skill",), "symlink_cycle")
                return
            if not target.is_dir():
                if path.is_symlink():
                    self.issue(path, ("skill",), "broken_or_non_directory_symlink")
                return
            entries = self.children(path, ("skill",))
            document = path / "SKILL.md"
            if document in entries:
                yield document
                return
            for child in entries:
                if child.name in EXCLUDED_DIRECTORIES:
                    continue
                try:
                    resolved = self.safe(child)
                    if resolved.is_dir():
                        if depth:
                            yield from self.skill_documents(child, depth - 1, ancestors | {target})
                        else:
                            self.issue(child, ("skill",), "depth_limit")
                except (OSError, ValueError, RuntimeError):
                    self.issue(child, ("skill",), "unsafe_path")
        except (OSError, ValueError, RuntimeError):
            self.issue(path, ("skill",), "unsafe_path")

    def add(
        self,
        kind,
        name,
        path,
        locator="",
        *,
        enabled=None,
        evidence="configured",
        config=None,
        raw=None,
    ):
        # Only caller-selected metadata is persisted. Commands, args, env, headers,
        # prompts, URLs and document bodies are deliberately never stored.
        if not isinstance(name, str):
            self.issue(path, (kind,), "invalid_item_name")
            name = "unknown"
        config = config or {}
        inv_id = uid("inventory", self.source_key, kind, str(path), locator)
        self.items[inv_id] = dict(
            inv_id=inv_id,
            type=kind,
            name=redact(str(name)),
            config_path=str(path),
            locator=locator,
            enabled=int(enabled) if isinstance(enabled, bool) else None,
            evidence=evidence,
            config=config,
            content_hash=hashlib.sha256(
                raw if raw is not None else canonical(config).encode()
            ).hexdigest(),
        )

    def file(self, path, kind, *, name=None, enabled=None):
        raw = self.read(path, (kind,))
        if raw is not None:
            self.add(kind, name or path.stem, path, enabled=enabled, evidence="file", raw=raw)

    def mapping(self, document, key, path, kinds):
        value = document.get(key, {})
        if not isinstance(value, dict):
            self.issue(path, kinds, "invalid_" + key)
            return {}
        return value
