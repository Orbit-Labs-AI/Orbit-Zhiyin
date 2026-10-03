"""Artifact adapters (A9-17 / A9-18): write a generated artifact's files where the host can
open them, and add an artifact that passed its self-check to the local catalog library.

``materialize`` writes ``files[].content`` to ``<home>/exports/artifacts/<id>/<name>``
(directory 0700, files 0600). Names are the last segment of each file target, made safe;
it is idempotent and never writes outside that directory. ``to_library`` upserts a catalog
local item (kind mapping below; ``glue`` becomes a ``workflow``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import AIError

LIBRARY_KIND = {"hook": "hook", "rule": "rule", "skill": "skill", "subagent": "subagent",
                "command": "command", "glue": "workflow", "workflow": "workflow"}
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _name(target: str) -> str:
    last = re.split(r"[/#\\]", str(target or ""))[-1]
    name = _SAFE.sub("_", last).strip("._") or "file"
    if name in (".", "..") or ".." in name.split("/"):
        raise AIError(422, "invalid_request", "产物文件名不合法")
    return name[:120]


def _names(files: list[dict]) -> list[str]:
    """Unique basenames; a collision is prefixed with the target's first segment."""
    out: list[str] = []
    for index, file in enumerate(files):
        target = str(file.get("target") or file.get("path") or "")
        name = _name(target)
        if name in out:
            head = _SAFE.sub("_", re.split(r"[/#\\]", target)[0]).strip("._") or f"f{index}"
            name = f"{head}-{name}"[:120]
        while name in out:
            name = f"{index}-{name}"[:120]
        out.append(name)
    return out


def materialize(artifact: dict, home: Path) -> dict:
    artifact_id = artifact["artifact_id"]
    if not _ID.match(artifact_id):
        raise AIError(422, "invalid_request", "artifact_id 不合法")
    base = (home / "exports" / "artifacts").resolve()
    folder = base / artifact_id
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.mkdir(exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    files = [f for f in artifact.get("files") or [] if isinstance(f, dict)]
    written = []
    for file, name in zip(files, _names(files), strict=True):
        path = folder / name
        if path.parent != folder or path.is_symlink():
            raise AIError(422, "invalid_request", "产物文件名不合法")
        content = str(file.get("content") or "")
        data = content.encode()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(path, 0o600)
        written.append({"target": file.get("target"), "path": str(path), "bytes": len(data)})
    return {"artifact_id": artifact_id, "dir": str(folder), "files": written}


def self_check(artifact: dict) -> dict:
    checks = artifact.get("checks") or {}
    lint = (checks.get("lint") or {}).get("status")
    scan = (checks.get("scan") or {}).get("status")
    return {"passed": lint != "fail" and scan == "ok", "checks": checks}


def library_item(artifact: dict) -> dict:
    kind = LIBRARY_KIND.get(artifact.get("kind") or "")
    if kind is None:
        raise AIError(422, "invalid_request", f"产物类型 {artifact.get('kind')} 不能加入资料库")
    files = [f for f in artifact.get("files") or [] if isinstance(f, dict)]
    body = "\n\n".join(str(f.get("content") or "") for f in files).strip()
    if not body:
        raise AIError(422, "invalid_request", "产物没有文件内容")
    check = self_check(artifact)
    if not check["passed"]:
        raise AIError(409, "self_check_failed", "产物自检未通过，不能加入资料库")
    payload = artifact.get("payload") or {}
    return {"kind": kind, "name": artifact.get("title") or artifact.get("name") or kind,
            "summary": artifact.get("goal") or "", "body": body,
            "agents": [a for a in payload.get("agents") or [] if isinstance(a, str)][:30],
            "template_id": artifact.get("template_id"), "job_id": artifact.get("job_id"),
            "self_check": check}


def to_library(artifact: dict, catalog) -> dict:
    """``catalog`` is a ``orbit_catalog`` CatalogService; returns {item_id, created}."""
    result = catalog.add_local(library_item(artifact))
    return {"item_id": result["item_id"], "created": bool(result.get("created"))}
