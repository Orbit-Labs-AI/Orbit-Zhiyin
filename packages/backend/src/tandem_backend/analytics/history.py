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


def runtime() -> dict:
    return {
        "python": python_version(),
        **{
            name: version(name)
            for name in ("tandem-backend", "tandem-data", "jieba", "numpy", "scipy", "scikit-learn")
        },
    }


def cache_key(store: Any, engine: str, request: dict) -> tuple[str, str] | None:
    """(request_key, input_fp) for canonical stores; legacy stores are never cached."""
    from tandem_data.analysis_fingerprint import digest, fingerprints

    from .cache import algo_version, supports_cache

    if not supports_cache(store):
        return None
    return digest(engine, request, algo_version()), fingerprints(store.home).input_fp()


def recorded(
    store: Any,
    engine: str,
    request: dict,
    compute: Callable[[], dict],
    *,
    key: tuple[str, str] | None = None,
) -> dict:
    """Serve a verified cached result for the same request and input, else compute and record.

    A hit records only a light run that points at the existing snapshot; no payload is
    written again. Every computation, success or failure, is still recorded.
    """
    history = history_for(store)
    request = {**request, "runtime": runtime()}
    key = key or cache_key(store, engine, request)
    request_key, input_fp = key or (None, None)
    if key is not None:
        hit = history.cached_run(engine, request_key, input_fp)
        if hit is not None:
            result = history.result(hit["run_id"])  # checksum errors propagate
            history.record_hit(
                engine,
                request,
                request_key=request_key,
                input_fp=input_fp,
                snapshot_id=hit["snapshot_id"],
            )
            return result
    run_id = history.start(engine, request, request_key=request_key, input_fp=input_fp)
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
