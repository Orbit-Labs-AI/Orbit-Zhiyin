"""Resumable, local JSONL imports of public resource dataset snapshots.

Download/Parquet conversion is an explicit preparation step. This adapter never
executes content or mistakes a compilation license for individual file rights.
"""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from ..contracts import Feature, Page, Record, Resource, digest, normalize_license
from .github import PERMISSIVE, frontmatter
from .structured import SKILL_AGENTS

MAX_LINE_BYTES = 32 * 1024 * 1024
BODY_LIMIT = 250000
MAX_BODY_LIMIT = 2000000
BULK_TYPES = {"skill", "command", "hook", "workflow", "mcp_server", "plugin"}
MAX_PROVENANCE_BYTES = 65536
MAX_MANIFEST_BYTES = 262144


def _public_url(value) -> str:
    """Keep source links as data; reject credentials and non-HTTPS schemes."""
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return ""


def _object(row: dict, key: str, limit: int) -> dict:
    value = row.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"bulk_invalid_{key}")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > limit:
        raise ValueError(f"bulk_{key}_too_large")
    return value


def _features(row: dict) -> list[Feature]:
    values = row.get("features", [])
    if not isinstance(values, list) or len(values) > 199:
        raise ValueError("bulk_invalid_features")
    result = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("bulk_invalid_feature")
        # A collected declaration is never promoted to a reviewed capability or
        # given extra ranking weight by an upstream dataset's self-assessment.
        feature = Feature.model_validate({**value, "origin": "declared", "weight": 1})
        result.append(feature)
    return result


