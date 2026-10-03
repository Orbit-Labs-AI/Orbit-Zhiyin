"""Freeze rolling past-only recommendations and inspect the actual future history."""

import argparse
import gc
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from orbit_data.service import wait_for_maintenance

from evals.analytics.robustness import metrics as fact_metrics
from evals.analytics.robustness import save, signature
from evals.analytics.robustness_invariants import validate_result
from orbit_backend.analytics import FEATURE_VERSION
from orbit_backend.analytics.common import human
from orbit_backend.analytics.context import AnalysisContext
from orbit_backend.analytics.cost_time.features import usage
from orbit_backend.analytics.diagnostics import diagnostics, terminal_text
from orbit_backend.analytics.inputs import Scope
from orbit_backend.analytics.service import analyze_bundle
from orbit_backend.data_access.store import CanonicalStore
from orbit_backend.privacy import direct_user_text
from orbit_backend.recommend.catalog import load_catalog
from orbit_backend.recommend.service import recommend

from .contracts import METHODS, NONE_ACTION, ExecutionRecord, TemporalSample
from .metrics import (
    DEFAULT_ACTION_SWEEP_BUDGET,
    DEFAULT_TOKEN_BUDGETS,
    action_sweep_budget,
    forward_utility,
    recommendation_quality,
)
from .score import bind_measurements, catalog_body_digests, freeze_study, read_study
from .temporal import DAY_MS, digest_id, episode_index, history_scope, make_sample, rolling_anchors

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "evals/recommendation/fixtures/reviewed-skills.json"


def choices(result):
    return list(dict.fromkeys(c["resource_id"] for c in result["recommendations"])) or [NONE_ACTION]


def overlap(left, right):
    a, b = set(left), set(right)
    return len(a & b) / len(a | b) if a | b else 1.0


def representation_view(analysis, name):
    """A local matching ablation; model-based representations are prepared separately."""
    value = dict(analysis)
    value["analysis_digest"] = digest_id(analysis["analysis_digest"], name)
    if name == "structured_features":
        for key in ("work_graph", "statistics", "lexical", "profile"):
            value.pop(key, None)
    elif name == "task_context_only":
        value["bottleneck_features"] = None
        value["sessions"] = [{**s, "bottleneck_features": None} for s in analysis["sessions"]]
        value["preferences"] = {"records": [], "evidence": [], "status": "excluded"}
        for key in ("instruction", "work_graph", "statistics", "lexical", "profile"):
            value.pop(key, None)
    else:
        raise ValueError("Unknown local representation ablation")
    return value


def bounded_view(value, limit=12000):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {
        "input_chars": min(len(encoded), limit),
        "original_chars": len(encoded),
        "truncated": len(encoded) > limit,
        "content_digest": hashlib.sha256(encoded.encode()).hexdigest(),
        "content": encoded[:limit],
    }


def profile_input(profile):
    """Keep the displayed facts before spending a model budget on graph identifiers."""
    iteration = profile.get("iteration") or {}
    candidates = iteration.get("review_candidates") or []
    return {
        **profile,
        "iteration": {
            **iteration,
            "review_candidate_count": len(candidates),
            "review_sample_limit": 8,
            "review_candidates": [
                {
                    **{k: v for k, v in row.items() if k != "evidence_node_uids"},
                    "evidence_node_counts": {
                        kind: len(uids) for kind, uids in row.get("evidence_node_uids", {}).items()
                    },
                }
                for row in candidates[:8]
            ],
        },
    }


def family_input(families):
    """Preserve every family and unknown value; traceability samples stay local."""
    return {
        family: {
            "status": row["status"],
            "quality": row["quality"],
            "input": {
                key: {k: v for k, v in m.items() if k != "path"} for key, m in row["input"].items()
            },
            "analyzed": {
                key: {k: v for k, v in m.items() if k != "path"}
                for key, m in row["analyzed"].items()
            },
            "unknown_reasons": row["unknown_reasons"],
            "evidence_count": row["evidence"]["count"],
            "interpretation": row["interpretation"],
        }
        for family, row in families.items()
    }


def _snapshot_stamp(home):
    database = (Path(home) / "orbit.db").resolve()
    hashes = {}
    for path in (database, Path(str(database) + "-wal")):
        if path.exists() and path.stat().st_size:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            hashes[path.name] = digest.hexdigest()
    with sqlite3.connect(
        f"{(Path(home) / 'orbit.db').resolve().as_uri()}?mode=ro", uri=True
    ) as db:
        return {
            "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
            "events": db.execute("SELECT count(*) FROM event").fetchone()[0],
            "latest_event_ts": db.execute("SELECT max(ts) FROM event").fetchone()[0],
            "raw_records": db.execute("SELECT count(*) FROM raw_record").fetchone()[0],
            "database_hashes": hashes,
        }


