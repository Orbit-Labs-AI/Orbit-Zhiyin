"""Fetch public GitHub metadata and Markdown through the official REST API.

No repository script, hook, installation command, or remote prompt is executed.
Atomic replacement preserves the last verified cache when a refresh fails.
"""

import base64
import hashlib
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .catalog import resources

MAX_RESPONSE = 2_000_000
MAX_SOURCE = 250_000


class SourceFetchError(ValueError):
    pass


class GitHubSourceClient:
    def __init__(self, token: str | None = None):
        self.token = token

    def get(self, endpoint: str) -> dict:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Tandem-local-backend",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = Request("https://api.github.com" + endpoint, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise SourceFetchError("source_response_too_large")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise SourceFetchError("invalid_source_response")
            return result
        except HTTPError as error:
            raise SourceFetchError(f"github_http_{error.code}") from None
        except (URLError, TimeoutError, ValueError) as error:
            if isinstance(error, SourceFetchError):
                raise
            raise SourceFetchError("source_network_or_format_error") from None

    def fetch(self, resource: dict, latest: bool = False) -> dict:
        repo = resource["url"].removeprefix("https://github.com/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise SourceFetchError("invalid_github_repository")
        path = resource["source_path"]
        parsed_path = PurePosixPath(path)
        if parsed_path.is_absolute() or ".." in parsed_path.parts or not path.endswith(".md"):
            raise SourceFetchError("invalid_source_path")
        info = self.get(f"/repos/{repo}")
        sha = resource.get("verified_sha")
        if latest or not sha:
            branch = info.get("default_branch")
            if not isinstance(branch, str) or not branch:
                raise SourceFetchError("missing_default_branch")
            ref = self.get(f"/repos/{repo}/branches/{quote(branch, safe='')}")
            commit = ref.get("commit")
            sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise SourceFetchError("invalid_commit_sha")
        source = self.get(f"/repos/{repo}/contents/{quote(path, safe='/')}?{urlencode({'ref': sha})}")
        if source.get("type") != "file" or source.get("encoding") != "base64":
            raise SourceFetchError("unsupported_source_type")
        try:
            encoded = source.get("content")
            if not isinstance(encoded, str):
                raise SourceFetchError("invalid_source_encoding")
            content = base64.b64decode("".join(encoded.split()), validate=True)
            text = content.decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError):
            raise SourceFetchError("invalid_source_encoding") from None
        if len(content) > MAX_SOURCE:
            raise SourceFetchError("source_file_too_large")
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if blob != source.get("sha"):
            raise SourceFetchError("source_blob_hash_mismatch")
        license_info = info.get("license")
        license_id = license_info.get("spdx_id") if isinstance(license_info, dict) else None
        return {**resource, "verified_sha": sha, "blob_sha": source.get("sha"),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "source_description": description(text),
                "license": license_id if isinstance(license_id, str) and license_id and license_id != "NOASSERTION" else "repository_specific",
                "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "verification": "repository_and_skill_read" if path.endswith("SKILL.md") else "repository_and_source_read",
                "source_status": "fresh", "last_error": None}


def description(text: str) -> str:
    """A bounded metadata preview, never a prompt fed into the analysis model."""
    match = re.search(r"^description:\s*(.+)$", text, re.M)
    if match and match[1].strip() not in ("|", ">"):
        return match[1].strip()[:240]
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith(("#", "<", "!", "---", "[")):
            return line.strip()[:240]
    return ""


def refresh_catalog(output: Path, client: GitHubSourceClient | None = None,
                    latest: bool = False, resource_ids: set[str] | None = None) -> dict:
    seeds = resources(output if output.is_file() else None)
    if resource_ids and not resource_ids <= {r["id"] for r in seeds}:
        raise ValueError("目录中没有指定资源")
    output.parent.mkdir(parents=True, exist_ok=True)
    client = client or GitHubSourceClient(os.environ.get("GITHUB_TOKEN"))

    def update(seed: dict) -> dict:
        if resource_ids and seed["id"] not in resource_ids:
            return seed
        try:
            return client.fetch(seed, latest)
        except SourceFetchError as error:
            return {**seed, "source_status": "refresh_failed", "last_error": str(error)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        refreshed = list(pool.map(update, seeds))
    payload = {"schema_version": "1.0", "resources": refreshed,
               "success": sum(r.get("source_status") == "fresh" for r in refreshed if not resource_ids or r["id"] in resource_ids),
               "failed": sum(r.get("source_status") == "refresh_failed" for r in refreshed if not resource_ids or r["id"] in resource_ids)}
    # Same-directory atomic rename: a crash cannot leave half of a usable catalog.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix=".catalog-", delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
        temporary.replace(output)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return payload
