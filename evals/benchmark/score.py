"""Score a frozen study using later independent reviews and paired execution records."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from evals.analytics.robustness import save
from tandem_backend.recommend.contracts import CatalogEnvelope, RecommendationItem

from .contracts import NONE_ACTION, ExecutionRecord, TaskReview, TemporalSample
from .metrics import forward_utility, recommendation_quality, validate_records

ROOT = Path(__file__).resolve().parents[2]


def catalog_body_digests(envelope):
    """Bind each action to its reviewed immutable source and parsed Skill body."""
    catalog = CatalogEnvelope.model_validate(envelope)
    if catalog.family != "skills" or not catalog.items:
        raise ValueError("Frozen benchmark catalog must contain Skills")
    expected = {}
    for raw in catalog.items:
        item = RecommendationItem.model_validate(raw)
        source = item.source
        if (
            item.family != "skills"
            or not item.identity.version
            or source.origin != "github"
            or source.status != "verified"
            or not source.url
            or not source.source_path
            or any(not value or not re.fullmatch(r"[0-9a-f]{40}", value) for value in (source.verified_sha, source.blob_sha))
            or not source.content_sha256
            or not re.fullmatch(r"[0-9a-f]{64}", source.content_sha256)
            or item.identity.id in expected
        ):
            raise ValueError("Frozen Skill needs a unique identity, version and immutable source body")
        expected[item.identity.id] = source.content_sha256
    return expected


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def freeze_study(output):
    output = Path(output)
    names = ["samples.json", "method-plan.json", "episode-index.json", "skill-catalog.json"]
    for path in sorted(output.glob("anchor-*/input-manifest.json")):
        if not path.parent.name.endswith("-future"):
            names.extend(
                [
                    str(path.relative_to(output)),
                    str(path.with_name("recommendations.json").relative_to(output)),
                    str(path.with_name("representation-inputs.json").relative_to(output)),
                ]
            )
    manifest = {
        "schema_version": "frozen-benchmark-study-v2",
        "artifacts": {name: file_digest(output / name) for name in names},
        "meaning": "Forecasts and sampling remain immutable; later human reviews and measurements are separate inputs.",
    }
    save(output / "study-manifest.json", manifest)
    return manifest


def read_study(study, *, expected_manifest_digest=None):
    study = Path(study).resolve()
    if expected_manifest_digest is not None and (
        re.fullmatch(r"[0-9a-f]{64}", expected_manifest_digest) is None
        or file_digest(study / "study-manifest.json") != expected_manifest_digest
    ):
        raise ValueError("Frozen study manifest differs from the independently recorded digest")
    manifest = json.loads((study / "study-manifest.json").read_text())
    artifacts = manifest.get("artifacts")
    if (
        manifest.get("schema_version") != "frozen-benchmark-study-v2"
        or not isinstance(artifacts, dict)
        or not {"samples.json", "method-plan.json", "episode-index.json", "skill-catalog.json"} <= set(artifacts)
        or any(
            not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
            for v in artifacts.values()
        )
    ):
        raise ValueError("Frozen study manifest has incomplete or invalid artifact coverage")
    for name, expected in artifacts.items():
        path = (study / name).resolve()
        if not path.is_relative_to(study) or file_digest(path) != expected:
            raise ValueError("Frozen study artifact changed or escaped the study directory")
    samples = [
        TemporalSample.model_validate(s) for s in json.loads((study / "samples.json").read_text())
    ]
    if len({s.sample_id for s in samples}) != len(samples):
        raise ValueError("Frozen study has repeated sample identities")
    plan = json.loads((study / "method-plan.json").read_text())
    bodies = catalog_body_digests(json.loads((study / "skill-catalog.json").read_text()))
    actions = plan.get("plausible_actions", [])
    if (
        plan.get("skill_body_digests") != bodies
        or len(actions) != len(set(actions))
        or set(actions) != {NONE_ACTION, *bodies}
    ):
        raise ValueError("Frozen action set or Skill body differs from its catalog snapshot")
    actionability = {}
    for sample in samples:
        name = (
            f"anchor-{sample.anchor_ts}-history-{sample.history_days}"
            if sample.variant == "correct_history"
            else f"anchor-{sample.anchor_ts}-{sample.variant}"
        )
        references = [
            f"{name}/input-manifest.json",
            f"{name}/recommendations.json",
            f"{name}/representation-inputs.json",
        ]
        if not set(references) <= set(artifacts):
            raise ValueError("Frozen study is missing a past forecast artifact")
        forecast = json.loads((study / references[1]).read_text())
        chosen = plan["ours_rankings"].get(sample.sample_id, [NONE_ACTION])[0]
        if chosen == NONE_ACTION:
            actionability[sample.sample_id] = "ready_no_intervention"
        else:
            cards = [c for c in forecast["recommendations"] if c["resource_id"] == chosen]
            actionability[sample.sample_id] = (
                "ready_for_trial"
                if cards and all(c["recommendation_status"] == "trial" for c in cards)
                else "requires_context_or_adaptation"
            )
    return samples, plan, actionability


def bind_measurements(samples, plan, measurements, reviews, *, actionability=None):
    """Reported independent review is an evaluation input, never a past feature."""
    samples = copy.deepcopy(samples)
    issues = validate_records(samples, measurements)
    by_task = {}
    for review in reviews:
        if review.task_uid in by_task:
            issues.append(
                {"code": "duplicate_independent_task_review", "task_uid": review.task_uid}
            )
        by_task[review.task_uid] = review
    task_ids = {t.task_uid for s in samples for t in s.future_tasks}
    if any(uid not in task_ids for uid in by_task):
        issues.append({"code": "review_task_outside_frozen_study"})
    reviewed = set()
    for sample in samples:
        for task in sample.future_tasks:
            review = by_task.get(task.task_uid)
            if review is None:
                continue
            if not review.boundary_correct or not review.meaningful_goal:
                issues.append(
                    {"code": "task_unit_rejected_requires_new_cohort", "task_uid": task.task_uid}
                )
                continue
            if (
                not set(review.evidence_event_uids) & set(task.human_event_uids)
                or review.available_at < task.start_ts
            ):
                issues.append(
                    {"code": "review_evidence_or_time_mismatch", "task_uid": task.task_uid}
                )
                continue
            task.review_status = "independent_human_reviewed"
            task.checkpoint_status = "verified_exact"
            reviewed.add(task.task_uid)
    config = plan["common_execution"]
    for record in measurements:
        expected_body = plan.get("skill_body_digests", {}).get(record.action_id)
        if expected_body is not None and record.skill_body_digest != expected_body:
            issues.append(
                {"code": "execution_skill_body_differs_from_frozen_catalog", "sample_id": record.sample_id, "action_id": record.action_id}
            )
        if record.purpose == "action_sweep":
            if record.action_id not in plan.get("plausible_actions", []):
                issues.append(
                    {"code": "action_outside_frozen_plausible_set", "sample_id": record.sample_id}
                )
            if record.budget.total_tokens != 10000 or record.seed != config["seeds"][0]:
                issues.append(
                    {
                        "code": "action_sweep_differs_from_registered_budget_or_seed",
                        "sample_id": record.sample_id,
                    }
                )
        if (
            record.method == "ours"
            and record.purpose == "method_comparison"
            and (actionability or {}).get(record.sample_id) == "requires_context_or_adaptation"
        ):
            issues.append(
                {
                    "code": "prediction_not_actionable_at_anchor_requires_new_contextual_study",
                    "sample_id": record.sample_id,
                }
            )
        review = by_task.get(record.task_uid)
        if review and (
            record.checkpoint_digest != review.checkpoint_digest
            or record.check_definition_digest != review.check_definition_digest
        ):
            issues.append(
                {
                    "code": "measurement_differs_from_reviewed_checkpoint_or_checks",
                    "task_uid": record.task_uid,
                }
            )
        if (
            record.model_id != config["model"]
            or record.reasoning_effort != config["reasoning_effort"]
            or record.seed not in config["seeds"]
        ):
            issues.append(
                {
                    "code": "execution_differs_from_registered_model_or_seed",
                    "sample_id": record.sample_id,
                }
            )
        if (
            record.budget.total_tokens not in config["token_budgets"]
            or record.budget.turns != config["turn_budget"]
            or record.budget.tool_calls != config["tool_call_budget"]
            or record.budget.wall_ms != config["wall_budget_ms"]
        ):
            issues.append(
                {"code": "execution_differs_from_registered_budget", "sample_id": record.sample_id}
            )
        if record.purpose == "method_comparison":
            expected = (
                NONE_ACTION
                if record.method == "no_recommendation"
                else plan["generic_policy"]["action"]
                if record.method == "generic"
                else plan["ours_rankings"].get(record.sample_id, [NONE_ACTION])[0]
                if record.method == "ours"
                else None
            )
            if expected is None:
                issues.append(
                    {
                        "code": "method_prediction_not_frozen_in_this_study",
                        "sample_id": record.sample_id,
                        "method": record.method,
                    }
                )
            elif record.action_id != expected:
                issues.append(
                    {"code": "action_differs_from_frozen_prediction", "sample_id": record.sample_id}
                )
    return samples, issues, reviewed


def run(study, output, *, measurements=(), reviews=(), expected_manifest_digest=None):
    study, output = Path(study).resolve(), Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Scoring output must remain under ignored .local/")
    samples, plan, actionability = read_study(
        study, expected_manifest_digest=expected_manifest_digest
    )
    measured = [ExecutionRecord.model_validate(r) for r in measurements]
    reviews = [TaskReview.model_validate(r) for r in reviews]
    samples, issues, reviewed = bind_measurements(
        samples, plan, measured, reviews, actionability=actionability
    )
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    primary = [
        s
        for s in samples
        if s.variant == "correct_history" and s.history_days == 7 and s.future_task_limit == 5
    ]
    ids = {s.sample_id for s in primary}
    records = [r for r in measured if r.sample_id in ids]
    plausible = plan["plausible_actions"]
    forward = forward_utility(
        primary,
        records,
        budgets=plan["common_execution"]["token_budgets"],
        seeds=plan["common_execution"]["seeds"],
    )
    quality = recommendation_quality(primary, records, plan["ours_rankings"], plausible)
    variations = {}
    for sample in samples:
        own = [r for r in measured if r.sample_id == sample.sample_id]
        variations[sample.sample_id] = {
            "history_days": sample.history_days,
            "future_task_limit": sample.future_task_limit,
            "variant": sample.variant,
            "forward": forward_utility(
                [sample],
                own,
                budgets=plan["common_execution"]["token_budgets"],
                seeds=plan["common_execution"]["seeds"],
            ),
            "quality": recommendation_quality([sample], own, plan["ours_rankings"], plausible),
        }
    if issues:
        forward = {"status": "invalid", "issues": issues, "rows": []}
        quality = {"status": "invalid", "issues": issues, "rows": []}
        variations = {}
    report = {
        "schema_version": "benchmark-score-v1",
        "status": "invalid" if issues else "completed",
        "forward_utility_status": forward["status"],
        "recommendation_quality_status": quality["status"],
        "reviews": len(reviewed),
        "measurements": len(measured),
        "model_calls": 0,
        "study_manifest_digest": file_digest(study / "study-manifest.json"),
        "manifest_digest_pinned": expected_manifest_digest is not None,
        "forecast_actionability": actionability,
        "limitations": [
            "Caller-supplied human reviews and execution log digests are not independently attested by this scoring tool.",
            "Unexecuted methods and incomplete controls keep their own unproven status.",
        ],
    }
    save(output / "forward-utility.json", forward)
    save(output / "recommendation-quality.json", quality)
    save(output / "variations.json", variations)
    save(output / "summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executions", type=Path, required=True)
    parser.add_argument("--task-reviews", type=Path, required=True)
    parser.add_argument("--expected-study-digest")
    args = parser.parse_args()
    report = run(
        args.study,
        args.output,
        measurements=json.loads(args.executions.read_text()),
        reviews=json.loads(args.task_reviews.read_text()),
        expected_manifest_digest=args.expected_study_digest,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
