"""AN-06 problem upgrade: aggregate signals by ``(type, key, scope, scope_id)``.

Upgrade iff ``sessions ≥ min_sessions`` and ``wilson_lo(sessions, denom) ≥ 0.05`` where
``denom`` counts sessions that had the opportunity for the signal kind and whose
detector evidence was available. ``label`` rows (resolved / dismissed) are read only.
"""

from collections import defaultdict
from typing import Any

from ...models import stable_id
from ..stats import proportion, wilson_lo
from .dictionary import PROBLEM_TYPES, RULES_VERSION, SCOPES, SIGNAL_KINDS, WILSON_LO_MIN

Record = dict[str, Any]
WEEK_MS = 7 * 24 * 3600 * 1000
LABELS = ("resolved", "dismissed")


def problem_id(problem_type: str, key: str, scope: str, scope_id: str) -> str:
    return stable_id(problem_type, key, scope, scope_id)


def _scope_ids(fact: Record, scope: str) -> str | None:
    return {"all": "all", "project": fact.get("project_id"), "source": fact.get("source_id")}[scope]


def _labels(labels: list[Record] | None) -> dict[str, str]:
    latest = {}
    for row in labels or []:
        if row.get("target_kind") == "problem" and row.get("label") in LABELS:
            latest[row["target_id"]] = row["label"]
    return latest


def upgrade_problems(signals: list[Record], facts: list[Record], *,
                     labels: list[Record] | None = None, scopes=SCOPES,
                     reference_ts: int | None = None) -> Record:
    """Return upgraded ``problems`` and non-upgraded ``candidates`` with their reason."""
    fact_map = {f["session_uid"]: f for f in facts}
    groups: dict[tuple, list[Record]] = defaultdict(list)
    for sig in signals:
        if sig["problem_type"] is None or sig["session_uid"] not in fact_map:
            continue
        for scope in scopes:
            sid = _scope_ids(fact_map[sig["session_uid"]], scope)
            if sid is not None:
                groups[(sig["problem_type"], sig["key"], scope, sid)].append(sig)
    stamps = [o["ts"] for s in signals for o in s["occurrences"] if o.get("ts") is not None]
    ref = reference_ts if reference_ts is not None else (max(stamps) + 1 if stamps else None)
    status = _labels(labels)
    problems, candidates = [], []
    for (ptype, key, scope, scope_id), rows in sorted(groups.items()):
        kinds = sorted({s["kind"] for s in rows})
        opportunity = {SIGNAL_KINDS[k]["opportunity"] for k in kinds}
        denom_ids = {f["session_uid"] for f in facts
                     if _scope_ids(f, scope) == scope_id
                     and all(f["opportunities"].get(o) is True for o in opportunity)
                     and all(f["signals_summary"].get(k) is not None for k in kinds)}
        session_ids = sorted({s["session_uid"] for s in rows} & denom_ids)
        n, d = len(session_ids), len(denom_ids)
        lo = wilson_lo(n, d) if d else None
        minimum = PROBLEM_TYPES[ptype]["min_sessions"]
        reason = ("no_denominator" if not d else "below_min_sessions" if n < minimum
                  else "below_wilson_lo" if lo < WILSON_LO_MIN else None)
        occ_ts = [o["ts"] for s in rows for o in s["occurrences"] if o.get("ts") is not None]
        weekly = (None if ref is None or not occ_ts
                  else sum(ref - 4 * WEEK_MS <= t < ref for t in occ_ts) / 4)
        pid = problem_id(ptype, key, scope, scope_id)
        label = status.get(pid)
        row = {"problem_id": pid, "type": ptype, "key": key, "scope": scope, "scope_id": scope_id,
               "signal_kinds": kinds, "sessions": n, "session_uids": session_ids,
               "denominator": d, "rate": proportion(n, d), "wilson_lo": lo,
               "min_sessions": minimum, "upgraded": reason is None, "reason": reason,
               "signal_count": sum(s["value"] for s in rows),
               "signal_ids": sorted(s["signal_id"] for s in rows),
               "first_seen": min(occ_ts) if occ_ts else None,
               "last_seen": max(occ_ts) if occ_ts else None, "weekly_count": weekly,
               "remedies": PROBLEM_TYPES[ptype]["remedies"], "label": label,
               "status": label or "active", "rules_version": RULES_VERSION}
        (problems if reason is None else candidates).append(row)
    return {"rules_version": RULES_VERSION, "wilson_lo_min": WILSON_LO_MIN,
            "problems": problems, "candidates": candidates}
