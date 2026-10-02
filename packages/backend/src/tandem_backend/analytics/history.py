"""Persist public store-based analyses while keeping pure family functions side-effect free."""

from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from platform import python_version
from typing import Any

from tandem_data.analysis_history import AnalysisHistory


def history_for(store: Any) -> AnalysisHistory:
    """Keep derived history separate from canonical facts and from native source directories."""
    home = getattr(store, "home", None)
    if isinstance(home, (str, Path)):
        return AnalysisHistory(Path(home) / "analysis.sqlite")
    path = getattr(store, "path", None)
    if isinstance(path, (str, Path)):
        path = Path(path)
        return AnalysisHistory(path.with_name(path.stem + ".analysis.sqlite"))
    raise ValueError("Persistent analysis requires a store home or database path")


def data_revision(store: Any) -> list[int] | None:
    """Published canonical revision (projection run, inventory scan), or None when unknown."""
    home = getattr(store, "home", None)
    if not isinstance(home, (str, Path)) or not hasattr(store, "analysis_bundle"):
        return None
    path = Path(home) / "tandem.db"
    if not path.is_file():
        return None
    import sqlite3

    from tandem_data.store import readonly_connection

    try:
        with readonly_connection(path) as db:
            run = db.execute("SELECT MAX(run_id) FROM projection_run").fetchone()[0]
            scan = db.execute("SELECT COALESCE(MAX(scan_id),0) FROM inventory_scan").fetchone()[0]
    except sqlite3.Error:
        return None
    return None if run is None else [run, scan]


def recorded(store: Any, engine: str, request: dict, compute: Callable[[], dict], *,
             reuse: bool = False) -> dict:
    """Persist every success or failure; identical successful results share only their payload.

    With ``reuse`` and a known canonical revision, an identical completed request (same
    scope, revision and runtime) is served from its verified snapshot instead of recomputed."""
    history = history_for(store)
    revision = data_revision(store) if reuse else None
    if revision is not None:
        request = {**request, "data_revision": revision}
    request = {
        **request,
        "runtime": {
            "python": python_version(),
            **{
                name: version(name)
                for name in (
                    "tandem-backend",
                    "tandem-data",
                    "jieba",
                    "numpy",
                    "scipy",
                    "scikit-learn",
                )
            },
        },
    }
    if revision is not None and (hit := history.reuse(engine, request)) is not None:
        return hit[1]
    run_id = history.start(engine, request)
    try:
        result = compute()
        history.complete(run_id, result)
        return result
    except BaseException as error:
        try:
            history.fail(run_id, error)
        except Exception as storage_error:
            error.add_note(f"Recording the failure also failed: {type(storage_error).__name__}")
            raise error from storage_error
        raise
