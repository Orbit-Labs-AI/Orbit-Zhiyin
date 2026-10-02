"""Source selection is explicit; no filesystem discovery or network on import."""

from ..contracts import SourceSpec


def default_sources() -> list[SourceSpec]:
    return [
        SourceSpec(source_id="tandem-seeds", kind="bundle", url="bundled:skills.json", priority=100),
        # Tandem's reviewed remedy templates; the gateway points config.file at the recommend KB.
        SourceSpec(source_id="tandem-kb", kind="kb", url="bundled:official.v1.json", priority=100),
        SourceSpec(source_id="anthropic-skills", kind="github", url="https://github.com/anthropics/skills", priority=90,
                   config={"repo": "anthropics/skills", "agents": ["claude_code", "codex"], "official": True}),
        SourceSpec(source_id="claude-plugins", kind="github", url="https://github.com/anthropics/claude-plugins-official", priority=90,
                   config={"repo": "anthropics/claude-plugins-official", "agents": ["claude_code"],
                           "marketplace": ".claude-plugin/marketplace.json", "official": True}),
        SourceSpec(source_id="openai-plugins", kind="github", url="https://github.com/openai/plugins", priority=90,
                   config={"repo": "openai/plugins", "agents": ["codex"], "marketplace": ".agents/plugins/marketplace.json", "official": True}),
        SourceSpec(source_id="awesome-copilot", kind="github", url="https://github.com/github/awesome-copilot", priority=80,
                   config={"repo": "github/awesome-copilot", "agents": ["copilot"], "marketplace": ".github/plugin/marketplace.json"}),
        SourceSpec(source_id="mcp-official", kind="mcp", url="https://registry.modelcontextprotocol.io/v0.1/servers", priority=90, refresh_seconds=3600),
        SourceSpec(source_id="models-dev", kind="models_dev", url="https://models.dev/api.json", priority=80),
        SourceSpec(source_id="litellm", kind="litellm", url="https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json", priority=80),
        SourceSpec(source_id="swe-bench", kind="swe_bench", url="https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json", priority=80),
    ]


def connector(source: SourceSpec, http):
    if source.kind == "github":
        from .github import GitHubConnector
        return GitHubConnector(source, http)
    from .structured import StructuredConnector
    return StructuredConnector(source, http)
