"""Distribution summaries and comparisons with auditable samples and session-level resampling."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import fmean, median, stdev
from typing import Any

import numpy as np

from ..common import human, nonnegative_number, quantile
from ..context import AnalysisContext
from ..cost_time.tokens import prepare_requests, token_total

Record = dict[str, Any]
STATISTICS_VERSION = "descriptive-statistics-v1"


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """1-based ranks with ties averaged: ``scipy.stats.rankdata(method="average")``."""
    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    first = np.r_[True, ordered[1:] != ordered[:-1]]
    dense = np.cumsum(first)
    bounds = np.r_[np.nonzero(first)[0], len(values)]
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = 0.5 * (bounds[dense] + bounds[dense - 1] + 1)
    return ranks


def spearman_rho(a: list[float], b: list[float]) -> float:
    """Spearman's rho exactly as ``scipy.stats.spearmanr(a, b).statistic`` computes it.

    Pearson correlation of average ranks via ``np.corrcoef``; only the statistic is
    needed, so the ~2 s ``scipy.stats`` import is avoided on cold analysis.
    """
    pair = np.column_stack((np.asarray(a), np.asarray(b)))
    ranked = np.column_stack([_average_ranks(pair[:, i]) for i in range(2)])
    return float(np.corrcoef(ranked, rowvar=False)[1, 0])


def rank_association(first: list[Record], second: list[Record]) -> Record:
    """Describe paired session-level rank association without interpreting a p-value as causality."""
    left = {row["session_uid"]: row["value"] for row in first if nonnegative_number(row["value"])}
    right = {row["session_uid"]: row["value"] for row in second if nonnegative_number(row["value"])}
    points = [
        {"session_uid": sid, "first": left[sid], "second": right[sid]}
        for sid in sorted(left.keys() & right.keys())
    ]
    result = {
        "method": "Spearman rank correlation",
        "n": len(points),
        "points": points,
        "rho": None,
        "status": "insufficient_samples",
        "meaning": "observational association, not causation",
    }
    if len(points) < 5:
        return result
    a, b = [p["first"] for p in points], [p["second"] for p in points]
    if len(set(a)) < 2 or len(set(b)) < 2:
        return {**result, "status": "constant_input"}
    return {**result, "rho": spearman_rho(a, b), "status": "available"}


def summarize(samples: list[Record], unit: str, grain: str) -> Record:
    """Retain every sample while summarizing known values; missing measurements never become zero."""
    known = [row for row in samples if nonnegative_number(row["value"])]
    values = [row["value"] for row in known]
    q1, q3 = quantile(values, 0.25), quantile(values, 0.75)
    center = median(values) if values else None
    iqr = q3 - q1 if values else None
    fences = [q1 - 1.5 * iqr, q3 + 1.5 * iqr] if values and len(values) >= 4 and iqr > 0 else None
    return {
        "unit": unit,
        "grain": grain,
        "n": len(known),
        "unknown_n": len(samples) - len(known),
        "status": "unavailable"
        if not known
        else "partial"
        if len(known) < len(samples)
        else "available",
        "sum": sum(values) if values else None,
        "mean": fmean(values) if values else None,
        "stddev": stdev(values) if len(values) >= 2 else None,
        "median": center,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "quantiles": {
            f"p{int(p * 100)}": quantile(values, p) for p in (0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)
        },
        "iqr": iqr,
        "mad": median(abs(value - center) for value in values) if values else None,
        "outlier_fences": fences,
        "outlier_sample_ids": [
            row["sample_id"]
            for row in known
            if fences and not fences[0] <= row["value"] <= fences[1]
        ],
        "samples": samples,
    }


def wilson(successes: int, trials: int) -> list[float] | None:
    """Return a 95% Wilson interval for an explicitly defined binary observed subset."""
    if trials <= 0:
        return None
    z, proportion = 1.959963984540054, successes / trials
    scale = 1 + z * z / trials
    center = (proportion + z * z / (2 * trials)) / scale
    radius = (
        z
        * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials))
        / scale
    )
    return [max(0.0, center - radius), min(1.0, center + radius)]


def statistical_analysis(context: AnalysisContext, base: Record) -> Record:
    """Measure sessions, calls, messages and requests at their own statistical units."""
    samples = defaultdict(list)

    def add(name: str, sid: str, sample_id: str, value: Any, evidence: list[str]) -> None:
        session = context.session_map[sid]
        samples[name].append(
            {
                "sample_id": sample_id,
                "session_uid": sid,
                "cluster_uid": session.get("root_uid") or sid,
                "project_id": session.get("project_id"),
                "source_id": session.get("source_id"),
                "value": value if nonnegative_number(value) else None,
                "evidence_ids": evidence,
            }
        )

    definitions = {
        "human_messages_per_session": ("message", "main_session"),
        "calls_per_session": ("call", "main_session_tree"),
        "turns_per_session": ("turn", "main_session"),
        "observed_span_ms": ("ms", "main_session"),
        "tokens_per_session": ("token", "main_session_tree"),
        "human_message_chars": ("character", "human_message"),
        "execution_duration_ms": ("ms", "tool_call"),
        "request_tokens": ("token", "model_request"),
        "request_latency_ms": ("ms", "model_request"),
        "request_ttft_ms": ("ms", "model_request"),
    }
    for row in base["sessions"]:
        if row["kind"] != "main":
            continue
        sid = row["session_uid"]
        for name, value in (
            ("human_messages_per_session", row["features"]["user_message_count"]),
            ("calls_per_session", row["features"]["tool_call_count"]),
            ("turns_per_session", row["features"]["turn_count"]),
            ("observed_span_ms", row["features"]["observed_session_span_ms"]),
            ("tokens_per_session", row["usage"]["total_tokens"]),
        ):
            add(name, sid, sid, value, row["human_evidence_ids"])
    for event in context.events:
        if human(event, context.main_ids):
            value = event.get("attrs", {}).get("original_chars")
            if not nonnegative_number(value):
                value = (
                    len(event["text"])
                    if event.get("text") is not None and not event.get("text_truncated")
                    else None
                )
            add(
                "human_message_chars",
                event["session_uid"],
                event["event_uid"],
                value,
                [event["event_uid"]],
            )
    families = base["bottleneck_features"]
    for row in families["cost_time"]["durations"]["execution_durations"] or []:
        add(
            "execution_duration_ms",
            row["session_uid"],
            row["call_uid"],
            row["execution_duration_ms"],
            row["evidence_event_uids"],
        )
    requests = prepare_requests(context.model_calls)["requests"]
    for row in requests:
        for name, value in (
            ("request_tokens", token_total(row) if row.get("coverage") == "self" else None),
            ("request_latency_ms", row.get("latency_ms")),
            ("request_ttft_ms", row.get("ttft_ms")),
        ):
            add(
                name,
                row["session_uid"],
                row["call_uid"],
                value,
                [row["usage_event_uid"]] if row.get("usage_event_uid") else [],
            )
    metrics = {
        name: summarize(samples[name], unit, grain) for name, (unit, grain) in definitions.items()
    }
    groups = []
    for field in ("project_id", "source_id"):
        group_ids = {s.get(field) for s in context.sessions}
        for group_id in sorted(group_ids, key=str):
            groups.append(
                {
                    "dimension": field,
                    "group_id": group_id,
                    "metrics": {
                        name: summarize(
                            [r for r in rows if r[field] == group_id], *definitions[name]
                        )
                        for name, rows in samples.items()
                    },
                }
            )
    # A session is one vote; many calls within one conversation are not independent trials.
    observed, failed, unresolved, evidence = 0, 0, 0, []
    for session in base["sessions"]:
        if session["kind"] != "main":
            continue
        respond = session["bottleneck_features"]["respond"]
        calls = respond["tool_sequence"]
        has_failure = any(row["tool_result_status"] == "failed" for row in calls or [])
        complete = (
            calls is not None
            and respond["status"] == "available"
            and all(row["tool_result_status"] in ("success", "failed") for row in calls)
        )
        if has_failure or complete and calls:
            observed += 1
            failed += has_failure
            evidence.append(session["session_uid"])
        else:
            unresolved += 1
    return {
        "version": STATISTICS_VERSION,
        "metrics": metrics,
        "groups": groups,
        "associations": [
            {"first": a, "second": b, **rank_association(samples[a], samples[b])}
            for a, b in (
                ("calls_per_session", "human_messages_per_session"),
                ("calls_per_session", "observed_span_ms"),
                ("calls_per_session", "tokens_per_session"),
            )
        ],
        "failure_session_rate": {
            "value": failed / observed if observed else None,
            "failed_session_n": failed,
            "known_session_n": observed,
            "unknown_session_n": unresolved,
            "confidence_interval_95": wilson(failed, observed),
            "session_uids": evidence,
            "meaning": "sessions with observed tool failures among classifiable sessions with calls",
        },
        "method": {
            "quantiles": "linear interpolation",
            "stddev": "sample standard deviation, ddof=1",
            "outliers": "Tukey 1.5*IQR with n>=4 and positive IQR; flags are not errors",
            "population": "observed eligible subsets; incomplete coverage can bias statistics",
        },
    }


def bootstrap_difference(
    current: list[Record], previous: list[Record], *, seed: int = 0, draws: int = 1000
) -> Record:
    """Resample whole sessions and preserve shared session identity across compared windows."""
    groups = [defaultdict(list), defaultdict(list)]
    for rows, group in zip((current, previous), groups, strict=False):
        for row in rows:
            if nonnegative_number(row["value"]):
                group[row.get("cluster_uid", row["session_uid"])].append(row["value"])
    counts = [len(group) for group in groups]
    common = len(groups[0].keys() & groups[1].keys())
    base = {
        "method": "session-cluster percentile bootstrap of mean difference",
        "seed": seed,
        "resamples": draws,
        "current_session_n": counts[0],
        "previous_session_n": counts[1],
        "shared_session_n": common,
        "confidence_interval_95": None,
    }
    if min(counts) < 5:
        return {**base, "status": "insufficient_sessions"}
    ids = sorted(groups[0].keys() | groups[1].keys())
    sums = np.array([[sum(group[sid]) for sid in ids] for group in groups], dtype=float)
    ns = np.array([[len(group[sid]) for sid in ids] for group in groups], dtype=float)
    rng, differences = np.random.default_rng(seed), []
    # Bound temporary allocation even when thousands of sessions are selected.
    batch_size = max(1, min(100, 200_000 // len(ids)))
    for start in range(0, draws, batch_size):
        indices = rng.integers(0, len(ids), size=(min(batch_size, draws - start), len(ids)))
        totals = sums[:, indices].sum(axis=2)
        sizes = ns[:, indices].sum(axis=2)
        valid = (sizes > 0).all(axis=0)
        differences.extend(
            (totals[0, valid] / sizes[0, valid] - totals[1, valid] / sizes[1, valid]).tolist()
        )
    if len(differences) < 0.9 * draws:
        return {**base, "status": "unstable_resamples", "valid_resamples": len(differences)}
    return {
        **base,
        "status": "available",
        "valid_resamples": len(differences),
        "confidence_interval_95": np.quantile(differences, [0.025, 0.975]).tolist(),
    }


def compare_distributions(current: Record, previous: Record) -> Record:
    """Report magnitude and uncertainty without converting association into a causal claim."""
    rows = []
    for name in current["metrics"].keys() & previous["metrics"].keys():
        a, b = current["metrics"][name], previous["metrics"][name]
        delta = a["mean"] - b["mean"] if a["mean"] is not None and b["mean"] is not None else None
        rows.append(
            {
                "metric": name,
                "unit": a["unit"],
                "grain": a["grain"],
                "current_n": a["n"],
                "previous_n": b["n"],
                "current_unknown_n": a["unknown_n"],
                "previous_unknown_n": b["unknown_n"],
                "mean_difference": delta,
                "median_difference": a["median"] - b["median"]
                if a["median"] is not None and b["median"] is not None
                else None,
                "relative_mean_change": delta / b["mean"]
                if delta is not None and b["mean"]
                else None,
                "uncertainty": bootstrap_difference(a["samples"], b["samples"]),
            }
        )
    return {
        "rows": sorted(rows, key=lambda row: row["metric"]),
        "meaning": "observational comparisons; intervals are conditional on observed sessions, not causal effects or missing-data corrections",
    }
