"""Shared small-sample statistics for the signal layer and metric engine (AN-10).

Every proportion and summary is returned as one metric object
``{value, n, k, lo, hi, basis, status}`` so the UI never receives a bare ratio.
Old Wilson implementations in ``profiling/analysis.py`` and
``products/statistics.py`` are left untouched; new code imports from here.
"""

import math
from typing import Any

Z = 1.96
INSUFFICIENT_N = 5
"""Denominators below this return ``value = None`` and ``status = insufficient``."""
INTERVAL_REQUIRED_N = 30
"""Between ``INSUFFICIENT_N`` and this bound the UI must show ``n`` with the interval."""
BASES = ("measured", "estimated", "proxy", "unknown")

Metric = dict[str, Any]


def wilson(k: int, n: int, z: float = Z) -> tuple[float | None, float | None]:
    """Wilson score interval; ``(None, None)`` when there is no denominator."""
    if not n or k is None:
        return None, None
    if k < 0 or k > n:
        raise ValueError("Wilson 区间要求 0 ≤ k ≤ n")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    # The bounds are exactly 0 / 1 at the edges; avoid 0.9999999 float residue.
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return lo, hi


def wilson_lo(k: int, n: int, z: float = Z) -> float | None:
    return wilson(k, n, z)[0]


def _check_basis(basis: str) -> str:
    if basis not in BASES:
        raise ValueError(f"未知的 basis：{basis}")
    return basis


def proportion(k: int | None, n: int | None, *, basis: str = "measured",
               min_n: int = INSUFFICIENT_N) -> Metric:
    """Pooled proportion ``k / n`` with a Wilson interval and an explicit sample gate.

    ``None`` inputs mean the evidence is unavailable; they never become ``0``.
    """
    basis = _check_basis(basis)
    if k is None or n is None:
        return {"value": None, "n": n, "k": k, "lo": None, "hi": None,
                "basis": "unknown", "status": "unknown", "kind": "proportion"}
    if n < min_n:
        return {"value": None, "n": n, "k": k, "lo": None, "hi": None,
                "basis": basis, "status": "insufficient", "kind": "proportion"}
    lo, hi = wilson(k, n)
    return {"value": k / n, "n": n, "k": k, "lo": lo, "hi": hi, "basis": basis,
            "status": "ok", "kind": "proportion",
            "interval": "wilson", "show_n": n < INTERVAL_REQUIRED_N}


def count(value: int | None, *, n: int | None = None, basis: str = "measured") -> Metric:
    """Counts have no interval; ``None`` stays unknown instead of zero."""
    basis = _check_basis(basis)
    return {"value": value, "n": n if n is not None else value, "k": None, "lo": None,
            "hi": None, "basis": basis if value is not None else "unknown",
            "status": "ok" if value is not None else "unknown", "kind": "count"}


def median(values: list[float] | None, *, basis: str = "measured",
           min_n: int = INSUFFICIENT_N) -> Metric:
    """Median with the same sample gate; the range is reported as ``lo``/``hi``."""
    basis = _check_basis(basis)
    if values is None:
        return {"value": None, "n": None, "k": None, "lo": None, "hi": None,
                "basis": "unknown", "status": "unknown", "kind": "median"}
    clean = sorted(v for v in values if v is not None)
    n = len(clean)
    if n < min_n:
        return {"value": None, "n": n, "k": None, "lo": None, "hi": None,
                "basis": basis, "status": "insufficient", "kind": "median"}
    mid = n // 2
    value = clean[mid] if n % 2 else (clean[mid - 1] + clean[mid]) / 2
    return {"value": value, "n": n, "k": None, "lo": clean[0], "hi": clean[-1],
            "basis": basis, "status": "ok", "kind": "median", "interval": "range"}
