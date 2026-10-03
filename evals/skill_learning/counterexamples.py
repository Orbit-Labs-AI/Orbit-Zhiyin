"""Build identical validation feedback for both adaptation methods, without test access."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .study import digest, object_digest, read, save


def collect(root, cohort, tasks):
    study = read(root / "study.json")
    records = []
    for task_id in tasks:
        task = next(t for t in study["tasks"] if t["task_id"] == task_id)
        if task["split"] != "validation":
            raise ValueError("Only validation feedback can enter counterexample refinement")
        observations = []
        for arm in ("ours", "llm"):
            attempt = root / cohort / (task_id + "--" + arm)
            result = read(attempt / "result.json")
            if result["split"] != "validation" or result["passed"] not in (True, False):
                raise ValueError("Incomplete or non-validation attempt")
            checks = []
            for case in ET.parse(attempt / "verifier/junit.xml").iter("testcase"):
                failed = case.find("failure")
                checks.append({"check": case.attrib["name"], "passed": failed is None,
                               "failure": failed.attrib.get("message") if failed is not None else None})
            observations.append({"arm": arm, "passed": result["passed"], "usage": result["usage"],
                "result_sha256": digest(attempt / "result.json"), "checks": checks,
                "usage_audit": read(attempt / "usage-review.json")})
        body = {"case_id": task_id, "split": "validation", "request": (root / "tasks/prompts" / (task_id + ".md")).read_text(),
                "observations": observations, "limitations": [
                    "External benchmark assertions; no verifier code or oracle intervention supplied.",
                    "Both methods receive the same paired feedback. Abstract a general correction, never copy a case answer."]}
        sha = object_digest(body)
        text = json.dumps(body, ensure_ascii=False)
        if len(text) > 32000:
            raise ValueError("Counterexample exceeds bounded product input; select less evidence explicitly")
        records.append({"split": "validation", "case_id": task_id, "session_uid": "validation:" + task_id,
                        "event_uid": "evaluation:" + sha, "report_digest": sha, "body": text})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--tasks", required=True, nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Counterexample input already exists; do not overwrite")
    save(args.output, collect(args.root, args.cohort, args.tasks))
    print({"feedback_sha256": digest(args.output), "cases": args.tasks})


if __name__ == "__main__":
    main()
