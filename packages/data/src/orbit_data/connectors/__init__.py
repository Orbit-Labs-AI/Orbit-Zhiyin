"""Native connectors.

Approval evidence per agent (what permission.request / permission.decision can carry;
checked against third_party sources). Where nothing is recorded, a prompt that would
have been shown ("would_prompt") cannot be measured from the logs and must stay unknown:

- claude_code: only refusals (``toolDenialKind`` on the tool result) -> decision denied;
  approvals and the prompt itself are not written to the transcript.
- codex: exec/apply_patch approval request + response events (ReviewDecision).
- dsh: ``approval/asked`` / ``approval/decided`` records.
- kimi: ``interaction.request`` (kind=approval) / ``interaction.resolved`` and
  ``permission.record_approval_result`` (ApprovalResponse.decision).
- opencode: no per-call approval record (the ``permission`` table holds saved "always"
  rules); only refusals are recoverable, from the exact PermissionV1 error messages
  stored as the tool error -> decision denied. Granted prompts are invisible.
- hermes: terminal results only: ``status: blocked`` (denied), ``pending_approval``
  (request), and the ``approval`` note on approved flagged commands. Other tools never
  prompt.
- pi: no permission system and no approval entries in the session format.
"""

from orbit_data.connectors.claude_code import ClaudeMapper
from orbit_data.connectors.codex import CodexMapper
from orbit_data.connectors.dsh import DshMapper
from orbit_data.connectors.hermes import HermesMapper
from orbit_data.connectors.kimi import KimiMapper
from orbit_data.connectors.opencode import OpenCodeMapper
from orbit_data.connectors.pi import PiMapper

MAPPERS = {
    "claude_code": ClaudeMapper,
    "codex": CodexMapper,
    "dsh": DshMapper,
    "pi": PiMapper,
    "kimi": KimiMapper,
    "hermes": HermesMapper,
    "opencode": OpenCodeMapper,
}


def register_mapper(agent: str, factory):
    """Add a connector implementing prepare(records) and map(RawRecord)->Mapping."""
    if agent in MAPPERS:
        raise ValueError(f"Connector already registered for {agent}")
    MAPPERS[agent] = factory
