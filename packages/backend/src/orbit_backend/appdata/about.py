"""``GET /v1/app/about`` (SET-13 / HLP-02): versions of every rule set and contract.

Only reads constants already defined by the packages; never touches the network. Update
checks are not part of the local app contract yet, so ``update`` stays null.
"""

from __future__ import annotations

import platform
import sys


def about() -> dict:
    from orbit_data import MAPPER_VERSION, REDUCER_VERSION
    from orbit_data import SCHEMA_VERSION as DB_SCHEMA
    from orbit_data.connectors import MAPPERS

    from orbit_catalog import CONTRACT_VERSION as CATALOG_CONTRACT
    from orbit_catalog.store import SCHEMA_VERSION as CATALOG_SCHEMA

    from .. import __version__, privacy_rules
    from ..ai.generate.tasks import PROMPT_VERSION
    from ..analytics import FEATURE_VERSION
    from ..features.vocab import VOCAB_VERSION
    from ..services.sections import rules_digest

    return {
        "app": {"name": "Orbit", "version": __version__, "contract": "orbit-app-v1"},
        "components": {
            "rules_version": rules_digest(), "analytics_version": FEATURE_VERSION,
            "redaction_version": privacy_rules.VERSION, "prompt_version": PROMPT_VERSION,
            "db_schema_version": DB_SCHEMA, "mapper_version": MAPPER_VERSION,
            "reducer_version": REDUCER_VERSION, "catalog_schema_version": CATALOG_SCHEMA,
            "catalog_contract": CATALOG_CONTRACT, "feature_vocab": VOCAB_VERSION,
            "mappers": sorted(MAPPERS)},
        "runtime": {"python": platform.python_version(), "platform": sys.platform,
                    "arch": platform.machine()},
        "update": {"channel": None, "available": None, "checked_at": None},
    }
