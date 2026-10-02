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


def recorded(store: Any, engine: str, request: dict, compute: Callable[[], dict]) -> dict:
    """Persist every success or failure; identical successful results share only their payload."""
    history = history_for(store)
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
