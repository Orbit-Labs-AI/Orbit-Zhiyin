"""Resource fetch (IN-08): pinned GitHub trees into a content-addressed cache.

Network happens only when ``fetch_source`` is called (user-triggered). Hosts are allow-listed,
a ref is pinned to a 40-hex commit before the codeload tarball is downloaded, and the archive
is never ``extractall``-ed: each member is checked (no links, devices, absolute paths or
``..``) and read into memory within size limits. Nothing is written to the cache until the
whole tree passed every check, so a rejected archive leaves no residue.

Cache layout under ``cache_dir``: ``objects/<sha[:2]>/<sha>`` (file bytes, 0600),
``trees/<tree_sha256>.json`` (manifest) and ``refs/<key>.json`` (pinned source -> tree).
Hashes here are plain hex; ``sha256:`` prefixes are accepted on input.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
import threading
import time
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_HOSTS = {"github.com", "codeload.github.com", "raw.githubusercontent.com", "api.github.com",
                 "objects.githubusercontent.com"}
LIMITS = {"archive": 8_000_000, "unpacked": 5_000_000, "files": 200, "file": 1_000_000,
          "scanned": 64_000_000, "members": 20_000, "api": 2_000_000}
CACHE_MAX = 200_000_000
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
COMMIT = re.compile(r"[0-9a-f]{40}")
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._@+ -]+")


class FetchError(Exception):
    def __init__(self, code: str, message: str = "", http: int = 502):
        super().__init__(message or code)
        self.code, self.message, self.http = code, message or code, http


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in ALLOWED_HOSTS:
        raise FetchError("host_not_allowed", f"refused URL host: {parts.hostname}", http=422)


class _Redirects(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrlFetcher:
    """urllib with an allow-list, ≤3 allow-listed redirects and a streaming size cap."""

    def __init__(self, token: str | None = None, timeout: float = 15.0):
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self.timeout = timeout
        self.opener = build_opener(_Redirects)

    def get(self, url: str, *, max_bytes: int, headers: dict | None = None) -> bytes:
        _check_url(url)
        request = Request(url, headers={"User-Agent": "Orbit-local-backend", **(headers or {})})
        if self.token and urlsplit(url).hostname == "api.github.com":
            # Unredirected: never forwarded to another host on a redirect.
            request.add_unredirected_header("Authorization", "Bearer " + self.token)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                chunks, total = [], 0
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError("too_large", f"response exceeds {max_bytes} bytes", http=422)
                    chunks.append(chunk)
                return b"".join(chunks)
        except HTTPError as error:
            raise FetchError("not_found" if error.code == 404 else f"http_{error.code}",
                             http=404 if error.code == 404 else 502) from None
        except (URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", None)
            if isinstance(reason, FetchError):
                raise reason from None
            raise FetchError("network_error", str(error)[:200]) from None


def _hex(value) -> str | None:
    if not value:
        return None
    text = str(value).removeprefix("sha256:").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise FetchError("invalid_sha256", http=422)
    return text


def _api_json(fetcher, path: str) -> dict:
    raw = fetcher.get("https://api.github.com" + path, max_bytes=LIMITS["api"],
                      headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        data = json.loads(raw)
    except ValueError:
        raise FetchError("invalid_api_response") from None
    if not isinstance(data, dict):
        raise FetchError("invalid_api_response")
    return data


def tree_hash(files: list[dict]) -> str:
    digest = hashlib.sha256()
    for f in sorted(files, key=lambda f: f["rel"]):
        digest.update(f"{f['rel']}\0{f['sha256']}\n".encode())
    return digest.hexdigest()


def _license(spdx) -> dict:
    spdx = spdx if isinstance(spdx, str) and spdx not in ("", "NOASSERTION", "NONE") else None
    return {"spdx": spdx, "status": "ok" if spdx else "link_only"}


def _safe_parts(name: str) -> tuple[str, ...] | None:
    if name.startswith("/") or "\\" in name:
        return None
    parts = tuple(p for p in PurePosixPath(name).parts if p != ".")
    if any(p == ".." for p in parts):
        return None
    return parts


def extract_tree(data: bytes, subpath: str, limits: dict) -> list[dict]:
    """Members under ``subpath`` (after the codeload top dir) as ``[{rel, data, mode}]``."""
    prefix = tuple(PurePosixPath(subpath).parts) if subpath else ()
    files, seen, scanned, unpacked = [], set(), 0, 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for count, member in enumerate(archive, 1):
                if count > limits["members"]:
                    raise FetchError("archive_too_many_members", http=422)
                parts = _safe_parts(member.name)
                if parts is None:
                    raise FetchError("unsafe_member", f"unsafe path in archive: {member.name!r}", http=422)
                scanned += max(member.size, 0)
                if scanned > limits["scanned"]:
                    raise FetchError("archive_too_large", http=422)
                inner = parts[1:]  # drop codeload's "<repo>-<sha>/" directory
                if prefix and inner[:len(prefix)] != prefix:
                    continue
                rel_parts = inner[len(prefix):] or (inner[-1:] if inner else ())
                if not rel_parts:
                    continue
                if member.isdir():
                    continue
                if not member.isreg():
                    raise FetchError("unsafe_member", f"link or special file: {member.name!r}", http=422)
                rel = "/".join(rel_parts)
                if any(not SAFE_SEGMENT.fullmatch(p) for p in rel_parts):
                    raise FetchError("unsafe_member", f"unsupported file name: {rel!r}", http=422)
                if rel in seen:
                    raise FetchError("duplicate_member", rel, http=422)
                seen.add(rel)
                if len(files) + 1 > limits["files"]:
                    raise FetchError("too_many_files", http=422)
                if member.size > limits["file"]:
                    raise FetchError("file_too_large", rel, http=422)
                unpacked += member.size
                if unpacked > limits["unpacked"]:
                    raise FetchError("unpacked_too_large", http=422)
                handle = archive.extractfile(member)
                body = handle.read(limits["file"] + 1) if handle else b""
                if len(body) != member.size:
                    raise FetchError("corrupt_archive", rel, http=422)
                files.append({"rel": rel, "data": body, "mode": 0o755 if member.mode & 0o111 else 0o644})
    except (tarfile.TarError, EOFError, OSError) as error:
        raise FetchError("corrupt_archive", str(error)[:200], http=422) from None
    if not files:
        raise FetchError("path_not_found", f"nothing under {subpath!r}", http=404)
    return files


# ---- cache --------------------------------------------------------------------------------

def _write_atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _object_path(cache_dir: Path, sha: str) -> Path:
    return cache_dir / "objects" / sha[:2] / sha


def _ref_key(source: dict, commit: str | None) -> str:
    ident = json.dumps([source.get("type"), source.get("repo"), commit, source.get("path") or "", source.get("url")])
    return hashlib.sha256(ident.encode()).hexdigest()


def _load_tree(cache_dir: Path, tree: str) -> dict | None:
    path = cache_dir / "trees" / f"{tree}.json"
    try:
        manifest = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not all(_object_path(cache_dir, f["sha256"]).is_file() for f in manifest.get("files", [])):
        return None
    try:
        os.utime(path)  # LRU touch
    except OSError:
        pass
    return manifest


def _lookup_ref(cache_dir: Path, key: str) -> dict | None:
    try:
        tree = json.loads((cache_dir / "refs" / f"{key}.json").read_text("utf-8"))["tree_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return _load_tree(cache_dir, tree)


def _result(manifest: dict, cached: bool) -> dict:
    return {"tree_sha256": manifest["tree_sha256"], "commit": manifest.get("commit"),
            "files": [{"rel": f["rel"], "size": f["size"], "sha256": f["sha256"]} for f in manifest["files"]],
            "license": manifest["license"], "size": manifest["size"], "cached": cached,
            "link_only": manifest["license"]["status"] != "ok", "source": manifest["source"]}


def _store(cache_dir: Path, source: dict, commit: str | None, license_info: dict, files: list[dict],
           expected: str | None) -> dict:
    entries = [{"rel": f["rel"], "sha256": hashlib.sha256(f["data"]).hexdigest(), "size": len(f["data"]),
                "mode": f["mode"]} for f in files]
    tree = tree_hash(entries)
    if expected and expected != tree:
        raise FetchError("hash_mismatch", f"expected {expected}, got {tree}", http=422)
    for f, e in zip(files, entries, strict=True):
        target = _object_path(cache_dir, e["sha256"])
        if not target.is_file():
            _write_atomic(target, f["data"])
    manifest = {"tree_sha256": tree, "source": source, "commit": commit, "license": license_info,
                "files": entries, "fetched_at": int(time.time() * 1000), "size": sum(e["size"] for e in entries)}
    _write_atomic(cache_dir / "trees" / f"{tree}.json", json.dumps(manifest, ensure_ascii=False).encode())
    _write_atomic(cache_dir / "refs" / f"{_ref_key(source, commit)}.json", json.dumps({"tree_sha256": tree}).encode())
    return manifest


def fetch_source(source: dict, *, cache_dir: Path, fetcher=None, refresh: bool = False,
                 limits: dict | None = None) -> dict:
    limits = {**LIMITS, **(limits or {})}
    cache_dir = Path(cache_dir)
    kind = source.get("type")
    expected = _hex(source.get("sha256"))
    if expected and not refresh and (hit := _load_tree(cache_dir, expected)):
        return _result(hit, cached=True)
    if kind == "raw":
        return _fetch_raw(source, cache_dir, fetcher, refresh, limits, expected)
    if kind != "github":
        raise FetchError("unsupported_source", f"unknown source type: {kind!r}", http=422)
    repo, ref, path = source.get("repo"), source.get("ref") or "HEAD", (source.get("path") or "").strip("/")
    if not isinstance(repo, str) or not REPO.fullmatch(repo) or ".." in repo:
        raise FetchError("invalid_repo", http=422)
    if path and _safe_parts(path) is None:
        raise FetchError("invalid_path", http=422)
    clean = {"type": "github", "repo": repo, "ref": ref, "path": path}
    fetcher = fetcher or UrlFetcher()
    commit = ref if COMMIT.fullmatch(str(ref)) else None
    if commit is None:
        commit = _api_json(fetcher, f"/repos/{repo}/commits/{quote(str(ref), safe='')}").get("sha")
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise FetchError("invalid_commit_sha")
    clean["commit"] = commit
    if not refresh and (hit := _lookup_ref(cache_dir, _ref_key(clean, commit))):
        return _result(hit, cached=True)
    info = _api_json(fetcher, f"/repos/{repo}")
    spdx = (info.get("license") or {}).get("spdx_id") if isinstance(info.get("license"), dict) else None
    archive = fetcher.get(f"https://codeload.github.com/{repo}/tar.gz/{commit}", max_bytes=limits["archive"])
    files = extract_tree(archive, path, limits)
    return _result(_store(cache_dir, clean, commit, _license(spdx), files, expected), cached=False)


def _fetch_raw(source: dict, cache_dir: Path, fetcher, refresh: bool, limits: dict, expected: str | None) -> dict:
    url = source.get("url")
    if not isinstance(url, str):
        raise FetchError("invalid_url", http=422)
    _check_url(url)
    rel = PurePosixPath(urlsplit(url).path).name
    if not rel or not SAFE_SEGMENT.fullmatch(rel) or rel in (".", ".."):
        raise FetchError("invalid_url", "URL has no usable file name", http=422)
    clean = {"type": "raw", "url": url}
    data = (fetcher or UrlFetcher()).get(url, max_bytes=limits["file"])
    given = source.get("license")
    spdx = given.get("spdx") if isinstance(given, dict) else None
    license_info = _license(spdx) if spdx else {"spdx": None, "status": "unknown"}
    return _result(_store(cache_dir, clean, None, license_info, [{"rel": rel, "data": data, "mode": 0o644}],
                          expected), cached=False)


def read_tree(cache_dir: Path, tree_sha256: str, skipped: list | None = None) -> dict[str, str]:
    """UTF-8 text files of a cached tree; binary/undecodable rels are appended to ``skipped``."""
    tree = _hex(tree_sha256)
    manifest = _load_tree(Path(cache_dir), tree)
    if manifest is None:
        raise FetchError("tree_not_cached", http=404)
    out = {}
    for f in manifest["files"]:
        data = _object_path(Path(cache_dir), f["sha256"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise FetchError("cache_corrupt", f["rel"], http=500)
        try:
            if b"\x00" in data:
                raise UnicodeDecodeError("utf-8", data, 0, 1, "binary")
            out[f["rel"]] = data.decode("utf-8")
        except UnicodeDecodeError:
            if skipped is not None:
                skipped.append(f["rel"])
    return out


def gc(cache_dir: Path, max_bytes: int = CACHE_MAX) -> dict:
    """LRU: drop unreferenced objects first, then the oldest trees and what they alone held."""
    cache_dir = Path(cache_dir)
    objects = {p.name: p for p in (cache_dir / "objects").glob("*/*") if p.is_file() and not p.name.startswith(".")}
    trees = sorted((cache_dir / "trees").glob("*.json"), key=lambda p: p.stat().st_mtime)
    refs: dict[Path, set[str]] = {}
    for t in trees:
        try:
            refs[t] = {f["sha256"] for f in json.loads(t.read_text("utf-8"))["files"]}
        except (OSError, ValueError, KeyError, TypeError):
            refs[t] = set()

    def size(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0

    total = sum(size(p) for p in objects.values())
    removed_objects, removed_trees = 0, 0

    def evict(candidates: list[str]) -> None:
        nonlocal total, removed_objects
        for sha in sorted(candidates, key=lambda s: max(_stat_time(objects[s]))):
            if total <= max_bytes:
                return
            total -= size(objects[sha])
            objects.pop(sha).unlink(missing_ok=True)
            removed_objects += 1

    referenced = set().union(*refs.values()) if refs else set()
    evict([s for s in objects if s not in referenced])
    while total > max_bytes and trees:
        oldest = trees.pop(0)
        oldest.unlink(missing_ok=True)
        refs.pop(oldest, None)
        removed_trees += 1
        referenced = set().union(*refs.values()) if refs else set()
        evict([s for s in objects if s not in referenced])
    if removed_trees:
        live = {t.stem for t in trees}
        for ref in (cache_dir / "refs").glob("*.json"):
            try:
                if json.loads(ref.read_text("utf-8")).get("tree_sha256") not in live:
                    ref.unlink()
            except (OSError, ValueError, AttributeError):
                ref.unlink(missing_ok=True)
    return {"removed_objects": removed_objects, "removed_trees": removed_trees, "bytes": total}


def _stat_time(path: Path) -> tuple[float, float]:
    try:
        st = path.stat()
        return st.st_atime, st.st_mtime
    except OSError:
        return 0.0, 0.0
