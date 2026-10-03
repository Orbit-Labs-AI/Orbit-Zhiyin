"""Discovery sources: awesome lists, GitHub topic search, rate-limit handling (offline fakes only)."""

from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from orbit_catalog.contracts import SourceSpec
from orbit_catalog.network import FetchError, HttpClient
from orbit_catalog.sources import default_sources
from orbit_catalog.sources.structured import StructuredConnector, awesome_entries

from .test_network import Response

AWESOME = """# Awesome
## Legend
- [legend](https://github.com/x/legend) - outside the section
## Server Implementations
### 🔗 <a name="aggregators"></a>Aggregators
- [acme/agg](https://github.com/acme/agg) [![agg MCP server](https://glama.ai/b.svg)](https://glama.ai/s) 🎖️ 📇 ☁️ - Aggregates servers.
### 🎨 <a name="art"></a>Art & Culture
- [bob/blender-mcp](https://github.com/bob/blender-mcp/) 🐍 🏠 🍎 - Connect to Blender - with dashes.
- [acme/agg](https://github.com/acme/agg) 📇 - listed twice
- [docs](https://example.com/docs) - not a repository
## Frameworks
- [fw/x](https://github.com/fw/x) - a framework, outside the section
"""


class Text:
    def __init__(self, text):
        self.text, self.calls = text, []

    def get(self, url, immutable=False):
        self.calls.append(url)
        return self.text.encode()


def test_awesome_entries_keep_section_category_and_legend():
    entries = awesome_entries(AWESOME, "Server Implementations")
    assert [e["repo"] for e in entries] == ["acme/agg", "bob/blender-mcp", "acme/agg"]
    agg, blender = entries[0], entries[1]
    assert agg == {"name": "acme/agg", "repo": "acme/agg", "summary": "Aggregates servers.", "category": "Aggregators",
                   "official": True, "languages": ["typescript"], "scope": "cloud"}
    assert blender["summary"] == "Connect to Blender - with dashes." and blender["category"] == "Art & Culture"
    assert blender["languages"] == ["python"] and blender["scope"] == "local" and not blender["official"]
    assert len(awesome_entries(AWESOME)) == 5  # no section: every GitHub entry, including legend/frameworks


def test_awesome_source_yields_metadata_only_unverified_items():
    source = SourceSpec(source_id="awesome", kind="awesome", url="https://raw.githubusercontent.com/o/l/main/README.md",
                        config={"type": "mcp_server", "section": "Server Implementations"})
    page = StructuredConnector(source, Text(AWESOME)).fetch_page({}, {})
    assert page.complete and [r.native_id for r in page.records] == ["acme/agg", "bob/blender-mcp"]
    agg = page.records[0].resource
    assert agg.item_id == "mcp_server:awesome:github.com/acme/agg" and agg.url == "https://github.com/acme/agg"
    assert agg.body == "" and agg.body_policy == "metadata" and not agg.official and agg.metadata["vendor_official"]
    assert agg.metadata["verification"] == "listed_only" and agg.metadata["category"] == "Aggregators"
    assert {(f.feature, f.value) for f in agg.features} == {("category", "Aggregators"), ("language", "typescript"),
                                                           ("transport", "remote")}
    again = StructuredConnector(source, Text(AWESOME)).fetch_page({}, {"revision": page.revision})
    assert again.mode == "incremental" and again.records == []


def repo(n, stars, **extra):
    return {"full_name": f"o/r{n}", "name": f"r{n}", "id": n, "description": f"repo {n}", "stargazers_count": stars,
            "topics": [], "pushed_at": "2026-09-01T00:00:00Z", "html_url": f"https://github.com/o/r{n}", "fork": False,
            "license": {"spdx_id": "MIT"}, **extra}


class Search:
    """topic -> list of repositories, paged like the search API."""

    def __init__(self, results):
        self.results, self.calls = results, []

    def json(self, url, immutable=False):
        query = parse_qs(urlsplit(url).query)
        self.calls.append((query["q"][0], int(query["page"][0])))
        topic = query["q"][0].split()[0].removeprefix("topic:")
        size, page = int(query["per_page"][0]), int(query["page"][0])
        rows = self.results[topic]
        return {"total_count": len(rows), "items": rows[(page - 1) * size:page * size]}


