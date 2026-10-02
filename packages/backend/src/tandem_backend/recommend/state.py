"""Scoped analytics + an existing diagnosis + explicit environment → state."""

import math
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass

from ..analytics.recommendations.diagnosis import diagnose_bottlenecks, feature_digest
from .contracts import Evidence, RecommendationContext, RecommendationState
from .preferences import resolve_preferences


@dataclass
class StateBuild:
    states: list[RecommendationState]
    signals: list[dict]
    assessments: list[dict]


def build_states(analysis, bottlenecks=None, context=None, policy=None):
    context = RecommendationContext.model_validate(context or {}) if not isinstance(context, RecommendationContext) else context.model_copy(deep=True)
    diagnosis = diagnose_bottlenecks(analysis, policy) if bottlenecks is None else deepcopy(bottlenecks)
    # A diagnosis made here carries this snapshot's digest already; re-serializing every
    # root's features only to compare it with itself is skipped.
    if (not isinstance(diagnosis, dict)
            or (bottlenecks is not None and diagnosis.get("feature_digest") != feature_digest(analysis))
            or diagnosis.get("scope") != analysis.get("scope") or diagnosis.get("analysis_digest") != analysis.get("analysis_digest")):
        raise ValueError("Bottleneck diagnosis does not match this scoped feature snapshot")
    roots = {r["session_uid"]: r for r in analysis.get("sessions") or []}
    for signal in diagnosis.get("signals", []):
        root = signal.get("scope", {}).get("root_session_uid")
        if root not in roots:
            raise ValueError("Bottleneck signal is outside selected roots")
        ids = roots[root].get("included_session_uids", [root])
        if not signal.get("evidence"):
            raise ValueError("Bottleneck signal requires evidence")
        for ref in signal["evidence"]:
            ref = Evidence.model_validate(ref)
            if ref.session_uid not in ids:
                raise ValueError("Bottleneck evidence crosses root scope")
        for key in ("confidence", "severity", "recurrence"):
            value = signal.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Invalid bottleneck strength")
    # Index signals by root and task records by id once (O(S + T)) instead of scanning
    # every signal and task record per root; both keep their original relative order.
    signals_by_root = defaultdict(list)
    for signal in diagnosis["signals"]:
        signals_by_root[signal["scope"]["root_session_uid"]].append(signal)
    all_tasks = (analysis.get("tasks") or {}).get("records") or []
    task_positions = defaultdict(list)
    for position, task in enumerate(all_tasks):
        task_positions[task.get("task_id")].append(position)
    # resolve_preferences reads only ``scope`` and the explicit observed preference records;
    # filter those once instead of once per root (the same filter, so it stays idempotent).
    preference_view = {"scope": analysis.get("scope"), "preferences": {"records": [
        r for r in ((analysis.get("preferences") or {}).get("records") or [])
        if r.get("status") == "observed" and r.get("preference_evidence")
        and r.get("confirmation") == "explicit_human_statement"]}}
    states = []
    for sid, row in sorted(roots.items()):
        own = signals_by_root.get(sid, [])
        features = row.get("bottleneck_features") or {}
        # Only scoped, extracted task labels are used in P0 lexical matching.
        # Raw conversation text and persona labels do not enter the query.
        positions = {p for tid in set(row.get("task_ids") or []) for p in task_positions.get(tid, ())}
        task_records = [all_tasks[p] for p in sorted(positions)]
        tasks = [{k: t.get(k) for k in ("task_id", "domain", "task_type")} for t in task_records]
        task_words = sorted({word for t in tasks for key in ("domain", "task_type") for word in t.get(key) or []})
        context_words = (context.languages or []) + (context.frameworks or []) + (context.tools or [])
        vector = {}
        for signal in own:
            vector[signal["rule_id"]] = max(vector.get(signal["rule_id"], 0.), signal["severity"] * signal["confidence"])
        interaction = features.get("interaction") or {}
        respond = features.get("respond") or {}
        outcome = features.get("outcome") or {}
        states.append(RecommendationState(
            root_session_uid=sid, scope={**(analysis.get("scope") or {}), "included_session_uids": row.get("included_session_uids", [sid])},
            analysis_digest=analysis.get("analysis_digest"), task_state={"records": tasks},
            workflow_state={"workflow": respond.get("workflow"), "retry_links": respond.get("retry_links")},
            interaction_state={k: interaction.get(k) for k in ("confirmed_correction_count", "confirmed_correction_rate", "repeated_requirement_count", "effective_samples", "unknown_counts")},
            outcome_state={k: outcome.get(k) for k in ("task_success", "validation_result_counts", "acceptance_results")},
            cost_state=features.get("cost_time") or {}, preference_state=resolve_preferences(preference_view, row, task_records, context),
            context_state=context.model_copy(deep=True), bottleneck_vector=vector,
            task_text=" ".join(task_words + context_words), problem_text=" ".join(s["reason"] for s in own),
            desired_effect_text=" ".join(sorted({c for s in own for c in s["capabilities"]})), signals=deepcopy(own)))
    return StateBuild(states, deepcopy(diagnosis["signals"]), deepcopy(diagnosis["assessments"]))
