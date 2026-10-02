"""Fetch tests run on in-memory tarballs and a fake fetcher; nothing touches the network."""

import base64
import hashlib
import io
import json
import tarfile

import pytest

from tandem_backend.install import fetch as fetchmod
from tandem_backend.install.fetch import FetchError, UrlFetcher, fetch_source, gc, read_tree
from tandem_backend.recommend.resource_fetch import GitHubSourceClient

COMMIT = "c" * 40
TOP = f"acme-skills-{COMMIT}"


def tarball(files=None, extra=None):
    """files: {rel: bytes}; extra: callables adding odd members to the archive."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        top = tarfile.TarInfo(TOP)
        top.type = tarfile.DIRTYPE
        archive.addfile(top)
        for rel, data in (files or {}).items():
            info = tarfile.TarInfo(f"{TOP}/{rel}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for add in extra or []:
            add(archive)
    return buffer.getvalue()


DEFAULT = {"skills/foo/SKILL.md": b"# foo\n", "skills/foo/ref/notes.md": b"notes", "skills/bar/SKILL.md": b"# bar",
           "README.md": b"readme"}


class FakeFetcher:
    def __init__(self, archive=None, spdx="MIT", commit=COMMIT):
        self.calls = []
        self.archive = tarball(DEFAULT) if archive is None else archive
        self.spdx, self.commit = spdx, commit

    def get(self, url, *, max_bytes, headers=None):
        self.calls.append(url)
        if url.startswith("https://api.github.com/repos/acme/skills/commits/"):
            body = json.dumps({"sha": self.commit}).encode()
        elif url == "https://api.github.com/repos/acme/skills":
            body = json.dumps({"license": {"spdx_id": self.spdx} if self.spdx else None}).encode()
        elif url == f"https://codeload.github.com/acme/skills/tar.gz/{self.commit}":
            body = self.archive
        elif url == "https://raw.githubusercontent.com/acme/skills/main/hook.sh":
            body = b"#!/bin/sh\necho hi\n"
        else:
            raise AssertionError(url)
        if len(body) > max_bytes:
            raise FetchError("too_large", http=422)
        return body


def source(**kw):
    return {"type": "github", "repo": "acme/skills", "ref": "main", "path": "skills/foo", **kw}


def residue(cache):
    return sorted(p.relative_to(cache).as_posix() for p in cache.rglob("*") if p.is_file()) if cache.exists() else []


def test_fetch_subtree_and_cache(tmp_path):
    cache, fake = tmp_path / "cache", FakeFetcher()
    result = fetch_source(source(), cache_dir=cache, fetcher=fake)
    assert [f["rel"] for f in result["files"]] == ["SKILL.md", "ref/notes.md"]
    assert result["commit"] == COMMIT and not result["cached"] and not result["link_only"]
    assert result["license"] == {"spdx": "MIT", "status": "ok"}
    sha = hashlib.sha256(b"# foo\n").hexdigest()
    expected = hashlib.sha256(f"SKILL.md\0{sha}\nref/notes.md\0{hashlib.sha256(b'notes').hexdigest()}\n".encode())
    assert result["tree_sha256"] == expected.hexdigest()
    obj = cache / "objects" / sha[:2] / sha
    assert obj.read_bytes() == b"# foo\n" and obj.stat().st_mode & 0o777 == 0o600
    manifest = json.loads((cache / "trees" / f"{result['tree_sha256']}.json").read_text())
    assert manifest["source"]["commit"] == COMMIT and manifest["files"][0]["mode"] == 0o644

    # a pinned commit hits the cache without any request
    pinned = FakeFetcher()
    hit = fetch_source(source(ref=COMMIT), cache_dir=cache, fetcher=pinned)
    assert pinned.calls == [] and hit["cached"] and hit["tree_sha256"] == result["tree_sha256"]
    # a branch needs one commit lookup, then hits
    branch = FakeFetcher()
    assert fetch_source(source(), cache_dir=cache, fetcher=branch)["cached"]
    assert len(branch.calls) == 1
    # a known tree hash needs nothing
    known = FakeFetcher()
    assert fetch_source(source(sha256="sha256:" + result["tree_sha256"]), cache_dir=cache, fetcher=known)["cached"]
    assert known.calls == []
    again = FakeFetcher()
    assert not fetch_source(source(ref=COMMIT), cache_dir=cache, fetcher=again, refresh=True)["cached"]
    assert len(again.calls) == 2  # repo info + tarball
    assert read_tree(cache, result["tree_sha256"]) == {"SKILL.md": "# foo\n", "ref/notes.md": "notes"}


def test_whole_repo_and_single_file_path(tmp_path):
    whole = fetch_source(source(path=""), cache_dir=tmp_path / "a", fetcher=FakeFetcher())
    assert len(whole["files"]) == 4
    single = fetch_source(source(path="README.md"), cache_dir=tmp_path / "b", fetcher=FakeFetcher())
    assert [f["rel"] for f in single["files"]] == ["README.md"]


def symlink(archive):
    info = tarfile.TarInfo(f"{TOP}/skills/foo/evil")
    info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
    archive.addfile(info)


def hardlink(archive):
    info = tarfile.TarInfo(f"{TOP}/skills/foo/hard")
    info.type, info.linkname = tarfile.LNKTYPE, f"{TOP}/README.md"
    archive.addfile(info)


def named(name):
    def add(archive):
        info = tarfile.TarInfo(name)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    return add


@pytest.mark.parametrize("archive,code", [
    (tarball(DEFAULT, [symlink]), "unsafe_member"),
    (tarball(DEFAULT, [hardlink]), "unsafe_member"),
    (tarball(DEFAULT, [named("/abs/file")]), "unsafe_member"),
    (tarball(DEFAULT, [named(f"{TOP}/skills/foo/../../x")]), "unsafe_member"),
    (tarball({f"skills/foo/{i}.md": b"x" for i in range(201)}), "too_many_files"),
    (tarball({"skills/foo/big.md": b"x" * 1_000_001}), "file_too_large"),
    (tarball({f"skills/foo/{i}.md": b"x" * 900_000 for i in range(6)}), "unpacked_too_large"),
    (tarball({}), "path_not_found"),
    (b"not a tarball", "corrupt_archive"),
], ids=["symlink", "hardlink", "absolute", "dotdot", "too_many_files", "file_too_large",
        "unpacked_too_large", "path_not_found", "corrupt"])  # gzip bytes carry a timestamp
def test_rejected_archives_leave_no_residue(tmp_path, archive, code):
    cache = tmp_path / "cache"
    with pytest.raises(FetchError) as error:
        fetch_source(source(ref=COMMIT), cache_dir=cache, fetcher=FakeFetcher(archive))
    assert error.value.code == code
    assert residue(cache) == []


def test_hash_mismatch_and_bad_inputs(tmp_path):
    cache = tmp_path / "cache"
    with pytest.raises(FetchError) as error:
        fetch_source(source(sha256="0" * 64), cache_dir=cache, fetcher=FakeFetcher())
    assert error.value.code == "hash_mismatch" and error.value.http == 422 and residue(cache) == []
    for bad in (source(repo="../x"), source(path="../up"), {"type": "ftp"}):
        with pytest.raises(FetchError):
            fetch_source(bad, cache_dir=cache, fetcher=FakeFetcher())
    with pytest.raises(FetchError, match="invalid_commit_sha"):
        fetch_source(source(), cache_dir=cache, fetcher=FakeFetcher(commit="nope"))


def test_missing_license_is_link_only(tmp_path):
    for spdx in (None, "NOASSERTION"):
        result = fetch_source(source(ref=COMMIT), cache_dir=tmp_path / str(spdx), fetcher=FakeFetcher(spdx=spdx))
        assert result["link_only"] and result["license"] == {"spdx": None, "status": "link_only"}


def test_raw_source(tmp_path):
    url = "https://raw.githubusercontent.com/acme/skills/main/hook.sh"
    result = fetch_source({"type": "raw", "url": url}, cache_dir=tmp_path, fetcher=FakeFetcher())
    assert [f["rel"] for f in result["files"]] == ["hook.sh"] and result["license"]["status"] == "unknown"
    with pytest.raises(FetchError) as error:
        fetch_source({"type": "raw", "url": "https://evil.example/hook.sh"}, cache_dir=tmp_path, fetcher=FakeFetcher())
    assert error.value.code == "host_not_allowed"


def test_url_fetcher_refuses_hosts_and_redirects():
    fetcher = UrlFetcher(token="t")
    for url in ("https://evil.example/x", "http://github.com/x", "file:///etc/passwd"):
        with pytest.raises(FetchError) as error:
            fetcher.get(url, max_bytes=10)
        assert error.value.code == "host_not_allowed"
    handler = fetchmod._Redirects()
    assert handler.max_redirections == 3
    with pytest.raises(FetchError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/payload")


def test_read_tree_skips_binary_and_gc_keeps_referenced(tmp_path):
    cache = tmp_path / "cache"
    files = {"skills/foo/SKILL.md": b"# foo", "skills/foo/logo.png": b"\x89PNG\x00\x01"}
    result = fetch_source(source(ref=COMMIT), cache_dir=cache, fetcher=FakeFetcher(tarball(files)))
    skipped = []
    assert read_tree(cache, result["tree_sha256"], skipped) == {"SKILL.md": "# foo"}
    assert skipped == ["logo.png"]
    with pytest.raises(FetchError):
        read_tree(cache, "f" * 64)
    orphan = cache / "objects" / "ab" / ("ab" + "0" * 62)
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x" * 5000)
    kept = sum(f["size"] for f in result["files"])
    report = gc(cache, max_bytes=kept)
    assert report == {"removed_objects": 1, "removed_trees": 0, "bytes": kept}
    assert read_tree(cache, result["tree_sha256"], []) == {"SKILL.md": "# foo"}
    assert gc(cache, max_bytes=0)["removed_trees"] == 1
    assert not list((cache / "objects").glob("*/*")) and not list((cache / "refs").glob("*.json"))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_github_source_client_opener_injection():
    seen = []
    content = b"---\ndescription: Hi\n---\n"
    blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()

    def opener(request, timeout):
        seen.append((request.full_url, request.get_header("Authorization"), timeout))
        url = request.full_url
        if "/contents/" in url:
            body = {"type": "file", "encoding": "base64", "content": base64.b64encode(content).decode(), "sha": blob}
        else:
            body = {"default_branch": "main", "license": {"spdx_id": "MIT"}}
        return FakeResponse(json.dumps(body).encode())

    client = GitHubSourceClient("tok", opener=opener)
    result = client.fetch({"id": "x", "url": "https://github.com/acme/skills", "source_path": "SKILL.md",
                           "verified_sha": COMMIT})
    assert result["license"] == "MIT" and result["source_description"] == "Hi"
    assert seen[0] == ("https://api.github.com/repos/acme/skills", "Bearer tok", 15)
