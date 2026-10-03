"""Gateway-owned application database ``app.db``.

``orbit.db`` has one writer (ingest-worker) and ``analysis.sqlite`` has one writer
(analysis-worker). User-driven state that is not derivable from them — recommendation
runs and exposures, labels, install plans and the install ledger, AI artifacts and usage,
local telemetry — lives here, written only by the gateway process.

Each module owns ``schema/<module>.sql``: idempotent DDL (``CREATE ... IF NOT EXISTS``)
applied in file-name order on open; the applied digest is recorded in ``module_schema``.
"""

from .store import AppDB

__all__ = ["AppDB"]
