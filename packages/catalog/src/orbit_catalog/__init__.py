"""Local resource acquisition and retrieval; independent of session analysis and UI."""

import atexit
import threading
from pathlib import Path

CONTRACT_VERSION = "catalog-v1"
_SERVICES: dict = {}
_LOCK = threading.Lock()


def get_service(path, **kwargs):
    """One CatalogService per resolved catalog.db path (jobs, writer lock and index are shared)."""
    from .service import CatalogService

    key = str(Path(path).expanduser().resolve())
    with _LOCK:
        if key not in _SERVICES:
            if not _SERVICES:
                atexit.register(_close_all)
            _SERVICES[key] = CatalogService(key, **kwargs)
        return _SERVICES[key]


def _close_all():
    with _LOCK:
        for service in _SERVICES.values():
            service.close()
        _SERVICES.clear()
