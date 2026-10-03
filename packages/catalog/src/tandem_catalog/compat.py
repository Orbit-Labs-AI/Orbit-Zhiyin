"""Agent support matrix of a catalog item: declared by the source, or inferred from the file format.

A source declares agents (``SourceSpec.config.agents``: anthropics/skills → claude_code ...). Many
resources are written in an open format that other agents read unchanged; for those the support is
inferred from the format, and only when the reader is visible in vendored upstream source
(``third_party/``, pinned in ``third_party/README.md``). An agent whose reader we could not read in
source (Kimi CLI, Cursor, Gemini CLI, Copilot are not vendored) is reported as ``unknown`` with
basis ``unverified``, never as supported.

Support values follow ``tandem_backend.recommend.contracts`` (native / manual /
adaptation_required / unsupported / unknown). ``native`` = the agent loads the file as is.
"""

import re
from pathlib import PurePosixPath

# Format readers with the upstream source that shows the agent loading that format unchanged.
# None = the agent is believed to read the format but its source is not vendored: unverified.
SKILL_READERS = {  # Agent Skills open standard: <dir>/SKILL.md with name/description front matter.
    "claude_code": "Agent Skills originate in Claude Code (claude-agent-sdk-python/src/claude_agent_sdk/types.py `skills`)",
    "codex": "third_party/codex/codex-rs/skills/src/loading.rs (.agents/skills/<name>/SKILL.md, selection_tests.rs)",
    "opencode": "third_party/opencode/packages/opencode/src/skill/index.ts (.claude|.agents/skills/**/SKILL.md)",
    "hermes": "third_party/hermes-agent/agent/skill_utils.py (SKILL.md under HERMES_HOME/skills)",
    "dsh": "third_party/deepseek-harness/packages/skill/skill-filesystem/src/index.ts (.dsh/skills, .agents/skills)",
    "pi": "third_party/pi/packages/coding-agent/src/core/skills.ts (~/.pi/agent/skills, .pi/skills)",
    "kimi": None, "cursor": None, "gemini": None, "copilot": None,
}
MCP_READERS = {  # Model Context Protocol clients (stdio / streamable HTTP servers).
    "claude_code": "claude-agent-sdk-python/src/claude_agent_sdk/types.py (McpServerConfig)",
    "codex": "third_party/codex/codex-rs/rmcp-client (config.toml [mcp_servers])",
    "opencode": "third_party/opencode/packages/opencode/src/mcp/catalog.ts",
    "hermes": "third_party/hermes-agent/hermes_cli/mcp_picker.py (config.yaml mcp_servers)",
    "dsh": "third_party/deepseek-harness/packages/mcp/mcp-client/src/connection.ts",
    "pi": "third_party/pi/packages/coding-agent/src/extensions/mcp/config.ts (mcp.json mcpServers)",
    "kimi": None, "cursor": None, "gemini": None, "copilot": None,
}
AGENTS_MD_READERS = {  # AGENTS.md project instructions.
    "codex": "third_party/codex/codex-rs/core/src/context/user_instructions.rs",
    "opencode": "third_party/opencode/packages/opencode/src/session/instruction.ts",
    "hermes": "third_party/hermes-agent/agent/subdirectory_hints.py (_HINT_FILENAMES)",
    "dsh": "third_party/deepseek-harness/packages/context/agent-instructions/src/config.ts",
    "pi": "third_party/pi/packages/coding-agent/src/core/resource-loader.ts (AGENTS.md, CLAUDE.md candidates)",
    "kimi": None, "cursor": None, "copilot": None, "gemini": None,
}
CLAUDE_MD_READERS = {  # CLAUDE.md is read by agents that also accept Claude Code's file name.
    "hermes": AGENTS_MD_READERS["hermes"],
    "dsh": AGENTS_MD_READERS["dsh"] + " (DEFAULT_INSTRUCTION_FILE_CANDIDATES)",
    "pi": AGENTS_MD_READERS["pi"],
}
CLAUDE_HOOK_READERS = {  # Claude Code hooks.json ({hooks: {PreToolUse: [{matcher, hooks: [...]}]}}).
    "dsh": "third_party/deepseek-harness/packages/hooks/hooks-claude-code/src/config.ts (runs CC command hooks)",
}
# Codex has its own hooks.json engine with the same event names but its own tool names in matchers.
CLAUDE_HOOK_ADAPT = {"codex": "third_party/codex/codex-rs/hooks/src/engine (own hooks.json; matchers differ)"}

FORMAT_READERS = {"agent_skill": SKILL_READERS, "mcp": MCP_READERS, "agents_md": AGENTS_MD_READERS,
                  "claude_md": CLAUDE_MD_READERS, "claude_hooks": CLAUDE_HOOK_READERS}
SUPPORTED = ("native", "manual")
_BLOB = re.compile(r"/(?:blob|tree)/[0-9a-f]{7,40}/(.+)$")


