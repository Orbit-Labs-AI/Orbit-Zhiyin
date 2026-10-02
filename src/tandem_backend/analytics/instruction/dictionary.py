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


STRUCTURAL_FIELDS = (
    "prompt_char_count prompt_line_count paragraph_count question_mark_count bullet_count "
    "numbered_list_count code_block_count url_count file_reference_count "
    "explicit_format_request_count explicit_tool_mention_count constraint_marker_count"
)
for name in STRUCTURAL_FIELDS.split():
    FEATURES[name] = {
        "name": name, "family": "instruction", "unit": "occurrence",
        "rule": "Structural counts over direct human text; removed code fences stay unknown",
        "source": "confirmed human text", "denominator": None, "type": "proxy",
        "missing_semantics": "null if unsupported; truncated text is a lower bound",
        "provenance": "session_uid, event_uid",
    }
FEATURES["constraint_density"] = {
    "name": "constraint_density", "family": "instruction", "unit": "marker / character",
    "rule": "Legacy compatibility field: marker count / retained text length; not a control score",
    "source": "confirmed human text", "denominator": "retained prompt chars", "type": "proxy",
    "missing_semantics": "null on an empty prompt", "provenance": "session_uid, event_uid",
    "deprecated": True,
}