def _native_main_ids(home):
    with sqlite3.connect(
        f"{(Path(home) / 'orbit.db').resolve().as_uri()}?mode=ro", uri=True
    ) as db:
        return {
            row[0]
            for row in db.execute(
                "SELECT s.native_id FROM session s JOIN source p USING(source_id) "
                "WHERE p.agent='codex' AND s.kind='main'"
            )
        }


def _forecast_case(home, sample, folder, loaded, context, *, scope=None, view=None):
    scope = scope or history_scope(sample)
    started = time.perf_counter()
    bundle = CanonicalStore(home).analysis_bundle(scope)
    analysis = analyze_bundle(bundle, scope, with_text=False, with_recommendations=False)
    consumed = representation_view(analysis, view) if view else analysis
    result = recommend(consumed, context=context, catalog=loaded.items, family="skills")
    invariant = validate_result(bundle, scope, consumed, result, home=home)
    selected = AnalysisContext.select(bundle, scope)
    event_ids = {e["event_uid"] for e in selected.events}
    future_ids = {uid for task in sample.future_tasks for uid in task.human_event_uids}
    past_only = all(e.get("ts") is not None and e["ts"] < sample.anchor_ts for e in selected.events)
    checks = {
        "past_only": past_only,
        "past_future_event_disjoint": not bool(event_ids & future_ids),
        "relational_invariants": invariant["status"] == "passed",
    }
    folder.mkdir(parents=True)
    grouped = diagnostics(analysis, result, loaded.items)
    save(folder / "diagnostics.json", grouped)
    (folder / "diagnostics.txt").write_text(terminal_text(grouped) + "\n", encoding="utf-8")
    save(folder / "recommendations.json", result)
    save(folder / "invariants.json", invariant)
    save(
        folder / "input-manifest.json",
        {
            "scope": asdict(scope),
            "sessions": [s["session_uid"] for s in selected.sessions],
            "statistical_event_uids": sorted(event_ids),
            "future_event_uids_seen": sorted(event_ids & future_ids),
            "input_signature": signature(
                sorted((e["event_uid"], e.get("ts")) for e in selected.events)
            ),
            "representation": view or "full_system",
            "feature_version": FEATURE_VERSION,
            "model_calls": 0,
        },
    )
    raw = [
        {
            "event_uid": e["event_uid"],
            "ts": e["ts"],
            "text": direct_user_text(e.get("text") or "")[:1200],
        }
        for e in selected.events
        if human(e, selected.main_ids)
    ]
    save(
        folder / "representation-inputs.json",
        {
            "status": "prepared_locally_not_sent_to_model",
            "model_calls": 0,
            "raw_history": bounded_view(raw),
            "ui_profile": bounded_view(profile_input(grouped["profile"])),
            "structured_features": bounded_view(family_input(grouped["families"])),
            "task_context": bounded_view(
                [
                    {k: task.get(k) for k in ("task_uid", "task_goal", "domain", "task_type")}
                    for task in analysis["tasks"]["records"]
                ]
            ),
        },
    )
    row = {
        "case_id": folder.name,
        "sample_id": sample.sample_id,
        "variant": sample.variant,
        "history_days": sample.history_days,
        "anchor_ts": sample.anchor_ts,
        "scope": asdict(scope),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "facts": fact_metrics(analysis),
        "selected_actions": choices(result),
        "recommendation_status": result["status"],
        "recommendation_cards": len(result["recommendations"]),
        "needs_context_cards": sum(
            c["recommendation_status"] == "needs_context" for c in result["recommendations"]
        ),
        "seconds": time.perf_counter() - started,
        "diagnostics": str(folder / "diagnostics.json"),
        "utility_status": "unproven",
    }
    roots = [s["session_uid"] for s in analysis["sessions"]]
    projects = sorted({s.get("project_id") for s in selected.sessions if s.get("project_id")})
    return row, roots, projects


