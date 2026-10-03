"""Public registries, model catalogs and benchmark snapshots."""

import hashlib
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlencode

from ..contracts import Feature, Page, Record, Resource, digest, normalize_license
from ..models import canonical_model_id, normalize_effort, resolve_benchmark_model, split_effort

MAX_SOURCE_FILE = 64 * 1024 * 1024
FILE_KINDS = {"models_dev", "litellm", "swe_bench", "gemini"}
SKILL_AGENTS = ["claude_code", "codex", "gemini", "opencode"]  # Agent Skills (SKILL.md) open standard
MCP_AGENTS = ["claude_code", "codex", "copilot", "gemini", "opencode"]
MCP_PUBLISH_EVERY = 10
MCP_MAX_PAGES = 120
CLAWHUB_MAX_ITEMS = 500


def slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-")[:64].strip("-")
    return out or "item"


def mcp_install(manifest: dict) -> dict | None:
    """MCP registry ``server.json`` → install payload: a remote URL, else an npm/pypi stdio package."""
    name = slug(str(manifest.get("name") or "").rsplit("/", 1)[-1])
    for remote in manifest.get("remotes") or []:
        if isinstance(remote, dict) and str(remote.get("url", "")).startswith("https://"):
            return {"name": name, "transport": "sse" if remote.get("type") == "sse" else "http", "url": remote["url"]}
    for package in manifest.get("packages") or []:
        if not isinstance(package, dict) or (package.get("transport") or {}).get("type", "stdio") != "stdio":
            continue
        ident, version = package.get("identifier"), package.get("version")
        if package.get("registryType") == "npm" and ident:
            return {"name": name, "transport": "stdio", "command": "npx", "args": ["-y", f"{ident}@{version}" if version else ident]}
        if package.get("registryType") == "pypi" and ident:
            return {"name": name, "transport": "stdio", "command": "uvx", "args": [f"{ident}=={version}" if version else ident]}
    return None


def mcp_config_install(name: str, server: dict) -> dict | None:
    """One ``.mcp.json`` ``mcpServers`` entry → install payload. Literal env values are dropped
    (only ``${VAR}`` references survive); the names stay visible as ``env_required``."""
    if not isinstance(server, dict):
        return None
    url, command = server.get("url"), server.get("command")
    payload: dict = {"name": slug(name)}
    if isinstance(url, str) and url.startswith("https://"):
        payload.update(transport="sse" if server.get("type") == "sse" else "http", url=url)
        headers = {k: v for k, v in (server.get("headers") or {}).items() if isinstance(v, str) and "${" in v}
        if headers:
            payload["headers"] = headers
    elif isinstance(command, str) and command:
        payload.update(transport="stdio", command=command, args=[str(a) for a in server.get("args") or [] if isinstance(a, (str, int, float))])
        env = {k: v for k, v in (server.get("env") or {}).items() if isinstance(v, str) and "${" in v}
        if env:
            payload["env"] = env
    else:
        return None
    return payload


def namespace_author(name: str) -> str | None:
    """Reverse-DNS registry namespace → publisher: ``io.github.acme/x`` → ``acme``, ``com.example/x`` → ``example.com``."""
    namespace = str(name or "").split("/", 1)[0]
    parts = [p for p in namespace.split(".") if p]
    if len(parts) >= 3 and parts[0] in ("io", "com") and parts[1] == "github":
        return parts[2]
    return ".".join(reversed(parts)) or None


def _mcp_features(manifest: dict, install: dict | None) -> list[Feature]:
    features = [Feature(feature="tool_kind", value="mcp", origin="declared", evidence="registry entry")]
    transport = "remote" if manifest.get("remotes") or (install or {}).get("url") else "stdio"
    features.append(Feature(feature="transport", value=transport, origin="declared", evidence="registry packages/remotes"))
    env = set()
    for package in manifest.get("packages") or []:
        for var in (package.get("environmentVariables") or []) if isinstance(package, dict) else []:
            if isinstance(var, dict) and var.get("name") and var.get("isRequired", True):
                env.add(str(var["name"])[:256])
    features += [Feature(feature="env_required", value=name, origin="declared", evidence="registry environmentVariables")
                 for name in sorted(env)[:20]]
    return features
OFFICIAL_FILE = "data/official.v1.json"


def _number(value) -> float | None:
    """Numeric field or None; missing/blank/non-numeric values are never coerced to 0."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _flag(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _bool(value) -> bool | None:
    """Booleans that some registries serialize as strings ("true"/"false"/"1"/"0")."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0", "yes", "no"):
        return value.strip().lower() in ("true", "1", "yes")
    return None


def _per_mtok(value) -> float | None:
    number = _number(value)
    return None if number is None else round(number * 1_000_000, 6)


def _int(value) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _iso_date(value) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


