"""Resource metadata is distinct from unmeasured effectiveness.

The bundled catalog is a reproducible offline seed. An explicit refresh can provide
newer source verification without allowing remote text to alter capability tags.
"""

import json
import re
from importlib.resources import files
from pathlib import Path

MAX_CACHE_BYTES = 2_000_000


def _cached_updates(path: Path) -> dict[str, dict]:
    """Reject malformed metadata as a whole instead of trusting partial verification."""
    if path.stat().st_size > MAX_CACHE_BYTES:
        raise ValueError("资源缓存过大")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("资源缓存格式不支持")
    rows = payload.get("resources")
    if not isinstance(rows, list):
        raise ValueError("资源缓存缺少列表")
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in by_id:
            raise ValueError("资源缓存含无效或重复条目")
        for field, length in (("verified_sha", 40), ("blob_sha", 40), ("content_sha256", 64)):
            value = row.get(field)
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value)):
                raise ValueError("资源版本校验字段无效")
        for field in ("source_description", "verified_at", "verification", "source_status", "license", "last_error"):
            if row.get(field) is not None and not isinstance(row[field], str):
                raise ValueError("资源元数据字段无效")
        by_id[row["id"]] = row
    return by_id


def resources(cache_file: str | Path | None = None) -> list[dict]:
    seeds = json.loads(files("tandem_catalog").joinpath("data/skills.json").read_text())
    if not cache_file or not Path(cache_file).is_file():
        return seeds
    try:
        by_id = _cached_updates(Path(cache_file))
    except (OSError, ValueError, UnicodeError):
        # A corrupt optional cache must not prevent offline analysis or masquerade as fresh.
        return [{**seed, "source_status": "cache_invalid", "last_error": "invalid_local_cache"} for seed in seeds]
    output = []
    for seed in seeds:
        update = by_id.get(seed["id"], {})
        # Trusted local tags remain authoritative. Cached source text is not an instruction.
        output.append({**seed, **{k: update[k] for k in (
            "verified_sha", "blob_sha", "content_sha256", "source_description", "verified_at",
            "verification", "source_status", "license", "last_error") if k in update}})
    return output


def skills() -> list[dict]:
    """Compatibility name for callers interested in the whole recommendation catalog."""
    return resources()
