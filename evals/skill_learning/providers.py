"""Predeclared provider recovery, preserving matched triplets and every failed attempt."""

from __future__ import annotations

import copy
from pathlib import Path

from evals.artificial_benchmark.resume import (
    balances,
    credential_directory,
    load_keys,
    tokendance_model,
)

from .runtime import one_run
from .study import read, save


def policy(credentials: Path, keys_path: Path) -> dict:
    load_keys(keys_path)  # Validate private storage without persisting credentials.
    return {"version": 1, "primary": "native-kimi-coding", "fallback": "tokendance",
            "fallback_model": tokendance_model(credentials), "key_file": str(keys_path.resolve()),
            "key_slots": 3, "minimum_balance_microyuan": 3_000_000,
            "trigger": "terminal provider error after Pi's bounded retries",
            "comparison": "A provider change reruns all three arms of that task as a separate cohort",
            "key_rotation": "Only on insufficient balance or rate/quota errors, at most three slots per arm",
            "preserve": "Keep every attempt and cost; never retry a completed task or budget failure"}


def grouped(prepared):
    result = {}
    for item in prepared:
        result.setdefault(item[0]["task_id"], []).append(item)
    return list(result.values())


def key_exhausted(output):
    trajectory = read(output / "trajectory.json")
    text = "\n".join(m.get("errorMessage", "") for m in trajectory.get("messages", [])
                     if m.get("role") == "assistant" and m.get("stopReason") == "error").lower()
    return any(marker in text for marker in ("5-hour usage limit", "insufficient balance", "insufficient_quota",
        "余额不足", "credit balance", "quota_exceeded", "quota exhausted", "rate_limit", "rate limit", "429"))


def run_group(root, study, items, credentials, docker, recovery, group_index, primary_unavailable):
    """One worker owns a task triplet; endpoint changes never create mixed matched arms."""
    task_id = items[0][0]["task_id"]
    receipt_path = root / "cohorts" / (task_id + ".json")
    receipt = {"task_id": task_id, "attempts": [], "selected": {}, "status": "running"}

    def persist():
        save(receipt_path, receipt)

    def attempt(item, cfg, creds, output, cohort, slot=None):
        task, _, arm, assets = item
        try:
            result = one_run(cfg, task, output, docker, creds, arm=arm, assets=assets)
            state = result["outcome_state"]
        except Exception as error:
            receipt["attempts"].append({"arm": arm, "output": str(output), "cohort": cohort,
                "key_slot": slot, "state": "infrastructure_error", "error": type(error).__name__})
            receipt["status"] = "incomplete"
            persist()
            raise
        receipt["attempts"].append({"arm": arm, "output": str(output), "cohort": cohort,
                                     "key_slot": slot, "state": state})
        persist()
        return state

    persist()
    if not primary_unavailable.is_set():
        selected = {}
        for item in items:
            state = attempt(item, study, credentials, item[1], "native-kimi-coding")
            if state == "provider_error":
                primary_unavailable.set()
                break
            selected[item[2]] = str(item[1])
        else:
            receipt.update(selected=selected, status="completed", cohort="native-kimi-coding")
            persist()
            return receipt
    if recovery is None:
        receipt["status"] = "provider_blocked"
        persist()
        return receipt

    keys = load_keys(Path(recovery["key_file"]))
    available = balances(keys)
    save(root / "balances" / (task_id + "-before-fallback.json"), available)
    model = recovery["fallback_model"]
    cfg = copy.deepcopy(study)
    cfg["model"] = model["id"]
    cfg["model_config"] = {key: model.get(key) for key in study["model_config"]}
    selected = {}
    for item in items:
        for offset in range(recovery["key_slots"]):
            slot = (group_index + offset) % recovery["key_slots"]
            if available[slot]["remaining_microyuan"] < recovery["minimum_balance_microyuan"]:
                continue
            output = root / f"test-tokendance-slot-{slot + 1}" / item[1].name
            with credential_directory(root / "private-credentials", keys[slot], model) as creds:
                state = attempt(item, cfg, creds, output, "tokendance", slot + 1)
            if state != "provider_error":
                selected[item[2]] = str(output)
                break
            if not key_exhausted(output):
                receipt["status"] = "provider_blocked"
                persist()
                return receipt
            available[slot]["remaining_microyuan"] = 0
        else:
            receipt["status"] = "prepaid_keys_exhausted"
            persist()
            return receipt
    receipt.update(selected=selected, status="completed", cohort="tokendance")
    persist()
    save(root / "balances" / (task_id + "-after-fallback.json"), balances(keys))
    return receipt