class _MCPSnapshot:
    """Validated raw registry pages; no arbitrary serialized Resource ingestion."""

    def __init__(self, directory: str, source_url: str):
        self.root = Path(directory)
        if not self.root.is_absolute():
            raise ValueError("mcp_snapshot_dir_must_be_absolute")
        self.manifest_bytes = self._bytes(self.root / "manifest.json")
        manifest = self._json(self.manifest_bytes)
        pages = manifest.get("pages")
        if manifest.get("complete") is not True or isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 10000:
            raise ValueError("mcp_snapshot_incomplete")
        if manifest.get("next_cursor") or manifest.get("source", source_url) != source_url:
            raise ValueError("mcp_snapshot_manifest_mismatch")
        try:
            fetched = datetime.fromisoformat(manifest["fetched_at"].replace("Z", "+00:00"))
            if fetched.tzinfo is None:
                raise ValueError("missing_timezone")
            self.fetched_at = fetched.isoformat()
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError("mcp_snapshot_invalid_fetched_at") from exc
        self.paths = [self.root / f"page-{index:04d}.json" for index in range(pages)]
        if set(self.root.glob("page-*.json")) != set(self.paths):
            raise ValueError("mcp_snapshot_noncontiguous_pages")
        self.hashes, self.cursors = [], [None]
        identity, names, cursors, count = hashlib.sha256(self.manifest_bytes), set(), set(), 0
        for index, path in enumerate(self.paths):
            raw = self._bytes(path)
            data = self._json(raw)
            if not isinstance(data.get("servers"), list) or not isinstance(data.get("metadata"), dict):
                raise ValueError("invalid_mcp_page")
            cursor = data["metadata"].get("nextCursor")
            if bool(cursor) != (index < pages - 1) or (cursor and (not isinstance(cursor, str) or cursor in cursors)):
                raise ValueError("mcp_snapshot_cursor_mismatch")
            if cursor:
                cursors.add(cursor)
            self.cursors.append(cursor)
            for entry in data["servers"]:
                name = (entry.get("server") or {}).get("name") if isinstance(entry, dict) else None
                if not isinstance(name, str) or not name or name in names:
                    raise ValueError("mcp_snapshot_invalid_or_duplicate_name")
                names.add(name)
            count += len(data["servers"])
            if data["metadata"].get("count", len(data["servers"])) != len(data["servers"]):
                raise ValueError("mcp_snapshot_count_mismatch")
            page_hash = hashlib.sha256(raw).digest()
            self.hashes.append(page_hash)
            identity.update(page_hash)
        if manifest.get("records", count) != count or manifest.get("unique_names", len(names)) != len(names):
            raise ValueError("mcp_snapshot_count_mismatch")
        self.identity = "mcp-snapshot:" + identity.hexdigest()

    @staticmethod
    def _bytes(path):
        if not path.is_file():
            raise ValueError("mcp_snapshot_file_not_found")
        if path.stat().st_size > MAX_SOURCE_FILE:
            raise ValueError("source_file_too_large")
        return path.read_bytes()

    @staticmethod
    def _json(raw):
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("not_object")
            return value
        except (ValueError, UnicodeError) as exc:
            raise ValueError("mcp_snapshot_invalid_json") from exc

    def page(self, checkpoint):
        index = checkpoint.get("pages", 0)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(self.paths):
            raise ValueError("mcp_snapshot_invalid_checkpoint")
        if checkpoint and (checkpoint.get("snapshot_revision") != self.identity or checkpoint.get("cursor") != self.cursors[index]):
            raise ValueError("mcp_snapshot_checkpoint_mismatch")
        raw = self._bytes(self.paths[index])
        if hashlib.sha256(raw).digest() != self.hashes[index] or self._bytes(self.root / "manifest.json") != self.manifest_bytes:
            raise ValueError("mcp_snapshot_changed_during_scan")
        return self._json(raw)


