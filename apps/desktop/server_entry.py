"""Frozen ``tandem-helper`` entry: ``gateway`` | ``worker ingest`` | ``worker analysis``.

The gateway re-executes this same binary for workers (``sys.frozen``), see
``tandem_backend.services.supervisor.worker_command``.
"""

import multiprocessing
import sys

from tandem_backend.services.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
