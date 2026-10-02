"""Preference field definitions, owned by the preference family."""

RULES = {
    "preference_statement": "Direct explicit human statement; quotations, attachments and reported speech excluded",
    "preference_type": "Versioned language/detail/format/tool/collaboration rule vocabulary",
    "preference_scope": "Explicit task/project/global scope; unspecified scope is unknown, never global",
    "preference_evidence": "Direct message, actor, event ID, session, native sequence and observation time",
    "effective_at": "Observed UTC-ms message time; no inferred backdating or future scheduling",
    "preference_history": "Evidence-linked supersedes/revokes/reaffirms relationships; unresolved values conflict",
    "polarity": "Explicit prefer/avoid, separate from revoking a previous preference",
}

FEATURES = {name: {"name": name, "family": "preference", "unit": "preference observation", "type": "explicit_observation",
    "rule": rule, "source": "confirmed main-session human messages", "denominator": "distinct preference_id",
    "missing_semantics": "unknown scope/time stays unresolved; no implicit preferences",
    "provenance": "preference_evidence, effective_position, preference_history"} for name, rule in RULES.items()}