class StructuredConnector:
    def __init__(self, source, http):
        self.source, self.http = source, http
        self.known_models: set[str] = set()
        self._mcp_snapshot = None


        self._last_search = float("-inf")

    def _load(self):
        """`config.file` imports a local fixture/cache snapshot without network or host allowlist."""
        path = self.source.config.get("file")
        if not path:
            return self.http.json(self.source.url)
        path = Path(path)
        if not path.is_absolute():
            raise ValueError("source_file_must_be_absolute")
        if not path.is_file():
            raise ValueError("source_file_not_found")
        if path.stat().st_size > MAX_SOURCE_FILE:
            raise ValueError("source_file_too_large")
        try:
            return json.loads(path.read_bytes())
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid_source_file") from exc

    def fetch_page(self, checkpoint: dict, state: dict) -> Page:
        if self.source.kind == "bundle":
            rows = json.loads(files("orbit_catalog").joinpath("data/skills.json").read_text())
            records = []
            for row in rows:
                features = [Feature(feature=key, value=value, origin="curated", evidence="Orbit reviewed seed")
                            for key, values in (("friction", row.get("problem_types", [])), ("dimension", row.get("dimensions", [])),
                                                ("scene", row.get("scenes", []))) for value in values]
                kind = {"mcp": "mcp_server", "integration": "guide"}.get(row["kind"], row["kind"])
                r = Resource(item_id="seed:" + row["id"], type=kind, name=row["name"], summary=row["summary"],
                             url=row["url"], language=row.get("language", "any"), license=row.get("license"),
                             agents=["claude_code", "codex"] if kind == "skill" else [], features=features,
                             commit_sha=row["verified_sha"], metadata={"seed_id": row["id"], "verification": row["verification"],
                             "trial": row.get("trial"), "limitations": row.get("limitations")})
                records.append(Record(native_id=row["id"], resource=r, raw=row))
            return Page(records=records, complete=True, revision=digest(rows))
        if self.source.kind == "snapshot":
            # Seed rows are written once by snapshot.import_snapshot and retired by the real
            # source; a scheduled visit must neither re-add nor remove them.
            return Page(records=[], complete=True, mode="incremental", revision=state.get("revision"))
        if self.source.kind == "kb":
            return self._kb(state)
        if self.source.kind == "mcp":
            return self._mcp(checkpoint, state)
        if self.source.kind == "clawhub":
            return self._clawhub(checkpoint, state)
        if self.source.kind == "awesome":
            return self._awesome(state)
        if self.source.kind == "github_topic":
            return self._github_topic(checkpoint, state)
        data = self._load() if self.source.kind in FILE_KINDS else self.http.json(self.source.url)
        revision = digest(data)
        if revision == state.get("revision"):
            return Page(records=[], complete=True, mode="incremental", revision=revision)
        self.known_models = set(state.get("known_models") or ()) | _known_model_ids(state.get("known") or {})
        parser = getattr(self, "_" + self.source.kind)
        return Page(records=list(parser(data)), complete=True, revision=revision)

    def _kb(self, state):
        """Orbit's reviewed remedy templates as official catalog items (read-only view of the KB)."""
        if self.source.config.get("file"):
            data = self._load()
        else:
            data = json.loads(files("orbit_catalog").joinpath(OFFICIAL_FILE).read_text())
        revision = digest(data)
        if revision == state.get("revision"):
            return Page(records=[], complete=True, mode="incremental", revision=revision)
        entries = official_entries(data) if isinstance(data, dict) and "rules" in data else data
        if not isinstance(entries, list) or not entries:
            raise ValueError("invalid_kb_catalog")
        records = [Record(native_id=entry["id"], resource=official_resource(entry), raw=entry) for entry in entries]
        return Page(records=records, complete=True, revision=revision)

    def _mcp(self, checkpoint, state):
        snapshot = None
        if self.source.config.get("snapshot_dir"):
            if self._mcp_snapshot is None:
                self._mcp_snapshot = _MCPSnapshot(self.source.config["snapshot_dir"], self.source.url)
            snapshot = self._mcp_snapshot
            if not checkpoint and state.get("revision") == snapshot.identity:
                return Page(records=[], complete=True, mode="incremental", revision=snapshot.identity,
                            watermark=snapshot.fetched_at)
            data = snapshot.page(checkpoint)
            scan_started_at, watermark, mode = snapshot.fetched_at, None, "full"
        else:
            params = {"limit": 100, "version": "latest"}
            scan_started_at = checkpoint.get("scan_started_at") or datetime.now(timezone.utc).isoformat()
            watermark = state.get("watermark")
            mode = "incremental" if watermark else "full"
            if watermark:
                dt = datetime.fromisoformat(watermark.replace("Z", "+00:00")) - timedelta(minutes=5)
                params["updated_since"] = dt.isoformat().replace("+00:00", "Z")
            if checkpoint.get("cursor"):
                params["cursor"] = checkpoint["cursor"]
            data = self.http.json(self.source.url + "?" + urlencode(params))
        if not isinstance(data, dict) or not isinstance(data.get("servers"), list) or not isinstance(data.get("metadata"), dict):
            raise ValueError("invalid_mcp_page")
        records, maximum = [], checkpoint.get("watermark", watermark)
        for entry in data["servers"]:
            server = entry["server"]
            meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
            updated = meta.get("updatedAt")
            if updated and (maximum is None or datetime.fromisoformat(updated.replace("Z", "+00:00")) > datetime.fromisoformat(maximum.replace("Z", "+00:00"))):
                maximum = updated
            name = server["name"]
            status = meta.get("status", "active")
            install = mcp_install(server)
            repository = server.get("repository") if isinstance(server.get("repository"), dict) else {}
            # Registry inclusion/namespace validation is not vendor endorsement. The registry's CC0
            # covers its metadata, not the server: the server license stays unknown (None).
            r = Resource(item_id="mcp:" + name, type="mcp_server", name=server.get("title") or name,
                         summary=server.get("description", "")[:12000], version=server.get("version"),
                         url=server.get("websiteUrl") or repository.get("url") or self.source.url,
                         manifest=server, license=None, agents=list(MCP_AGENTS),
                         status=status if status in ("active", "deprecated", "deleted") else "deprecated",
                         install={"mcp": install} if install else {}, features=_mcp_features(server, install),
                         risk=["external_tools"],
                         metadata={"registry_status": status, "source_updated_at": updated, "author": namespace_author(name),
                                   "registry_license": "CC0-1.0", "repository_url": repository.get("url"),
                                   "installable": bool(install), "stars_scope": "unavailable"})
            records.append(Record(native_id=name, resource=r, raw=entry))
        cursor = data["metadata"].get("nextCursor")
        if cursor and cursor == checkpoint.get("cursor"):
            raise ValueError("mcp_cursor_did_not_advance")
        pages = int(checkpoint.get("pages", 0)) + 1
        if snapshot:
            return Page(records=records, complete=pages == len(snapshot.paths), mode="full",
                        revision=snapshot.identity, watermark=snapshot.fetched_at,
                        checkpoint={"pages": pages, "cursor": cursor, "snapshot_revision": snapshot.identity})
        # Empty registry has no provider clock; the bounded overlap covers the initial scan time.
        maximum = maximum or scan_started_at
        # Never advance past the scan start: updates behind the pagination cursor must
        # be eligible next time, even when a full scan takes longer than the overlap.
        committed = min(datetime.fromisoformat(maximum.replace("Z", "+00:00")), datetime.fromisoformat(scan_started_at)).isoformat()
        return Page(records=records, complete=not bool(cursor), mode=mode, watermark=committed,
                    checkpoint={"cursor": cursor, "watermark": maximum, "scan_started_at": scan_started_at, "pages": pages},
                    revision=maximum)

    def _models_dev(self, data):
        if not isinstance(data, dict) or not data:
            raise ValueError("invalid_models_catalog")
        for provider, info in data.items():
            if not isinstance(info, dict) or not isinstance(info.get("models"), dict):
                raise ValueError("invalid_model_provider")
            for model_id, model in info["models"].items():
                if not isinstance(model, dict):
                    raise ValueError("invalid_model_entry")
                key = provider + "/" + model_id
                canonical = canonical_model_id(model_id, provider)
                cost, limit = model.get("cost") or {}, model.get("limit") or {}
                metadata = {"provider": provider, "model_id": model_id, "canonical_id": canonical,
                            "family": model.get("family"), "aliases": sorted({model_id, key} - {canonical}),
                            "context_window": _int(limit.get("context")), "max_output": _int(limit.get("output")),
                            "input_per_mtok": _number(cost.get("input")), "output_per_mtok": _number(cost.get("output")),
                            "cache_read_per_mtok": _number(cost.get("cache_read")),
                            "reasoning": _flag(model.get("reasoning")), "tool_call": _flag(model.get("tool_call")),
                            "modalities": model.get("modalities"), "knowledge_cutoff": model.get("knowledge"),
                            "source_updated_at": model.get("last_updated"), "pricing_source": "models.dev"}
                r = Resource(item_id="model:models.dev:" + key, type="model", name=model.get("name") or model_id,
                             summary=str(model.get("description") or "")[:12000], url=info.get("doc") or "https://models.dev",
                             manifest=model, metadata=metadata,
                             features=[Feature(feature="model_family", value=str(model["family"])[:256], origin="declared")] if model.get("family") else [])
                yield Record(native_id=key, resource=r, raw=model)

    def _litellm(self, data):
        if not isinstance(data, dict) or not data:
            raise ValueError("invalid_litellm_catalog")
        for key, model in data.items():
            if key == "sample_spec":
                continue
            if not isinstance(model, dict):
                raise ValueError("invalid_litellm_model")
            provider = model.get("litellm_provider") or "unknown"
            canonical = canonical_model_id(key, provider)
            resolved = not canonical.startswith("unknown/")
            metadata = {"provider": provider, "model_id": key, "canonical_id": canonical if resolved else None,
                        "family": None, "aliases": [key] if key != canonical else [],
                        "context_window": _int(model.get("max_input_tokens") or model.get("max_tokens")),
                        "max_output": _int(model.get("max_output_tokens")),
                        "input_per_mtok": _per_mtok(model.get("input_cost_per_token")),
                        "output_per_mtok": _per_mtok(model.get("output_cost_per_token")),
                        "cache_read_per_mtok": _per_mtok(model.get("cache_read_input_token_cost")),
                        "reasoning": _flag(model.get("supports_reasoning")), "tool_call": _flag(model.get("supports_function_calling")),
                        "modalities": None, "knowledge_cutoff": None, "mode": model.get("mode"),
                        "pricing_source": "litellm", "price_unit": "USD/token",
                        "canonical_identity": "resolved" if resolved else "unresolved"}
            r = Resource(item_id="model:litellm:" + key, type="model", name=key, url=self.source.url,
                         summary=f"{provider} model pricing and capabilities", manifest=model, metadata=metadata)
            yield Record(native_id=key, resource=r, raw=model)

    def _swe_bench(self, data):
        leaderboards = data.get("leaderboards") if isinstance(data, dict) else None
        if not isinstance(leaderboards, list):
            raise ValueError("invalid_swe_bench_catalog")
        for board in leaderboards:
            name = board.get("name") or board.get("id")
            rows = board.get("results")
            if not isinstance(rows, list) or not name:
                raise ValueError("invalid_swe_bench_board")
            for row in rows:
                model = row.get("model_display") or row.get("name")
                if not model:
                    raise ValueError("missing_benchmark_model")
                identity = [name, row.get("folder"), row.get("name"), model, row.get("agent"), row.get("reasoning_effort"), row.get("date")]
                effort_raw = row.get("reasoning_effort")
                manifest = {"model_id": model, "canonical_model_id": resolve_benchmark_model(str(model), self.known_models),
                            "effort": normalize_effort(effort_raw) if effort_raw else split_effort(str(model))[1],
                            "effort_raw": effort_raw, "harness": row.get("agent"), "benchmark": "SWE-bench",
                            "benchmark_version": name, "measured_at": _iso_date(row.get("date")),
                            "score": _number(row.get("resolved")), "unit": "percent", "source_result": row}
                site = row.get("site")
                if isinstance(site, list):
                    site = next((url for url in site if isinstance(url, str) and url), None)
                r = Resource(item_id="benchmark:swe:" + digest(identity), type="benchmark", name=str(model)[:300],
                             url=site if isinstance(site, str) and site else "https://www.swebench.com/",
                             summary=f"SWE-bench {name}", manifest=manifest,
                             metadata={"source_updated_at": manifest["measured_at"]})
                yield Record(native_id=digest(identity), resource=r, raw=row)

    def _gemini(self, data):
        if not isinstance(data, list):
            raise ValueError("invalid_gemini_catalog")
        for row in data:
            key = row["fullName"]
            stars = _int(row.get("stars"))
            r = Resource(item_id="gemini-extension:" + key, type="plugin", name=row.get("extensionName") or key,
                         summary=(row.get("extensionDescription") or row.get("repoDescription") or "")[:12000],
                         url=row["url"], agents=["gemini"], version=row.get("extensionVersion"),
                         license=normalize_license(row.get("licenseKey")), official=_bool(row.get("isGoogleOwned")) is True,
                         manifest=row, popularity={"stars": stars} if stars is not None else {},
                         install={"gemini_extension": {"url": row["url"]}},
                         metadata={"source_updated_at": row.get("lastUpdated") or row.get("updatedAt"),
                                   "author": key.split("/", 1)[0] if "/" in key else None, "stars_scope": "repo",
                                   "has_mcp": _bool(row.get("hasMCP")), "has_hooks": _bool(row.get("hasHooks")),
                                   "has_skills": _bool(row.get("hasSkills")), "has_context": _bool(row.get("hasContext"))})
            yield Record(native_id=key, resource=r, raw=row)

    def _clawhub(self, checkpoint, state):
        params = {"limit": 100}
        if self.source.config.get("sort"):
            params["sort"] = str(self.source.config["sort"])
        if checkpoint.get("cursor"):
            params["cursor"] = checkpoint["cursor"]
        data = self.http.json(self.source.url + "?" + urlencode(params))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("invalid_clawhub_page")
        records = []
        for row in data["items"]:
            owner, slug = row.get("ownerHandle"), row.get("slug")
            if not owner or not slug:
                raise ValueError("missing_clawhub_owner_identity")
            native_id = owner + "/" + slug
            version = row.get("latestVersion") or {}
            stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
            popularity = {key: value for key, value in (
                ("installs", next((v for v in map(_int, (stats.get("installs"), stats.get("installsAllTime"),
                                                         stats.get("installsCurrent"))) if v is not None), None)),
                ("downloads", _int(stats.get("downloads"))), ("stars", _int(stats.get("stars")))) if value is not None}
            r = Resource(item_id="clawhub:" + native_id, type="skill", name=row.get("displayName") or slug,
                         summary=str(row.get("summary") or "")[:12000], url=f"https://clawhub.ai/{owner}/skills/{slug}",
                         version=version.get("version"), popularity=popularity, manifest=row,
                         agents=sorted(set(SKILL_AGENTS) | set(self.source.config.get("agents", []))),
                         license=normalize_license(row.get("license")),
                         metadata={"resolution": "registry_metadata", "author": owner, "installs_scope": "item",
                                   "source_updated_at": row.get("updatedAt")})
            records.append(Record(native_id=native_id, resource=r, raw=row))
        cursor = data.get("nextCursor")
        if cursor and cursor == checkpoint.get("cursor"):
            raise ValueError("clawhub_cursor_did_not_advance")
        count = int(checkpoint.get("count", 0)) + len(records)
        limit = int(self.source.config.get("max_items", CLAWHUB_MAX_ITEMS))
        return Page(records=records, complete=not bool(cursor) or count >= limit, checkpoint={"cursor": cursor, "count": count})


    def _awesome(self, state):
        """An awesome-list README: one metadata-only item per ``- [name](https://github.com/o/r) … - text`` line.

        Only the link, the list's category heading, legend emojis and the one-line description are
        kept (the list's own text, under the list's license); nothing from the linked repository is
        read, so ``verification`` is ``listed_only`` and the recommender's source gate rejects it.
        """
        text = self.http.get(self.source.url).decode("utf-8")
        revision = digest(text)
        if revision == state.get("revision"):
            return Page(records=[], complete=True, mode="incremental", revision=revision)
        kind = self.source.config.get("type", "mcp_server")
        agents = list(self.source.config.get("agents", []))
        records, seen = [], set()
        for entry in awesome_entries(text, self.source.config.get("section")):
            native_id = entry["repo"].lower()
            if native_id in seen:
                continue  # A server listed under two categories is one item; the first category wins.
            seen.add(native_id)
            features = [Feature(feature="category", value=entry["category"][:256], origin="declared",
                                evidence="awesome list heading")] if entry["category"] else []
            features += [Feature(feature="language", value=v, origin="declared", evidence="awesome list legend")
                         for v in entry["languages"]]
            if entry["scope"]:
                features.append(Feature(feature="transport", value="remote" if entry["scope"] == "cloud" else "stdio",
                                        origin="declared", evidence="awesome list legend"))
            r = Resource(item_id=f"{kind}:awesome:github.com/{native_id}", type=kind, name=entry["name"][:300],
                         summary=entry["summary"][:12000], url="https://github.com/" + entry["repo"], agents=agents,
                         features=features,
                         # 🎖️ = "official implementation" by the integrated service's vendor, which is not
                         # the catalog's ``official`` (published by an agent vendor's own source).
                         metadata={"verification": "listed_only", "resolution": "repository_pointer",
                                   "vendor_official": entry["official"],
                                   "list": self.source.url, "category": entry["category"],
                                   "author": entry["repo"].split("/")[0]})
            records.append(Record(native_id=native_id, resource=r, raw=entry))
        return Page(records=records, complete=True, revision=revision)

    def _github_topic(self, checkpoint, state):
        """GitHub repository search by topic (``config.topics``), most-starred first, one repo = one item.

        Search allows 30 requests/min with a token and 10 without, and returns at most 1000 results
        per query (docs.github.com "REST API endpoints for search"); calls are spaced by
        ``config.min_interval`` (default 2.1 s) and capped at ``config.max_pages`` pages per topic.
        Repository metadata only: description, topics, license, stars, push date.
        """
        topics = [t for t in self.source.config.get("topics") or [] if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", str(t))]
        if not topics:
            raise ValueError("github_topic_without_topics")
        index, page = int(checkpoint.get("topic", 0)), int(checkpoint.get("page", 1))
        max_pages = min(10, int(self.source.config.get("max_pages", 10)))
        per_page = min(100, int(self.source.config.get("per_page", 100)))
        wait = float(self.source.config.get("min_interval", GITHUB_SEARCH_INTERVAL)) - (time.monotonic() - self._last_search)
        if wait > 0:
            time.sleep(wait)
        topic = topics[index]
        query = urlencode({"q": f"topic:{topic} archived:false", "sort": "stars", "order": "desc",
                           "per_page": per_page, "page": page})
        data = self.http.json("https://api.github.com/search/repositories?" + query)
        self._last_search = time.monotonic()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("invalid_github_search_page")
        kind = self.source.config.get("type", "skill")
        min_stars = int(self.source.config.get("min_stars", 0))
        records = []
        for repo in data["items"]:
            name, stars = repo.get("full_name"), _int(repo.get("stargazers_count"))
            if not isinstance(name, str) or "/" not in name or repo.get("fork") or (stars or 0) < min_stars:
                continue
            license_id = normalize_license(((repo.get("license") or {}).get("spdx_id") or "").replace("NOASSERTION", ""))
            repo_topics = [str(t)[:256] for t in repo.get("topics") or []][:30]
            r = Resource(item_id=f"{kind}:topic:github.com:{repo.get('id')}", type=kind, name=repo.get("name") or name,
                         summary=str(repo.get("description") or "")[:12000], url=repo.get("html_url") or "https://github.com/" + name,
                         license=license_id, agents=_topic_agents(repo_topics, self.source.config.get("agents", [])),
                         repo_id=str(repo.get("id")), popularity={"stars": stars} if stars is not None else {},
                         features=[Feature(feature="topic", value=t, origin="declared", evidence="GitHub topics") for t in repo_topics],
                         metadata={"verification": "repository_metadata", "resolution": "repository", "author": name.split("/")[0],
                                   "source_updated_at": repo.get("pushed_at"), "stars_scope": "repo", "topic": topic,
                                   "repository": name})
            records.append(Record(native_id=name.lower(), resource=r, raw={k: repo.get(k) for k in (
                "full_name", "id", "description", "topics", "stargazers_count", "pushed_at", "html_url")}))
        total = min(int(data.get("total_count") or 0), 1000)
        last_page = page >= max_pages or page * per_page >= total or not data["items"]
        if last_page and index + 1 >= len(topics):
            return Page(records=records, complete=True)
        nxt = {"topic": index + 1, "page": 1} if last_page else {"topic": index, "page": page + 1}
        return Page(records=records, complete=False, checkpoint=nxt)


GITHUB_SEARCH_INTERVAL = 2.1  # 60 s / 30 authenticated search requests, plus margin.
# GitHub topics that name an agent; a repository that tags itself is the publisher's declaration.
TOPIC_AGENTS = {"claude-code": "claude_code", "codex": "codex", "openai-codex": "codex",
                "cursor": "cursor", "gemini-cli": "gemini", "opencode": "opencode", "github-copilot": "copilot",
                "hermes-agent": "hermes", "deepseek-harness": "dsh", "dsh": "dsh", "kimi-cli": "kimi", "pi-agent": "pi"}


def _topic_agents(topics, configured) -> list[str]:
    return sorted(set(configured) | {TOPIC_AGENTS[t] for t in topics if t in TOPIC_AGENTS})


_AWESOME_ENTRY = re.compile(r"^\s*[-*]\s+\[([^\]]+)\]\(https://github\.com/([\w.-]+/[\w.-]+?)/?\)(.*)$")
_BADGE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)|!\[[^\]]*\]\([^)]*\)")
# punkpeye/awesome-mcp-servers README "Legend".
AWESOME_LANGUAGES = {"🐍": "python", "📇": "typescript", "🏎️": "go", "🦀": "rust", "#️⃣": "csharp", "☕": "java",
                     "🌊": "c++", "💎": "ruby"}


