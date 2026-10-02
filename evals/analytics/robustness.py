"""Controlled fact overlays and scoped replays, with eight-family/Skill diagnostics."""

import argparse
import copy
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from tandem_backend.analytics.diagnostics import diagnostics, terminal_text
from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.service import recommend

from .local_diagnostics import snapshot_scope
from .robustness_invariants import validate_result

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "evals/recommendation/fixtures/reviewed-skills.json"
SECTIONS = (
    "overview",
    "sessions",
    "tools",
    "workflow",
    "projects",
    "bottleneck_features",
    "tasks",
    "preferences",
    "instruction",
    "work_graph",
    "lexical",
    "statistics",
)


def save(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def signature(value):
    digest = hashlib.sha256()
    for part in json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).iterencode(value):
        digest.update(part.encode())
    return digest.hexdigest()


def metrics(analysis):
    features = analysis["bottleneck_features"]
    calls = features["respond"].get("tool_sequence")
    retries = features["respond"].get("retry_links")
    validations = features["outcome"].get("validation_runs")
    preferences, instruction = analysis["preferences"], analysis["instruction"]
    return {
        "main_sessions": analysis["overview"]["counts"]["main_sessions"],
        "human_messages": analysis["overview"]["counts"]["human_messages"],
        "projects": len(analysis["projects"]),
        "tool_calls": len(calls) if calls is not None else None,
        "tool_failures": sum(c["tool_result_status"] == "failed" for c in calls)
        if calls is not None
        else None,
        "confirmed_retries": sum(r["state"] == "confirmed" for r in retries)
        if retries is not None
        else None,
        "candidate_retries": sum(r["state"] == "candidate" for r in retries)
        if retries is not None
        else None,
        "total_tokens": features["cost_time"]["usage"].get("total_tokens"),
        "validations": len(validations) if validations is not None else None,
        "validation_failures": sum(v["validation_result"] == "failed" for v in validations)
        if validations is not None
        else None,
        "preference_records": len(preferences["records"])
        if preferences["records"] is not None
        else None,
        "preference_evidence": len(preferences["evidence"])
        if preferences["evidence"] is not None
        else None,
        "instruction_messages": instruction["summary"].get("effective_n"),
    }


def fact_signature(analysis):
    return signature({k: analysis[k] for k in SECTIONS})


def fixture_seed(bundle, scope):
    """A declared constructed failed attempt provides the retry oracle's baseline.

    Three successful retries add three links and zero new failures. Four new
    failed attempts would test both failure and retry changes instead.
    """
    value = copy.deepcopy(bundle)
    source = next((s for s in value.sessions if s.get("kind") == "main"), None)
    if source is None:
        raise ValueError("A main-session baseline is required for the constructed retry seed")
    sid, task, turn = "constructed:retry-root", "constructed:retry-task", "constructed:retry-turn"
    start = (
        scope.from_ts + 1000
        if scope.from_ts is not None
        else min((e["ts"] for e in value.events or [] if e.get("ts") is not None), default=1000)
    )
    if scope.until_ts is not None and start + 100 >= scope.until_ts:
        raise ValueError("Scope too short for the controlled retry fixture")
    value.sessions.append(
        {
            "session_uid": sid,
            "root_uid": sid,
            "kind": "main",
            "agent": "codex",
            "source_id": source.get("source_id"),
            "project_id": source.get("project_id"),
            "started_at": start,
            "status": "unknown",
        }
    )
    value.versions = {**value.versions, "evaluation_overlay": "constructed-retry-seed-v1"}
    add_attempt(value, sid, task, turn, "constructed:seed", 0, start, "failed")
    return value


