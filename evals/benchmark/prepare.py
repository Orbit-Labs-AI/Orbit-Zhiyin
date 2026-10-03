"""Prepare unfilled independent-review and execution work from a frozen study."""

import argparse
from collections import Counter
from pathlib import Path

from evals.analytics.robustness import save

from .contracts import NONE_ACTION
from .metrics import action_sweep_budget
from .score import ROOT, file_digest, read_study


def run(study, output, *, expected_manifest_digest=None):
    study, output = Path(study).resolve(), Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Review and execution preparation must remain under ignored .local/")
    samples, plan, actionability = read_study(
        study, expected_manifest_digest=expected_manifest_digest
    )
    primary = [
        s
        for s in samples
        if s.variant == "correct_history" and s.history_days == 7 and s.future_task_limit == 5
    ]
    tasks = {}
    for sample in samples:
        for task in sample.future_tasks:
            row = tasks.setdefault(
                task.task_uid,
                {
                    "task_uid": task.task_uid,
                    "root_session_uids": task.root_session_uids,
                    "project_id": task.project_id,
                    "start_ts": task.start_ts,
                    "boundary_quality": task.boundary_quality,
                    "human_event_uids": set(),
                    "status": "pending_independent_human_review",
                },
            )
            row["human_event_uids"].update(task.human_event_uids)
    for row in tasks.values():
        row["human_event_uids"] = sorted(row["human_event_uids"])
    review_packet = {
        "schema_version": "benchmark-review-packet-v1",
        "status": "unlabeled",
        "tasks": list(tasks.values()),
        "reviewed_tasks": 0,
        "required_review_fields": [
            "reviewer_id",
            "source=independent_human",
            "boundary_correct",
            "meaningful_goal",
            "evidence_event_uids",
            "checkpoint_digest",
            "check_definition_digest",
            "available_at",
        ],
        "instructions": [
            "从本地 canonical 轨迹回查列出的真人事件，独立确认目标及边界。",
            "独立审阅者提供判断；此文件没有程序或模型答案。",
            "找回任务开始前的真实 checkpoint 和验收定义，不以当前仓库状态替代。",
            "边界不正确时另建 cohort，不能静默删除已有坏样本后提高分数。",
        ],
    }
    grid = []
    config = plan["common_execution"]
    for sample in primary:
        for task in sample.future_tasks:
            for budget in config["token_budgets"]:
                for seed in config["seeds"]:
                    for method in plan["methods"]:
                        action = (
                            NONE_ACTION
                            if method == "no_recommendation"
                            else plan["generic_policy"]["action"]
                            if method == "generic"
                            else plan["ours_rankings"].get(sample.sample_id, [NONE_ACTION])[0]
                            if method == "ours"
                            else None
                        )
                        status = (
                            "requires_checkpoint_environment_and_checks"
                            if action is not None
                            else "prediction_not_frozen"
                        )
                        if (
                            method == "ours"
                            and actionability[sample.sample_id] == "requires_context_or_adaptation"
                        ):
                            status = "requires_new_contextual_study"
                        grid.append(
                            {
                                "sample_id": sample.sample_id,
                                "task_uid": task.task_uid,
                                "method": method,
                                "purpose": "method_comparison",
                                "action_id": action,
                                "expected_skill_body_digest": plan["skill_body_digests"].get(action),
                                "seed": seed,
                                "budget": {
                                    "total_tokens": budget,
                                    "turns": config["turn_budget"],
                                    "tool_calls": config["tool_call_budget"],
                                    "wall_ms": config["wall_budget_ms"],
                                },
                                "status": status,
                                "measurement": None,
                            }
                        )
            for action in plan["plausible_actions"]:
                grid.append(
                    {
                        "sample_id": sample.sample_id,
                        "task_uid": task.task_uid,
                        "method": "oracle",
                        "purpose": "action_sweep",
                        "action_id": action,
                        "expected_skill_body_digest": plan["skill_body_digests"].get(action),
                        "seed": config["seeds"][0],
                        "budget": {
                            "total_tokens": action_sweep_budget(config),
                            "turns": config["turn_budget"],
                            "tool_calls": config["tool_call_budget"],
                            "wall_ms": config["wall_budget_ms"],
                        },
                        "status": "requires_checkpoint_environment_and_checks",
                        "measurement": None,
                    }
                )
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    save(output / "review-packet.json", review_packet)
    save(output / "execution-grid.json", {"common_execution": config, "rows": grid})
    save(output / "task-reviews.json", [])
    save(output / "executions.json", [])
    summary = {
        "schema_version": "benchmark-preparation-v1",
        "status": "prepared_unmeasured",
        "future_tasks": len(tasks),
        "primary_samples": len(primary),
        "primary_task_instances": sum(len(s.future_tasks) for s in primary),
        "planned_slots": len(grid),
        "slot_status": dict(Counter(row["status"] for row in grid)),
        "reviews": 0,
        "measurements": 0,
        "model_calls": 0,
        "study_manifest_digest": file_digest(study / "study-manifest.json"),
    }
    save(output / "summary.json", summary)
    return summary


def main():
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-study-digest")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.study, args.output, expected_manifest_digest=args.expected_study_digest),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
