"""Field meanings for Instruction; compatible with the global feature dictionary."""

from .extraction import FIELDS

FEATURES = {
    name: {
        "name": name, "family": "instruction", "unit": "confirmed human message",
        "rule": "Explicit lexical candidates; retain condition, targets and evidence; no inferred permission",
        "source": "message.user + actor=human/user + attrs.origin=human + main session",
        "denominator": "confirmed human messages in the selected scope",
        "type": "proxy", "missing_semantics": "null means no supported explicit signal, not absence",
        "provenance": "session_uid, event_uid, constraint_uid, seq, ts, task_id",
    } for name in FIELDS
}
