"""Source selection is explicit; no filesystem discovery or network on import."""

from ..contracts import SourceSpec


def default_sources() -> list[SourceSpec]:
    """Codex custom prompts have no public registry (`~/.codex/prompts` is local; inventory scans it)."""
    return [
        SourceSpec(source_id="orbit-seeds", kind="bundle", url="bundled:skills.json", priority=100),
        # Orbit's reviewed remedy templates; the gateway points config.file at the recommend KB.
        SourceSpec(source_id="orbit-kb", kind="kb", url="bundled:official.v1.json", priority=100),
        SourceSpec(source_id="anthropic-skills", kind="github", url="https://github.com/anthropics/skills", priority=90,
                   config={"repo": "anthropics/skills", "agents": ["claude_code", "codex"], "official": True}),
        SourceSpec(source_id="claude-plugins", kind="github", url="https://github.com/anthropics/claude-plugins-official", priority=90,
                   config={"repo": "anthropics/claude-plugins-official", "agents": ["claude_code"],
                           "marketplace": ".claude-plugin/marketplace.json", "official": True}),
        SourceSpec(source_id="openai-plugins", kind="github", url="https://github.com/openai/plugins", priority=90,
                   config={"repo": "openai/plugins", "agents": ["codex"], "marketplace": ".agents/plugins/marketplace.json", "official": True}),
        SourceSpec(source_id="awesome-copilot", kind="github", url="https://github.com/github/awesome-copilot", priority=80,
                   config={"repo": "github/awesome-copilot", "agents": ["copilot"], "marketplace": ".github/plugin/marketplace.json"}),
        SourceSpec(source_id="wshobson-agents", kind="github", url="https://github.com/wshobson/agents", priority=75,
                   config={"repo": "wshobson/agents", "agents": ["claude_code"]}),
        SourceSpec(source_id="superpowers", kind="github", url="https://github.com/obra/superpowers", priority=75,
                   config={"repo": "obra/superpowers", "agents": ["claude_code"]}),
        SourceSpec(source_id="claude-code-plugins", kind="github", url="https://github.com/anthropics/claude-code", priority=80,
                   config={"repo": "anthropics/claude-code", "agents": ["claude_code"], "official": True}),
        SourceSpec(source_id="openai-skills", kind="github", url="https://github.com/openai/skills", priority=80,
                   config={"repo": "openai/skills", "agents": ["codex"], "official": True}),
        SourceSpec(source_id="voltagent-subagents", kind="github", url="https://github.com/VoltAgent/awesome-claude-code-subagents",
                   priority=60, config={"repo": "VoltAgent/awesome-claude-code-subagents", "agents": ["claude_code"],
                                        "kind_rules": [{"glob": "categories/*/*.md", "type": "subagent"}]}),
        # Large and uneven in quality: listed but off until the user enables it.
        SourceSpec(source_id="composio-skills", kind="github", url="https://github.com/ComposioHQ/awesome-claude-skills",
                   priority=40, enabled=False, config={"repo": "ComposioHQ/awesome-claude-skills", "agents": ["claude_code"]}),
        SourceSpec(source_id="mcp-official", kind="mcp", url="https://registry.modelcontextprotocol.io/v0.1/servers", priority=90, refresh_seconds=3600,
                   config={"publish_every_pages": 10, "max_pages": 120}),
        SourceSpec(source_id="gemini-extensions", kind="gemini", url="https://geminicli.com/extensions.json", priority=70),
        # The only default source with per-item community install counts (top N only).
        SourceSpec(source_id="clawhub", kind="clawhub", url="https://clawhub.ai/api/v1/skills", priority=60,
                   config={"max_items": 500}),
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
