"""Tandem's local, source-backed data contract. See docs/data-contract.md."""

CONTRACT_VERSION = 1
MAPPER_VERSION = "1.3.2"
REDUCER_VERSION = "1.2.0"

# A connector-only fix must not invalidate unrelated multi-gigabyte source projections.
MAPPER_VERSIONS = {
    agent: "1.3.1" for agent in ("claude_code", "dsh", "pi", "hermes", "opencode", "kimi")
}
MAPPER_VERSIONS["codex"] = "1.3.2"


def mapper_version_for(agent: str) -> str:
    return MAPPER_VERSIONS.get(agent, MAPPER_VERSION)
