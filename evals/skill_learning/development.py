"""Validation-only reliability and headroom runs. Every arm starts a fresh container."""

from __future__ import annotations

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .runtime import create_container, one_run, verifier
from .study import command, digest, read, save, tree


def audit_verifier(root: Path, study: dict, task: dict, docker: str, references: dict | None = None) -> dict:
    if task["split"] != "validation":
        raise ValueError("Reliability screening may only inspect validation")
    output = root / "reliability" / task["task_id"]
    receipt = output / "audit.json"
    if receipt.exists():
        return read(receipt)
    output.mkdir(parents=True, exist_ok=True)
    reference = (references or {}).get(task["task_id"], {})
    source = Path(reference.get("solution", Path(study["source"]) / task["source_relative"] / "solution"))
    result = {"task_id": task["task_id"], "verifier_digest": task["verifier_digest"],
              "reference_available": (source / "solve.sh").exists(),
              "reference_provenance": {"source": str(source), "files": tree(source),
                                       "basis": reference.get("basis", "upstream official solution"),
                                       "attachments": []}}
    for asset in reference.get("attachments", []):
        result["reference_provenance"]["attachments"].append(
            {**asset, "files": tree(Path(asset["source"]))})
    for arm in ("empty", "reference"):
        if arm == "reference" and not result["reference_available"]:
            result[arm] = {"status": "reference_unavailable", "passed": None}
            continue
        name = create_container(docker, study, task)
        try:
            if arm == "reference":
                command([docker, "cp", str(source), name + ":/solution"])
                for asset in reference.get("attachments", []):
                    destination = asset["destination"]
                    if not destination.startswith("/") or ".." in Path(destination).parts:
                        raise ValueError("Reference attachment destination must be absolute")
                    command([docker, "exec", name, "mkdir", "-p", destination])
                    command([docker, "cp", asset["source"] + "/.", name + ":" + destination])
                with (output / "reference.log").open("w") as log:
                    proc = subprocess.run([docker, "exec", name, "timeout", "900", "bash", "/solution/solve.sh"],
                                          stdout=log, stderr=subprocess.STDOUT, timeout=930)
                result["reference_exit_code"] = proc.returncode
            result[arm] = verifier(docker, name, task, study, output / arm)
        finally:
            subprocess.run([docker, "rm", "-f", name], capture_output=True)
    result["controls_pass"] = result["empty"]["passed"] is False and result["reference"]["passed"] is True
    result["prompt_consistency"] = "requires_manual_review"
    save(receipt, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["audit", "preflight", "run", "headroom"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--tasks", required=True, nargs="+")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--credentials", type=Path, default=Path.home() / ".pi/agent")
    parser.add_argument("--arm", default="vanilla")
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--cohort", default="validation")
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    parser.add_argument("--references", type=Path,
                        help="Validation-only reference solutions/attachments; never injected into model runs")
    args = parser.parse_args()
    study = read(args.root / "study.json")
    tasks = [t for t in study["tasks"] if t["task_id"] in args.tasks]
    if len(tasks) != len(args.tasks) or any(t["split"] == "test" for t in tasks):
        parser.error("Development execution only accepts prepared history/validation tasks")
    if args.action == "audit":
        for task in tasks:
            print(audit_verifier(args.root, study, task, args.docker,
                                 read(args.references) if args.references else None), flush=True)
        return
    if (args.arm != "vanilla" or args.action == "headroom") and args.assets is None:
        parser.error("Non-vanilla arms require an explicit asset directory")
    if args.action in {"run", "headroom"} and any(t["split"] == "validation" for t in tasks):
        for task in tasks:
            if task["split"] == "validation":
                receipt = read(args.root / "reliability" / task["task_id"] / "audit.json")
                if not receipt["controls_pass"]:
                    raise ValueError("Validate empty/reference controls before paid headroom runs")
                review = read(args.root / "reliability" / task["task_id"] / "manual-review.json")
                if review.get("prompt_consistent") is not True:
                    raise ValueError("Manually review prompt/verifier consistency before paid headroom runs")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for task in tasks:
            arms = ("vanilla", "oracle") if args.action == "headroom" else (args.arm,)
            for arm in arms:
                cohort = args.action if args.action in {"preflight", "headroom"} else args.cohort
                folder = args.root / cohort / f"{task['task_id']}--{arm}"
                assets = (args.assets / task["family"] if arm == "oracle" else None) \
                    if args.action == "headroom" else args.assets
                futures.append(pool.submit(one_run, study, task, folder, args.docker, args.credentials,
                                           preflight=args.action == "preflight", arm=arm, assets=assets))
        for future in as_completed(futures):
            result = future.result()
            save(args.root / "last-development-result.json", {
                "task": result.get("task_id"), "arm": result.get("arm"), "passed": result.get("passed"),
                "runtime_sha256": digest(Path(__file__).with_name("runtime.py"))})


if __name__ == "__main__":
    main()
