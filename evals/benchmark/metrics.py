"""Budget success and recommendation regret from actual comparable measurements."""

from collections import Counter, defaultdict
from statistics import mean

from .contracts import METHODS, NONE_ACTION, ExecutionRecord, TemporalSample


def _ready(record):
    return (
        record.source in ("paired_execution", "constructed_execution")
        and record.provenance_complete
        and record.measurement_complete
    )


def _reviewed(task):
    return (
        task.review_status == "independent_human_reviewed"
        and task.checkpoint_status == "verified_exact"
        and task.goal_observed
    )


def validate_records(samples, records):
    samples = {s.sample_id: s for s in samples}
    seen, issues = set(), []
    for record in records:
        key = (
            record.sample_id,
            record.task_uid,
            record.method,
            record.action_id,
            record.purpose,
            record.budget.total_tokens,
            record.seed,
        )
        if key in seen:
            issues.append(
                {
                    "code": "duplicate_execution",
                    "sample_id": record.sample_id,
                    "task_uid": record.task_uid,
                }
            )
        seen.add(key)
        sample = samples.get(record.sample_id)
        if sample is None:
            issues.append({"code": "unknown_sample", "sample_id": record.sample_id})
            continue
        if record.task_uid not in {t.task_uid for t in sample.future_tasks}:
            issues.append(
                {
                    "code": "task_not_in_frozen_future",
                    "sample_id": record.sample_id,
                    "task_uid": record.task_uid,
                }
            )
        if record.recommendation_anchor_ts != sample.anchor_ts:
            issues.append(
                {"code": "recommendation_not_frozen_at_anchor", "sample_id": record.sample_id}
            )
        if record.method == "no_recommendation" and record.action_id != NONE_ACTION:
            issues.append({"code": "baseline_has_intervention", "sample_id": record.sample_id})
    return issues


def forward_utility(
    samples: list[TemporalSample],
    records: list[ExecutionRecord],
    *,
    budgets=(5000, 10000, 20000),
    seeds=(0,),
):
    issues = validate_records(samples, records)
    if issues:
        return {"status": "invalid", "issues": issues, "rows": []}
    indexed = defaultdict(list)
    for r in records:
        if r.purpose == "method_comparison":
            indexed[r.sample_id, r.task_uid, r.method, r.budget.total_tokens, r.seed].append(r)
    rows = []
    expected_tasks = [(s, t) for s in samples for t in s.future_tasks]
    for budget in budgets:
        for method in METHODS:
            complete, paired, missing, conflicts = [], [], [], []
            for sample, task in expected_tasks:
                for seed in seeds:
                    values = indexed[sample.sample_id, task.task_uid, method, budget, seed]
                    base = indexed[
                        sample.sample_id, task.task_uid, "no_recommendation", budget, seed
                    ]
                    if len(values) != 1 or not _ready(values[0]):
                        missing.append((sample.sample_id, task.task_uid, seed))
                        continue
                    record = values[0]
                    complete.append(record)
                    if method != "no_recommendation":
                        if len(base) != 1 or not _ready(base[0]):
                            continue
                        if record.comparable_signature != base[0].comparable_signature:
                            conflicts.append((sample.sample_id, task.task_uid, seed))
                            continue
                        paired.append((base[0], record))
            expected = len(expected_tasks) * len(seeds)
            fully_observed = expected > 0 and len(complete) == expected and not conflicts
            sources = Counter(r.source for r in complete)
            reviewed = all(_reviewed(t) for _, t in expected_tasks)
            real = (
                fully_observed
                and reviewed
                and all(s.future_complete for s in samples)
                and set(sources) == {"paired_execution"}
            )
            reductions = {}
            successes = [(a, b) for a, b in paired if a.pass_at_budget and b.pass_at_budget]
            for label, getter in (
                ("tokens", lambda x: x.total_tokens),
                ("turns", lambda x: x.turns),
                ("tool_calls", lambda x: x.tool_calls),
                ("wall_ms", lambda x: x.wall_ms),
            ):
                amounts = [(getter(a), getter(b)) for a, b in successes]
                reductions[label] = {
                    "paired_success_n": len(amounts),
                    "mean_absolute_reduction": mean(a - b for a, b in amounts) if amounts else None,
                    "mean_relative_reduction": mean((a - b) / a for a, b in amounts if a > 0)
                    if any(a > 0 for a, _ in amounts)
                    else None,
                }
            paired_complete = method == "no_recommendation" or len(paired) == expected
            status = (
                "measured"
                if real and paired_complete
                else "constructed_only"
                if fully_observed and set(sources) == {"constructed_execution"}
                else "unproven"
            )
            per_anchor = defaultdict(list)
            for r in complete:
                per_anchor[r.sample_id].append(int(r.pass_at_budget))
            rows.append(
                {
                    "method": method,
                    "token_budget": budget,
                    "status": status,
                    "expected_runs": expected,
                    "complete_runs": len(complete),
                    "missing_runs": len(missing),
                    "paired_runs": len(paired),
                    "control_conflicts": len(conflicts),
                    "sources": dict(sources),
                    "pass_at_budget": mean(r.pass_at_budget for r in complete)
                    if status == "measured"
                    else None,
                    "observed_complete_run_pass_rate": mean(r.pass_at_budget for r in complete)
                    if complete
                    else None,
                    "mean_anchor_pass_rate": mean(mean(v) for v in per_anchor.values())
                    if per_anchor
                    else None,
                    "efficiency_reductions": reductions if status == "measured" else None,
                    "paired_success_diagnostics": reductions,
                }
            )
    return {
        "schema_version": "forward-utility-v1",
        "status": "measured"
        if rows and all(r["status"] == "measured" for r in rows)
        else "unproven",
        "rows": rows,
        "unique_future_tasks": len({t.task_uid for _, t in expected_tasks}),
        "limitations": [
            "Unknown costs/results and incomplete methods are not counted as zero or failures.",
            "Recommendation tokens are included in the common total-token budget.",
            "Efficiency compares only paired tasks where both methods pass the same budget and checks.",
            "Overlapping rolling anchors reuse tasks; raw pooled rates are not independent-user evidence.",
            "Execution values are caller-supplied measurements; the runner does not independently attest the run logs.",
        ],
    }


