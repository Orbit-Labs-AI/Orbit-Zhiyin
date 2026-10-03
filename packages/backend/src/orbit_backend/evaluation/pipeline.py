"""Run labeled synthetic contrasts through the actual acquisition-to-recommendation path.

Expected labels are read only AFTER predictions. Every case gets its own disposable
database, so evaluation inputs cannot update a user's profile or any normal ledger.
"""

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from importlib.resources import files
from pathlib import Path

from .. import __version__
from ..profiling.analysis import analyze
from ..profiling.feedback import signals
from ..recommend.legacy import recommend
from ..recommend.legacy_catalog import resources
from ..reporting.narrative import explain, markdown
from ..store import Store, import_codex


def _write_case(home: Path, case_id: str, steps: list[dict]) -> Path:
    """Convert fixture steps to a Codex-shaped log, without consulting expected labels."""
    if not re.fullmatch(r"[a-z0-9_]{1,64}", case_id):
        raise ValueError("评价案例 ID 无效")
    folder = home / "sessions"
    folder.mkdir(parents=True)
    rows = []
    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def emit(kind, payload):
        rows.append({"type": kind, "payload": payload,
                     "timestamp": (clock + timedelta(seconds=len(rows))).isoformat()})

    emit("session_meta", {"id": case_id, "source": "cli", "cwd": "/fictional/evaluation/" + case_id})
    turn = 0
    for index, step in enumerate(steps):
        if step["kind"] == "user":
            turn += 1
            emit("event_msg", {"type": "task_started", "turn_id": str(turn)})
            emit("turn_context", {"turn_id": str(turn), "model": "evaluation-model"})
        if step["kind"] in ("user", "assistant"):
            emit("response_item", {"type": "message", "role": step["kind"],
                                   "channel": "final" if step["kind"] == "assistant" else None,
                                   "content": [{"type": "text", "text": step["text"]}]})
        elif step["kind"] == "tool":
            emit("response_item", {"type": "function_call", "call_id": str(index),
                                   "name": step["tool"], "arguments": step["arguments"]})
            emit("response_item", {"type": "function_call_output", "call_id": str(index),
                                   "output": step["output"]})
        else:
            raise ValueError("评价案例包含未知步骤")
    target = folder / (case_id + ".jsonl")
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return target


def _metrics(pairs: list[tuple[set, set]]) -> dict:
    """Set precision/recall counts false additions and missed labels separately."""
    tp = sum(len(actual & expected) for actual, expected in pairs)
    fp = sum(len(actual - expected) for actual, expected in pairs)
    fn = sum(len(expected - actual) for actual, expected in pairs)
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "exact_cases": sum(a == e for a, e in pairs), "case_count": len(pairs)}


def evidence_checks(store: Store, data: dict, recs: list[dict]) -> dict:
    """Check traceability and conditional decisions independently of prose style."""
    events = {e.id: e for e in store.events()}
    incidents = {b["id"]: b for b in data["bottlenecks"]}
    observed = signals(list(events.values()))
    catalog = {r["id"]: r for r in resources()}
    references_valid = True
    context_valid = True
    support_valid = True
    source_valid = True
    language_valid = True
    for rec in recs:
        bottleneck = incidents.get(rec["bottleneck_id"])
        profile_ids = rec["profile_evidence_ids"]
        references_valid &= bool(profile_ids and rec["bottleneck_evidence_ids"])
        references_valid &= all(i in events and events[i].kind == "user_message" for i in profile_ids)
        references_valid &= all(i in events for i in rec["bottleneck_evidence_ids"])
        context_valid &= bool(bottleneck and rec["scene"] == bottleneck["scene"])
        context_valid &= bool(bottleneck and set(rec["bottleneck_evidence_ids"]) == set(bottleneck["evidence_ids"]))
        context_valid &= rec["match_basis"] == "profile_and_bottleneck"
        context_valid &= rec["effect_status"] == "unmeasured"
        support_valid &= any(s.event_id in profile_ids and s.dimension in rec["matched_dimensions"] and
                             s.scene == rec["scene"] for s in observed)
        resource = catalog.get(rec["resource_id"])
        sha = rec.get("verified_sha", "")
        source_valid &= bool(resource and re.fullmatch(r"[0-9a-f]{40}", sha) and
                             rec.get("source_url") == f"{resource['url']}/blob/{sha}/{resource['source_path']}")
        language_valid &= bool(bottleneck and resource and rec.get("language") == bottleneck["language"] and
                               resource["language"] in (*bottleneck["language"].split('_or_'), "any"))
        language_valid &= all(i in events and events[i].kind == "user_message" for i in rec.get("context_evidence_ids", []))
    no_profile = recommend({**data, "preferences": []}) == []
    no_incident = recommend({**data, "bottlenecks": []}) == []
    empty_contexts = [{**c, "preferences": []} for c in data.get("contexts", [])]
    no_context = recommend({**data, "contexts": empty_contexts}) == []
    return {"references_valid": bool(references_valid), "original_context_preserved": bool(context_valid),
            "cited_profile_supports_match": bool(support_valid), "versioned_source_reference_valid": bool(source_valid),
            "deliverable_language_preserved": bool(language_valid),
            "profile_ablation_abstains": no_profile, "bottleneck_ablation_abstains": no_incident,
            "context_ablation_abstains": no_context}


