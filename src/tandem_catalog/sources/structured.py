"""Public registries, model catalogs and benchmark snapshots."""

import re
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from urllib.parse import urlencode

from ..contracts import Feature, Page, Record, Resource, digest


class StructuredConnector:
    def __init__(self, source, http):
        self.source, self.http = source, http

    def fetch_page(self, checkpoint: dict, state: dict) -> Page:
        if self.source.kind == "bundle":
            import json
            rows = json.loads(files("tandem_backend").joinpath("data/skills.json").read_text())
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
        data = self.http.json(self.source.url)
        revision = digest(data)
        if revision == state.get("revision"):
            return Page(records=[], complete=True, mode="incremental", revision=revision)
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
            # Registry inclusion/namespace validation is not vendor endorsement.
            r = Resource(item_id="mcp:" + name, type="mcp_server", name=server.get("title") or name,
                         summary=server.get("description", "")[:12000], version=server.get("version"),
                         url=server.get("websiteUrl") or server.get("repository", {}).get("url") or self.source.url,
                         manifest=server, license="CC0-1.0 (registry metadata)", agents=["claude_code", "codex", "copilot", "gemini", "opencode"],
                         status=status if status in ("active", "deprecated", "deleted") else "deprecated",
                         risk=["external_tools"], metadata={"registry_status": status})
            records.append(Record(native_id=name, resource=r, raw=entry))
        cursor = data["metadata"].get("nextCursor")
        if cursor and cursor == checkpoint.get("cursor"):
            raise ValueError("mcp_cursor_did_not_advance")
        # Empty registry has no provider clock; the bounded overlap covers the initial scan time.
        maximum = maximum or scan_started_at
        # Never advance past the scan start: updates behind the pagination cursor must
        # be eligible next time, even when a full scan takes longer than the overlap.
        committed = min(datetime.fromisoformat(maximum.replace("Z", "+00:00")), datetime.fromisoformat(scan_started_at)).isoformat()
        return Page(records=records, complete=not bool(cursor), mode=mode, watermark=committed,
                    checkpoint={"cursor": cursor, "watermark": maximum, "scan_started_at": scan_started_at}, revision=maximum)

    def _models_dev(self, data):
        if not isinstance(data, dict) or not data:
            raise ValueError("invalid_models_catalog")
        for provider, info in data.items():
            if not isinstance(info, dict) or not isinstance(info.get("models"), dict):
                raise ValueError("invalid_model_provider")
            for model_id, model in info["models"].items():
                key = provider + "/" + model_id
                r = Resource(item_id="model:models.dev:" + key, type="model", name=model.get("name") or model_id,
                             summary=str(model.get("description") or "")[:12000], url=info.get("doc") or "https://models.dev",
                             manifest=model, metadata={"provider": provider, "model_id": model_id, "pricing_source": "models.dev"},
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
            provider = model.get("litellm_provider", "unknown")
            r = Resource(item_id="model:litellm:" + key, type="model", name=key, url=self.source.url,
                         summary=f"{provider} model pricing and capabilities", manifest=model,
                         metadata={"provider": provider, "model_id": key, "pricing_source": "litellm",
                                   "price_unit": "USD/token", "canonical_identity": "unresolved"})
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
                manifest = {"model_id": model, "effort": row.get("reasoning_effort"), "harness": row.get("agent"),
                            "benchmark": "SWE-bench", "benchmark_version": name, "measured_at": row.get("date"),
                            "score": row.get("resolved"), "unit": "percent", "source_result": row}
                site = row.get("site")
                if isinstance(site, list):
                    site = next((url for url in site if isinstance(url, str) and url), None)
                r = Resource(item_id="benchmark:swe:" + digest(identity), type="benchmark", name=str(model)[:300],
                             url=site if isinstance(site, str) and site else "https://www.swebench.com/",
                             summary=f"SWE-bench {name}", manifest=manifest)
                yield Record(native_id=digest(identity), resource=r, raw=row)

    def _gemini(self, data):
        if not isinstance(data, list):
            raise ValueError("invalid_gemini_catalog")
        for row in data:
            key = row["fullName"]
            r = Resource(item_id="gemini-extension:" + key, type="plugin", name=row.get("extensionName") or key,
                         summary=(row.get("extensionDescription") or row.get("repoDescription") or "")[:12000],
                         url=row["url"], agents=["gemini"], version=row.get("extensionVersion"),
                         license=row.get("licenseKey"), official=bool(row.get("isGoogleOwned")), manifest=row)
            yield Record(native_id=key, resource=r, raw=row)

    def _clawhub(self, checkpoint, state):
        params = {"limit": 100}
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
            r = Resource(item_id="clawhub:" + native_id, type="skill", name=row.get("displayName") or slug,
                         summary=str(row.get("summary") or "")[:12000], url=f"https://clawhub.ai/{owner}/skills/{slug}",
                         version=version.get("version"), popularity=row.get("stats") or {}, manifest=row,
                         metadata={"resolution": "registry_metadata"})
            records.append(Record(native_id=native_id, resource=r, raw=row))
        cursor = data.get("nextCursor")
        if cursor and cursor == checkpoint.get("cursor"):
            raise ValueError("clawhub_cursor_did_not_advance")
        return Page(records=records, complete=not bool(cursor), checkpoint={"cursor": cursor})


def safe_path(path: str) -> str:
    path = path.removeprefix("./")
    if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path or re.search(r"[\x00-\x1f]", path):
        raise ValueError("invalid_repository_path")
    return path