def awesome_entries(text: str, section: str | None = None) -> list[dict]:
    """Parse list entries; with ``section``, only under the ``## <section>`` heading until the next ``## ``."""
    out, inside, category = [], section is None, ""
    for line in text.splitlines():
        heading = re.match(r"^(#{2,4})\s+(.*)$", line)
        if heading:
            title = re.sub(r"<[^>]+>", "", heading.group(2)).strip()
            if len(heading.group(1)) == 2 and section is not None:
                inside = title.casefold() == section.casefold()
            category = re.sub(r"^[^\w(]+", "", title).strip() if len(heading.group(1)) > 2 else ""
            continue
        match = _AWESOME_ENTRY.match(line) if inside else None
        if not match:
            continue
        rest = _BADGE.sub("", match.group(3))
        marks, _, summary = rest.partition(" - ")
        out.append({"name": match.group(1).strip(), "repo": match.group(2).removesuffix(".git"),
                    "summary": summary.strip(), "category": category, "official": "🎖️" in marks,
                    "languages": [v for k, v in AWESOME_LANGUAGES.items() if k in marks],
                    "scope": "cloud" if "☁️" in marks else "local" if "🏠" in marks else None})
    return out


def safe_path(path: str) -> str:
    path = path.removeprefix("./")
    if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path or re.search(r"[\x00-\x1f]", path):
        raise ValueError("invalid_repository_path")
    return path


