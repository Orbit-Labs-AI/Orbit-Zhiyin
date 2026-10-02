"""Tandem's local, source-backed data contract. See docs/contracts/data.md."""

CONTRACT_VERSION = 1
SCHEMA_VERSION = 7
MAPPER_VERSION = "1.4.0"
REDUCER_VERSION = "1.2.0"

# Shared source-index integration starts a new baseline. Future fixes can advance
# one connector without invalidating unrelated source projections.
MAPPER_VERSIONS = {
    agent: "1.4.0" for agent in ("codex", "claude_code", "dsh", "pi", "hermes", "opencode", "kimi")
}


def mapper_version_for(agent: str) -> str:
    return MAPPER_VERSIONS.get(agent, MAPPER_VERSION)
