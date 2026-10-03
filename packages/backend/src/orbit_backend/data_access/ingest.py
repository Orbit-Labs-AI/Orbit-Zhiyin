"""Application commands compose acquisition and publication; no native format logic here."""

from pathlib import Path

from orbit_data.bridge import import_connector
from orbit_data.cli import statistics
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store


def ingest(home: Path, agent: str, root: Path, *, limit=None, progress=None):
    root, home = root.expanduser().resolve(), home.expanduser().resolve()
    if home.is_relative_to(root) or root.is_relative_to(home):
        raise ValueError("来源目录和 Orbit 数据目录必须分开")
    with Store(home) as store:
        result = ImportService(store, progress=progress).import_source(ImportRequest(agent, root, limit=limit))
        return {"import": result, "stored": statistics(store)}


def ingest_staging(home: Path, staging: Path, *, progress=None):
    with Store(home) as store:
        with ImportService(store).writer():
            result = import_connector(store, staging)
            store.rebuild(progress=progress)
            return {"import": result, "stored": statistics(store)}


def maintain(home: Path, command: str, *, progress=None):
    with Store(home) as store:
        with ImportService(store).writer():
            if command in ("init", "rebuild"):
                store.rebuild(progress=progress)
            return store.verify() if command == "verify" else statistics(store)
