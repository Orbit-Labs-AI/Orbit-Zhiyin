"""Install module: environment, landing table, fetch, plan/preview/apply/revert.

Other modules use the narrow functions below; they delegate to one process-wide
``InstallService`` set by the gateway (``routes_install.router``) or, outside the gateway,
built lazily on ``$TANDEM_HOME/app.db``.
"""

from __future__ import annotations

import json
import threading

from .errors import ApplyFailed, InstallError, OpConflict, PlanError, RiskBlocked, StaleError
from .service import InstallService

_default: InstallService | None = None
_lock = threading.Lock()


def set_default_service(service: InstallService | None) -> None:
    global _default
    _default = service


def get_default_service() -> InstallService:
    global _default
    with _lock:
        if _default is None:
            from tandem_data.paths import default_home  # noqa: PLC0415

            from ..appdb import AppDB  # noqa: PLC0415

            home = default_home()
            _default = InstallService(AppDB(home / "app.db"), home)
        return _default


def environment(refresh: bool = False) -> dict:
    return get_default_service().environment(refresh)


def plan(source: dict, **kw) -> dict:
    return get_default_service().plan(source, **kw)


def preview(plan_id: str, **kw) -> dict:
    return get_default_service().preview(plan_id, **kw)


def apply(plan_id: str, preview_digest: str, **kw) -> dict:
    return get_default_service().apply(plan_id, preview_digest, **kw)


def revert(install_id: str, **kw) -> dict:
    return get_default_service().revert(install_id, **kw)


def cli(args) -> None:
    """``tandem install environment|ledger``: read-only views for the terminal."""
    from ..appdb import AppDB  # noqa: PLC0415

    appdb = AppDB(args.home / "app.db")
    try:
        service = InstallService(appdb, args.home)
        if args.install_command == "environment":
            info = service.environment()
            if args.json:
                print(json.dumps(info, ensure_ascii=False, indent=2))
                return
            for agent in info["agents"]:
                mark = "+" if agent["installed"] else "-"
                print(f"{mark} {agent['name']:<12} {agent.get('version') or '?':<10} {agent['install_support']:<9} "
                      f"{agent['root']}")
        else:
            for entry in service.ledger(limit=args.limit)["entries"]:
                print(json.dumps({k: entry[k] for k in ("ts", "action", "install_id", "target_idx", "path", "note")},
                                 ensure_ascii=False))
    finally:
        appdb.close()


__all__ = ["ApplyFailed", "InstallError", "InstallService", "OpConflict", "PlanError", "RiskBlocked", "StaleError",
           "apply", "environment", "get_default_service", "plan", "preview", "revert", "set_default_service"]
