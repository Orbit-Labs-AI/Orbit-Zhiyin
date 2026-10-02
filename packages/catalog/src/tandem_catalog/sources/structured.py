"""Public registries, model catalogs and benchmark snapshots."""

import json
import math
import re
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


class StructuredConnector:
    def __init__(self, source, http):
        self.source, self.http = source, http
        self.known_models: set[str] = set()

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
            rows = json.loads(files("tandem_catalog").joinpath("data/skills.json").read_text())
            records = []
            for row in rows:
                features = [Feature(feature=key, value=value, origin="curated", evidence="Tandem reviewed seed")
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
        if self.source.kind == "mcp":
            return self._mcp(checkpoint, state)
        if self.source.kind == "clawhub":
            return self._clawhub(checkpoint, state)
        data = self._load() if self.source.kind in FILE_KINDS else self.http.json(self.source.url)
        revision = digest(data)
        if revision == state.get("revision"):
            return Page(records=[], complete=True, mode="incremental", revision=revision)
        self.known_models = set(state.get("known_models") or ()) | _known_model_ids(state.get("known") or {})
        parser = getattr(self, "_" + self.source.kind)
        return Page(records=list(parser(data)), complete=True, revision=revision)

    def _mcp(self, checkpoint, state):
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
