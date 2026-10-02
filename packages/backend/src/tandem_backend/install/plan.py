"""RC-12 plan builder: turn a candidate, catalog item, AI artifact or direct spec into an
InstallSpec, resolve its landing targets (IN-01) and store the plan in ``app.db``.

Other modules are reached only through ``app.db`` tables or lazy imports with a fallback:
install never imports recommend/ai code to build a plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import PurePosixPath

from . import store
from . import targets as targets_mod
from .env import FULL_SUPPORT, inventory_names
from .errors import PlanError
from .fetch import FetchError, fetch_source, read_tree
from .templates import READONLY_ALLOWLIST, render_template

REQUIRED = {"permission_rule": ("allow",), "rule": ("text",), "skill": ("name", "files"),
            "subagent": ("name", "text"), "command": ("name", "text"), "hook": ("event", "command"),
            "mcp": ("name",), "plugin": ("plugin", "marketplace"), "setting": ("settings",)}
FILE_KINDS = ("skill", "subagent", "command", "rule")
INVENTORY_KIND = {"skill": "skill", "mcp": "mcp", "hook": "hook", "plugin": "plugin", "rule": "rule"}
SUMMARY_KEYS = ("idx", "agent", "scope", "display", "action", "mappable", "reason", "requires_trust",
                "shared_layer", "note", "group")


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-")[:64].strip("-")
    return out or "item"


# ---- spec validation ----------------------------------------------------------------------------

def validate_spec(spec: dict) -> dict:
    """Check kind/slug/payload fields and fill defaults. Raises ``invalid_spec`` (422)."""
    if not isinstance(spec, dict):
        raise PlanError("invalid_spec", "spec 必须是对象")
    kind = spec.get("kind")
    if kind not in REQUIRED:
        raise PlanError("invalid_spec", f"未知 kind：{kind!r}")
    sid = spec.get("id")
    if not isinstance(sid, str) or not targets_mod.SLUG.fullmatch(sid):
        raise PlanError("invalid_spec", f"id 须匹配 [a-z0-9][a-z0-9-]{{0,63}}：{sid!r}")
    payload = spec.get("payload")
    if not isinstance(payload, dict):
        raise PlanError("invalid_spec", "payload 必须是对象")
    missing = [f for f in REQUIRED[kind] if payload.get(f) in (None, "", [], {})]
    if kind == "mcp" and not (payload.get("command") or payload.get("url")):
        missing.append("command|url")
    if missing:
        raise PlanError("invalid_spec", f"{kind} 缺少字段：{', '.join(missing)}", detail={"missing": missing})
    source = {"type": "spec", "id": None, "template": None, "license": None, "sha256": None,
              **(spec.get("source") or {})}
    return {"title": spec.get("title") or sid, "agents": spec.get("agents") or None,
            "scope": spec.get("scope") or "user", "project_path": spec.get("project_path"),
            "ai_ranges": spec.get("ai_ranges"), "evidence_refs": list(spec.get("evidence_refs") or []),
            **{k: v for k, v in spec.items() if v is not None and k != "source"}, "kind": kind, "id": sid,
            "payload": payload, "source": source}


# ---- catalog --------------------------------------------------------------------------------------

def _license(value) -> dict | None:
    if isinstance(value, dict):
        return value if value.get("spdx") or value.get("status") else None
    if isinstance(value, str) and value and value not in ("NOASSERTION", "NONE"):
        return {"spdx": value, "status": "ok"}
    return None


def _legacy_item(entry: dict) -> dict:
    """Map a ``legacy_catalog`` seed onto the catalog item shape install expects."""
    url = entry.get("url") or ""
    repo = url.split("github.com/", 1)[1].strip("/") if "github.com/" in url else None
    kind = entry.get("kind") or "skill"
    path = entry.get("source_path") or ""
    if kind == "skill":
        path = str(PurePosixPath(path).parent) if path else ""
        path = "" if path == "." else path
    source = {"type": "github", "repo": repo, "ref": entry.get("verified_sha") or "HEAD",
              "path": path} if repo else None
    return {"id": entry["id"], "kind": kind, "name": entry.get("name") or entry["id"],
            "description": entry.get("summary"), "url": url, "source": source, "install": None,
            "license": entry.get("license"), "agents": entry.get("agents") or ["claude_code"]}


def default_catalog_lookup(item_id: str) -> dict | None:
    """``tandem_catalog`` item if that API exists, else the bundled legacy seed catalog."""
    try:
        import tandem_catalog  # noqa: PLC0415 - optional, wired later

        lookup = getattr(tandem_catalog, "item", None)
        if callable(lookup):
            found = lookup(item_id)
            if found:
                return found
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    try:
        from ..recommend.legacy_catalog import resources  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    for entry in resources():
        if entry.get("id") == item_id:
            return _legacy_item(entry)
    return None


class _Offline:
    """Fetcher used to ask "is this already cached?" without touching the network."""

    def get(self, url, **_):
        raise FetchError("needs_fetch", url, http=409)


def _from_catalog(item: dict, *, cache_dir, fetcher, allow_network: bool) -> tuple[dict, dict]:
    kind = item.get("kind")
    name = item.get("name") or item["id"]
    source = item.get("source")
    lic = _license(item.get("license"))
    base = {"kind": kind, "id": slug(item["id"]), "title": name, "agents": item.get("agents"),
            "source": {"type": "catalog", "id": item["id"], "template": None, "license": lic,
                       "sha256": (source or {}).get("sha256")}}
    install = item.get("install") or {}
    if kind in ("mcp", "plugin", "hook"):
        payload = install.get(kind) if isinstance(install, dict) else None
        if not isinstance(payload, dict):
            raise PlanError("catalog_not_installable", f"目录条目 {item['id']} 没有 {kind} 安装声明")
        return {**base, "payload": dict(payload)}, {"status": "ready"}
    if kind not in FILE_KINDS:
        raise PlanError("catalog_not_installable", f"不支持的目录条目类型：{kind!r}")
    link = {"links": [item.get("url")] if item.get("url") else []}
    if not source:
        return {**base, "payload": {}, **link}, {"status": "link_only"}
    if lic is None or lic.get("status") == "link_only":
        return {**base, "payload": {}, **link}, {"status": "link_only"}
    try:
        fetched = fetch_source(source, cache_dir=cache_dir, fetcher=fetcher if allow_network else _Offline())
    except FetchError as error:
        if error.code == "needs_fetch":
            return {**base, "payload": {}}, {"status": "needs_fetch"}
        raise
    if fetched.get("link_only") and not lic:
        return {**base, "payload": {}, **link}, {"status": "link_only"}
    skipped: list[str] = []
    tree = read_tree(cache_dir, fetched["tree_sha256"], skipped)
    base["source"]["sha256"] = "sha256:" + fetched["tree_sha256"]
    if kind == "skill":
        files = [{"rel": rel, "text": text} for rel, text in sorted(tree.items())]
        payload = {"name": targets_mod.safe_name(name) if targets_mod.NAME.fullmatch(name) else slug(name),
                   "files": files}
    else:
        rel = PurePosixPath(source.get("path") or "").name
        text = tree.get(rel) if rel in tree else (next(iter(tree.values())) if len(tree) == 1 else None)
        if text is None:
            raise PlanError("catalog_not_installable", "目录条目来源不是单个文本文件")
        payload = {"text": text, "heading": name} if kind == "rule" else {"name": slug(name), "text": text}
    return {**base, "payload": payload}, {"status": "ready", "fetch": fetched, "skipped": skipped}


# ---- sources --------------------------------------------------------------------------------------

def _row(appdb, sql: str, params, missing_code: str) -> dict | None:
    try:
        with appdb.read() as db:
            row = db.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        raise PlanError(missing_code, f"{missing_code}", http=404) from None
    return dict(row) if row is not None else None


def _json(value):
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _rec_candidate_row(appdb, sid) -> dict | None:
    """Recommend's persisted candidate: install hints live inside the JSON ``card``."""
    try:
        row = _row(appdb, "SELECT * FROM rec_candidate WHERE candidate_id = ?", (sid,), "recommend_unavailable")
    except PlanError:
        raise PlanError("recommend_unavailable", "推荐候选不可用", http=404) from None
    if row is None:
        return None
    card = _json(row.get("card")) or {}
    for key in ("install_spec", "remedy_rule", "template", "template_params", "catalog_item_id",
                "target_agents", "scope"):
        if key in card and key not in row:
            row[key] = json.dumps(card[key]) if isinstance(card[key], (dict, list)) else card[key]
    return row