def pipeline_benchmark(cases_file: str | Path | None = None, dataset: str = "development") -> dict:
    datasets = {"development": "pipeline_cases.json", "probe": "pipeline_probe_cases.json"}
    if dataset not in datasets:
        raise ValueError("未知的评价数据集")
    raw = Path(cases_file).read_bytes() if cases_file else files("orbit_backend").joinpath("data/" + datasets[dataset]).read_bytes()
    corpus = json.loads(raw)
    if corpus.get("schema_version") != "1.0" or corpus.get("purpose") != "evaluation_only":
        raise ValueError("评价数据必须明确声明 evaluation_only 和支持的格式")
    results = []
    pairs = {key: [] for key in ("dimensions", "bottlenecks", "resources", "readers")}
    with tempfile.TemporaryDirectory(prefix="orbit-evaluation-") as temporary:
        root = Path(temporary)
        for index, case in enumerate(corpus["cases"]):
            home = root / str(index) / "codex"
            source = _write_case(home, case["id"], case["steps"])
            original = sha256(source.read_bytes()).hexdigest()
            store = Store(root / str(index) / "evaluation.sqlite")
            import_codex(store, home)
            data = analyze(store)
            recs = recommend(data)
            report = explain(data, recs)
            # The prediction path above receives neither labels nor evaluation criteria.
            expected = case["expected"]
            actual = {"dimensions": sorted({p["dimension"] for p in data["preferences"]}),
                      "bottlenecks": sorted({b["type"] for b in data["bottlenecks"]}),
                      "resources": sorted({r["resource_id"] for r in recs}),
                      "readers": sorted({r["id"] for c in data["contexts"] for r in c["readers"]}),
                      "user_messages": data["counts"]["user_messages"]}
            for key in pairs:
                pairs[key].append((set(actual[key]), set(expected[key])))
            checks = evidence_checks(store, data, recs)
            checks["source_unchanged"] = sha256(source.read_bytes()).hexdigest() == original
            differences = {key: {"expected": expected[key], "actual": actual[key]} for key in actual
                           if (set(actual[key]) != set(expected[key]) if isinstance(actual[key], list) else actual[key] != expected[key])}
            results.append({"case": case["id"], "matches": not differences and all(checks.values()),
                            "differences": differences, "checks": checks, "output": markdown(report)})
    return {"version": "pipeline-contrasts-v1", "backend_version": __version__,
            "dataset_sha256": sha256(raw).hexdigest(), "split": corpus["split"],
            "cases": len(results), "correct": sum(r["matches"] for r in results),
            "metrics": {key: _metrics(values) for key, values in pairs.items()}, "results": results,
            "human_acceptance": "pending", "history_updated": False,
            "limitation": "构造对照集测量明确规则的误报与漏报，不是独立人类语义评分，也不证明真实资源收益。"}
