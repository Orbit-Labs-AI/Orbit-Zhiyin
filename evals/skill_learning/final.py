"""Freeze before test access, then execute the fixed three-arm held-out comparison."""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from orbit_backend.recommend.learned import DEFAULTS, retrieve

from .interventions import ACTIVATION, export_llm, export_selection
from .runtime import one_run
from .study import REPOSITORY, command, digest, object_digest, read, save, tree, validate_protocol

RUNTIME_KEYS = ("pi", "provider", "model", "thinking", "memory", "context_limit", "max_turns",
                "hard_timeout_seconds", "workers", "container_memory", "container_cpus", "model_config",
                "pip_index", "apt_mirror", "pi_version")


def freeze(root, library_path, llm_path, validation_path, *, mode="bundle", top_k=2):
    if (root / "freeze.json").exists():
        raise ValueError("A final freeze already exists; never overwrite it")
    if command(["git", "-C", REPOSITORY, "status", "--porcelain"]):
        raise ValueError("Commit and verify the complete implementation before freezing")
    protocol, study = read(root / "protocol.json"), read(root / "study.json")
    validate_protocol(protocol)
    headroom, validation = read(root / "headroom-summary.json"), read(validation_path)
    families = headroom["formal_candidate_families"]
    library = read(library_path)
    if set(validation) != set(families):
        raise ValueError("Validation must cover every family selected before formal testing")
    proof, comparisons, used_skills = {}, [], 0
    for family in families:
        if not any(p["family"] == family and p["headroom_passed"] for p in headroom["pairs"]):
            raise ValueError("Selected family lacks pre-test oracle headroom")
        rows = validation[family]
        baseline = read(Path(rows["baseline"]) / "result.json")
        ours = read(Path(rows["ours"]) / "result.json")
        usage = read(Path(rows["ours"]) / "usage-observation.json")
        if any(r["split"] != "validation" or r["family"] != family for r in (baseline, ours)):
            raise ValueError("Validation proof contains the wrong split or family")
        if not isinstance(ours["passed"], bool) or not isinstance(baseline["passed"], bool):
            raise ValueError("Unknown validation outcomes cannot establish improvement")
        used_skills += usage["counts"]["confirmed_used_skills"]
        bound = baseline["usage"]["known_total_tokens"]
        tokens = ours["usage"]["total_tokens"]
        comparisons.append((baseline["passed"], ours["passed"], bound, tokens))
        task = next(t for t in study["tasks"] if t["task_id"] == ours["task_id"])
        query = (root / "tasks/prompts" / (task["task_id"] + ".md")).read_text()
        selected = retrieve(library, query, capabilities=["read", "write", "edit", "bash"],
                            config={"top_k": top_k})
        proof[family] = {"baseline": rows["baseline"], "ours": rows["ours"],
                         "validated_recommendations": [c["candidate_id"] for c in selected["candidates"]],
                         "baseline_sha256": digest(Path(rows["baseline"]) / "result.json"),
                         "ours_sha256": digest(Path(rows["ours"]) / "result.json"),
                         "usage_sha256": digest(Path(rows["ours"]) / "usage-observation.json")}
    baseline_passes = sum(row[0] for row in comparisons)
    ours_passes = sum(row[1] for row in comparisons)
    total_lower_bound = sum(row[2] for row in comparisons)
    complete_ours = all(row[3] is not None for row in comparisons)
    improved = ours_passes > baseline_passes or (
        ours_passes == baseline_passes and complete_ours and total_lower_bound > 0
        and sum(row[3] for row in comparisons) <= .9 * total_lower_bound)
    if not improved or not used_skills or not any(p["validated_recommendations"] for p in proof.values()):
        raise ValueError("Require aggregate validation improvement and confirmed use; retain every selected family")
    if any(t["split"] == "test" for t in study["tasks"]):
        raise ValueError("Test tasks were prepared before freeze")
    tests = [{"task_id": f"{family}-{number}", "family": family, "split": "test"}
             for family in families for number in protocol["candidate_families"][family]["test"]]
    for task in tests:
        if (Path(study["source"]) / "tasks" / task["family"] / task["task_id"]).exists():
            raise ValueError("Held-out test content is already present before freeze")
    order = [{**task, "arm": arm} for task in tests for arm in ("vanilla", "ours", "llm")]
    random.Random(20261004).shuffle(order)
    receipt = {"version": "orbit-skill-learning-final-v1", "created_at": time.time(),
               "code_commit": command(["git", "-C", REPOSITORY, "rev-parse", "HEAD"]),
               "protocol_sha256": digest(root / "protocol.json"), "source_commit": protocol["source"]["commit"],
               "selected_families": families, "splits": {f: protocol["candidate_families"][f] for f in families},
               "runtime": {key: study.get(key) for key in RUNTIME_KEYS},
               "library": str(library_path), "library_sha256": digest(library_path),
               "llm_result": str(llm_path), "llm_sha256": digest(llm_path),
               "validation_proof": proof, "headroom_sha256": digest(root / "headroom-summary.json"),
               "retrieval": {**DEFAULTS, "top_k": top_k}, "intervention_mode": mode,
               "activation_instruction": ACTIVATION, "run_order": order,
               "heldout_content_present_at_freeze": False,
               "rules": ["No test feedback enters learning, retrieval parameters or family selection",
                         "Preserve all attempts, costs, unknown usage and valid task failures",
                         "Provider changes require a separate cohort; never silently mix matched arms"]}
    save(root / "freeze.json", receipt)
    (root / "freeze.sha256").write_text(digest(root / "freeze.json") + "\n")
    return receipt