def build_spec(source: dict, *, appdb, catalog_lookup=None, cache_dir, fetcher=None,
               allow_network: bool = False) -> tuple[dict, dict]:
    """Return ``(spec, extra)``; ``extra['status']`` is ready | needs_fetch | link_only."""
    stype = (source or {}).get("type")
    sid = source.get("id")
    if stype == "spec":
        return validate_spec(source.get("spec")), {"status": "ready"}
    if stype == "candidate":
        try:
            row = _row(appdb, "SELECT * FROM candidate WHERE candidate_id = ?", (sid,), "recommend_unavailable")
        except PlanError:
            row = None
        if row is None:
            row = _rec_candidate_row(appdb, sid)
        if row is None:
            raise PlanError("not_found", f"候选不存在：{sid}", http=404)
        agents = _json(row.get("target_agents"))
        spec = _json(row.get("install_spec"))
        template = row.get("remedy_rule") or row.get("template")
        extra = {"status": "ready"}
        if isinstance(spec, dict) and spec:
            spec = {**spec, "id": spec.get("id") or slug(sid)}
        elif template == READONLY_ALLOWLIST:
            spec = render_template(template, _json(row.get("template_params")) or {}, agents)
        elif row.get("catalog_item_id"):
            spec, extra = build_spec({"type": "catalog", "id": row["catalog_item_id"]}, appdb=appdb,
                                     catalog_lookup=catalog_lookup, cache_dir=cache_dir, fetcher=fetcher,
                                     allow_network=allow_network)
        else:
            raise PlanError("candidate_not_renderable", "候选没有可安装的规格或内置模板")
        src = {**(spec.get("source") or {}), "type": "candidate", "id": sid}
        spec = {**spec, "source": src, "title": spec.get("title") or row.get("title") or sid,
                "agents": spec.get("agents") or agents, "scope": spec.get("scope") or row.get("scope") or "user"}
        if extra["status"] != "ready":
            return spec, extra
        return validate_spec(spec), extra
    if stype == "catalog":
        item = (catalog_lookup or default_catalog_lookup)(sid)
        if not item:
            raise PlanError("catalog_unavailable", f"目录条目不可用：{sid}", http=404)
        spec, extra = _from_catalog(item, cache_dir=cache_dir, fetcher=fetcher, allow_network=allow_network)
        return (validate_spec(spec) if extra["status"] == "ready" else spec), extra
    if stype == "artifact":
        row = _row(appdb, "SELECT * FROM ai_artifact WHERE artifact_id = ?", (sid,), "artifact_unavailable")
        if row is None:
            raise PlanError("artifact_unavailable", f"AI 产物不存在：{sid}", http=404)
        body = _json(row.get("payload")) or {}
        inner = body.get("payload") if isinstance(body.get("payload"), dict) else body
        spec = {"kind": body.get("kind") or row.get("kind"), "id": slug(body.get("id") or sid),
                "title": body.get("title") or row.get("title") or sid, "agents": body.get("agents"),
                "payload": inner, "ai_ranges": body.get("ai_ranges"),
                "source": {"type": "artifact", "id": sid, "template": None, "license": None, "sha256": None}}
        return validate_spec(spec), {"status": "ready"}
    raise PlanError("invalid_source", f"未知来源类型：{stype!r}")


