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
