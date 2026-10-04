"""Offline, loss-aware report data. Never chooses runs by their task outcome."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .study import digest, read, save

ARMS = ("vanilla", "ours", "llm")


def usage_total(rows):
    known = sum(r["known_total_tokens"] for r in rows)
    complete = bool(rows) and all(r["complete"] and r["total_tokens"] is not None for r in rows)
    return {"attempts": len(rows), "known_tokens_lower_bound": known,
            "unknown_usage_attempts": sum(not r["complete"] for r in rows),
            "total_tokens": sum(r["total_tokens"] for r in rows) if complete else None}


def snapshot(root):
    frozen, study = read(root / "freeze.json"), read(root / "study.json")
    cohorts = {p.stem: read(p) for p in (root / "cohorts").glob("*.json")}
    rows = []
    for item in frozen["run_order"]:
        task = next(t for t in study["tasks"] if t["task_id"] == item["task_id"])
        group = cohorts.get(task["task_id"], {})
        path = group.get("selected", {}).get(item["arm"])
        row = {**item, "raw_directory": path, "cohort": group.get("cohort"), "passed": None,
               "outcome_state": "no_complete_cohort", "usage": None, "activation": None,
               "prompt_sha256": task["prompt_sha256"], "verifier_digest": task["verifier_digest"],
               "source_relative": task["source_relative"]}
        if path:
            path = Path(path)
            row.update(read(path / "result.json"))
            row["result_sha256"] = digest(path / "result.json")
            row["code_commit"] = read(path / "provenance.json")["code_commit"]
            if (path / "usage-observation.json").exists():
                row["activation"] = read(path / "usage-observation.json")["counts"]
        rows.append(row)
    adaptation = {}
    for arm in ("ours", "llm"):
        calls = [p for p in root.glob(f"adaptation-v*/{arm}*/model/call-*/trajectory.json")]
        adaptation[arm] = {**usage_total([read(p)["usage"] for p in calls]),
                           "raw_calls": [str(p.parent) for p in sorted(calls)]}
    aggregates = {}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        passed = sum(r["passed"] is True for r in selected)
        usages = [r["usage"] for r in selected if r["usage"] is not None]
        tokens = usage_total(usages)
        if len(usages) != len(selected):
            tokens["total_tokens"] = None
        aggregates[arm] = {"planned": len(selected), "passed": passed,
            "failed": sum(r["passed"] is False for r in selected),
            "unknown": sum(r["passed"] is None for r in selected), "online": tokens,
            "tokens_per_success": tokens["total_tokens"] / passed
                if passed and tokens["total_tokens"] is not None else None,
            "known_tokens_per_success_lower_bound": tokens["known_tokens_lower_bound"] / passed if passed else None,
            "activation": dict(sum((Counter(r["activation"] or {}) for r in selected), Counter()))}
    paired = []
    for task_id in dict.fromkeys(r["task_id"] for r in rows):
        selected = {r["arm"]: r for r in rows if r["task_id"] == task_id}
        for baseline in ("vanilla", "llm"):
            ours, other = selected["ours"], selected[baseline]
            comparable = all(isinstance(r["passed"], bool) for r in (ours, other))
            a, b = (r["usage"]["total_tokens"] if r["usage"] else None for r in (ours, other))
            paired.append({"task_id": task_id, "baseline": baseline, "outcomes_known": comparable,
                "success_delta": int(ours["passed"]) - int(other["passed"]) if comparable else None,
                "ours_to_baseline_tokens": a / b if a is not None and b else None,
                "both_passed": ours["passed"] is True and other["passed"] is True})
    # Includes all discarded provider attempts, adaptation, history, oracle and validation.
    paths = sorted(root.rglob("trajectory.json"))
    ledger = [{"path": str(p.parent), "usage": read(p)["usage"]} for p in paths]
    output = {"freeze": frozen, "freeze_sha256": digest(root / "freeze.json"), "rows": rows,
              "aggregates": aggregates, "paired": paired, "adaptation": adaptation,
              "cohorts": cohorts, "all_attempt_tokens": usage_total([r["usage"] for r in ledger]),
              "all_attempt_ledger": ledger,
              "limits": ["A token subtotal with failed or unreported requests is a lower bound, not a total",
                         "Four predeclared held-out tasks do not establish statistical significance",
                         "Provider cohorts must be identified; endpoint equivalence is not assumed"]}
    save(root / "report-data.json", output)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    result = snapshot(args.root)
    print({arm: {k: v for k, v in value.items() if k not in ("online", "activation")}
           for arm, value in result["aggregates"].items()})


if __name__ == "__main__":
    main()
