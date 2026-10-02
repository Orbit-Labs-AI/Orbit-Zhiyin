from tandem_data.connectors.claude_code import ClaudeMapper
from tandem_data.connectors.codex import CodexMapper
from tandem_data.connectors.dsh import DshMapper
from tandem_data.connectors.hermes import HermesMapper
from tandem_data.connectors.kimi import KimiMapper
from tandem_data.connectors.opencode import OpenCodeMapper
from tandem_data.connectors.pi import PiMapper

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
