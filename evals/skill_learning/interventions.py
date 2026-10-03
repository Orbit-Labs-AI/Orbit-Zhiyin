"""Reviewable deterministic exports of learned content, with all retrieval decisions saved."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from orbit_backend.recommend.learned import DEFAULTS, render, retrieve

from .study import digest, read, save, tree

ACTIVATION = (
    "Before planning the task, inspect the available skill descriptions. Read the full body of each "
    "skill whose activation condition matches the current task, then apply its procedure and "
    "verification checks. Derive all task-specific values from the current inputs. If a skill's "
    "assumptions do not hold, skip it and explain the mismatch. Current user instructions take priority."
)


def export_selection(selection, output, *, mode="bundle"):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"instructions": [], "skills": [], "hooks": []}
    for candidate in selection["candidates"]:
        if candidate["kind"] == "skill":
            path = output / "skills" / candidate["name"] / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(render(candidate))
            manifest["skills"].append({"name": candidate["name"], "description": candidate["description"],
                                       "path": str(path.relative_to(output))})
        elif mode == "bundle" and candidate["kind"] in ("rule", "workflow"):
            manifest["instructions"].append(render(candidate))
    if mode == "bundle" and manifest["skills"]:
        manifest["instructions"].insert(0, ACTIVATION)
    save(output / "manifest.json", manifest)
    return {"manifest": manifest, "files": tree(output), "mode": mode}


def export_llm(result, output, *, mode="bundle"):
    output.mkdir(parents=True, exist_ok=False)
    body = result["result"]
    path = output / "skills" / body["name"] / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: " + body["name"] + "\ndescription: " + json.dumps(body["description"]) +
                    "\n---\n\n" + body["content"] + "\n")
    manifest = {"instructions": [ACTIVATION] if mode == "bundle" else [],
                "skills": [{"name": body["name"], "description": body["description"],
                            "path": str(path.relative_to(output))}], "hooks": []}
    save(output / "manifest.json", manifest)
    return {"manifest": manifest, "files": tree(output), "mode": mode}


def diagnostic_ablations(library, query):
    common = {"require_validation": False}
    variants = {"default_provisional": common, "support_1": {**common, "min_support": 1},
                "support_3": {**common, "min_support": 3}, "top_1": {**common, "top_k": 1},
                "top_4": {**common, "top_k": 4}, "dedup_off": {**common, "dedup": False},
                "relevance_0": {**common, "min_score": 0},
                "relevance_0_15": {**common, "min_score": .15},
                "validated_only": {"require_validation": True}}
    outputs = {name: retrieve(library, query, capabilities=["read", "write", "edit", "bash"], config=cfg)
               for name, cfg in variants.items()}
    outputs["all_capabilities"] = retrieve(library, query,
        capabilities=["read", "write", "edit", "bash", "network", "mcp", "subagent"], config=common)
    # This isolates selection sensitivity, not the causal effect of retraining on less history.
    for count in (1, 2, 3):
        truncated = copy.deepcopy(library)
        allowed = set(library["payload"]["training_session_uids"][:count])
        for candidate in truncated["payload"]["candidates"]:
            candidate["support_sessions"] = len({e["session_uid"] for e in candidate["evidence"]} & allowed)
        outputs[f"retained_evidence_first_{count}"] = retrieve(
            truncated, query, capabilities=["read", "write", "edit", "bash"], config=common)
    return {"purpose": "deterministic retrieval/evidence sensitivity; not model retraining or outcome ablation",
            "defaults": DEFAULTS, "variants": outputs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path)
    parser.add_argument("--llm-result", type=Path)
    parser.add_argument("--query", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["skill", "bundle"], default="bundle")
    parser.add_argument("--provisional", action="store_true")
    parser.add_argument("--top-k", type=int, default=2)
    args = parser.parse_args()
    if bool(args.library) == bool(args.llm_result):
        parser.error("Choose exactly one learned library or direct-LLM result")
    if args.llm_result:
        print(export_llm(read(args.llm_result), args.output, mode=args.mode)["manifest"])
        return
    if args.query is None:
        parser.error("Learned retrieval requires a current-task query")
    library = read(args.library)
    selection = retrieve(library, args.query.read_text(), capabilities=["read", "write", "edit", "bash"],
                         config={"require_validation": not args.provisional, "top_k": args.top_k})
    result = export_selection(selection, args.output, mode=args.mode)
    audit = args.output.with_name(args.output.name + "-audit")
    audit.mkdir(exist_ok=False)
    save(audit / "selection.json", selection)
    save(audit / "retrieval-ablations.json", diagnostic_ablations(library, args.query.read_text()))
    save(audit / "export.json", {"library_sha256": digest(args.library), "query_sha256": digest(args.query),
                                      "mode": args.mode, "manifest": result["manifest"]})
    print(json.dumps({"candidates": [c["name"] for c in selection["candidates"]],
                      "provisional": selection["provisional"], "mode": args.mode}), flush=True)


if __name__ == "__main__":
    main()