def resource_format(kind: str, url: str | None = None, agents=(), repo_path: str | None = None) -> str | None:
    """Open format of the item when its file is one other agents read unchanged, else None."""
    path = repo_path or ""
    if not path and url:
        match = _BLOB.search(url)
        path = match.group(1) if match else ""
    name = PurePosixPath(path).name.lower() if path else ""
    if kind == "skill":
        return "agent_skill"  # Every catalog skill is a SKILL.md directory (sources/github.file_kind).
    if kind == "mcp_server":
        return "mcp"
    if kind == "rule":
        if name == "agents.md":
            return "agents_md"
        if name == "claude.md":
            return "claude_md"
        return None  # .mdc (Cursor), *.instructions.md (Copilot): agent-specific front matter.
    if kind == "hook" and "claude_code" in agents and (not name or name.endswith(".json")):
        return "claude_hooks"
    return None


LEVELS = ("native", "manual", "adaptation_required", "unsupported")


def support_matrix(kind: str, agents, url: str | None = None, repo_path: str | None = None,
                   declared: dict | None = None) -> dict:
    """agent -> {"support", "basis", "evidence"}; agents absent from the matrix are unknown.

    Listed agents are the source's declaration (``native``). Format inference adds agents whose
    reader is in vendored source (``native``, basis ``format``) or not (``unknown``, ``unverified``).
    A listed agent that the format table marks unverified stays ``native``: its source declared it.
    """
    agents = list(dict.fromkeys(agents or ()))
    fmt = resource_format(kind, url, agents, repo_path)
    out = {agent: {"support": "native", "basis": "source_declared", "evidence": "source agents"} for agent in agents}
    for agent, evidence in (FORMAT_READERS.get(fmt) or {}).items():
        if agent in out:
            if evidence:
                out[agent]["evidence"] = evidence
            continue
        out[agent] = ({"support": "native", "basis": "format:" + fmt, "evidence": evidence} if evidence else
                      {"support": "unknown", "basis": "unverified", "evidence": f"{fmt} reader not vendored"})
    if fmt == "claude_hooks":
        for agent, evidence in CLAUDE_HOOK_ADAPT.items():
            out.setdefault(agent, {"support": "adaptation_required", "basis": "format:claude_hooks", "evidence": evidence})
    # A per-agent level the publisher states (Tandem KB metadata.agent_support) wins over inference.
    for agent, level in (declared or {}).items():
        if level in LEVELS and agent != "generic":
            out[str(agent)] = {"support": level, "basis": "declared_level", "evidence": "metadata.agent_support"}
    return out


def supported_agents(kind: str, agents, url: str | None = None, repo_path: str | None = None) -> list[str]:
    """Agents with native/manual support (declared or format-verified); the eligibility set."""
    matrix = support_matrix(kind, agents, url, repo_path)
    return sorted(agent for agent, row in matrix.items() if row["support"] in SUPPORTED)


# Install locations an agent reads without extra configuration (user scope, then project scope),
# from the same upstream sources as the reader tables above.
SKILL_DIRS = {
    "claude_code": ("~/.claude/skills/{name}/SKILL.md", ".claude/skills/{name}/SKILL.md"),
    "codex": ("~/.agents/skills/{name}/SKILL.md", ".agents/skills/{name}/SKILL.md"),
    "opencode": ("~/.config/opencode/skills/{name}/SKILL.md", ".opencode/skills/{name}/SKILL.md"),
    "hermes": ("~/.hermes/skills/{name}/SKILL.md", None),
    "dsh": ("~/.dsh/skills/{name}/SKILL.md", ".dsh/skills/{name}/SKILL.md"),
    "pi": ("~/.pi/agent/skills/{name}/SKILL.md", ".pi/skills/{name}/SKILL.md"),
}
RULE_FILES = {  # Project instructions file; rules are appended as a section, never overwrite it.
    "claude_code": ("~/.claude/CLAUDE.md", "CLAUDE.md"),
    "codex": ("~/.codex/AGENTS.md", "AGENTS.md"),
    "opencode": ("~/.config/opencode/AGENTS.md", "AGENTS.md"),
    "hermes": (None, "AGENTS.md"),
    "dsh": ("~/.dsh/AGENTS.md", "AGENTS.md"),
    "pi": ("~/.pi/agent/AGENTS.md", "AGENTS.md"),
    "copilot": (None, ".github/copilot-instructions.md"),
    "cursor": (None, ".cursor/rules/{name}.mdc"),
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:64] or "item"


def install_targets(kind: str, name: str, matrix: dict) -> list[dict]:
    """Per-agent install target paths for skills and rules (other types install via their manifest).

    Only agents with native/manual support get a path; others are omitted rather than guessed.
    """
    table, mode = (SKILL_DIRS, "copy_dir") if kind == "skill" else (RULE_FILES, "append_section") if kind == "rule" \
        else (None, None)
    if table is None:
        return []
    slug = _slug(name)
    out = []
    for agent in sorted(matrix):
        if matrix[agent]["support"] not in SUPPORTED or agent not in table:
            continue
        user, project = table[agent]
        out.append({"agent": agent, "mode": mode, "user_path": user.format(name=slug) if user else None,
                    "project_path": project.format(name=slug) if project else None})
    return out
