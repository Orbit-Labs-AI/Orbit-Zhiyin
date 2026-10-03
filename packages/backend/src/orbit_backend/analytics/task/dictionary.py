"""Task field definitions, owned by the task family."""

RULES = {
    "domain": "Versioned multi-label domain vocabulary over direct human requests; unknown=null",
    "domain_details": "27 stable subdomain IDs with Chinese labels, six compatible parent domains, contextual rule IDs and per-session evidence; absent in old records=unknown, not zero",
    "task_type": "Versioned multi-label action vocabulary; forbidden actions excluded",
    "task_title": "First 60 retained characters of the current explicit goal; no generated facts",
    "task_goal": "Initial actionable request, amended only by an explicit goal-change statement",
    "task_goal_history": "Observed goal versions and the event/time at which each became visible",
    "expected_artifacts": "Named outputs after a production verb; requested does not mean produced",
    "task_boundaries": "Per-session observed starts and explicit close/next-task boundaries; open end=null",
    "related_session_ids": "Explicit native/human-confirmed task identity only; cwd similarity never merges tasks",
}

FEATURES = {name: {"name": name, "family": "task", "unit": "task", "type": "rule_candidate",
    "rule": rule, "source": "confirmed main-session human messages", "denominator": "distinct task_id for distributions",
    "missing_semantics": "null + missing_reasons; unconfirmed labels and boundaries remain candidates",
    "provenance": "label_evidence, human_evidence_ids, task_boundaries, taxonomy_version"} for name, rule in RULES.items()}
