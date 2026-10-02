"""Library source quality (P1): offline fixtures only, never the network or a real HOME."""

import hashlib
import io
import json
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from tandem_catalog import risk
from tandem_catalog.contracts import SourceSpec, normalize_license
from tandem_catalog.network import HttpClient
from tandem_catalog.sources import default_sources
from tandem_catalog.sources.github import GitHubConnector, file_kind
from tandem_catalog.sources.structured import StructuredConnector, namespace_author
from tandem_catalog.store import CatalogStore
from tandem_catalog.sync import CatalogSync

FIXTURES = Path(__file__).parent / "fixtures" / "library"
MCP_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def git_sha(text: str) -> str:
    data = text.encode()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class FakeRepo:
    """Serves one synthetic repository revision from a fixture's `files` map."""

    def __init__(self, files: dict[str, str], repo="acme/tools"):
        self.files, self.repo, self.raw = files, repo, 0

    def json(self, url, immutable=False):
        if url.endswith(f"/repos/{self.repo}"):
            return {"id": 99, "default_branch": "main", "license": {"spdx_id": "MIT"}, "stargazers_count": 5}
        if "/branches/" in url:
            return {"commit": {"sha": "c" * 40, "commit": {"committer": {"date": "2026-09-30T10:00:00Z"}}}}
        return {"tree": [{"path": p, "type": "blob", "sha": git_sha(t), "size": len(t.encode())} for p, t in self.files.items()]}

    def get(self, url, immutable=False):
        self.raw += 1
        path = url.split("c" * 40 + "/", 1)[1]
        return self.files[path].encode()


def crawl(name, **config):
    files = fixture(name)["files"]
    spec = SourceSpec(source_id="lib", kind="github", url="https://github.com/acme/tools",
                      config={"repo": "acme/tools", "agents": ["claude_code"], **config})
    adapter, checkpoint, records = GitHubConnector(spec, FakeRepo(files)), {}, []
    while True:
        page = adapter.fetch_page(checkpoint, {})
        records += page.records
        if page.complete:
            return {r.native_id: r.resource for r in records}
        checkpoint = page.checkpoint


def test_skill_internal_markdown_is_not_a_standalone_item():
    items = crawl("tree_skills_nested.json")
    kinds = sorted((r.type, r.name) for r in items.values())
    assert kinds == [("skill", "review"), ("subagent", "standalone")]
    skill = items["skills/review/SKILL.md"]
    assert skill.license == "MIT" and skill.body == "Steps."  # 'MIT License' normalized, still inlined
    assert skill.agents == ["claude_code", "codex", "gemini", "opencode"]  # Agent Skills standard + source agents
    assert skill.metadata["stars_scope"] == "repo" and skill.metadata["updated_scope"] == "repo"


def test_agents_inference_can_be_disabled_and_keeps_source_agents():
    items = crawl("tree_skills_nested.json", agents=["copilot"], agents_infer=False)
    assert items["skills/review/SKILL.md"].agents == ["copilot"]
    items = crawl("tree_skills_nested.json", agents=["copilot"])
    assert items["skills/review/SKILL.md"].agents[0] == "copilot" and "codex" in items["skills/review/SKILL.md"].agents


def test_hook_named_after_plugin_with_install_payload_per_event():
    items = crawl("hooks_plugin_tree.json")
    hooks = {r.metadata["hook_event"]: r for r in items.values() if r.type == "hook"}
    assert set(hooks) == {"PreToolUse", "Stop"}
    pre = hooks["PreToolUse"]
    assert pre.name == "hookify · PreToolUse" and pre.item_id.endswith("plugins/hookify/hooks/hooks.json#PreToolUse")
    assert pre.install["hook"] == {"event": "PreToolUse", "matcher": "Bash", "timeout": 10,
                                   "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/guard.py"}
    assert ("hook_event", "PreToolUse") in {(f.feature, f.value) for f in pre.features}
    assert "runs_command" in pre.risk and "runs_command" in risk.assess(pre)[0]
    assert pre.metadata["plugin_relative"] is True
    plugin = items["plugins/hookify/.claude-plugin/plugin.json"]
    assert {pre.item_id, hooks["Stop"].item_id} <= set(plugin.components)
    assert plugin.install == {"marketplace": "example-market", "name": "hookify"}
    plan = pytest.importorskip("tandem_backend.install.plan")
    item = plan.catalog_item({"resource": pre.model_dump()})
    assert item["kind"] == "hook" and item["install"]["hook"]["event"] == "PreToolUse"


