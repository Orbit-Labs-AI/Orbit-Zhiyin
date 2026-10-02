"""Compatibility facade and legacy prompt/persona measurements.

The bottleneck feature families live in interaction/respond/cost_time/outcome.
Existing callers keep their imports and v1 field meanings.
"""

from collections import Counter
from statistics import mean, median
from zoneinfo import ZoneInfo

from .common import human, quantile, ratio, timestamp
from .cost_time import activity, token_total, usage
from .cost_time.activity import local_parts
from .instruction.structure import FILE, structure
from .interaction import correction_terms
from .outcome import legacy_objective_candidates
from .outcome_subjective import analyze_subjective_outcomes
from .respond import tool_summary, workflow

__all__ = ["activity", "correction_terms", "human", "quantile", "ratio", "session_features",
           "structure", "text_lengths", "token_total", "tool_summary", "usage", "workflow"]


LANG = {"py": "Python", "ipynb": "Python", "ts": "TypeScript", "tsx": "TypeScript",
        "js": "JavaScript", "jsx": "JavaScript", "tex": "LaTeX", "rs": "Rust", "go": "Go",
        "java": "Java", "cpp": "C++", "c": "C", "h": "C/C++", "sh": "Shell",
        "html": "HTML", "css": "CSS", "md": "Markdown", "json": "JSON", "yaml": "YAML", "yml": "YAML"}


def text_lengths(events):
    values, exact, unknown = [], 0, 0
    for e in events:
        text, attrs = e.get("text"), e.get("attrs", {})
        n = attrs.get("original_chars")
        if isinstance(n, int) and n >= 0:
            values.append(n)
            exact += 1
        elif text is not None:
            values.append(len(text))
            exact += not e.get("text_truncated", False)
        else:
            unknown += 1
    return {"avg": mean(values) if values else None, "median": median(values) if values else None,
            "effective_n": len(values), "unknown_n": unknown, "exact_n": exact,
            "quality": "lower_bound" if exact < len(values) else "normalized_text"}


def session_features(session, events, calls, main_ids, supported_kinds=None, event_status="available",
                     display_timezone="UTC", *, with_workflow=True):
    users = [e for e in events if human(e, main_ids)]
    assistants = [e for e in events if e["kind"] == "message.assistant"]
    unknown_humans = sum(e["kind"] == "message.user" and e.get("attrs", {}).get("origin", "unknown") == "unknown" for e in events)
    times, dates = [], set()
    ZoneInfo(display_timezone)  # an unknown zone still fails here, before any timestamp
    for e in events:
        ts = e.get("ts")
        if timestamp(ts):
            parts = local_parts(ts, display_timezone)  # None when the conversion fails
            if parts is not None:
                dates.add(parts[0])
                times.append(ts)
    lengths_u, lengths_a = text_lengths(users), text_lengths(assistants)
    corrections = [{"event_uid": e["event_uid"], "terms": terms} for e in users
                   if (terms := correction_terms(e.get("text") or ""))]
    structures = [s for e in users if (s := structure(e)) is not None]
    languages = Counter(ext.lower() for e in users for ext in FILE.findall(e.get("text") or ""))
    objective = legacy_objective_candidates(calls)
    subjective = analyze_subjective_outcomes(events, main_ids, event_status)
    feedback = None if subjective["feedback"] is None else [
        {key: f[key] for key in ("event_uid", "delivery_event_uid", "signal")}
        for f in subjective["feedback"] if f["delivery_event_uid"] is not None
        and f["signal"] in ("positive", "negative")]
    main = session["session_uid"] in main_ids
    features = {"user_message_count": len(users) if main and (users or not unknown_humans) else None,
                "assistant_message_count": len(assistants), "turn_count": len({e["turn_uid"] for e in events if e.get("turn_uid")}) or None,
                "total_event_count": len(events), "first_observed_ts": min(times, default=None),
                "last_observed_ts": max(times, default=None),
                "observed_session_span_ms": max(times) - min(times) if times else None,
                "observed_event_dates": sorted(dates), "observed_timestamp_n": len(times),
                "time_unknown_event_count": len(events) - len(times),
                "avg_user_message_chars": lengths_u["avg"], "median_user_message_chars": lengths_u["median"],
                "avg_assistant_message_chars": lengths_a["avg"], "median_assistant_message_chars": lengths_a["median"],
                "tool_call_count": len(calls) if calls is not None else None,
                "correction_signal_count": len(corrections) if users else None,
                "correction_signal_rate": ratio(len(corrections), len(users))}
    return {"features": features, "effective_samples": {"human_messages": len(users), "assistant_messages": len(assistants),
                "tools": len(calls) if calls is not None else None},
            "unknown_counts": {"human_origin": unknown_humans, "event_time": len(events) - len(times),
                               "turn_identity": sum(not e.get("turn_uid") for e in events)},
            "text_measurements": {"user": lengths_u, "assistant": lengths_a},
            "workflow": workflow(events, calls, main_ids, supported_kinds) if with_workflow else None, "correction_signals": corrections,
            "correction_denominator": "confirmed human messages in main sessions",
            "prompt_structure": structures, "language_signals": [{"language": LANG[k], "extension": k, "count": n,
                "basis": "human_text_file_extension"} for k, n in languages.most_common()],
            "objective_outcomes": objective, "subjective_outcome_candidates": feedback,
            "subjective_outcomes": subjective,
            "task_success": None, "tool_sequence": calls,
            "human_evidence_ids": [e["event_uid"] for e in users]}
