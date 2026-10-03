"""Separate descriptor injection, successful body reads, and reviewed method use."""

from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import events_from
from .study import digest, read, save


def observe(directory: Path, review: dict | None = None) -> dict:
    injections, activations, hooks, runtime = [], [], [], []
    call_positions = {}
    activated_positions = {}
    position = 0
    sessions = sorted((directory / "sessions").glob("*.jsonl"))
    if len(sessions) != 1:
        raise ValueError("A benchmark attempt must have one native Pi session")
    for event in events_from(sessions[0]):
        position += 1
        kind, data = event.get("customType"), event.get("data") or {}
        if kind == "orbit.benchmark.injection":
            injections.append(data)
        elif kind == "orbit.benchmark.activation":
            activations.append(data)
            if data.get("observation") == "body_read" and data.get("success") is True:
                activated_positions.setdefault(data["skill"], position)
        elif kind == "orbit.benchmark.hook":
            hooks.append(data)
        elif kind == "orbit.benchmark.runtime":
            runtime.append(data)
        message = event.get("message") or {}
        if message.get("role") == "assistant":
            for part in message.get("content") or []:
                if part.get("type") == "toolCall":
                    call_positions[part["id"]] = position
    injected = {skill["name"] for injection in injections for skill in injection.get("skills") or []}
    reviewed = (review or {}).get("skills") or {}
    if not set(reviewed) <= injected:
        raise ValueError("Usage review names a skill that was not injected")
    skills = []
    for name in sorted(injected):
        decision = reviewed.get(name) or {}
        used = decision.get("used")
        if used is not None and type(used) is not bool:
            raise ValueError("Usage must be true, false or unknown")
        evidence = decision.get("evidence") or []
        if used is True:
            if name not in activated_positions or not evidence:
                raise ValueError("Confirmed usage requires a successful body read and tool evidence")
            for item in evidence:
                if call_positions.get(item.get("tool_call_id"), -1) <= activated_positions[name] \
                        or not str(item.get("step") or "").strip():
                    raise ValueError("Usage evidence must identify a later observed tool call and method step")
        skills.append({"name": name, "injected": True, "body_read": name in activated_positions,
                       "actual_usage": used, "evidence": evidence,
                       "review_note": decision.get("note"),
                       "usage_status": "unreviewed" if used is None else "reviewed"})
    return {"native_session_sha256": digest(sessions[0]),
            "runtime": runtime, "injection_events": injections, "activation_events": activations,
            "skills": skills, "counts": {"injected_skills": len(injected),
                "successfully_read_skills": len(activated_positions),
                "confirmed_used_skills": sum(s["actual_usage"] is True for s in skills),
                "unreviewed_skills": sum(s["actual_usage"] is None for s in skills),
                "hook_calls": len(hooks),
                "hook_blocks": sum(h.get("code") == 2 for h in hooks),
                "hook_errors": sum(h.get("code") not in (0, 2) for h in hooks)},
            "interpretation": "Descriptor injection and body reading do not establish method adoption; reviewed use is behavioral evidence, not a causal estimate."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    result = observe(args.run, read(args.review) if args.review else None)
    save(args.run / "usage-observation.json", result)
    print(result["counts"])


if __name__ == "__main__":
    main()
