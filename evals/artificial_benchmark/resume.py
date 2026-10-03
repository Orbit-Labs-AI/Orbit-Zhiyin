"""Resume interrupted tests by task, preserving frozen runs and every attempt."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import copy
import datetime
import fcntl
import json
import os
import shutil
import tempfile
import urllib.request
import uuid
from pathlib import Path

from .evaluate import check_adaptation, report
from .runner import one_run
from .study import ARMS, command, digest, load_frozen, read, save, tree, verify_source

BASE_URL = "https://tokendance.space/gateway/v1"
BALANCE_URL = "https://tokendance.space/portal/api/v1/user/balance"
TERMINAL = {"completed", "budget_exhausted"}


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def classify(folder: Path) -> str:
    """Missing tokens alone never justify repeating a valid task failure."""
    result_path = folder / "result.json"
    if not result_path.exists():
        return "unfinished"
    row = read(result_path)
    trajectory = read(folder / "trajectory.json")
    if row.get("agent_completed"):
        return "completed" if row["verifier"]["status"] in ("passed", "failed") else "needs_rescore"
    errors = "\n".join(m.get("errorMessage", "") for m in trajectory.get("messages", [])
                       if m.get("role") == "assistant" and m.get("stopReason") == "error").lower()
    if errors:
        if any(s in errors for s in ("5-hour usage limit", "rate_limit", "rate limit", "429")):
            return "rate_limited"
        if any(s in errors for s in ("insufficient balance", "insufficient_quota", "余额不足",
                                    "credit balance", "quota_exceeded", "quota exhausted")):
            return "balance_exhausted"
        return "provider_error"
    if row.get("termination") in ("timeout", "turn_limit"):
        return "budget_exhausted" if row["verifier"]["status"] in ("passed", "failed") else "needs_rescore"
    return "interrupted"


def task_groups(order: list[dict], completed: set[tuple[str, str]]) -> list[dict]:
    """Finish partially completed triplets first; preserve original order within ties."""
    grouped: dict[str, list[str]] = {}
    for item in order:
        grouped.setdefault(item["task_id"], []).append(item["arm"])
    tasks = sorted(grouped, key=lambda tid: -sum((tid, arm) in completed for arm in ARMS))
    return [{"task_id": tid, "arms": [arm for arm in grouped[tid] if (tid, arm) not in completed]}
            for tid in tasks if any((tid, arm) not in completed for arm in ARMS)]


def tokendance_model(source: Path) -> dict:
    original = next(m for m in read(source / "models-store.json")["kimi-coding"]["models"] if m["id"] == "k3")
    model = copy.deepcopy(original)
    model.update(id="kimi-k3", name="Kimi K3 via TokenDance", api="openai-completions", baseUrl=BASE_URL,
                 compat={"supportsStore": False, "supportsDeveloperRole": False,
                         "supportsReasoningEffort": True, "supportsUsageInStreaming": True,
                         "maxTokensField": "max_tokens", "thinkingFormat": "openai",
                         "requiresReasoningContentOnAssistantMessages": True})
    return model


def amended_study(study: dict, model: dict) -> dict:
    result = copy.deepcopy(study)
    result["model"] = model["id"]
    result["model_config"] = {k: model.get(k) for k in study["model_config"]}
    return result


def balances(keys: list[str]) -> list[dict]:
    values = []
    for index, key in enumerate(keys):
        req = urllib.request.Request(BALANCE_URL, headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=30) as response:
            value = json.load(response)["balance"]
        values.append({"key_slot": index + 1, "remaining_microyuan": value["balance"],
                       "used_microyuan": value["credits_used"], "checked_utc": now()})
    return values


def load_keys(path: Path) -> list[str]:
    if path.stat().st_mode & 0o077:
        raise ValueError("Key file must be private (chmod 600)")
    keys = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(keys) != 3 or len(set(keys)) != 3 or any(any(c.isspace() for c in key) for key in keys):
        raise ValueError("Expected three distinct API keys, one per line")
    return keys


@contextlib.contextmanager
def credential_directory(parent: Path, key: str, model: dict):
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="key-", dir=parent) as name:
        folder = Path(name)
        for filename, value in {
            "auth.json": {"kimi-coding": {"type": "api_key", "key": key}},
            "models-store.json": {"kimi-coding": {"models": [model]}},
        }.items():
            save(folder / filename, value)
            (folder / filename).chmod(0o600)
        yield folder


def ensure_old_runner_stopped(output: Path) -> None:
    status = output / "execution-status.json"
    if status.exists() and read(status).get("status") == "running":
        pid = read(status).get("pid")
        if pid:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError("Original runner is still active; wait for its terminal result")


def prepare(output: Path, source: Path) -> dict:
    study = load_frozen(output)
    check_adaptation(output)
    ensure_old_runner_stopped(output)
    folder = output / "resume"
    amendment = folder / "amendment.json"
    if amendment.exists():
        return check_amendment(output)
    completed = set()
    inventory = []
    for job in read(output / "planned-test-order.json"):
        path = output / "test" / f"{job['task_id']}--{job['arm']}"
        state = classify(path)
        if state == "needs_rescore":
            raise ValueError(f"Recover verifier without repeating agent: {path.name}")
        if state in TERMINAL:
            completed.add((job["task_id"], job["arm"]))
        inventory.append({**job, "original_state": state, "original_path": str(path.relative_to(output)),
                          "files": tree(path) if path.exists() else {}})
    model = tokendance_model(source)
    value = {"version": 1, "created_utc": now(), "reason": "User requested new prepaid keys and task-grouped resumption",
             "study_sha256": digest(output / "benchmark_manifest.json"),
             "adaptation_sha256": digest(output / "adaptation/frozen.json"),
             "resume_code_sha256": digest(Path(__file__)), "original_model": study["model_config"],
             "resume_pi_sha256": digest(Path(__file__).with_name("resume_pi.py")),
             "model": model, "inventory": inventory,
             "groups": task_groups(read(output / "planned-test-order.json"), completed),
             "workers": study["workers"], "key_budget_yuan": [101, 101, 101],
             "rules": ["Keep normal completions including failures and missing usage",
                       "Keep model time/turn budget failures; retry only interrupted/provider-failed attempts",
                       "Archive all interrupted attempts before fresh-container reruns",
                       "Finish one task's remaining arms before advancing to another task",
                       "Never regenerate history or adaptation; no model fallbacks",
                       "Switch prepaid key only on balance exhaustion; stop on unresolved rate/provider errors",
                       "API protocol and endpoint changed; report old/new cohorts explicitly",
                       "Use balance API for actual yuan spend; Pi model-cost estimates are not billing"]}
    save(amendment, value)
    amendment.with_suffix(".sha256").write_text(digest(amendment) + "\n")
    return value


def check_amendment(output: Path) -> dict:
    path = output / "resume/amendment.json"
    value = read(path)
    if digest(path) != path.with_suffix(".sha256").read_text().strip() \
            or digest(Path(__file__)) != value["resume_code_sha256"] \
            or digest(Path(__file__).with_name("resume_pi.py")) != value["resume_pi_sha256"]:
        raise ValueError("Resume amendment or code changed")
    if value["study_sha256"] != digest(output / "benchmark_manifest.json") \
            or value["adaptation_sha256"] != digest(output / "adaptation/frozen.json"):
        raise ValueError("Original study or adaptation changed")
    load_frozen(output)
    check_adaptation(output)
    for item in value["inventory"]:
        if item["original_state"] in TERMINAL and tree(output / item["original_path"]) != item["files"]:
            raise ValueError("Previously completed run changed")
    return value


def archive_incomplete(output: Path, amendment: dict) -> None:
    root = output / "resume"
    report_archive = root / "original-report"
    if (output / "report").exists() and not report_archive.exists():
        shutil.copytree(output / "report", report_archive)
    for item in amendment["inventory"]:
        if item["original_state"] in TERMINAL:
            continue
        source = output / item["original_path"]
        destination = root / "original-attempts" / source.name
        if destination.exists():
            if tree(destination) != item["files"]:
                raise ValueError("Archived original attempt changed")
            continue
        if source.exists():
            if tree(source) != item["files"]:
                raise ValueError("Original attempt changed after resume preparation")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)


def progress(output: Path, amendment: dict, status: str, *, publish: bool = True, **extra) -> dict:
    summary = report(output)
    rows = [read(p) for p in sorted((output / "test").glob("*/result.json"))]
    completed = {(r["task_id"], r["arm"]) for r in rows}
    triplets = sum(all((tid, arm) in completed for arm in ARMS) for tid in {r["task_id"] for r in rows})
    attempts = []
    for root in (output / "resume/original-attempts", output / "resume-attempts"):
        for path in sorted(root.glob("*/trajectory.json")):
            value = read(path)
            attempts.append({"path": str(path.parent.relative_to(output)), "usage": value["usage"]})
    cohorts = []
    for path in sorted((output / "test").glob("*/result.json")):
        row = read(path)
        model = read(path.parent / "model.json")
        cohorts.append({"task_id": row["task_id"], "arm": row["arm"], "api": model["api"],
                        "base_url": model["baseUrl"], "model": model["id"]})
    value = {"status": status, "stage": "test-resume", "pid": os.getpid(), "updated_utc": now(),
             "completed_test_runs": len(rows), "completed_triplets": triplets, "planned_test_runs": 36,
             "pending_test_runs": 36 - len(rows), "groups": amendment["groups"],
             "cohorts": cohorts, "interrupted_attempts": attempts,
             "interrupted_known_tokens": sum(a["usage"]["known_total_tokens"] for a in attempts),
             "interrupted_total_tokens": (sum(a["usage"]["total_tokens"] for a in attempts)
                                          if all(a["usage"]["complete"] for a in attempts) else None), **extra}
    if publish:
        save(output / "resume/status.json", value)
        save(output / "execution-status.json", {k: v for k, v in value.items()
                                               if k not in ("cohorts", "interrupted_attempts", "groups")})
    summary["resumption"] = value
    save(output / "report/summary.json", summary)
    ours = read(output / "adaptation/ours/summary.json")
    note = ("\n## 8. 续跑说明\n\n"
            f"有效完成 {len(rows)}/36，补齐三组的任务 {triplets}/12。API 额度/传输中断的旧尝试"
            "保存在 `../resume/original-attempts/`；新中断尝试保存在 `../resume-attempts/`。"
            "这些尝试不计作模型任务失败，但其已知消耗单独计入 summary.json；未知用量仍为未知。\n\n"
            "保留正常失败与原定时间/轮数上限失败，不能因失败或 token 缺失重跑。新请求使用"
            " TokenDance 的 OpenAI Chat Completions，kimi-k3 / reasoning_effort=max；旧请求使用"
            " Kimi Coding 的 Anthropic Messages，k3 / max。模型别名与传输协议不同，"
            "因此合并结果属于服务切换后的探索性续跑，不能声称 API 条件完全一致。"
            "逐次服务配置见 summary.json 的 resumption.cohorts。\n\n"
            f"history 与 B/C 资产沿用原冻结版本；本次 B 的真实产品生成状态为 {ours.get('status')}，"
            f"规则 {ours.get('instructions')}、Skill {ours.get('skills')}、Hook {ours.get('hooks')}。"
            "具体见 adaptation/ours/summary.json。\n")
    report_path = output / "report/BENCHMARK_REPORT.md"
    report_path.write_text(report_path.read_text() + note)
    print(json.dumps({k: value[k] for k in ("status", "completed_test_runs", "completed_triplets", "pending_test_runs")}), flush=True)
    return value


def attempt(output: Path, study: dict, task: dict, arm: str, docker: str, key: str,
            slot: int, model: dict) -> tuple[Path, str]:
    path = output / "resume-attempts" / f"{task['task_id']}--{arm}--{uuid.uuid4().hex[:10]}"
    assets = output / "adaptation" / arm / "assets" if arm != "vanilla" else None
    with credential_directory(output / "resume/credentials", key, model) as credentials:
        try:
            one_run(study, task, path, docker, credentials, arm=arm, assets=assets)
        finally:
            save(path / "resume-attempt.json", {"key_slot": slot, "api_base_url": BASE_URL,
                                               "model": model["id"], "effort": "max"})
    return path, classify(path)


def run(output: Path, key_file: Path, docker: str, *, preflight: bool = False) -> None:
    amendment = check_amendment(output)
    ensure_old_runner_stopped(output)
    study = amended_study(load_frozen(output), amendment["model"])
    verify_source(study)
    if command([study["pi"], "--version"]) != study["pi_version"]:
        raise ValueError("Pi version changed")
    os.environ["ORBIT_BENCH_PI_EXECUTABLE"] = study["pi"]
    study["pi"] = str(Path(__file__).with_name("resume_pi.py"))
    keys = load_keys(key_file)
    with (output / "resume/runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        initial = balances(keys)
        save(output / "resume" / f"balance-{uuid.uuid4().hex[:10]}.json", initial)
        if preflight:
            task = next(t for t in study["tasks"] if t["family"] == "offer-letter-generator" and t["split"] == "history")
            destination = output / "resume-preflight" / uuid.uuid4().hex[:10]
            with credential_directory(output / "resume/credentials", keys[0], amendment["model"]) as credentials:
                result = one_run(study, task, destination, docker, credentials, preflight=True)
            if result["status"] != "passed":
                raise ValueError("New provider tool/usage preflight failed")
            if not result["trajectory_usage"]["complete"]:
                raise ValueError("New provider does not report complete token usage")
            messages = read(destination / "trajectory.json")["messages"]
            assistants = [m for m in messages if m.get("role") == "assistant"]
            if not assistants or any(m.get("api") != "openai-completions" or m.get("model") != "kimi-k3"
                                     or m.get("thinkingLevel") != "max" for m in assistants):
                raise ValueError("Pi did not use the explicit Kimi K3 max resume configuration")
            save(output / "resume/provider-preflight.json", {"path": str(destination.relative_to(output)),
                                                             "files": tree(destination)})
            return
        probe = read(output / "resume/provider-preflight.json")
        if tree(output / probe["path"]) != probe["files"]:
            raise ValueError("Provider preflight evidence changed")
        archive_incomplete(output, amendment)
        tasks = {t["task_id"]: t for t in study["tasks"] if t["split"] == "test"}
        disabled_path = output / "resume/exhausted-key-slots.json"
        disabled = set(read(disabled_path)) if disabled_path.exists() else set()
        progress(output, amendment, "running", balances=initial)
        try:
            for group in amendment["groups"]:
                tid = group["task_id"]
                pending = [arm for arm in group["arms"] if not (output / "test" / f"{tid}--{arm}").exists()]
                while pending:
                    check_amendment(output)
                    current = balances(keys)
                    available = sorted((b for b in current if b["remaining_microyuan"] > 0
                                        and b["key_slot"] not in disabled),
                                       key=lambda b: (-b["remaining_microyuan"], b["key_slot"]))
                    if not available:
                        progress(output, amendment, "balance_exhausted", balances=current, current_task=tid)
                        return
                    batch = list(zip(pending[:study["workers"]], available, strict=False))
                    progress(output, amendment, "running", balances=current, current_task=tid,
                             active_arms=[arm for arm, _ in batch])
                    problems = []
                    with concurrent.futures.ThreadPoolExecutor(max_workers=study["workers"]) as pool:
                        futures = {pool.submit(attempt, output, study, tasks[tid], arm, docker,
                                               keys[b["key_slot"] - 1], b["key_slot"], amendment["model"]): (arm, b["key_slot"])
                                   for arm, b in batch}
                        for future in concurrent.futures.as_completed(futures):
                            arm, slot = futures[future]
                            try:
                                path, state = future.result()
                            except Exception as error:
                                problems.append((arm, "infrastructure_error:" + type(error).__name__))
                                continue
                            if state in TERMINAL:
                                path.rename(output / "test" / f"{tid}--{arm}")
                                pending.remove(arm)
                            else:
                                problems.append((arm, state))
                                if state == "balance_exhausted":
                                    disabled.add(slot)
                                    save(disabled_path, sorted(disabled))
                            progress(output, amendment, "running", current_task=tid)
                    if problems:
                        current = balances(keys)
                        # Do not rotate credentials to evade a provider's short-window limit.
                        if any(state != "balance_exhausted" for _, state in problems):
                            progress(output, amendment, "needs_attention", problems=problems, balances=current)
                            return
            progress(output, amendment, "completed", balances=balances(keys))
        except BaseException as error:
            progress(output, amendment, "needs_attention", error_type=type(error).__name__)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "preflight", "run", "report"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--pi-config", type=Path, default=Path.home() / ".pi/agent")
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    args = parser.parse_args()
    output = args.study.resolve()
    if args.stage == "prepare":
        value = prepare(output, args.pi_config)
        print(json.dumps({"groups": value["groups"], "model": value["model"]["id"]}), flush=True)
    elif args.stage == "report":
        value = check_amendment(output)
        status = read(output / "resume/status.json")
        progress(output, value, status["status"], publish=False)
    else:
        if args.key_file is None:
            parser.error("--key-file is required for preflight/run")
        run(output, args.key_file.resolve(), args.docker, preflight=args.stage == "preflight")


if __name__ == "__main__":
    main()
