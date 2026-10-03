import hashlib
from pathlib import Path

import pytest

from orbit_catalog.contracts import Page, Resource, SourceSpec
from orbit_catalog.network import FetchError, validate_url
from orbit_catalog.sources.github import GitHubConnector, frontmatter
from orbit_catalog.sources.structured import StructuredConnector
from orbit_catalog.store import CatalogStore
from orbit_catalog.sync import CatalogSync

from .test_storage import record


class JSONClient:
    def __init__(self, response):
        self.response, self.urls = response, []

    def json(self, url, immutable=False):
        self.urls.append(url)
        return self.response


def test_mcp_overlap_tombstone_and_nonendorsement():
    http = JSONClient({"servers": [{"server": {"name": "com.example/tool", "description": "tool", "version": "2"},
                                   "_meta": {"io.modelcontextprotocol.registry/official": {"status": "deleted", "updatedAt": "2026-10-02T12:00:00Z"}}}],
                       "metadata": {}})
    source = SourceSpec(source_id="mcp", kind="mcp", url="https://registry.modelcontextprotocol.io/v0.1/servers")
    page = StructuredConnector(source, http).fetch_page({}, {"watermark": "2026-10-02T11:00:00Z"})
    assert "10%3A55%3A00Z" in http.urls[0]
    assert page.mode == "incremental" and page.records[0].resource.status == "deleted"
    assert page.records[0].resource.official is False


def test_malformed_catalog_is_not_a_successful_empty_snapshot():
    adapter = StructuredConnector(SourceSpec(source_id="models", kind="models_dev", url="https://models.dev/api.json"), JSONClient({"error": "bad"}))
    with pytest.raises(ValueError, match="invalid_model_provider"):
        adapter.fetch_page({}, {})


