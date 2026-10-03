"""Run fresh memory-off Pi processes against isolated, offline task containers."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import queue
import random
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .study import (
    FAMILIES,
    MODULE,
    command,
    digest,
    load_frozen,
    object_digest,
    read,
    save,
    verify_source,
)


def summarize_events(events) -> dict:
    """Only message_end owns usage; agent_end repeats messages and is never summed."""
    totals = dict.fromkeys(("input", "output", "cacheRead", "cacheWrite"), 0)
    seen_usage = False
    complete = True
    messages, calls, failures, turns, retries, final = [], [], 0, 0, 0, ""
    last_stop = None
    for event in events:
        kind = event.get("type")
        turns += kind == "turn_end"
        retries += kind == "auto_retry_start"
        if kind != "message_end":
            continue
        msg = event.get("message", {})
        messages.append(msg)
        if msg.get("role") == "assistant":
            usage = msg.get("usage")
            if not isinstance(usage, dict) or not all(
                isinstance(usage.get(k), (int, float)) and not isinstance(usage[k], bool)
                and usage[k] >= 0 for k in totals
            ):
                complete = False
            else:
                seen_usage = True
                for key in totals:
                    totals[key] += usage[key]
            last_stop = msg.get("stopReason")
            if last_stop in ("aborted", "error"):
                complete = False  # Failed requests may have billed usage not reported by the provider.
            final = "".join(p.get("text", "") for p in msg.get("content", []) if p.get("type") == "text")
            calls.extend(p for p in msg.get("content", []) if p.get("type") == "toolCall")
        elif msg.get("role") == "toolResult":
            failures += bool(msg.get("isError"))
    complete = complete and seen_usage
    return {"usage": {**totals, "known_total_tokens": sum(totals.values()),
                      "total_tokens": sum(totals.values()) if complete else None,
                      "complete": complete},
            "agent_turns": turns, "tool_calls": len(calls), "failed_tool_calls": failures,
            "retries": retries, "shell_commands": sum(c.get("name") == "bash" for c in calls),
            "edits": sum(c.get("name") in ("write", "edit") for c in calls),
            "final_answer": final, "last_stop_reason": last_stop,
            "messages": messages, "tool_call_details": calls}


def events_from(path: Path):
    for line in path.open():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid or truncated event stream: {path}") from None


def agent_directory(target: Path, source: Path, study: dict) -> dict:
    target.mkdir(parents=True, mode=0o700)
    credentials = read(source / "auth.json")
    if credentials.get("kimi-coding", {}).get("type") != "api_key":
        raise ValueError("This benchmark expects the existing Kimi API-key provider")
    registry = read(source / "models-store.json")["kimi-coding"]
    model = next(m for m in registry["models"] if m["id"] == study["model"])
    if model.get("thinkingLevelMap", {}).get("max") != "max":
        raise ValueError("Kimi max effort is not supported by the configured model")
    if model["contextWindow"] != study["context_limit"]:
        raise ValueError("Model context limit changed")
    configured = {key: model.get(key) for key in ("id", "provider", "api", "baseUrl", "contextWindow",
                                                  "maxTokens", "thinkingLevelMap", "compat")}
    if study.get("model_config") is not None and configured != study["model_config"]:
        raise ValueError("Model endpoint or configuration changed after freeze")
    for name, value in {
        "auth.json": {"kimi-coding": credentials["kimi-coding"]},
        "models-store.json": {"kimi-coding": {**registry, "models": [model]}},
        "settings.json": {"defaultProvider": "kimi-coding", "defaultModel": study["model"],
                          "defaultThinkingLevel": "max", "compaction": {"enabled": False},
                          "cacheWarming": "off", "retry": {"enabled": True, "maxRetries": 2},
                          "quietStartup": True, "defaultProjectTrust": "never"},
    }.items():
        save(target / name, value)
        (target / name).chmod(0o600)
    return configured


def create_container(docker: str, study: dict, task: dict, assets: Path | None = None) -> str:
    name = "orbit-bench-" + uuid.uuid4().hex
    image = study["images"][task["task_id"]]["id"]
    mounts = []
    if assets is not None:
        if not (assets / "manifest.json").is_file():
            raise ValueError("Missing frozen personalization manifest")
        command([docker, "volume", "create", name + "-assets"])
        try:
            command([docker, "create", "--name", name + "-setup", "--network", "none",
                     "--mount", f"type=volume,src={name}-assets,dst=/assets", image, "true"])
            command([docker, "cp", str(assets) + "/.", name + "-setup:/assets"])
        except BaseException:
            subprocess.run([docker, "rm", "-f", name + "-setup"], capture_output=True)
            subprocess.run([docker, "volume", "rm", name + "-assets"], capture_output=True)
            raise
        finally:
            subprocess.run([docker, "rm", "-f", name + "-setup"], capture_output=True)
        mounts = ["--mount", f"type=volume,src={name}-assets,dst=/opt/orbit-personalization,readonly"]
    command([docker, "run", "-d", "--name", name, "--network", "none", "--cap-drop", "ALL",
             "--security-opt", "no-new-privileges", "--pids-limit", "512",
             "--memory", study["container_memory"], "--cpus", study["container_cpus"],
             "--workdir", "/root", *mounts, image, "sleep", "infinity"])
    try:
        info = json.loads(command([docker, "inspect", name]))[0]
        allowed_mounts = all(m["Type"] == "volume" and m["Name"] == name + "-assets"
                             and m["Destination"] == "/opt/orbit-personalization" and not m["RW"]
                             for m in info["Mounts"])
        if info["HostConfig"]["NetworkMode"] != "none" or not allowed_mounts \
                or len(info["Mounts"]) != int(assets is not None):
            raise ValueError("Task container permits only its frozen personalization volume, read-only")
        command([docker, "exec", name, "bash", "-c",
                 "test ! -e /tests && test ! -e /solution && "
                 "test -z \"$(find /root -type f -name SKILL.md -print -quit)\""])
    except BaseException:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)
        if assets is not None:
            subprocess.run([docker, "volume", "rm", name + "-assets"], capture_output=True)
        raise
    return name


def verifier(docker: str, name: str, task: dict, study: dict, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if not task["verifier_available"]:
        result = {"status": "missing_upstream_verifier", "passed": None,
                  "reason": "weighted-gdp-calculation-2 has no upstream test_outputs.py"}
        save(output / "result.json", result)
        return result
    source = Path(study["source"]) / task["source_relative"] / "tests"
    command([docker, "exec", name, "mkdir", "-p", "/tests", "/logs/verifier"])
    command([docker, "cp", str(source) + "/.", name + ":/tests"])
    launcher = output / "offline-test.sh"
    launcher.write_text(task["verifier_launcher"])
    command([docker, "cp", launcher, name + ":/tests/orbit-test.sh"])
    with (output / "stdout.log").open("w") as log:
        proc = subprocess.run([docker, "exec", name, "timeout", "300", "bash", "/tests/orbit-test.sh"],
                              stdout=log, stderr=subprocess.STDOUT, timeout=330)
    copied = subprocess.run([docker, "cp", name + ":/logs/verifier/.", str(output)], capture_output=True)
    ctrf = output / "ctrf.json"
    reward = output / "reward.txt"
    if proc.returncode != 0 or copied.returncode != 0 or not ctrf.exists() or not reward.exists():
        result = {"status": "infrastructure_error", "passed": None, "launcher_exit_code": proc.returncode}
    else:
        report = read(ctrf)["results"]["summary"]
        value = reward.read_text().strip()
        if not report.get("tests") or value not in ("0", "1"):
            result = {"status": "infrastructure_error", "passed": None, "summary": report}
        else:
            passed = value == "1" and report.get("failed", 0) == 0
            result = {"status": "passed" if passed else "failed", "passed": passed, "summary": report}
    save(output / "result.json", result)
    return result


def run_pi(study: dict, output: Path, prompt: str, name: str, docker: str, credentials: Path,
           *, assets: bool = False) -> dict:
    agent = output / "agent"
    model = agent_directory(agent, credentials, study)
    save(output / "model.json", model)
    sessions = output / "sessions"
    args = [study["pi"], "--mode", "json", "--print", "--provider", study["provider"],
            "--model", study["model"], "--thinking", study["thinking"], "--offline",
            "--no-extensions", "--no-skills", "--no-context-files", "--no-prompt-templates",
            "--no-themes", "--no-approve", "--session-dir", str(sessions),
            "--no-builtin-tools", "--extension", str(MODULE / "docker-tools.ts"), "--", prompt]
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1", "PI_TELEMETRY": "0",
           "ORBIT_BENCH_CONTAINER": name, "ORBIT_DOCKER_BIN": docker,
           "ORBIT_BENCH_ASSETS": "1" if assets else "0"}
    start = time.monotonic()
    termination = "completed"
    messages: queue.Queue = queue.Queue(maxsize=64)
    process = None
    # One logical study project in native session metadata. All actual file operations
    # still execute in a fresh container; this empty host folder is never a tool workspace.
    runtime = output.parents[1] / "runtime"
    runtime.mkdir(exist_ok=True)
    try:
        with (output / "stderr.log").open("w") as stderr, (output / "events.jsonl").open("w") as stdout:
            process = subprocess.Popen(args, cwd=runtime, env=env, stdout=subprocess.PIPE, stderr=stderr,
                                       text=True, start_new_session=True)

            def read_events():
                try:
                    for line in process.stdout:
                        stdout.write(line)
                        stdout.flush()
                        messages.put(line)
                finally:
                    messages.put(None)

            thread = threading.Thread(target=read_events, daemon=True)
            thread.start()
            turns = 0
            while True:
                if time.monotonic() - start >= study["hard_timeout_seconds"]:
                    termination = "timeout"
                    break
                try:
                    line = messages.get(timeout=1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                event = json.loads(line)
                if event.get("type") == "turn_end":
                    turns += 1
                    if turns >= study["max_turns"]:
                        termination = "turn_limit"
                        break
            if termination != "completed":
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            # Drain the bounded queue so the writer can finish without dropping final events.
            while thread.is_alive():
                try:
                    messages.get(timeout=.1)
                except queue.Empty:
                    pass
            thread.join()
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        (agent / "auth.json").unlink(missing_ok=True)
        subprocess.run([docker, "stop", "--time", "1", name], capture_output=True)
    result = summarize_events(events_from(output / "events.jsonl"))
    result.update(termination=termination, exit_code=process.returncode,
                  wall_time_seconds=round(time.monotonic() - start, 3))
    if termination != "completed":
        result["usage"]["complete"] = False
        result["usage"]["total_tokens"] = None
    save(output / "trajectory.json", result)
    return result


def one_run(study: dict, task: dict, output: Path, docker: str, credentials: Path, *, preflight=False,
            arm="vanilla", assets: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    name = create_container(docker, study, task, assets)
    started = time.time()
    try:
        if preflight:
            prompt = ('Use bash to confirm that /tests and /solution are absent and that /root/.agents/skills '
                      'is absent. Use write to create /root/orbit_probe.txt with the exact text "alpha"; '
                      'use read to inspect it; use edit to replace alpha with beta. Finally use bash to '
                      'check its contents are beta. Do not read or modify any other task files. '
                      'Reply with exactly ORBIT_CONTAINER_READY.')
        else:
            path = output.parents[1] / "tasks/prompts" / (task["task_id"] + ".md")
            prompt = path.read_text()
            if hashlib_text(prompt) != task["prompt_sha256"]:
                raise ValueError("Task prompt changed")
        (output / "prompt.md").write_text(prompt)
        trajectory = run_pi(study, output, prompt, name, docker, credentials, assets=assets is not None)
        # No agent remains alive when hidden tests are copied into the container.
        command([docker, "start", name])
        verdict = verifier(docker, name, task, study, output / "verifier")
        normal = trajectory["termination"] == "completed" and trajectory["exit_code"] == 0 \
            and trajectory["last_stop_reason"] == "stop"
        if preflight:
            actual = command([docker, "exec", name, "cat", "/root/orbit_probe.txt"])
            tools = {c.get("name") for c in trajectory["tool_call_details"]}
            passed = normal and actual == "beta" and tools >= {"read", "write", "edit", "bash"} \
                and verdict["status"] in ("passed", "failed")
            result = {"status": "passed" if passed else "failed", "verifier": verdict,
                      "adapter_tools": sorted(tools), "trajectory_usage": trajectory["usage"],
                      "runtime_files": runtime_digests()}
        else:
            passed = bool(normal and verdict["passed"]) if verdict["passed"] is not None else None
            result = {"task_id": task["task_id"], "family": task["family"], "arm": arm,
                      "split": task["split"], "passed": passed, "verifier": verdict,
                      "termination": trajectory["termination"], "agent_completed": normal,
                      "usage": trajectory["usage"], "agent_turns": trajectory["agent_turns"],
                      "tool_calls": trajectory["tool_calls"], "failed_tool_calls": trajectory["failed_tool_calls"],
                      "shell_commands": trajectory["shell_commands"], "edits": trajectory["edits"],
                      "wall_time_seconds": trajectory["wall_time_seconds"], "started_at": started,
                      "image_id": study["images"][task["task_id"]]["id"],
                      "prompt_sha256": task["prompt_sha256"], "environment_digest": task["environment_digest"],
                      "verifier_digest": task["verifier_digest"],
                      "raw_events_sha256": digest(output / "events.jsonl")}
        changes = command([docker, "diff", name])
        (output / "container-diff.txt").write_text(changes + "\n")
        # Keep every changed/new task file, including generated scripts and document outputs.
        artifacts = output / "artifacts"
        for line in changes.splitlines():
            status, _, path = line.partition(" ")
            if status not in ("A", "C") or not path.startswith("/root/"):
                continue
            regular = subprocess.run([docker, "exec", name, "test", "-f", path], capture_output=True)
            if regular.returncode == 0:
                target = artifacts / path.removeprefix("/root/")
                target.parent.mkdir(parents=True, exist_ok=True)
                command([docker, "cp", name + ":" + path, str(target)])
        save(output / "result.json", result)
        print(json.dumps({"task": task["task_id"], "preflight": preflight,
                          "passed": result.get("passed", result.get("status")),
                          "tokens": trajectory["usage"]["total_tokens"]}), flush=True)
        return result
    except BaseException as error:
        save(output / "infrastructure-error.json", {"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)
        if assets is not None:
            subprocess.run([docker, "volume", "rm", name + "-assets"], capture_output=True)


def hashlib_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def runtime_digests() -> dict:
    return {name: digest(MODULE / name) for name in ("runner.py", "docker-tools.ts")}


def preflight(output: Path, docker: str, credentials: Path, families=FAMILIES) -> None:
    study = read(output / "study-draft.json")
    index = read(output / "image-index.json")
    study["images"] = {}
    for task in study["tasks"]:
        key = object_digest({"files": task["environment_files"], "dockerfile": task["dockerfile"]})
        if key in index:
            study["images"][task["task_id"]] = index[key]
    result_file = output / "container-preflight.json"
    results = read(result_file) if result_file.exists() else {}
    for family in families:
        task = next(t for t in study["tasks"] if t["family"] == family)
        directory = output / "preflight" / family
        if directory.exists() and (not (directory / "result.json").exists() or
                read(directory / "result.json").get("runtime_files") != runtime_digests()):
            archive = output / "preflight-archive" / (family + "-" + uuid.uuid4().hex[:8])
            archive.parent.mkdir(exist_ok=True)
            directory.rename(archive)
        if (directory / "result.json").exists():
            results[family] = read(directory / "result.json")
        else:
            results[family] = one_run(study, task, directory, docker, credentials, preflight=True)
        save(result_file, results)
        if results[family]["status"] != "passed":
            raise ValueError(f"Preflight failed: {family}")


def history(output: Path, docker: str, credentials: Path) -> None:
    study = load_frozen(output)
    verify_source(study)
    if command([study["pi"], "--version"]) != study["pi_version"]:
        raise ValueError("Pi version changed after freeze")
    tasks = [t for t in study["tasks"] if t["split"] == "history"]
    random.Random(study["seed"]).shuffle(tasks)
    with concurrent.futures.ThreadPoolExecutor(max_workers=study["workers"]) as pool:
        futures = []
        for task in tasks:
            destination = output / "history" / task["task_id"]
            if (destination / "result.json").exists():
                continue
            futures.append(pool.submit(one_run, study, task, destination, docker, credentials))
        for future in concurrent.futures.as_completed(futures):
            future.result()
    histories = []
    for task in sorted(tasks, key=lambda t: t["task_id"]):
        directory = output / "history" / task["task_id"]
        histories.append({"task_id": task["task_id"], "family": task["family"],
                          "prompt": (directory / "prompt.md").read_text(),
                          "result": read(directory / "result.json"),
                          "trajectory": read(directory / "trajectory.json")})
    bundle = {"schema_version": "orbit-history-bundle-v1", "source_manifest_sha256":
              digest(output / "benchmark_manifest.json"), "histories": histories}
    save(output / "history_bundle.json", bundle)
    save(output / "history_bundle.digest.json", {"sha256": object_digest(bundle)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("preflight", "history"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    parser.add_argument("--pi-config", type=Path, default=Path.home() / ".pi/agent")
    parser.add_argument("--family", choices=FAMILIES, help="Preflight an already-built family")
    args = parser.parse_args()
    if args.stage == "preflight":
        preflight(args.study.resolve(), args.docker, args.pi_config.resolve(),
                  (args.family,) if args.family else FAMILIES)
    else:
        history(args.study.resolve(), args.docker, args.pi_config.resolve())


if __name__ == "__main__":
    main()
