"""Compatibility facade and legacy prompt/persona measurements.

The bottleneck feature families live in interaction/respond/cost_time/outcome.
Existing callers keep their imports and v1 field meanings.
"""

import re
from collections import Counter
from statistics import mean, median

from ..privacy import direct_user_text
from .common import human, quantile, ratio
from .cost_time import activity, token_total, usage
from .interaction import correction_terms
from .outcome import legacy_objective_candidates
from .respond import tool_summary, workflow

__all__ = ["activity", "correction_terms", "human", "quantile", "ratio", "session_features",
           "structure", "text_lengths", "token_total", "tool_summary", "usage", "workflow"]


CONSTRAINT = re.compile(r"必须|不要|只能|要求|\b(?:must|do not|don't|only|require)\b", re.I)
FILE = re.compile(r"(?<![\w.])(?:[\w@~-]+/)*[\w.-]+\.(py|ts|tsx|js|jsx|tex|md|json|yaml|yml|rs|go|java|cpp|c|h|sh|html|css|ipynb)\b", re.I)
LANG = {"py": "Python", "ipynb": "Python", "ts": "TypeScript", "tsx": "TypeScript",
        "js": "JavaScript", "jsx": "JavaScript", "tex": "LaTeX", "rs": "Rust", "go": "Go",
        "java": "Java", "cpp": "C++", "c": "C", "h": "C/C++", "sh": "Shell",
        "html": "HTML", "css": "CSS", "md": "Markdown", "json": "JSON", "yaml": "YAML", "yml": "YAML"}


def structure(e):
    text = e.get("text")
    if text is None:
        return None
    attrs = e.get("attrs", {})
    out = {"prompt_char_count": attrs.get("original_chars", len(text)),
           "prompt_line_count": len(text.splitlines()) if text else 0,
           "paragraph_count": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
           "question_mark_count": len(re.findall(r"[?？]", text)),
           "bullet_count": len(re.findall(r"(?m)^\s*[-*+]\s+", text)),
           "numbered_list_count": len(re.findall(r"(?m)^\s*\d+[.)、]\s*", text)),
           "code_block_count": None,  # Legacy normalization removed fenced material.
           "url_count": len(re.findall(r"https?://[^\s<>]+", text)),
           "file_reference_count": len(FILE.findall(text)),
           "explicit_format_request_count": len(re.findall(r"(?:请|用|输出为|写成).{0,8}(?:表格|列表|JSON|Markdown|分点)", text, re.I)),
           "explicit_tool_mention_count": len(re.findall(r"(?:使用|调用|用)\s*`?[\w.]*?(?:MCP|工具|skill|pytest|git|bash)\b", text, re.I)),
           "constraint_marker_count": len(CONSTRAINT.findall(text))}
    if "prompt_structure" in attrs:
        out.update(attrs["prompt_structure"])
    out["constraint_density"] = ratio(out["constraint_marker_count"], len(text))
    out["quality"] = "lower_bound" if e.get("text_truncated") else "normalized_text"
    out["event_uid"] = e["event_uid"]
    return out


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


def session_features(session, events, calls, main_ids, supported_kinds=None):
    users = [e for e in events if human(e, main_ids)]
    assistants = [e for e in events if e["kind"] == "message.assistant"]
    unknown_humans = sum(e["kind"] == "message.user" and e.get("attrs", {}).get("origin", "unknown") == "unknown" for e in events)
    times = [e["ts"] for e in events if e.get("ts") is not None]
    lengths_u, lengths_a = text_lengths(users), text_lengths(assistants)
    corrections = [{"event_uid": e["event_uid"], "terms": terms} for e in users
                   if (terms := correction_terms(e.get("text") or ""))]
    structures = [s for e in users if (s := structure(e)) is not None]
    languages = Counter(ext.lower() for e in users for ext in FILE.findall(e.get("text") or ""))
    objective = legacy_objective_candidates(calls)
    # Subjective signals require a prior final delivery, and explicitly shared task identity.
    feedback, delivered = [], {}
    for e in events:
        a = e.get("attrs", {})
        if e["kind"] == "message.assistant" and a.get("phase") == "final" and a.get("task_id"):
            delivered[a["task_id"]] = e["event_uid"]
        elif human(e, main_ids) and a.get("task_id") in delivered:
            text = direct_user_text(e.get("text") or "").strip()
            m = re.fullmatch(r"(可以了|这样可以|解决了|还是不行|不对|算了)[。！!\s]*", text)
            if m:
                feedback.append({"event_uid": e["event_uid"], "delivery_event_uid": delivered[a["task_id"]],
                                 "signal": "positive" if m[1] in ("可以了", "这样可以", "解决了") else "negative"})
    main = session["session_uid"] in main_ids
    features = {"user_message_count": len(users) if main and (users or not unknown_humans) else None,
                "assistant_message_count": len(assistants), "turn_count": len({e["turn_uid"] for e in events if e.get("turn_uid")}) or None,
                "total_event_count": len(events), "first_observed_ts": min(times, default=None),
                "last_observed_ts": max(times, default=None),
                "observed_session_span_ms": max(times) - min(times) if times else None,
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
            "workflow": workflow(events, calls, main_ids, supported_kinds), "correction_signals": corrections,
            "correction_denominator": "confirmed human messages in main sessions",
            "prompt_structure": structures, "language_signals": [{"language": LANG[k], "extension": k, "count": n,
                "basis": "human_text_file_extension"} for k, n in languages.most_common()],
            "objective_outcomes": objective, "subjective_outcome_candidates": feedback,
            "task_success": None, "tool_sequence": calls,
            "human_evidence_ids": [e["event_uid"] for e in users]}