def test_github_topic_pages_through_topics_and_filters():
    fake = Search({"t1": [repo(1, 50, topics=["hermes-agent", "agent-skills"]), repo(2, 5),
                          repo(3, 90, fork=True)],
                   "t2": [repo(4, 30, license={"spdx_id": "NOASSERTION"})]})
    source = SourceSpec(source_id="topic", kind="github_topic", url="https://api.github.com/search/repositories",
                        config={"topics": ["t1", "t2"], "type": "skill", "per_page": 2, "max_pages": 5,
                                "min_stars": 10, "min_interval": 0, "agents": ["claude_code"]})
    connector, checkpoint, pages = StructuredConnector(source, fake), {}, []
    while True:
        page = connector.fetch_page(checkpoint, {})
        pages.append(page)
        if page.complete:
            break
        checkpoint = page.checkpoint
    # t1 has 3 results -> pages 1 (r1, r2) and 2 (r3); t2 -> page 1; then complete.
    assert fake.calls == [("topic:t1 archived:false", 1), ("topic:t1 archived:false", 2), ("topic:t2 archived:false", 1)]
    records = [r for p in pages for r in p.records]
    assert [r.native_id for r in records] == ["o/r1", "o/r4"]  # r2 under the star floor, r3 a fork
    r1, r4 = records[0].resource, records[1].resource
    assert r1.item_id == "skill:topic:github.com:1" and r1.agents == ["claude_code", "hermes"]
    assert r1.popularity == {"stars": 50} and r1.license == "MIT" and r1.metadata["verification"] == "repository_metadata"
    assert r4.license is None  # NOASSERTION is not a license
    assert ("topic", "agent-skills") in {(f.feature, f.value) for f in r1.features}


def test_github_topic_respects_page_cap():
    fake = Search({"t": [repo(n, 100) for n in range(1, 8)]})
    source = SourceSpec(source_id="topic", kind="github_topic", url="https://api.github.com/search/repositories",
                        config={"topics": ["t"], "per_page": 2, "max_pages": 2, "min_interval": 0})
    connector = StructuredConnector(source, fake)
    first = connector.fetch_page({}, {})
    second = connector.fetch_page(first.checkpoint, {})
    assert not first.complete and second.complete and len(fake.calls) == 2


def test_default_discovery_sources_are_registered():
    ids = {s.source_id: s for s in default_sources()}
    assert ids["awesome-mcp-servers"].kind == "awesome"
    assert ids["topic-agent-skills"].config["topics"] == ["agent-skills", "claude-code-skills", "claude-skills"]
    assert ids["awesome-cursorrules"].config["agents"] == ["cursor"]


class LimitedOpener:
    def __init__(self, headers):
        self.headers, self.calls = headers, 0

    def open(self, request, timeout=30):
        self.calls += 1
        if self.calls == 1:
            headers = Message()
            for key, value in self.headers.items():
                headers[key] = value
            raise HTTPError(request.full_url, 403, "forbidden", headers, None)
        return Response(b'{"ok": 1}')


@pytest.mark.parametrize("headers,waits", [({"Retry-After": "3"}, [3]), ({"x-ratelimit-remaining": "0",
                                                                          "x-ratelimit-reset": "0"}, [1])])
def test_github_rate_limit_403_waits_and_retries(tmp_path, headers, waits):
    seen = []
    http = HttpClient(tmp_path, opener=LimitedOpener(headers), sleep=seen.append)
    assert http.json("https://api.github.com/search/repositories?q=x") == {"ok": 1}
    assert seen == waits  # reset already passed -> the 1 s floor


def test_plain_403_is_final(tmp_path):
    http = HttpClient(tmp_path, opener=LimitedOpener({}), sleep=lambda s: None)
    with pytest.raises(FetchError, match="http_403"):
        http.json("https://api.github.com/repos/o/r")


def test_rule_summary_falls_back_to_first_prose_paragraph():
    from orbit_catalog.sources.github import first_paragraph
    body = "# Title\n\n```py\nx = 1\n\nprint(x)\n```\n\n- list item\n\nYou are an expert in FastAPI.\nWrite typed code.\n\nMore."
    assert first_paragraph(body) == "You are an expert in FastAPI. Write typed code."
    assert first_paragraph("# Only a heading\n\n- and a list") == ""
    assert first_paragraph("[ComponentName](https://v0.dev/chat?q={encoded_prompt})\n\nSee [the docs](https://x) for every rule.") \
        == "See the docs for every rule."