def check_freeze(root):
    receipt = read(root / "freeze.json")
    if digest(root / "freeze.json") != (root / "freeze.sha256").read_text().strip():
        raise ValueError("Freeze record changed")
    if command(["git", "-C", REPOSITORY, "status", "--porcelain"]) or receipt["code_commit"] != command(
            ["git", "-C", REPOSITORY, "rev-parse", "HEAD"]):
        raise ValueError("Test execution requires the clean frozen code commit")
    for path, sha in ((root / "protocol.json", receipt["protocol_sha256"]),
                      (Path(receipt["library"]), receipt["library_sha256"]),
                      (Path(receipt["llm_result"]), receipt["llm_sha256"])):
        if digest(path) != sha:
            raise ValueError("Frozen protocol, library or baseline changed")
    study = read(root / "study.json")
    if {key: study.get(key) for key in RUNTIME_KEYS} != receipt["runtime"]:
        raise ValueError("Execution settings or provider changed after freeze")
    if study["benchmark_commit"] != receipt["source_commit"]:
        raise ValueError("Benchmark revision changed")
    expected = {r["task_id"] for r in receipt["run_order"]}
    actual = {t["task_id"] for t in study["tasks"] if t["split"] == "test"}
    if actual != expected:
        raise ValueError("Prepared test tasks do not match frozen split")
    return receipt, study


def execute(root, credentials, docker="docker"):
    receipt, study = check_freeze(root)
    library, llm = read(Path(receipt["library"])), read(Path(receipt["llm_result"]))
    prepared = []
    for item in receipt["run_order"]:
        task = next(t for t in study["tasks"] if t["task_id"] == item["task_id"])
        output = root / "test" / f"{task['task_id']}--{item['arm']}"
        if output.exists():
            raise ValueError("Formal attempt already exists; preserve it and review before resuming")
        assets = None
        if item["arm"] != "vanilla":
            assets = root / "test-assets" / output.name
            if item["arm"] == "llm":
                export_llm(llm, assets, mode=receipt["intervention_mode"])
            else:
                prompt_path = root / "tasks/prompts" / (task["task_id"] + ".md")
                if digest(prompt_path) != task["prompt_sha256"]:
                    raise ValueError("Prepared task prompt changed")
                selection = retrieve(library, prompt_path.read_text(),
                    capabilities=["read", "write", "edit", "bash"], config=receipt["retrieval"])
                export_selection(selection, assets, mode=receipt["intervention_mode"])
                save(root / "test-selection" / (output.name + ".json"), selection)
        prepared.append((task, output, item["arm"], assets))
    save(root / "execution-plan.json", {"freeze_sha256": digest(root / "freeze.json"),
         "study_digest": object_digest(study), "attempts": [
             {"task_id": t["task_id"], "arm": arm, "output": str(output),
              "assets": tree(assets) if assets else None} for t, output, arm, assets in prepared]})
    with ThreadPoolExecutor(max_workers=study["workers"]) as pool:
        futures = {pool.submit(one_run, study, task, output, docker, credentials, arm=arm, assets=assets): output
                   for task, output, arm, assets in prepared}
        failures = []
        for future in as_completed(futures):
            try:
                future.result()
            except BaseException as error:
                failures.append({"output": str(futures[future]), "type": type(error).__name__, "message": str(error)})
    save(root / "execution-status.json", {"status": "completed_with_infrastructure_failures" if failures else "completed",
                                          "infrastructure_failures": failures})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["freeze", "run"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--llm-result", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--mode", choices=["skill", "bundle"], default="bundle")
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--credentials", type=Path, default=Path.home() / ".pi/agent")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    if args.action == "freeze":
        if any(path is None for path in (args.library, args.llm_result, args.validation)):
            parser.error("Freeze needs the library, LLM result and validation proof")
        result = freeze(args.root, args.library, args.llm_result, args.validation, mode=args.mode, top_k=args.top_k)
        print(json.dumps({"code_commit": result["code_commit"], "tasks": len(result["run_order"])}))
    else:
        execute(args.root, args.credentials, args.docker)


if __name__ == "__main__":
    main()
