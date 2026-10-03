"""``orbit-helper`` entry: ``gateway`` | ``worker ingest`` | ``worker analysis``.

One frozen executable serves every role, so the gateway can start workers from its own
path. Development uses ``python -m orbit_backend.services …`` with the same arguments.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from orbit_data.paths import default_home

    parser = argparse.ArgumentParser(prog="orbit-helper")
    parser.add_argument("--home", type=Path, default=None, help="data directory")
    roles = parser.add_subparsers(dest="role", required=True)
    gateway = roles.add_parser("gateway", help="HTTP + SSE gateway on 127.0.0.1")
    gateway.add_argument("--home", type=Path, default=None, dest="role_home")
    gateway.add_argument("--port", type=int, default=0, help="0 picks a free port")
    gateway.add_argument("--assets", type=Path, default=None,
                         help="single-file UI served at /app and /lite (else $ORBIT_ASSETS)")
    worker = roles.add_parser("worker", help="supervised child process (stdio JSON Lines)")
    worker.add_argument("kind", choices=("ingest", "analysis"))
    worker.add_argument("--home", type=Path, default=None, dest="role_home")
    args = parser.parse_args(argv)
    home = (args.role_home or args.home or default_home()).expanduser().resolve()
    if args.role == "gateway":
        from .gateway import run_gateway
        from .pages import ASSETS_ENV

        if args.assets is not None:
            os.environ[ASSETS_ENV] = str(args.assets.expanduser().resolve())

        return run_gateway(home, port=args.port)
    if args.kind == "ingest":
        from .worker_ingest import main as ingest

        return ingest(home)
    from .worker_analysis import main as analysis

    return analysis(home)


if __name__ == "__main__":
    sys.exit(main())