# ---- plan -----------------------------------------------------------------------------------------

def _default_agents(env_info: dict) -> list[str]:
    found = [a["agent"] for a in env_info.get("agents", []) if a["agent"] in FULL_SUPPORT and a.get("installed")]
    return found or ["claude_code"]


def _name(spec: dict) -> str:
    p = spec.get("payload") or {}
    return str(p.get("name") or p.get("plugin") or spec.get("id"))


def make_plan(source: dict, *, agents=None, scope: str = "user", project_path: str | None = None,
              fetch: bool = False, service) -> dict:
    spec, extra = build_spec(source, appdb=service.appdb, catalog_lookup=service.catalog_lookup,
                             cache_dir=service.cache_dir, fetcher=service.fetcher, allow_network=fetch)
    env_info = service.environment()
    spec["agents"] = list(agents or spec.get("agents") or _default_agents(env_info))
    spec["scope"] = scope or spec.get("scope") or "user"
    if spec["scope"] == "project":
        if not project_path or not os.path.isabs(project_path) or not os.path.isdir(project_path):
            raise PlanError("project_path_required", "项目作用域需要已存在的绝对目录 project_path")
        spec["project_path"] = os.path.abspath(project_path)
    else:
        spec["project_path"] = None
    status, warnings, targets = extra["status"], [], []
    if status == "ready":
        try:
            targets = targets_mod.resolve_targets(spec, env_info, env=service.env)
        except targets_mod.PlanError as error:
            raise PlanError(error.code, error.message, http=error.http) from None
        if targets and not any(t.get("mappable") for t in targets):
            status = "unmappable"
        inv = INVENTORY_KIND.get(spec["kind"])
        if inv:
            for agent in spec["agents"]:
                if _name(spec) in inventory_names(service.reads, agent, inv):
                    warnings.append(f"already_present:{inv}:{_name(spec)}")
                    break
    warnings += [f"skipped_binary:{rel}" for rel in extra.get("skipped") or []]
    spec_hash = digest({k: v for k, v in spec.items() if k not in ("agents", "scope", "project_path")})
    plan_id = "pl_" + hashlib.sha256(canonical([spec_hash, spec["agents"], spec["scope"],
                                                spec["project_path"]])).hexdigest()[:16]
    src = spec.get("source") or {}
    source_type, source_id = src.get("type") or source.get("type"), src.get("id")
    if source_type == "spec" and source_id is None:
        source_id = spec["id"]
    store.save_plan(service.appdb, {
        "plan_id": plan_id, "source_type": source_type, "source_id": source_id, "spec": spec,
        "spec_hash": spec_hash, "targets": targets, "agents": spec["agents"], "scope": spec["scope"],
        "project_path": spec["project_path"], "status": status, "warnings": warnings})
    active = store.find_active(service.appdb, source_type, source_id)
    return {"plan_id": plan_id, "status": status, "title": spec.get("title"), "kind": spec["kind"],
            "source": {"type": source_type, "id": source_id, "template": src.get("template"),
                       "license": src.get("license")},
            "agents": spec["agents"], "scope": spec["scope"], "project_path": spec["project_path"],
            "warnings": warnings, "links": spec.get("links") or [],
            "fetch": {k: extra["fetch"][k] for k in ("tree_sha256", "commit", "cached")} if extra.get("fetch") else None,
            "targets": [{k: t.get(k) for k in SUMMARY_KEYS} for t in targets],
            "already_installed": {"install_id": active["install_id"], "state": active["state"],
                                  "tracking_id": active.get("tracking_id")} if active else None}