def recommendation_quality(
    samples, records, rankings, plausible_actions, *, token_budget=10000, seed=0, top_k=3
):
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be positive")
    issues = validate_records(samples, records)
    if issues:
        return {"status": "invalid", "issues": issues, "rows": []}
    actions = sorted(set(plausible_actions) | {NONE_ACTION})
    index = defaultdict(list)
    for r in records:
        if r.purpose == "action_sweep" and r.budget.total_tokens == token_budget and r.seed == seed:
            index[r.sample_id, r.task_uid, r.action_id].append(r)
    rows = []
    for sample in samples:
        selected = rankings.get(sample.sample_id, [NONE_ACTION]) or [NONE_ACTION]
        values, signatures, missing, sources = {}, set(), [], set()
        for action in actions:
            records_for_action = []
            for task in sample.future_tasks:
                observed = index[sample.sample_id, task.task_uid, action]
                if len(observed) != 1 or not _ready(observed[0]):
                    missing.append((action, task.task_uid))
                    continue
                record = observed[0]
                records_for_action.append(record)
                sources.add(record.source)
                signatures.add((task.task_uid, record.comparable_signature))
            if records_for_action and len(records_for_action) == len(sample.future_tasks):
                values[action] = mean(r.pass_at_budget for r in records_for_action)
        per_task_signatures = defaultdict(set)
        for uid, signature in signatures:
            per_task_signatures[uid].add(signature)
        mismatch = any(len(v) != 1 for v in per_task_signatures.values())
        unknown_choice = any(action not in actions for action in selected)
        complete = bool(sample.future_tasks) and not missing and not mismatch and not unknown_choice
        real = (
            complete
            and sample.future_complete
            and sources == {"paired_execution"}
            and all(_reviewed(t) for t in sample.future_tasks)
        )
        status = (
            "measured"
            if real
            else "constructed_only"
            if complete and sources == {"constructed_execution"}
            else "unproven"
        )
        best = max(values.values()) if complete else None
        oracle = [a for a in actions if complete and values[a] == best]
        chosen = selected[0]
        row = {
            "sample_id": sample.sample_id,
            "status": status,
            "chosen_action": chosen,
            "top_k": selected[:top_k],
            "missing_measurements": len(missing),
            "control_mismatch": mismatch,
            "unknown_choice": unknown_choice,
            "utility_definition": "mean Pass@common budget over the frozen future tasks",
            "observed_action_utilities": values,
            "oracle_actions": oracle,
            "regret_at_1": best - values[chosen] if real else None,
            "regret_at_k": best - max(values[a] for a in selected[:top_k]) if real else None,
            "harm": values[chosen] < values[NONE_ACTION] if real else None,
            "no_intervention_is_optimal": NONE_ACTION in oracle if real else None,
            "unnecessary_intervention": chosen != NONE_ACTION and NONE_ACTION in oracle
            if real
            else None,
        }
        rows.append(row)
    measured = [r for r in rows if r["status"] == "measured"]
    none_optimal = [r for r in measured if r["no_intervention_is_optimal"]]
    return {
        "schema_version": "recommendation-quality-v1",
        "status": "measured" if rows and len(measured) == len(rows) else "unproven",
        "token_budget": token_budget,
        "rows": rows,
        "measured_samples": len(measured),
        "regret_at_1": mean(r["regret_at_1"] for r in measured) if measured else None,
        "regret_at_k": mean(r["regret_at_k"] for r in measured) if measured else None,
        "harm_rate": mean(r["harm"] for r in measured) if measured else None,
        "unnecessary_intervention_rate": mean(r["unnecessary_intervention"] for r in none_optimal)
        if none_optimal
        else None,
        "limitations": [
            "Oracle is hindsight-only and never enters past recommendation input.",
            "No-intervention wins utility ties; a zero score is still an observed result, not missing data.",
            "Top-K regret is retrospective best-in-set coverage, not an executable oracle selector.",
        ],
    }