def _known_model_ids(known: dict) -> set[str]:
    """Canonical ids of stored model resources passed by sync as `state['known']`."""
    ids = set()
    for value in known.values():
        resource = value.get("resource") if isinstance(value, dict) else value[1] if isinstance(value, (tuple, list)) else value
        metadata = resource.get("metadata") if isinstance(resource, dict) else getattr(resource, "metadata", None)
        if isinstance(metadata, dict) and metadata.get("canonical_id"):
            ids.add(metadata["canonical_id"])
    return ids


# -- Orbit official entries (recommend KB remedies.v1.json -> catalog shape) ------------------
KB_TYPES = {"hook": "hook", "skill": "skill", "rule": "rule", "flow": "workflow", "mcp": "mcp_server",
            "agent": "subagent", "model": "guide"}
KB_LICENSE = "MIT"


def _hook_event(template: str | None) -> str | None:
    """'hook-post-tool-use@1' -> 'PostToolUse'; 'hook-stop@1' -> 'Stop'."""
    if not template or not template.startswith("hook-"):
        return None
    return "".join(part.capitalize() for part in template.removeprefix("hook-").split("@")[0].split("-"))


def _hook_install(rule: dict) -> dict | None:
    remedy = rule.get("remedy") or {}
    if remedy.get("kind") != "hook":
        return None
    event, matcher, command = _hook_event(remedy.get("template")), None, None
    text = "".join(line for line, _ in rule.get("file") or [])
    try:
        hooks = json.loads(text).get("hooks") if text else None
    except ValueError:
        hooks = None
    if isinstance(hooks, dict) and hooks:
        event, groups = next(iter(hooks.items()))
        group = groups[0] if isinstance(groups, list) and groups else {}
        matcher = group.get("matcher")
        command = ((group.get("hooks") or [{}])[0]).get("command")
    if not event:
        return None
    hook = {"event": event, "command": command or f"~/.orbit/hooks/{rule['id']}.sh"}
    if matcher:
        hook["matcher"] = matcher
    return hook