def add_attempt(bundle, sid, task, turn, uid, seq, start, status, *, retry_of=None):
    call_id, result_id = uid + ":call", uid + ":result"
    digest = hashlib.sha256(b'{"cmd":"constructed_validator"}').hexdigest()
    bundle.events.extend(
        [
            {
                "event_uid": call_id,
                "session_uid": sid,
                "turn_uid": turn,
                "seq": seq,
                "ts": start,
                "kind": "tool.call",
                "actor": "assistant",
                "text": None,
                "attrs": {
                    "task_uid": task,
                    "name_raw": "constructed_validator",
                    "category": "shell",
                    "argument_digest": digest,
                    "argument_digest_kind": "sha256",
                    "fixture_source": "controlled fact overlay, not executed utility",
                },
            },
            {
                "event_uid": result_id,
                "session_uid": sid,
                "turn_uid": turn,
                "seq": seq + 1,
                "ts": start + 10,
                "kind": "tool.result",
                "actor": "tool",
                "text": None,
                "attrs": {
                    "task_uid": task,
                    "status": status,
                    "status_scope": "direct_command",
                    "fixture_source": "controlled fact overlay, not executed utility",
                },
            },
        ]
    )
    bundle.tool_calls.append(
        {
            "call_uid": uid,
            "session_uid": sid,
            "turn_uid": turn,
            "task_uid": task,
            "call_event_uid": call_id,
            "result_event_uid": result_id,
            "name_raw": "constructed_validator",
            "kind": "shell",
            "status": status,
            "status_scope": "direct_command",
            "started_at": start,
            "ended_at": start + 10,
            "wall_elapsed_ms": 10,
            "native_execution_ms": 10,
            "interval_reliable": True,
            "argument_digest": digest,
            "argument_digest_kind": "sha256",
            "retry_of_call_uid": retry_of,
        }
    )
    if bundle.statistical_members is not None:
        bundle.statistical_members["event_uids"].extend([call_id, result_id])


def subset(bundle, ids):
    value = copy.deepcopy(bundle)
    value.sessions = [s for s in value.sessions if s["session_uid"] in ids]
    for field in ("events", "tool_calls", "model_calls", "turns"):
        rows = getattr(value, field)
        if rows is not None:
            setattr(value, field, [r for r in rows if r["session_uid"] in ids])
    if value.statistical_members is not None:
        selected_events = set(bundle.statistical_members["event_uids"])
        value.statistical_members["event_uids"] = [
            e["event_uid"] for e in value.events if e["event_uid"] in selected_events
        ]
    value.versions = {**value.versions, "evaluation_overlay": "controlled-session-ablation-v1"}
    return value