def _future_observations(home, samples, folder, loaded):
    primary = max(samples, key=lambda s: s.future_task_limit)
    roots = sorted({uid for task in primary.future_tasks for uid in task.root_session_uids})
    scope = Scope(
        agent_ids=["codex"],
        from_ts=primary.anchor_ts,
        until_ts=primary.future_until_ts,
        root_session_uids=roots,
    )
    bundle = CanonicalStore(home).analysis_bundle(scope)
    context = AnalysisContext.select(bundle, scope)
    analysis = analyze_bundle(bundle, scope, with_text=False, with_recommendations=False)
    features = analysis["bottleneck_features"]
    calls = features["respond"].get("tool_sequence") or []
    validations = features["outcome"].get("validation_runs") or []
    observations = []
    for task in primary.future_tasks:
        own_calls = [c for c in calls if c.get("task_uid") == task.task_uid]
        own_validations = [v for v in validations if v.get("task_uid") == task.task_uid]
        own_models = [m for m in context.model_calls or [] if m.get("task_uid") == task.task_uid]
        own_events = [e for e in context.events if e.get("task_uid") == task.task_uid]
        ambiguous_models = [
            m
            for m in context.model_calls or []
            if m.get("task_uid") is None and m["session_uid"] in task.root_session_uids
        ]
        tokens = usage(
            own_models,
            own_events,
            context.sessions,
            scope,
            context.model_calls is not None and not ambiguous_models,
        )
        observations.append(
            {
                "task_uid": task.task_uid,
                "boundary_quality": task.boundary_quality,
                "human_review_status": task.review_status,
                "checkpoint_status": task.checkpoint_status,
                "tool_calls": len(own_calls),
                "known_tool_failures": sum(c["tool_result_status"] == "failed" for c in own_calls),
                "unknown_tool_status": sum(
                    c["tool_result_status"] not in ("success", "failed") for c in own_calls
                ),
                "validation_result_counts": dict(
                    Counter(v["validation_result"] for v in own_validations)
                ),
                "observed_request_tokens": tokens.get("total_tokens"),
                "model_task_unknown_n": len(ambiguous_models),
                "task_pass": None,
                "recommendation_uplift": None,
                "meaning": "historical observations only; individual command checks do not establish task acceptance or intervention effect",
            }
        )
    folder.mkdir()
    save(folder / "observations.json", observations)
    grouped = diagnostics(analysis, None, loaded.items)
    save(folder / "diagnostics.json", grouped)
    (folder / "diagnostics.txt").write_text(terminal_text(grouped) + "\n", encoding="utf-8")
    save(
        folder / "input-manifest.json",
        {
            "scope": asdict(scope),
            "purpose": "evaluation_only_never_used_by_forecast",
            "selected_future_task_uids": [t.task_uid for t in primary.future_tasks],
            "model_calls": 0,
        },
    )
    return observations


