"""Shared coverage contract for observed inputs, independent of Agent and presentation.

None means no usable input, zero means an observed empty set. Gaps make provided
inputs partial; an explicit exclusion takes precedence. This is never a job/tool
success status, nor a guarantee of semantic inference accuracy.
"""

from collections.abc import Iterable, Mapping

COVERAGE_CONTRACT = "input-coverage-v1"
STATUSES = frozenset({"available", "partial", "unavailable", "excluded"})


def dataset_coverage(
    rows: int | None,
    *,
    excluded: bool = False,
    reasons: Iterable[str] = (),
    reason_counts: Mapping[str, int] | None = None,
) -> dict:
    if rows is not None and (isinstance(rows, bool) or not isinstance(rows, int) or rows < 0):
        raise ValueError("coverage rows must be a nonnegative integer or None")
    if not isinstance(excluded, bool):
        raise ValueError("coverage excluded must be an explicit boolean")
    if isinstance(reasons, str):
        raise ValueError("coverage reasons must be a sequence of codes")
    reasons = tuple(reasons)
    counts = dict(reason_counts or {})
    if any(not isinstance(code, str) or not code for code in (*reasons, *counts)):
        raise ValueError("coverage reasons must be nonempty machine-readable codes")
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in counts.values()):
        raise ValueError("coverage reason counts must be nonnegative integers")
    codes = list(
        dict.fromkeys(
            [code for code in reasons if counts.get(code, 1)]
            + [code for code, n in counts.items() if n]
        )
    )
    if any(not isinstance(code, str) or not code for code in (*codes, *counts)):
        raise ValueError("coverage reasons must be nonempty machine-readable codes")
    status = (
        "excluded"
        if excluded
        else "unavailable"
        if rows is None
        else "partial"
        if codes
        else "available"
    )
    if not codes and status in ("excluded", "unavailable"):
        codes = ["excluded_by_scope" if excluded else "input_not_provided"]
    return {
        "status": status,
        "rows": rows,
        "reasons": codes,
        "reason_counts": {code: n for code, n in counts.items() if n},
    }