def test_sync_budget_resume_cancellation_and_failure(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    class Adapter:
        def fetch_page(self, checkpoint, state):
            offset = checkpoint.get("offset", 0)
            return Page(records=[record(str(offset))], complete=offset == 1, checkpoint={"offset": offset + 1})
    sync = CatalogSync(store, None, connector_factory=lambda *_: Adapter())
    assert sync.sync(max_pages=1)[0]["status"] == "paused"
    assert store.stats()["items"] == 0
    assert sync.sync()[0]["status"] == "completed"
    assert store.stats()["items"] == 2
    assert sync.sync(force=True, cancelled=lambda: True)[0]["status"] == "paused"
    class Broken:
        def fetch_page(self, *_):
            raise FetchError("http_429", 300)
    failing = CatalogSync(store, None, connector_factory=lambda *_: Broken())
    assert failing.sync(force=True)[0]["status"] == "failed"
    assert failing.sync()[0]["status"] == "not_due"
    assert store.stats()["items"] == 2


def test_github_body_hash_and_component_license_precedence():
    text = "---\nname: check\ndescription: Run pytest\nlicense: Custom\n---\nUseful body"
    license_text = "Custom proprietary terms, except some Apache code."
    contents = {"skills/check/SKILL.md": text, "skills/check/LICENSE": license_text}
    blobs = {p: {"sha": hashlib.sha1(b"blob " + str(len(s.encode())).encode() + b"\0" + s.encode()).hexdigest(), "size": len(s)} for p, s in contents.items()}
    class HTTP:
        def get(self, url, immutable=False):
            return next(value.encode() for path, value in contents.items() if url.endswith(path))
    adapter = GitHubConnector(SourceSpec(source_id="git", kind="github", url="https://github.com/a/b", config={"repo": "a/b"}), HTTP())
    row = adapter._document(("skills/check/SKILL.md", "skill"), {"sha": "a" * 40, "repo_id": "42", "license": "MIT"}, blobs)
    assert row.resource.item_id == "skill:github.com:42:skills/check/SKILL.md"
    assert row.resource.body == "" and row.resource.license == "Custom"
    assert row.resource.metadata["source_blob_sha"]


@pytest.mark.parametrize("url", ["http://models.dev/api.json", "https://localhost/a", "https://api.github.com:444/a", "https://x:y@api.github.com/a", "https://169.254.169.254/latest"])
def test_network_allowlist_rejects_untrusted_endpoints(url):
    with pytest.raises(FetchError):
        validate_url(url)


def test_yaml_is_data_and_invalid_frontmatter_is_marked():
    parsed, body = frontmatter("---\nname: test\ndescription: |\n  line one\n  line two\n---\nbody")
    assert "line two" in parsed["description"] and body == "body"
    assert frontmatter("---\nx: !!python/object:os.system {}\n---\nbody")[0]["parse_error"]


def test_mcp_watermark_does_not_skip_updates_during_long_scan():
    http = JSONClient({"servers": [{"server": {"name": "com.example/x"}, "_meta": {
        "io.modelcontextprotocol.registry/official": {"updatedAt": "2026-10-02T12:30:00Z"}}}], "metadata": {}})
    adapter = StructuredConnector(SourceSpec(source_id="mcp", kind="mcp", url="https://registry.modelcontextprotocol.io/v0.1/servers"), http)
    page = adapter.fetch_page({"scan_started_at": "2026-10-02T12:00:00+00:00"}, {})
    assert page.watermark == "2026-10-02T12:00:00+00:00"


def test_oversize_github_entry_remains_indexed_with_explicit_coverage():
    adapter = GitHubConnector(SourceSpec(source_id="git", kind="github", url="https://github.com/a/b", config={"repo": "a/b"}), None)
    row = adapter._document(("skills/large/SKILL.md", "skill"), {"sha": "a" * 40, "repo_id": "42"},
                            {"skills/large/SKILL.md": {"size": 300000, "sha": "b" * 40}})
    assert row.resource.metadata["content_status"] == "oversize_metadata_only"
    assert row.resource.metadata["verification"] == "tree_metadata_only"


def test_benchmark_keeps_configuration_and_normalizes_multiple_links():
    source = SourceSpec(source_id="swe", kind="swe_bench", url="https://example.org")
    rows = list(StructuredConnector(source, None)._swe_bench({"leaderboards": [{"name": "Verified", "results": [
        {"name": "Model", "site": ["https://a.example", "https://b.example"], "reasoning_effort": "high", "agent": "harness", "resolved": 42, "date": "2026-10-02"}]}]}))
    assert rows[0].resource.url == "https://a.example"
    assert rows[0].resource.manifest["effort"] == "high"
    assert len(rows[0].raw["site"]) == 2


def test_component_license_cannot_be_overridden_by_root_license():
    adapter = GitHubConnector(SourceSpec(source_id="git", kind="github", url="https://github.com/a/b", config={"repo": "a/b"}), None)
    assert adapter._license("skills/a/SKILL.md", {"license": "Proprietary"}, {"license": "MIT"}, {}) == "Proprietary"
    assert adapter._license("skills/a/SKILL.md", {"license": {"name": "MIT"}}, {"license": "MIT"}, {}) == "unrecognized_component_license"


FIXTURES = Path(__file__).parent / "fixtures"


def git_sha(text: str) -> str:
    data = text.encode()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class FakeGitHub:
    """Serves one synthetic repository revision; counts raw.githubusercontent.com downloads."""

    def __init__(self, files: dict[str, str], head: str):
        self.files, self.head, self.raw = files, head, 0

    def json(self, url, immutable=False):
        if url.endswith("/repos/a/b"):
            return {"id": 42, "default_branch": "main", "license": {"spdx_id": "MIT"}, "stargazers_count": 7}
        if "/branches/" in url:
            return {"commit": {"sha": self.head, "commit": {"committer": {"date": "2026-09-30T10:00:00Z"}}}}
        assert "/git/trees/" + self.head in url
        return {"tree": [{"path": p, "type": "blob", "sha": git_sha(t), "size": len(t)} for p, t in self.files.items()]}

    def get(self, url, immutable=False):
        self.raw += 1
        return next(t.encode() for p, t in self.files.items() if url.endswith("/" + p))


def crawl(adapter, state):
    checkpoint, records = {}, []
    while True:
        page = adapter.fetch_page(checkpoint, state)
        records += page.records
        if page.complete:
            return records
        checkpoint = page.checkpoint


def test_github_incremental_sync_downloads_only_changed_blobs():
    files = {f"skills/s{i}/SKILL.md": f"---\nname: s{i}\ndescription: skill {i}\nlicense: MIT\n---\nbody {i}" for i in range(200)}
    spec = SourceSpec(source_id="git", kind="github", url="https://github.com/a/b", config={"repo": "a/b"})
    first = FakeGitHub(files, "a" * 40)
    records = crawl(GitHubConnector(spec, first), {})
    assert first.raw == 200 and len(records) == 200
    meta = records[0].resource.metadata
    assert meta["blob_sha"] == git_sha(files[records[0].native_id]) and meta["author"] == "a"
    assert meta["source_updated_at"] == "2026-09-30T10:00:00Z" and records[0].resource.popularity == {"stars": 7}

    known = {r.native_id: (r.resource.metadata["blob_sha"], r.resource, r.raw) for r in records}
    files["skills/s5/SKILL.md"] += " changed"
    second = FakeGitHub(files, "b" * 40)
    again = crawl(GitHubConnector(spec, second), {"revision": "a" * 40, "known": known})
    assert second.raw == 1 and len(again) == 200
    changed = next(r for r in again if r.native_id == "skills/s5/SKILL.md")
    assert changed.resource.body.endswith("changed") and changed.resource.commit_sha == "b" * 40
    # Same head as the stored revision: no tree read, no downloads.
    third = FakeGitHub(files, "b" * 40)
    assert crawl(GitHubConnector(spec, third), {"revision": "b" * 40}) == [] and third.raw == 0


def test_github_reuse_accepts_dict_form_and_rejects_stale_blob():
    spec = SourceSpec(source_id="git", kind="github", url="https://github.com/a/b", config={"repo": "a/b"})
    stored = Resource(item_id="skill:x", type="skill", name="x", url="https://github.com/a/b", metadata={"blob_sha": "1" * 40})
    adapter = GitHubConnector(spec, None)
    blobs = {"skills/x/SKILL.md": {"sha": "1" * 40, "size": 10}}
    hit = adapter._reuse(("skills/x/SKILL.md", "skill"), {"stars": 3}, blobs, {"skills/x/SKILL.md": {"resource": stored.model_dump()}})
    assert hit.resource.item_id == "skill:x" and hit.resource.popularity == {"stars": 3}
    blobs["skills/x/SKILL.md"]["sha"] = "2" * 40
    assert adapter._reuse(("skills/x/SKILL.md", "skill"), {}, blobs, {"skills/x/SKILL.md": ("1" * 40, stored, {})}) is None


def file_source(kind, name, **config):
    return SourceSpec(source_id=kind.replace("_", "-"), kind=kind, url="https://models.dev/api.json",
                      config={"file": str(FIXTURES / name), **config})


def test_models_dev_fixture_writes_normalized_keys_without_network():
    page = StructuredConnector(file_source("models_dev", "models_dev_mini.json"), None).fetch_page({}, {})
    rows = {r.native_id: r.resource.metadata for r in page.records}
    sonnet = rows["anthropic/claude-3-5-sonnet-20241022"]
    assert sonnet["canonical_id"] == "anthropic/claude-3-5-sonnet-20241022"
    assert (sonnet["context_window"], sonnet["max_output"], sonnet["input_per_mtok"], sonnet["cache_read_per_mtok"]) == (100000, 4000, 1.5, 0.15)
    assert sonnet["tool_call"] is True and sonnet["reasoning"] is False and sonnet["source_updated_at"] == "2024-10-22"
    gpt = rows["openai/gpt-5"]
    assert gpt["output_per_mtok"] is None and gpt["max_output"] is None and gpt["tool_call"] is None
    bedrock = rows["amazon-bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"]
    assert bedrock["canonical_id"] == sonnet["canonical_id"] and bedrock["aliases"]
    assert rows["anthropic/claude-3-5-sonnet-latest"]["canonical_id"] == "anthropic/claude-3-5-sonnet-latest"
    unchanged = StructuredConnector(file_source("models_dev", "models_dev_mini.json"), None).fetch_page({}, {"revision": page.revision})
    assert unchanged.records == [] and unchanged.mode == "incremental"


def test_litellm_fixture_converts_prices_and_resolves_identity():
    page = StructuredConnector(file_source("litellm", "litellm_mini.json"), None).fetch_page({}, {})
    rows = {r.native_id: r.resource.metadata for r in page.records}
    assert "sample_spec" not in rows
    direct = rows["claude-3-5-sonnet-20241022"]
    assert direct["input_per_mtok"] == 1.5 and direct["output_per_mtok"] == 7.5 and direct["cache_read_per_mtok"] == 0.15
    assert direct["context_window"] == 100000 and direct["canonical_identity"] == "resolved"
    assert rows["bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0"]["canonical_id"] == direct["canonical_id"]
    assert rows["azure/gpt-5"]["canonical_id"] == "openai/gpt-5" and rows["azure/gpt-5"]["input_per_mtok"] is None
    mystery = rows["fireworks_ai/mystery-model"]
    assert mystery["canonical_identity"] == "unresolved" and mystery["canonical_id"] is None and mystery["context_window"] is None


def test_swe_bench_fixture_normalizes_effort_score_and_model():
    state = {"known_models": {"anthropic/claude-3-5-sonnet-20241022", "openai/gpt-5"}}
    page = StructuredConnector(file_source("swe_bench", "swe_bench_mini.json"), None).fetch_page({}, state)
    rows = [r.resource.manifest for r in page.records]
    assert rows[0]["canonical_model_id"] == "anthropic/claude-3-5-sonnet-20241022" and rows[0]["score"] == 41.5
    assert rows[0]["measured_at"] == "2024-10-22" and rows[0]["unit"] == "percent" and rows[0]["benchmark_version"] == "Verified"
    assert (rows[1]["canonical_model_id"], rows[1]["effort"], rows[1]["measured_at"]) == ("openai/gpt-5", "high", "2025-08-01")
    assert rows[2]["effort"] == "high" and rows[2]["effort_raw"] == "high" and rows[2]["score"] is None and rows[2]["measured_at"] is None
    assert rows[3]["canonical_model_id"] is None and rows[3]["score"] is None
    assert page.records[0].resource.metadata["source_updated_at"] == "2024-10-22"


def test_source_file_must_be_absolute_and_present(tmp_path):
    for path, code in (("relative.json", "source_file_must_be_absolute"), (str(tmp_path / "missing.json"), "source_file_not_found")):
        spec = SourceSpec(source_id="models", kind="models_dev", url="https://models.dev/api.json", config={"file": path})
        with pytest.raises(ValueError, match=code):
            StructuredConnector(spec, None).fetch_page({}, {})