def run(
    home,
    output,
    *,
    user_id="local-codex-user",
    anchors=None,
    anchor_count=3,
    history_days=(3, 7, 14, 30),
    future_counts=(1, 3, 5, 10),
    context=None,
    execution_records=None,
    wrong_user_home=None,
    wrong_user_id=None,
    progress=None,
):
    if not history_days or any(
        isinstance(n, bool) or n not in (3, 7, 14, 30) for n in history_days
    ):
        raise ValueError("History sensitivity uses 3/7/14/30 days")
    if not future_counts or any(
        isinstance(n, bool) or n not in (1, 3, 5, 10) for n in future_counts
    ):
        raise ValueError("Future sensitivity uses 1/3/5/10 meaningful tasks")
    if wrong_user_home is not None and (not wrong_user_id or wrong_user_id == user_id):
        raise ValueError(
            "Wrong-user ablation needs an explicitly different user identity and database"
        )
    if wrong_user_home is not None and Path(wrong_user_home).resolve() == Path(home).resolve():
        raise ValueError("Own history cannot be relabeled as a wrong user's history")
    if wrong_user_home is not None:
        own_ids, other_ids = _native_main_ids(home), _native_main_ids(wrong_user_home)
        if not other_ids or own_ids & other_ids:
            raise ValueError("Wrong-user history needs distinct native main sessions, not a copy")
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Real benchmark output must remain under ignored .local/")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    context = context or {"agent": "codex"}
    loaded = load_catalog(items=json.loads(CATALOG.read_text())["items"])
    catalog_snapshot = {"schema_version": "recommendation-catalog-v1", "family": "skills", "items": [item.model_dump(mode="json") for item in loaded.items]}
    bodies = catalog_body_digests(catalog_snapshot)
    save(output / "skill-catalog.json", catalog_snapshot)
    wait_for_maintenance(home)
    if wrong_user_home is not None:
        wait_for_maintenance(wrong_user_home)
    before = _snapshot_stamp(home)
    wrong_user_before = _snapshot_stamp(wrong_user_home) if wrong_user_home is not None else None
    report = {
        "schema_version": "temporal-benchmark-v1",
        "status": "running",
        "model_calls": 0,
        "user_id": user_id,
        "snapshot_before": before,
        "wrong_user_snapshot_before": wrong_user_before,
        "cases": [],
        "samples": [],
        "future_observations": [],
        "utility_status": "unproven",
        "accuracy_status": "unreviewed",
        "limitations": [
            "One user's observational history is not a randomized intervention trial.",
            "Task episodes remain candidates until independently reviewed.",
            "Exact pre-task repository snapshots and paired control executions are not supplied.",
            "Raw-history/profile LLM baselines are prepared locally; external history transmission is not authorized.",
            "Installed resources, tools and permissions are unknown unless supplied in context.",
            "Retrospective replay fixes the current reviewed catalog and model; their availability at the historical anchor is not established.",
        ],
    }
    save(output / "summary.json", report)
    samples, rankings = [], {}

    def record(row):
        report["cases"].append(row)
        save(output / "summary.json", report)
        if progress:
            progress(
                {
                    k: row[k]
                    for k in ("case_id", "status", "seconds", "selected_actions")
                    if k in row
                }
            )

    try:
        index = episode_index(home)
        chosen_anchors = sorted(
            set(anchors if anchors is not None else rolling_anchors(index, anchor_count))
        )
        if not chosen_anchors or any(
            isinstance(ts, bool) or not isinstance(ts, int) for ts in chosen_anchors
        ):
            raise ValueError("At least one explicit or recorded rolling anchor is required")
        save(
            output / "episode-index.json",
            {**index, "episodes": [e.model_dump() for e in index["episodes"]]},
        )
        report["episode_count"] = len(index["episodes"])
        report["observed_range"] = [index["observed_from_ts"], index["observed_until_ts"]]
        report["anchors"] = chosen_anchors
        for anchor in chosen_anchors:
            history_rows = {}
            for days in sorted(set(history_days) | {7}):
                sample = make_sample(
                    index, user_id=user_id, anchor_ts=anchor, history_days=days, future_task_limit=5
                )
                row, roots, projects = _forecast_case(
                    home, sample, output / f"anchor-{anchor}-history-{days}", loaded, context
                )
                row["available_history_days"] = min(
                    days, max(0, (anchor - index["observed_from_ts"]) / DAY_MS)
                )
                record(row)
                history_rows[days] = (row, roots, projects)
                for count in sorted(set(future_counts) | {5}):
                    frozen = make_sample(
                        index,
                        user_id=user_id,
                        anchor_ts=anchor,
                        history_days=days,
                        future_task_limit=count,
                    )
                    samples.append(frozen)
                    rankings[frozen.sample_id] = row["selected_actions"]
            baseline, roots, projects = history_rows[7]
            base_sample = make_sample(
                index, user_id=user_id, anchor_ts=anchor, history_days=7, future_task_limit=5
            )
            variants = []
            for seed in (7, 11, 19):
                ordered = sorted(
                    roots, key=lambda uid: digest_id("missing-root-seed", seed, anchor, uid)
                )
                for percent in (10, 30, 50):
                    drop = (
                        min(len(roots), max(1, round(len(roots) * percent / 100))) if roots else 0
                    )
                    kept = ordered[drop:]
                    variants.append(
                        (
                            f"missing_roots_{percent}_seed_{seed}",
                            home,
                            history_scope(base_sample, root_session_uids=kept),
                            None,
                            {
                                "missing_unit": "main root session",
                                "missing_seed": seed,
                                "requested_missing_percent": percent,
                                "actual_missing_fraction": drop / len(roots) if roots else None,
                                "removed_roots": drop,
                                "original_roots": len(roots),
                            },
                        )
                    )
            future_projects = {t.project_id for t in base_sample.future_tasks if t.project_id}
            variants.append(
                (
                    "cross_project",
                    home,
                    history_scope(
                        base_sample, project_ids=[p for p in projects if p not in future_projects]
                    ),
                    None,
                    {
                        "history_projects_excluded": sorted(future_projects),
                        "future_projects": sorted(future_projects),
                    },
                )
            )
            variants.append(
                ("no_history", home, history_scope(base_sample, root_session_uids=[]), None, {})
            )
            for view in ("task_context_only", "structured_features"):
                variants.append((view, home, history_scope(base_sample), view, {}))
            if wrong_user_home is not None:
                variants.append(
                    (
                        "wrong_user_history",
                        wrong_user_home,
                        history_scope(base_sample),
                        None,
                        {"history_user_id": wrong_user_id},
                    )
                )
            else:
                record(
                    {
                        "case_id": f"anchor-{anchor}-wrong_user_history",
                        "status": "unavailable",
                        "reason": "No independently identified second user's canonical history supplied; own history is not relabeled as another user's.",
                    }
                )
            for name, source_home, scope, view, details in variants:
                data = base_sample.model_dump()
                data.update(sample_id=digest_id(base_sample.sample_id, name), variant=name)
                variant_sample = TemporalSample.model_validate(data)
                row, _, _ = _forecast_case(
                    source_home,
                    variant_sample,
                    output / f"anchor-{anchor}-{name}",
                    loaded,
                    context,
                    scope=scope,
                    view=view,
                )
                row.update(
                    details,
                    top_k_jaccard_with_correct_history=overlap(
                        row["selected_actions"], baseline["selected_actions"]
                    ),
                )
                record(row)
                samples.append(variant_sample)
                rankings[variant_sample.sample_id] = row["selected_actions"]
            future_samples = [
                s
                for s in samples
                if s.anchor_ts == anchor and s.history_days == 7 and s.variant == "correct_history"
            ]
            observed = _future_observations(
                home, future_samples, output / f"anchor-{anchor}-future", loaded
            )
            report["future_observations"].append({"anchor_ts": anchor, "tasks": observed})
            gc.collect()
        save(output / "samples.json", [s.model_dump() for s in samples])
        generic_action = loaded.items[0].identity.id
        save(
            output / "method-plan.json",
            {
                "methods": list(METHODS),
                "no_recommendation_action": NONE_ACTION,
                "generic_policy": {
                    "action": generic_action,
                    "basis": "fixed first reviewed catalog entry; independent of history and future",
                },
                "ours_rankings": rankings,
                "plausible_actions": [NONE_ACTION, *[i.identity.id for i in loaded.items]],
                "skill_body_digests": bodies,
                "resource_availability": "retrospective replay using a fixed current catalog; historical availability unproven",
                "raw_history_llm": {
                    "status": "not_executed",
                    "model": "gpt-6.1-sol",
                    "reasoning_effort": "medium",
                    "input_char_cap": 12000,
                    "model_calls": 0,
                },
                "oracle": {
                    "status": "unavailable_without_complete_action_sweep",
                    "hindsight_only": True,
                },
                "common_execution": {
                    "token_budgets": list(DEFAULT_TOKEN_BUDGETS),
                    "action_sweep_budget": DEFAULT_ACTION_SWEEP_BUDGET,
                    "turn_budget": 20,
                    "tool_call_budget": 50,
                    "wall_budget_ms": 300000,
                    "model": "gpt-6.1-sol",
                    "reasoning_effort": "medium",
                    "seeds": [0],
                    "require_exact_checkpoint_and_environment": True,
                    "include_recommendation_tokens": True,
                },
            },
        )
        execution = [ExecutionRecord.model_validate(r) for r in (execution_records or [])]
        freeze_study(output)
        frozen_samples, plan, actionability = read_study(output)
        samples, execution_issues, _ = bind_measurements(
            frozen_samples, plan, execution, (), actionability=actionability
        )
        report["forecast_actionability"] = actionability
        primary_samples = [
            s
            for s in samples
            if s.variant == "correct_history" and s.history_days == 7 and s.future_task_limit == 5
        ]
        primary_ids = {s.sample_id for s in primary_samples}
        primary_execution = [r for r in execution if r.sample_id in primary_ids]
        forward = forward_utility(primary_samples, primary_execution)
        quality = recommendation_quality(
            primary_samples, primary_execution, rankings, [i.identity.id for i in loaded.items],
            token_budget=action_sweep_budget(plan["common_execution"]),
            seed=plan["common_execution"]["seeds"][0],
        )
        if execution_issues:
            forward = {"status": "invalid", "issues": execution_issues, "rows": []}
            quality = {"status": "invalid", "issues": execution_issues, "rows": []}
        save(output / "forward-utility.json", forward)
        save(output / "recommendation-quality.json", quality)
        report["samples"] = [
            {
                "sample_id": s.sample_id,
                "anchor_ts": s.anchor_ts,
                "history_days": s.history_days,
                "variant": s.variant,
                "future_task_limit": s.future_task_limit,
                "future_task_count": len(s.future_tasks),
                "future_complete": s.future_complete,
            }
            for s in samples
        ]
        report["snapshot_after"] = _snapshot_stamp(home)
        report["source_snapshot_unchanged"] = before == report["snapshot_after"]
        report["wrong_user_snapshot_after"] = (
            _snapshot_stamp(wrong_user_home) if wrong_user_home is not None else None
        )
        report["wrong_user_snapshot_unchanged"] = (
            wrong_user_before == report["wrong_user_snapshot_after"]
            if wrong_user_home is not None
            else None
        )
        report["forward_utility_status"] = forward["status"]
        report["recommendation_quality_status"] = quality["status"]
        report["counts"] = dict(Counter(r["status"] for r in report["cases"]))
        report["status"] = (
            "passed"
            if report["source_snapshot_unchanged"]
            and report["wrong_user_snapshot_unchanged"] is not False
            and not execution_issues
            and all(r["status"] in ("passed", "unavailable") for r in report["cases"])
            else "failed"
        )
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        save(output / "summary.json", report)
        raise
    save(output / "summary.json", report)
    (output / "report.md").write_text(report_text(report, forward, quality), encoding="utf-8")
    return report


