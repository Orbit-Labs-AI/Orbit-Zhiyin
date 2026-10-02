import hashlib

import pytest

from tandem_catalog.contracts import Page, SourceSpec
from tandem_catalog.network import FetchError, validate_url
from tandem_catalog.sources.github import GitHubConnector, frontmatter
from tandem_catalog.sources.structured import StructuredConnector
from tandem_catalog.store import CatalogStore
from tandem_catalog.sync import CatalogSync

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