def test_plugin_mcp_json_becomes_installable_mcp_servers():
    items = crawl("mcp_json_plugin.json")
    servers = {r.name: r for r in items.values() if r.type == "mcp_server"}
    assert set(servers) == {"postgres", "docs"}  # the repository's own root .mcp.json is ignored
    pg = servers["postgres"]
    assert pg.install["mcp"] == {"name": "postgres", "transport": "stdio", "command": "npx",
                                 "args": ["-y", "@example/pg-mcp"], "env": {"DATABASE_URL": "${DATABASE_URL}"}}
    assert {(f.feature, f.value) for f in pg.features} >= {("transport", "stdio"), ("env_required", "DATABASE_URL"),
                                                           ("env_required", "LITERAL")}
    assert "s3cr3t-value" not in json.dumps(pg.install)
    assert servers["docs"].install["mcp"] == {"name": "docs", "transport": "http", "url": "https://mcp.example.com/mcp"}
    plugin = items["plugins/db/.claude-plugin/plugin.json"]
    assert {pg.item_id, servers["docs"].item_id} <= set(plugin.components)
    plan = pytest.importorskip("tandem_backend.install.plan")
    assert plan.catalog_item({"resource": pg.model_dump()})["install"]["mcp"]["command"] == "npx"


def test_plugin_json_gets_marketplace_install_and_declared_fields():
    items = crawl("plugin_json_with_marketplace.json")
    fmt = items["plugins/fmt/.claude-plugin/plugin.json"]
    assert fmt.install == {"marketplace": "acme-tools", "name": "formatter"}
    assert fmt.version == "0.3.1" and fmt.license == "MIT"
    assert fmt.metadata["author"] == "Acme Dev" and fmt.metadata["homepage"] == "https://acme.example/fmt"
    assert fmt.metadata["repository"] == "https://github.com/acme/fmt" and fmt.metadata["installable"] is True
    assert items["plugins/orphan/.claude-plugin/plugin.json"].install == {}
    pointer = items["marketplace:formatter"]
    assert pointer.item_id == fmt.item_id  # marketplace pointer and plugin.json merge into one catalog item


def test_kind_rules_classify_category_directories():
    rules = [{"glob": "categories/*/*.md", "type": "subagent"}]
    assert file_kind("categories/01-core/api-designer.md", rules=rules) == "subagent"
    assert file_kind("categories/01-core/README.md", rules=rules) is None
    assert file_kind("categories/01-core/api-designer.md") is None
    assert file_kind("x/skills/a/agents/b.md", skill_dirs={"x/skills/a"}) is None


class RegistryOpener:
    """urllib opener stand-in serving registry pages by cursor; `fail` maps page index → remaining 500s."""

    def __init__(self, pages, fail):
        self.pages, self.fail, self.calls = pages, dict(fail), []

    def open(self, request, timeout=30):
        cursor = parse_qs(urlsplit(request.full_url).query).get("cursor", [None])[0]
        index = {None: 0, "c1": 1, "c2": 2}[cursor]
        self.calls.append(index)
        if self.fail.get(index):
            self.fail[index] -= 1
            raise HTTPError(request.full_url, 500, "boom", Message(), None)
        response = io.BytesIO(json.dumps(self.pages[index]).encode())
        response.headers = Message()
        return response


def registry_sync(tmp_path, fail, **config):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="mcp-official", kind="mcp", url=MCP_URL, config=config)])
    waits = []
    http = HttpClient(tmp_path / "cache", opener=RegistryOpener(fixture("mcp_registry_pages.json")["pages"], fail),
                      sleep=waits.append)
    return store, CatalogSync(store, http).sync(force=True)[0], waits


def item_ids(store):
    with store.connect(True) as conn:
        return {r[0] for r in conn.execute("SELECT item_id FROM catalog_item WHERE status='active'")}


def test_mcp_registry_retries_transient_500_and_completes(tmp_path):
    store, result, waits = registry_sync(tmp_path, {1: 1})
    assert result["status"] == "completed" and waits == [1]
    assert item_ids(store) == {"mcp:io.github.acme/server-1", "mcp:io.github.acme/server-2", "mcp:com.example/tool",
                               "mcp:io.github.acme/server-5"}


def test_mcp_partial_publication_survives_a_later_failure(tmp_path):
    store, result, waits = registry_sync(tmp_path, {2: 99}, publish_every_pages=1)
    assert result["status"] == "failed" and result["error"] == "http_500" and len(waits) == 4
    assert item_ids(store) == {"mcp:io.github.acme/server-1", "mcp:io.github.acme/server-2", "mcp:com.example/tool"}
    # Without partial publication the same failure leaves nothing visible.
    empty, result, _ = registry_sync(tmp_path / "plain", {2: 99}, publish_every_pages=0)
    assert result["status"] == "failed" and item_ids(empty) == set()