def report_text(report, forward, quality):
    lines = [
        "# 过去到未来推荐 Benchmark",
        "",
        "## 做了什么",
        "",
        "在多个滚动锚点冻结过去的推荐，再单独读取最多 72 小时内接下来的真实任务。对照历史长度、未来任务数、缺失历史、跨项目和输入表示。",
        "",
        "## 如何做",
        "",
        f"共 {len(report['anchors'])} 个锚点，{len(report['samples'])} 个冻结样本；自动检查结果：{report['counts']}。每次分析都有八族与逐 Skill 诊断、范围、事件清单和关系校验。",
        "",
        "## 为什么",
        "",
        "防止未来数据进入推荐，并让评委区分解析覆盖、推荐触发和真实工具效用。",
        "",
        "## 结论",
        "",
        f"时间与证据检查：{report['status']}。效用与质量：{forward['status']} / {quality['status']}。",
        "",
        "| 指标 | 当前结果 |",
        "| --- | --- |",
        "| Pass@5k / 10k / 20k | 未证实 |",
        "| Token / Turn / Tool / Wall 改善 | 未证实 |",
        "| Regret@1 / @K / Harm | 未证实 |",
        "",
        "历史未来窗口中的失败、检查和 Token 是观察值，不能替代同任务同环境的干预对照。未执行的 LLM 和 Oracle baseline 不填入虚构分数。",
        "",
        "## 难点",
        "",
        *["- " + value for value in report["limitations"]],
        "",
        "## 下一步",
        "",
        "独立确认任务边界，保存开始前完整 checkpoint，按 method-plan.json 的相同模型与预算执行五组对照及 action sweep，再提交符合执行记录契约的测量。",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--user-id", default="local-codex-user")
    parser.add_argument("--anchor-ts", type=int, action="append")
    parser.add_argument("--anchors", type=int, default=3)
    parser.add_argument("--history-days", type=int, nargs="+", default=[3, 7, 14, 30])
    parser.add_argument("--future-counts", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--context", type=Path)
    parser.add_argument("--execution-records", type=Path)
    parser.add_argument("--wrong-user-home", type=Path)
    parser.add_argument("--wrong-user-id")
    args = parser.parse_args()
    output = args.output or ROOT / ".local/benchmark" / (
        "run-" + str(int(time.time())) + "-" + uuid4().hex[:8]
    )
    previous = os.umask(0o077)
    try:
        report = run(
            args.home,
            output,
            user_id=args.user_id,
            anchors=args.anchor_ts,
            anchor_count=args.anchors,
            history_days=args.history_days,
            future_counts=args.future_counts,
            context=json.loads(args.context.read_text()) if args.context else None,
            execution_records=json.loads(args.execution_records.read_text())
            if args.execution_records
            else None,
            wrong_user_home=args.wrong_user_home,
            wrong_user_id=args.wrong_user_id,
            progress=lambda r: print(json.dumps(r, ensure_ascii=False), flush=True),
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "utility": report["forward_utility_status"],
                    "output": str(output),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0 if report["status"] == "passed" else 1
    finally:
        os.umask(previous)


if __name__ == "__main__":
    raise SystemExit(main())