def _kb_body(rule: dict) -> str:
    """Library body of a KB rule: title/summary in listing wording, slots elsewhere as 〈wording〉."""
    explain = rule.get("explain") or {}
    parts = [f"# {listing_text(rule['title'])}", listing_text(rule.get("summary", ""))]
    for heading, key in (("原理", "mechanism"), ("试用", "trial"), ("局限", "limitation")):
        if explain.get(key):
            parts += [f"## {heading}", body_text(explain[key])]
    if rule.get("steps"):
        parts += ["## 步骤", "\n".join(f"{i}. {body_text(step)}" for i, step in enumerate(rule["steps"], 1))]
    if rule.get("file"):
        parts += ["## 改动预览", "```json\n" + "\n".join(body_text(line) for line, _ in rule["file"]) + "\n```"]
    return "\n\n".join(p for p in parts if p)


# Static wording for session-specific slots in KB titles/summaries. The library lists these rules
# as general resources, so a public name must read without a session; the template survives in
# metadata (``title_template`` / ``summary_template``) for the recommendation renderer.
LISTING_SLOTS = {"software": "所用软件", "instruction": "", "build_command": "构建命令"}
_SLOT = re.compile(r"\{([a-z_]+)\}")
_FILLED_SLOT = re.compile(r"( ?)\{([a-z_]+)\}( ?)")


