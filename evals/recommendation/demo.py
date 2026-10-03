"""Generate a reviewable recommendation report using fictional records only.

Run after installing the package: uv run python -m evals.recommendation.demo
"""

import argparse
import json
from pathlib import Path

from orbit_backend.analytics.inputs import AnalysisInputBundle
from orbit_backend.analytics.recommendations import recommend_bottlenecks
from orbit_backend.analytics.service import analyze_bundle


def synthetic_bundle():
    events = [{"event_uid": "delivery", "session_uid": "demo", "turn_uid": "turn", "seq": 0,
               "kind": "message.assistant", "actor": "assistant", "ts": 100, "text": "fictional output",
               "attrs": {"task_uid": "task"}}]
    for i in range(8):
        label = {"state": "confirmed", "source": "synthetic-reviewer", "available_at": 100,
                 "intents": ["correction" if i < 3 else "request"], "requirements": []}
        if i < 3:
            label.update(target_event_uid="delivery", evidence_event_uids=["delivery"], friction_types=["scope"])
        events.append({"event_uid": f"request-{i}", "session_uid": "demo", "turn_uid": "turn", "seq": i + 1,
                       "kind": "message.user", "actor": "human", "ts": 110 + i * 10, "text": "fictional request",
                       "attrs": {"origin": "human", "task_uid": "task", "interaction": label}})
    calls = []
    for i in range(10):
        call = {"call_uid": f"call-{i}", "session_uid": "demo", "turn_uid": "turn", "task_uid": "task",
                "call_event_uid": f"start-{i}", "result_event_uid": f"result-{i}", "seq": 20 + 2 * i,
                "result_seq": 21 + 2 * i, "name_raw": "exec_command", "kind": "shell", "status_scope": "command",
                "status": "failed" if i < 3 else "success", "started_at": 1000 + i * 100,
                "ended_at": 1010 + i * 100, "argument_digest": "same-input" if i < 3 else f"input-{i}",
                "argument_digest_kind": "sha256"}
        calls.append(call)
        for uid, seq, ts, kind in ((call["call_event_uid"], call["seq"], call["started_at"], "tool.call"),
                                  (call["result_event_uid"], call["result_seq"], call["ended_at"], "tool.result")):
            events.append({"event_uid": uid, "session_uid": "demo", "turn_uid": "turn", "seq": seq,
                           "kind": kind, "actor": "assistant", "ts": ts,
                           "attrs": {"task_uid": "task", "call_id": call["call_uid"]}})
    models = [{"call_uid": f"model-{i}", "session_uid": "demo", "turn_uid": "turn", "model_id": "synthetic-model",
               "usage_scope": "call", "measurement": "delta", "boundary_reliable": True, "coverage": "self",
               "ts": 2000 + i * 100, "input_tokens": 4000, "cache_read_tokens": 0, "cache_write_tokens": 0,
               "output_tokens": 100} for i in range(5)]
    return AnalysisInputBundle(
        sessions=[{"session_uid": "demo", "root_uid": "demo", "kind": "main", "project_id": "synthetic-project", "started_at": 100}],
        events=events, tool_calls=calls, model_calls=models,
        coverage={name: {"status": "available"} for name in ("sessions", "events", "tool_calls", "model_calls", "turns", "projects", "lineage")},
        versions={"content_digest": "fictional-recommendation-demo-v1"},
    )


def main():
    parser = argparse.ArgumentParser(description="Generate recommendations from fictional data; no local history is read.")
    parser.add_argument("--output", type=Path, default=Path(".local/recommendation-demo.json"))
    parser.add_argument("--target-agent", choices=("generic", "codex", "claude_code"), default="codex")
    args = parser.parse_args()
    result = recommend_bottlenecks(analyze_bundle(synthetic_bundle(), with_text=False), target_agent=args.target_agent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"synthetic_only": True, "status": result["status"], "rules": [s["rule_id"] for s in result["signals"]],
                      "recommendations": [{"name": c["name"], "kind": c["kind"], "priority": c["priority_score"]}
                                          for c in result["recommendations"]], "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
