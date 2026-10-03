"""Select direct human text and a bounded, strictly preceding context."""

import hashlib
import json
from dataclasses import asdict, dataclass

from ..common import final_assistant_uids, human, task_uid


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Budget:
    message_chars: int = 1200
    context_chars: int = 800
    batch_chars: int = 12000
    batch_messages: int = 6
    max_calls: int = 40
    timeout_seconds: int = 60
    max_failures: int = 1

    def __post_init__(self):
        ranges = {
            "message_chars": (100, 2000),
            "context_chars": (0, 2000),
            "batch_chars": (1000, 20000),
            "batch_messages": (1, 8),
            "max_calls": (1, 100),
            "timeout_seconds": (1, 90),
            "max_failures": (1, 3),
        }
        for name, (low, high) in ranges.items():
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"invalid semantic budget: {name}")


def source_text(event):
    from ..instruction.text import instruction_text

    return instruction_text(event.get("text"))


def source_stamp(event):
    return {
        "session_uid": event["session_uid"],
        "event_uid": event["event_uid"],
        "seq": event["seq"],
        "ts": event.get("ts"),
        "kind": event["kind"],
        "task_uid": task_uid(event),
        "text_hash": digest(source_text(event)),
        "text_truncated": bool(event.get("text_truncated")),
    }


DEFAULT_BUDGET = Budget()


def select_candidates(events, main_ids, budget=DEFAULT_BUDGET):
    seen, histories, candidates, skipped = set(), {}, [], []
    finals = final_assistant_uids(events)
    for event in sorted(events, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        sid, uid = event["session_uid"], event["event_uid"]
        if (sid, uid) in seen:
            continue
        seen.add((sid, uid))
        history = histories.setdefault(sid, [])
        if human(event, main_ids):
            text = source_text(event)
            reason = (
                "text_unavailable"
                if event.get("text") is None
                else "source_truncated"
                if event.get("text_truncated")
                else "no_direct_text"
                if not text
                else "message_budget_exceeded"
                if len(text) > budget.message_chars
                else None
            )
            if reason:
                skipped.append({"session_uid": sid, "event_uid": uid, "reason": reason})
            else:
                context, chars = [], 0
                for prior in reversed(history):
                    if (
                        prior["seq"] >= event["seq"]
                        or not task_uid(event)
                        or task_uid(prior) != task_uid(event)
                        or prior.get("text_truncated")
                        or prior.get("ts") is not None
                        and event.get("ts") is not None
                        and prior["ts"] > event["ts"]
                    ):
                        continue
                    value = source_text(prior)
                    if not value or chars + len(value) > budget.context_chars:
                        continue
                    context.append({**source_stamp(prior), "text": value})
                    chars += len(value)
                    if len(context) == 2:
                        break
                item = {**source_stamp(event), "text": text, "context": list(reversed(context))}
                item["input_digest"] = digest(item)
                candidates.append(item)
        if (
            human(event, main_ids)
            or (sid, uid) in finals
        ):
            history.append(event)
    return candidates, skipped


def batches(candidates, budget):
    pending, size = [], 0
    for item in candidates:
        amount = len(json.dumps(item, ensure_ascii=False))
        if pending and (
            len(pending) >= budget.batch_messages or size + amount > budget.batch_chars
        ):
            yield pending
            pending, size = [], 0
        if amount > budget.batch_chars:
            raise ValueError("one candidate exceeds batch budget")
        pending.append(item)
        size += amount
    if pending:
        yield pending


def cache_identity(events, main_ids, budget):
    candidates, skipped = select_candidates(events, main_ids, budget)
    return (
        digest({"inputs": candidates, "skipped": skipped, "budget": asdict(budget)}),
        candidates,
        skipped,
    )