def listing_text(template: str) -> str:
    """KB title/summary with every ``{slot}`` replaced by its static wording; unknown slots fail export.

    Spaces that only separated the slot from Han text go away ("运行 {build_command}" -> "运行构建命令");
    an empty wording also drops a dangling "：".
    """
    def fill(match):
        if match.group(2) not in LISTING_SLOTS:
            raise ValueError(f"kb_slot_without_listing_text:{match.group(2)}")
        value = LISTING_SLOTS[match.group(2)]
        before, after = match.string[:match.start()], match.string[match.end():]
        left = match.group(1) if value and before[-1:].isascii() and before[-1:].isalnum() else ""
        right = match.group(3) if value and after[:1].isascii() and after[:1].isalnum() else ""
        return left + value + right
    return _FILLED_SLOT.sub(fill, template).rstrip("：: ")


# Body slots stay visible as a marked blank ("〈所用软件〉"): the preview shows where a session value
# goes without printing raw template syntax. Unknown slots fail export like listing_text.
BODY_SLOTS = {"software": "所用软件", "instruction": "你反复提出的要求", "build_command": "构建命令",
              "sequence": "固定步骤序列", "platforms": "部署平台", "project": "项目名"}


def body_text(template: str) -> str:
    def fill(match):
        if match.group(1) not in BODY_SLOTS:
            raise ValueError(f"kb_slot_without_listing_text:{match.group(1)}")
        return "〈" + BODY_SLOTS[match.group(1)] + "〉"
    return _SLOT.sub(fill, template)