def prepare_parquet(source: Path, destination: Path) -> dict:
    """Convert a separately downloaded snapshot to JSONL with bounded batches.

    ``pyarrow`` is only needed in the preparation environment; Catalog's runtime
    does not depend on it. The output replaces its destination only on success.
    No dataset code is loaded or executed.
    """
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise RuntimeError("bulk_preparation_requires_pyarrow") from exc
    if source.resolve() == destination.resolve():
        raise ValueError("bulk_input_equals_output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    rows, checksum = 0, hashlib.sha256()
    try:
        with temporary.open("wb") as output:
            for batch in parquet.ParquetFile(source).iter_batches(batch_size=1000):
                for row in batch.to_pylist():
                    line = (json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode()
                    if len(line) > MAX_LINE_BYTES:
                        raise ValueError("bulk_row_too_large")
                    output.write(line)
                    checksum.update(line)
                    rows += 1
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {"rows": rows, "bytes": destination.stat().st_size, "sha256": checksum.hexdigest()}


class BulkConnector:
    """SkillMD-shaped JSONL, using byte offsets rather than repeated full scans.

    Required config: absolute ``file`` and immutable ``revision``. Optional:
    ``dataset_id``, ``dataset_license`` and ``page_size`` (1..2000; default 500).
    Other libraries set ``resource_type`` and may supply ``content_license``
    with a pinned ``license_url`` for verified original-source rights. Merely
    setting ``dataset_license`` never enables licensed content or installation.
    Every JSONL row must contain nonempty ``content``; repo/path/html_url and
    content_hash preserve provenance. A full SHA256 is computed independently.
    """

    def __init__(self, source, http=None):
        self.source = source
        self.path = Path(source.config.get("file", ""))
        if not self.path.is_absolute():
            raise ValueError("source_file_must_be_absolute")
        if not self.path.is_file():
            raise ValueError("source_file_not_found")
        self.revision = str(source.config.get("revision") or "")
        if not self.revision:
            raise ValueError("bulk_revision_required")
        self.page_size = int(source.config.get("page_size", 500))
        if not 1 <= self.page_size <= 2000:
            raise ValueError("bulk_invalid_page_size")
        self.body_limit = int(source.config.get("body_limit", BODY_LIMIT))
        if not 1 <= self.body_limit <= MAX_BODY_LIMIT:
            raise ValueError("bulk_invalid_body_limit")
        self.resource_type = source.config.get("resource_type", "skill")
        if self.resource_type not in BULK_TYPES:
            raise ValueError("bulk_invalid_resource_type")
        self.content_license = normalize_license(source.config.get("content_license"))
        if self.content_license and (self.content_license not in PERMISSIVE or not source.config.get("license_url")):
            raise ValueError("bulk_content_license_requires_evidence")

    def fetch_page(self, checkpoint: dict, state: dict) -> Page:
        stat = self.path.stat()
        identity = digest([self.revision, stat.st_size, stat.st_mtime_ns, self.source.config])
        if checkpoint and checkpoint.get("file_identity") != identity:
            raise ValueError("bulk_file_changed_during_scan")
        if not checkpoint and state.get("revision") == identity:
            return Page(records=[], complete=True, mode="incremental", revision=identity)
        offset = checkpoint.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= stat.st_size:
            raise ValueError("bulk_invalid_offset")
        records = []
        with self.path.open("rb") as stream:
            stream.seek(offset)
            for _ in range(self.page_size):
                line = stream.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES:
                    raise ValueError("bulk_row_too_large")
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise ValueError("bulk_invalid_jsonl") from exc
                records.append(self._record(row))
            offset = stream.tell()
        after = self.path.stat()
        if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            raise ValueError("bulk_file_changed_during_scan")
        return Page(records=records, complete=offset == stat.st_size, revision=identity,
                    checkpoint={"offset": offset, "file_identity": identity})

    def _record(self, row: dict) -> Record:
        if not isinstance(row, dict) or not isinstance(row.get("content"), str) or not row["content"].strip():
            raise ValueError("bulk_missing_content")
        content = row["content"]
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        declared_hash = row.get("content_hash")
        if declared_hash and (not isinstance(declared_hash, str)
                              or not re.fullmatch(r"[0-9a-fA-F]{16,64}", declared_hash)
                              or not content_hash.startswith(declared_hash.lower())):
            raise ValueError("bulk_content_hash_mismatch")
        repo, path = str(row.get("repo") or ""), str(row.get("path") or "")
        url = _public_url(row.get("canonical_url")) or _public_url(row.get("html_url"))
        if not url and re.fullmatch(r"[\w.-]+/[\w.-]+", repo) and path:
            url = f"https://github.com/{repo}/blob/HEAD/{quote(path, safe='/')}"
        url = url or self.source.url
        # Bound YAML processing while retaining all original bytes in the raw snapshot.
        header, _ = frontmatter(content[:32000].replace("\r\n", "\n"))
        fallback = PurePosixPath(path).parent.name or repo.rsplit("/", 1)[-1] or content_hash[:16]
        name = row.get("name") or header.get("name")
        name = str(name).strip() if isinstance(name, (str, int)) else fallback
        description = row.get("summary") or header.get("description")
        summary = description.strip()[:12000] if isinstance(description, str) else ""
        metadata = {
            "dataset_id": self.source.config.get("dataset_id", self.source.source_id),
            "dataset_revision": self.revision,
            "dataset_license": self.source.config.get("dataset_license"),
            "license_scope": "original_repository" if self.content_license else "compilation_only; original_repository_license_unverified",
            "license_url": self.source.config.get("license_url"),
            "verification": "dataset_snapshot_read", "installable": False,
            "content_sha256": content_hash, "original_content_chars": len(content),
            "body_truncated": len(content) > self.body_limit, "indexed_content_chars": min(len(content), self.body_limit),
            "repository": repo, "source_path": path, "collection_method": row.get("source"),
            "author": repo.split("/", 1)[0] or None, "stars_scope": "repository_at_collection",
            "declared_license": header.get("license") if isinstance(header.get("license"), str) else None,
        }
        metadata.update({
            "canonical_url": url, "upstream_id": str(row.get("upstream_id") or row.get("native_id") or "")[:1000],
            "origin": str(row.get("origin") or "")[:2000],
            "artifact_kind": str(row.get("artifact_kind") or self.resource_type)[:100],
            "provenance": _object(row, "provenance", MAX_PROVENANCE_BYTES),
        })
        manifest = _object(row, "manifest", MAX_MANIFEST_BYTES)
        agents = row.get("agents", self.source.config.get("agents", list(SKILL_AGENTS) if self.resource_type == "skill" else []))
        if not isinstance(agents, list) or any(not isinstance(agent, str) or not agent or len(agent) > 100 for agent in agents):
            raise ValueError("bulk_invalid_agents")
        if header.get("parse_error"):
            metadata["frontmatter_error"] = header["parse_error"]
        if self.source.config.get("embedding_policy") == "all":
            metadata["embedding_policy"] = "all"
        popularity = {}
        stars = row.get("stars")
        if isinstance(stars, int) and not isinstance(stars, bool) and stars >= 0:
            popularity["stars"] = stars
        resource = Resource(
            item_id=self.resource_type + ":sha256:" + content_hash, type=self.resource_type, name=(name or fallback)[:300],
            summary=summary, url=url[:2000], body=content[:self.body_limit],
            body_policy="licensed" if self.content_license else "index_only",
            license=self.content_license, agents=agents, repo_path=path or None,
            features=[Feature(feature="tool_kind", value=self.resource_type, origin="declared", evidence="dataset record"),
                      *_features(row)],
            manifest=manifest, metadata=metadata, popularity=popularity, install={},
            risk=[] if self.content_license else ["unverified_license"],
        )
        raw = {key: row.get(key) for key in ("content_hash", "repo", "path", "html_url", "canonical_url", "upstream_id", "native_id",
                                                    "origin", "artifact_kind", "source", "stars", "lines", "words")}
        return Record(native_id=content_hash, resource=resource, raw=raw)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prepare a pinned public Parquet snapshot for local Catalog indexing")
    parser.add_argument("parquet", type=Path)
    parser.add_argument("jsonl", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(prepare_parquet(arguments.parquet, arguments.jsonl)))
