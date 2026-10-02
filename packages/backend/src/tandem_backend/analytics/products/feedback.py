"""Evidence-backed expression trends, separate from acceptance and task success."""

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..common import semantic_messages, timestamp
from ..lexicon import emotion_cues
from ..outcome_subjective.extraction import classify_feedback
from .contracts import metric

Record = dict[str, Any]
POSITIVE = re.compile(
    r"(?:我(?:现在|真的|非常|很)?(?:很)?(?:开心|满意|高兴)|太棒了|非常感谢|做得很好|I'm (?:very )?(?:happy|pleased)|I am (?:very )?(?:happy|pleased))",
    re.I,
)
NEGATIVE = re.compile(
    r"(?:我(?:现在|真的|非常|很)?(?:很)?(?:失望|沮丧|生气|不满意)|太令人失望了|I'm (?:very )?(?:frustrated|disappointed)|I am (?:very )?(?:frustrated|disappointed))",
    re.I,
)
NEUTRAL = re.compile(r"(?:我没有特别的感受|我没什么感觉|I feel neutral)", re.I)
NON_ASSERTION = re.compile(
    r"如果|假如|比如|例如|假设|他说|她说|用户说|请(?:翻译|分析|输出|判断|回复)|\b(?:if|suppose|example|translate|say|said)\b",
    re.I,
)


def calendar_key(ts: int | None, zone: ZoneInfo, bucket: str = "day") -> str | None:
    """Convert a valid log timestamp to a local calendar bucket without inventing time."""
    if not timestamp(ts):
        return None
    try:
        date = datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone(zone).date()
    except (ValueError, OverflowError, OSError):
        return None
    if bucket == "month":
        return date.strftime("%Y-%m")
    if bucket == "week":
        year, week, _ = date.isocalendar()
        return f"{year}-W{week:02d}"
    return date.isoformat()


def classify_emotion(text: str) -> str | None:
    """Recognize explicit first-person expressions; correction and silence are not emotion."""
    if NON_ASSERTION.search(text) or re.search(r"[?？]|(?:是否|吗)", text):
        return None
    clauses = [
        part.strip(" ，,。！!.；;\n")
        for part in re.split(r"[，,。！!；;\n]|但是|\bbut\b", text, flags=re.I)
    ]
    cues = [emotion_cues(part) for part in clauses if part]
    positive = any(POSITIVE.fullmatch(part) for part in clauses) or any(p for p, _ in cues)
    negative = any(NEGATIVE.fullmatch(part) for part in clauses) or any(n for _, n in cues)
    if positive and negative:
        return "mixed"
    return (
        "positive"
        if positive
        else "negative"
        if negative
        else "neutral"
        if any(NEUTRAL.fullmatch(p) for p in clauses)
        else None
    )


def expression_summary(rows: list[Record], status: str) -> Record:
    """Summarize signed expression balance; it is not a psychological intensity score."""
    states = Counter(row["emotion"] or "unknown" for row in rows)
    known = len(rows) - states["unknown"]
    balance = (states["positive"] - states["negative"]) / known if known else None
    return {
        "counts": dict(states),
        "balance": metric(
            balance,
            "expression_balance",
            known,
            states["unknown"],
            basis="explicit_lexical_candidate",
            status=status,
        ),
        "human_message_n": len(rows),
        "evidence_event_uids": [r["event_uid"] for r in rows if r["emotion"]],
    }


def analyze_feedback(
    events: list[Record] | None,
    sessions: list[Record],
    timezone_name: str,
    status: str = "available",
) -> Record:
    """Combine explicit emotion, feedback phrases and time buckets over confirmed humans."""
    if events is None or status in ("excluded", "unavailable"):
        return {
            "status": status,
            "experimental": True,
            "summary": None,
            "by_day": None,
            "messages": None,
            "phrases": None,
            "time_unknown_n": None,
        }
    zone = ZoneInfo(timezone_name)
    rows, days, phrases = [], defaultdict(list), defaultdict(list)
    for event in semantic_messages(events, sessions):
        # A truncated suffix may reverse the apparent sentiment of a retained prefix.
        text = event["semantic_text"]
        emotion = None if event.get("text_truncated") else classify_emotion(text)
        feedback = None if event.get("text_truncated") else classify_feedback(text)
        row = {
            "event_uid": event["event_uid"],
            "session_uid": event["session_uid"],
            "ts": event.get("ts"),
            "day": calendar_key(event.get("ts"), zone),
            "emotion": emotion,
            "feedback_signal": feedback["signal"] if feedback else None,
            "basis": "explicit_lexical_candidate",
            "unknown_reason": "truncated_text"
            if event.get("text_truncated")
            else "no_explicit_expression"
            if emotion is None
            else None,
        }
        rows.append(row)
        if row["day"] is not None:
            days[row["day"]].append(row)
        if feedback:
            phrases[feedback["evidence_text"]].append(row)
    unknown_origin = sum(
        e["kind"] == "message.user" and e.get("attrs", {}).get("origin") in (None, "unknown")
        for e in events
    )
    effective_status = "partial" if unknown_origin or status == "partial" else status
    return {
        "status": effective_status,
        "experimental": True,
        "display_timezone": timezone_name,
        "meaning": "explicit expression balance, not mood diagnosis; unrecognized messages stay unknown",
        "summary": expression_summary(rows, effective_status),
        "messages": rows,
        "by_day": [
            {"day": day, **expression_summary(items, effective_status)}
            for day, items in sorted(days.items())
        ],
        "time_unknown_n": sum(r["day"] is None for r in rows),
        "origin_unknown_n": unknown_origin,
        "phrases": [
            {
                "phrase": phrase,
                "count": len(items),
                "session_uids": sorted({r["session_uid"] for r in items}),
                "evidence_event_uids": [r["event_uid"] for r in items],
            }
            for phrase, items in sorted(phrases.items(), key=lambda pair: (-len(pair[1]), pair[0]))[
                :30
            ]
        ],
    }