def test_mcp_registry_fields_author_install_license():
    pages = fixture("mcp_registry_pages.json")["pages"]

    class Pages:
        def json(self, url, immutable=False):
            cursor = parse_qs(urlsplit(url).query).get("cursor", [None])[0]
            return pages[{None: 0, "c1": 1, "c2": 2}[cursor]]

    adapter = StructuredConnector(SourceSpec(source_id="mcp", kind="mcp", url=MCP_URL), Pages())
    first = {r.native_id: r.resource for r in adapter.fetch_page({}, {}).records}
    npm = first["io.github.acme/server-1"]
    assert npm.license is None and npm.metadata["registry_license"] == "CC0-1.0"
    assert npm.metadata["author"] == "acme"
    assert npm.install["mcp"] == {"name": "server-1", "transport": "stdio", "command": "npx", "args": ["-y", "@acme/server-1@1.0.0"]}
    assert {(f.feature, f.value) for f in npm.features} >= {("tool_kind", "mcp"), ("transport", "stdio"), ("env_required", "ACME_TOKEN")}
    remote = first["io.github.acme/server-2"]
    assert remote.install["mcp"]["url"] == "https://mcp.acme.example/2" and ("transport", "remote") in {(f.feature, f.value) for f in remote.features}
    second = adapter.fetch_page({"cursor": "c1"}, {}).records[0].resource
    assert second.metadata["author"] == "example.com" and second.install["mcp"]["command"] == "uvx"


def test_gemini_string_fields_are_typed():
    spec = SourceSpec(source_id="gemini-extensions", kind="gemini", url="https://geminicli.com/extensions.json",
                      config={"file": str(FIXTURES / "gemini_mini.json")})
    rows = {r.native_id: r.resource for r in StructuredConnector(spec, None).fetch_page({}, {}).records}
    db = rows["acme/gemini-db"]
    assert db.popularity == {"stars": 1234} and db.license == "MIT" and db.official is False
    assert db.metadata["has_mcp"] is True and db.metadata["has_hooks"] is False and db.metadata["has_skills"] is True
    official = rows["google/official-ext"]
    assert official.license == "Apache-2.0" and official.official is True and official.popularity == {"stars": 7}


def test_clawhub_maps_community_installs_and_caps_items():
    data = fixture("clawhub_mini.json")

    class One:
        def json(self, url, immutable=False):
            return data

    spec = SourceSpec(source_id="clawhub", kind="clawhub", url="https://clawhub.ai/api/v1/skills")
    page = StructuredConnector(spec, One()).fetch_page({}, {})
    rows = {r.native_id: r.resource for r in page.records}
    assert rows["alice/pdf-tools"].popularity == {"installs": 1200, "downloads": 5400, "stars": 88}
    assert rows["alice/pdf-tools"].metadata["author"] == "alice" and rows["bob/no-stats"].popularity == {}
    capped = StructuredConnector(spec.model_copy(update={"config": {"max_items": 1}}), One())
    assert capped.fetch_page({}, {}).complete is True


@pytest.mark.parametrize(("raw", "expected"), [
    ("MIT License", "MIT"), ("mit", "MIT"), (" MIT ", "MIT"), ("Apache License 2.0", "Apache-2.0"),
    ("apache-2.0", "Apache-2.0"), ("Proprietary. LICENSE.txt has complete terms", "Proprietary"),
    ("", None), (None, None), ("   ", None), ("bsd-3-clause", "BSD-3-Clause"), ("Custom", "Custom"),
])
def test_license_normalize(raw, expected):
    assert normalize_license(raw) == expected


@pytest.mark.parametrize(("name", "author"), [
    ("io.github.acme/x", "acme"), ("com.example/tool", "example.com"), ("ai.smithery/y", "smithery.ai"), ("", None),
])
def test_namespace_author(name, author):
    assert namespace_author(name) == author


def test_default_sources_cover_new_libraries():
    sources = {s.source_id: s for s in default_sources()}
    for source_id in ("wshobson-agents", "superpowers", "claude-code-plugins", "openai-skills", "voltagent-subagents",
                      "gemini-extensions", "clawhub"):
        assert sources[source_id].enabled and sources[source_id].priority <= 80
    assert sources["composio-skills"].enabled is False and sources["composio-skills"].priority == 40
    assert sources["voltagent-subagents"].config["kind_rules"]
    assert sources["mcp-official"].config["publish_every_pages"] == 10