def official_entries(kb: dict) -> list[dict]:
    """Export recommend KB rules (``remedies-v1``) as catalog-shaped official entries."""
    if not isinstance(kb, dict) or not isinstance(kb.get("rules"), list):
        raise ValueError("invalid_kb_catalog")
    entries = []
    for rule in kb["rules"]:
        remedy, problem = rule.get("remedy") or {}, rule.get("problem") or {}
        kind = "guide" if remedy.get("kind") == "removal" else KB_TYPES.get(remedy.get("dim"), "guide")
        features = [{"feature": "friction", "value": value, "origin": "curated", "evidence": "Orbit KB problem type"}
                    for value in problem.get("types", [])]
        features += [{"feature": "dimension", "value": remedy["dim"], "origin": "curated", "evidence": "Orbit KB"}] \
            if remedy.get("dim") else []
        features += [{"feature": "scene", "value": value, "origin": "curated", "evidence": "Orbit KB gate"}
                     for value in (rule.get("gates") or {}).get("scenes") or []]
        features += [{"feature": "tag", "value": value, "origin": "curated", "evidence": "Orbit KB tag"}
                     for value in rule.get("tags", [])]
        install = {"kb_rule": rule["id"]}
        if remedy.get("template"):
            install["template"] = remedy["template"]
        if hook := _hook_install(rule):
            install["hook"] = hook
        agents = remedy.get("agents") or {"claude_code": "native", "codex": "manual"}
        risk = rule.get("risk") or {}
        entries.append({
            "id": rule["id"], "type": kind, "name": listing_text(rule["title"]),
            "summary": listing_text(rule.get("summary", "")),
            "official": True, "agents": [a for a, support in agents.items() if support != "unsupported"],
            "install": install, "features": features, "license": KB_LICENSE, "difficulty": remedy.get("level", 2),
            "version": str(rule.get("version", 1)), "body": _kb_body(rule), "risk": list(risk.get("flags", [])),
            "metadata": {"origin": "orbit-kb", "kb_rule": rule["id"], "remedy_kind": remedy.get("kind"),
                         "dim": remedy.get("dim"), "agent_support": agents, "risk_level": risk.get("level", "low"),
                         "cost": rule.get("cost") or {}, "catalog_ref": rule.get("catalog_ref"),
                         "explain": rule.get("explain") or {}, "track": rule.get("track") or {},
                         "problem_types": problem.get("types", []),
                         **({"title_template": rule["title"]} if _SLOT.search(rule["title"]) else {}),
                         **({"summary_template": rule["summary"]} if _SLOT.search(rule.get("summary", "")) else {})},
        })
    return entries


def official_resource(entry: dict) -> Resource:
    return Resource(item_id="kb:" + entry["id"], type=entry["type"], name=entry["name"], summary=entry.get("summary", ""),
                    url="", body=entry.get("body", ""), body_policy="licensed", license=entry.get("license", KB_LICENSE),
                    agents=entry.get("agents", []), official=True, difficulty=entry.get("difficulty", 2),
                    version=entry.get("version"), features=[Feature.model_validate(f) for f in entry.get("features", [])],
                    install=entry.get("install", {}), risk=entry.get("risk", []),
                    metadata=entry.get("metadata", {"origin": "orbit-kb", "kb_rule": entry["id"]}))