def _run(bundle, scope, output, *, home=None, repeats=5, progress=None):
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 5 <= repeats <= 10:
        raise ValueError("repeats must be between 5 and 10")
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("replays must remain under ignored .local/")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    loaded = load_catalog(items=json.loads(CATALOG.read_text())["items"])
    report = {
        "schema_version": "analysis-robustness-v1",
        "status": "running",
        "scope": asdict(scope),
        "model_calls": 0,
        "cases": [],
        "limitations": [
            "Fact overlays test analytics; native import equivalence runs separately.",
            "Constructed oracles do not measure real semantic accuracy or causal Skill utility.",
            "Independent human golden sessions have not been supplied.",
        ],
    }

    def measure(
        name, source, selected_scope=scope, *, expected=None, unchanged=None, comparison=None
    ):
        started = time.perf_counter()
        analysis = analyze_bundle(
            source, selected_scope, with_text=False, with_recommendations=False
        )
        recommendations = recommend(
            analysis, context={"agent": "codex"}, catalog=loaded.items, family="skills"
        )
        fixture_ids = [
            e["event_uid"] for e in source.events or [] if e.get("attrs", {}).get("fixture_source")
        ]
        invariant = validate_result(
            source,
            selected_scope,
            analysis,
            recommendations,
            home=home,
            fixture_event_uids=fixture_ids,
        )
        observed = metrics(analysis)
        checks = [{"kind": "relational_invariants", "passed": invariant["status"] == "passed"}]
        for key, target in (expected or {}).items():
            checks.append(
                {
                    "kind": "expected_value",
                    "metric": key,
                    "expected": target,
                    "observed": observed[key],
                    "passed": observed[key] == target,
                }
            )
        for key in unchanged or []:
            checks.append(
                {
                    "kind": "must_not_change",
                    "metric": key,
                    "expected": comparison["metrics"][key],
                    "observed": observed[key],
                    "passed": observed[key] == comparison["metrics"][key],
                }
            )
        grouped = diagnostics(analysis, recommendations, loaded.items)
        folder = output / name
        folder.mkdir()
        save(folder / "diagnostics.json", grouped)
        (folder / "diagnostics.txt").write_text(terminal_text(grouped) + "\n", encoding="utf-8")
        save(folder / "recommendations.json", recommendations)
        save(folder / "invariants.json", invariant)
        if fixture_ids:
            save(
                folder / "fixture-events.json",
                [e for e in source.events if e["event_uid"] in set(fixture_ids)],
            )
        row = {
            "case": name,
            "status": "passed" if all(c["passed"] for c in checks) else "failed",
            "metrics": observed,
            "checks": checks,
            "seconds": time.perf_counter() - started,
            "facts_digest": fact_signature(analysis),
            "cards_digest": signature(recommendations["recommendations"]),
            "diagnostics": str(folder / "diagnostics.json"),
            "fixture_event_count": len(fixture_ids),
        }
        report["cases"].append(row)
        save(output / "summary.json", report)
        if progress:
            progress(
                {
                    "case": name,
                    "status": row["status"],
                    "seconds": round(row["seconds"], 2),
                    "violations": invariant["violation_counts"],
                }
            )
        return {
            "row": row,
            "metrics": observed,
            "analysis": analysis,
            "recommendations": recommendations,
        }

    def equality(current, reference, field):
        checks = current["row"]["checks"]
        checks.append({"kind": field, "passed": current["row"][field] == reference["row"][field]})
        if not checks[-1]["passed"]:
            current["row"]["status"] = "failed"

    base = measure("baseline", bundle)
    contexts = [
        ("permission_denied", {"denied_permissions": ["repository_read"]}, "no_cards"),
        ("tools_missing", {"tools": []}, "no_cards"),
        (
            "skills_installed",
            {"installed_resources": [i.identity.id for i in loaded.items]},
            "no_cards",
        ),
        (
            "preference_global",
            {"preferences": [{"dimension": "capability", "value": "debugging"}]},
            "same_signals",
        ),
        (
            "preference_wrong_project",
            {
                "preferences": [
                    {
                        "scope": "project",
                        "target_id": "constructed:unrelated-project",
                        "dimension": "capability",
                        "value": "debugging",
                    }
                ]
            },
            "same_cards",
        ),
    ]
    for name, changes, expectation in contexts:
        started = time.perf_counter()
        fixed_analysis = base["analysis"]
        result = recommend(
            fixed_analysis,
            context={"agent": "codex", **changes},
            catalog=loaded.items,
            family="skills",
        )
        invariant = validate_result(bundle, scope, fixed_analysis, result, home=home)
        checks = [
            {"kind": "relational_invariants", "passed": invariant["status"] == "passed"},
            {
                "kind": "signals_unchanged",
                "passed": result["signals"] == base["recommendations"]["signals"],
            },
        ]
        if expectation == "no_cards":
            checks.append({"kind": "hard_gate", "passed": result["recommendations"] == []})
        elif expectation == "same_cards":
            checks.append(
                {
                    "kind": "wrong_project_ignored",
                    "passed": result["recommendations"]
                    == base["recommendations"]["recommendations"],
                }
            )
        folder = output / name
        folder.mkdir()
        grouped = diagnostics(fixed_analysis, result, loaded.items)
        save(folder / "diagnostics.json", grouped)
        (folder / "diagnostics.txt").write_text(terminal_text(grouped) + "\n", encoding="utf-8")
        save(folder / "recommendations.json", result)
        save(folder / "invariants.json", invariant)
        save(folder / "context.json", {"agent": "codex", **changes})
        row = {
            "case": name,
            "stage": "fixed_analytics_context_counterfactual",
            "status": "passed" if all(c["passed"] for c in checks) else "failed",
            "checks": checks,
            "metrics": base["metrics"],
            "facts_digest": base["row"]["facts_digest"],
            "cards_digest": signature(result["recommendations"]),
            "seconds": time.perf_counter() - started,
            "diagnostics": str(folder / "diagnostics.json"),
        }
        report["cases"].append(row)
        if progress:
            progress({"case": name, "status": row["status"], "seconds": round(row["seconds"], 2)})
        save(output / "summary.json", report)
    seed = fixture_seed(bundle, scope)
    seed_result = measure("retry_seed", seed)
    injected = copy.deepcopy(seed)
    first = next(c for c in injected.tool_calls if c["call_uid"] == "constructed:seed")
    for i in range(3):
        add_attempt(
            injected,
            first["session_uid"],
            first["task_uid"],
            first["turn_uid"],
            f"constructed:retry-{i}",
            2 + i * 2,
            first["ended_at"] + 10 + i * 20,
            "success",
            retry_of=first["call_uid"],
        )
    injected.versions["evaluation_overlay"] = "constructed-three-retries-v1"
    retry = measure(
        "inject_retry",
        injected,
        expected={
            "confirmed_retries": seed_result["metrics"]["confirmed_retries"] + 3,
            "tool_calls": seed_result["metrics"]["tool_calls"] + 3,
        },
        unchanged=(
            "tool_failures",
            "projects",
            "total_tokens",
            "human_messages",
            "validations",
            "preference_records",
            "preference_evidence",
            "instruction_messages",
        ),
        comparison=seed_result,
    )
    retry_signals = [
        s
        for s in retry["recommendations"]["signals"]
        if s["rule_id"] == "identical_retries"
        and s["scope"]["root_session_uid"] == "constructed:retry-root"
    ]
    retry["row"]["checks"].append(
        {
            "kind": "retry_signal_has_new_evidence",
            "passed": bool(retry_signals)
            and any(
                r["id"].startswith("constructed:retry-")
                for s in retry_signals
                for r in s["evidence"]
            ),
        }
    )

    removed = copy.deepcopy(bundle)
    failed = {
        (c["session_uid"], c["call_uid"])
        for c in base["analysis"]["bottleneck_features"]["respond"]["tool_sequence"]
        if c["tool_result_status"] == "failed"
    }
    excluded_events = {
        uid
        for c in removed.tool_calls
        if (c["session_uid"], c["call_uid"]) in failed
        for uid in (c.get("call_event_uid"), c.get("result_event_uid"))
        if uid
    }
    removed.tool_calls = [
        c for c in removed.tool_calls if (c["session_uid"], c["call_uid"]) not in failed
    ]
    removed.events = [e for e in removed.events if e["event_uid"] not in excluded_events]
    if removed.statistical_members is not None:
        removed.statistical_members["event_uids"] = [
            u for u in removed.statistical_members["event_uids"] if u not in excluded_events
        ]
    removed.versions["evaluation_overlay"] = "controlled-failure-ablation-v1"
    measure(
        "remove_failures",
        removed,
        expected={"tool_failures": 0},
        unchanged=(
            "projects",
            "total_tokens",
            "human_messages",
            "preference_records",
            "preference_evidence",
            "instruction_messages",
        ),
        comparison=base,
    )

    for name in ("permute", "unrelated_field", "duplicate"):
        value = copy.deepcopy(bundle)
        for field in ("sessions", "events", "tool_calls", "model_calls", "turns", "projects"):
            rows = getattr(value, field)
            if rows is not None and name == "permute":
                rows.reverse()
            elif (
                rows
                and name == "duplicate"
                and field in ("sessions", "events", "tool_calls", "model_calls")
            ):
                rows.extend(copy.deepcopy(rows[:3]))
        if name == "unrelated_field":
            for event in value.events:
                event["attrs"]["robustness_ui_only"] = "constructed display hint"
        current = measure(name, value, unchanged=base["metrics"], comparison=base)
        equality(current, base, "facts_digest")
        equality(current, base, "cards_digest")

    project = next((s.get("project_id") for s in bundle.sessions if s.get("project_id")), None)
    if project is not None:
        selected_scope = Scope(**{**asdict(scope), "project_ids": [project]})
        value = (
            CanonicalStore(home).analysis_bundle(selected_scope) if home else copy.deepcopy(bundle)
        )
        if not home:
            value.selection_scope = None
        measure("scope_isolation", value, selected_scope)
    children = {
        s["session_uid"] for s in bundle.sessions if s.get("kind") in ("subagent", "workflow_agent")
    }
    if children:
        measure(
            "subagent_only",
            subset(bundle, children),
            expected={"main_sessions": 0, "human_messages": 0},
        )
    main = next(s["session_uid"] for s in bundle.sessions if s.get("kind") == "main")
    selected_scope = Scope(
        **{**asdict(scope), "root_session_uids": [main], "include_children": False}
    )
    value = CanonicalStore(home).analysis_bundle(selected_scope) if home else copy.deepcopy(bundle)
    if not home:
        value.selection_scope = None
    measure("one_session", value, selected_scope, expected={"main_sessions": 1})
    empty_scope = Scope(**{**asdict(scope), "project_ids": []})
    value = CanonicalStore(home).analysis_bundle(empty_scope) if home else copy.deepcopy(bundle)
    if not home:
        value.selection_scope = None
    measure(
        "empty_selection", value, empty_scope, expected={"main_sessions": 0, "human_messages": 0}
    )
    for i in range(repeats):
        current = measure(f"repeat_{i + 1}", bundle, unchanged=base["metrics"], comparison=base)
        equality(current, base, "facts_digest")
        equality(current, base, "cards_digest")
    for row in report["cases"]:
        row["status"] = "passed" if all(c["passed"] for c in row["checks"]) else "failed"
    report["status"] = (
        "passed" if all(r["status"] == "passed" for r in report["cases"]) else "failed"
    )
    report["counts"] = dict(Counter(r["status"] for r in report["cases"]))
    save(output / "summary.json", report)
    return report


def run(bundle, scope, output, *, home=None, repeats=5, progress=None):
    output = Path(output).resolve()
    existed = output.exists()
    try:
        return _run(bundle, scope, output, home=home, repeats=repeats, progress=progress)
    except Exception as exc:
        if not existed and output.is_relative_to((ROOT / ".local").resolve()) and output.is_dir():
            path = output / "summary.json"
            report = json.loads(path.read_text()) if path.exists() else {}
            save(path, {**report, "status": "failed", "error_type": type(exc).__name__})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--home", type=Path)
    selection.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-ts", type=int)
    parser.add_argument("--until-ts", type=int)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.home:
        scope = snapshot_scope(args.home, from_ts=args.from_ts, until_ts=args.until_ts)
        bundle = CanonicalStore(args.home).analysis_bundle(scope)
    else:
        from benchmarks.analytics.synthetic import generate_bundle

        scope = Scope(display_timezone="Asia/Shanghai")
        bundle = AnalysisInputBundle.from_dict(generate_bundle(20, 7))
    report = run(
        bundle,
        scope,
        args.output,
        home=args.home,
        repeats=args.repeats,
        progress=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True),
    )
    print(
        json.dumps(
            {"status": report["status"], "counts": report["counts"], "output": str(args.output)},
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
