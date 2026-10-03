"""Orbit's local, source-backed data contract. See docs/data-contract.md."""

CONTRACT_VERSION = 1
SCHEMA_VERSION = 15
MAPPER_VERSION = "1.6.1"
REDUCER_VERSION = "1.9.1"
CONTRACT_ID = "orbit-session-v1"

from orbit_data import legacy as _legacy  # noqa: E402

_legacy.adopt_env()  # TANDEM_* settings from before the rename still apply
