"""Freeze public tasks and prepare offline Docker images, without exposing verifiers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

FAMILIES = ("organize-messy-files", "weighted-gdp-calculation",
            "offer-letter-generator", "financial-analysis")
ARMS = ("vanilla", "ours", "llm")
UPSTREAM_COMMIT = "726e1f79b96b0cb3d729d0e55a1c847e0b5353ae"
MODULE = Path(__file__).resolve().parent
REPOSITORY = MODULE.parents[1]


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree(path: Path, *, exclude_skills: bool = False) -> dict[str, str]:
    files = {}
    for file in sorted(path.rglob("*")):
        relative = file.relative_to(path)
        if exclude_skills and "skills" in relative.parts:
            continue
        if file.is_symlink():
            raise ValueError(f"Unexpected source symlink: {file}")
        if file.is_file():
            files[str(relative)] = digest(file)
    return files


def object_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def command(args, **kwargs) -> str:
    return subprocess.check_output([str(arg) for arg in args], text=True, **kwargs).strip()


def code_digests() -> dict[str, str]:
    return {p.name: digest(p) for p in sorted(MODULE.iterdir()) if p.suffix in (".py", ".ts")}


def strip_skills(dockerfile: str) -> str:
    """Only the upstream's known COPY skills form is removed; unknown forms fail closed."""
    lines = []
    for line in dockerfile.splitlines():
        if re.match(r"\s*COPY\s+skills\s+/root/\.[\w/-]+\s*$", line, re.I):
            continue
        if re.match(r"\s*(COPY|ADD)\b", line, re.I) and "skills" in line:
            raise ValueError(f"Unsupported skills copy: {line}")
        lines.append(line)
    return "\n".join(lines) + "\n"


def cache_arxiv_downloads(dockerfile: str) -> str:
    """Reuse exact versioned URLs during builds; the cache never enters a task image."""
    header = "RUN <<'EOF'\nset -euo pipefail\nmkdir -p /root/papers/all"
    start = '    if [ ! -f "$paper" ]; then\n'
    end = '            -O "$paper" "$url"\n    fi\n'
    if any(dockerfile.count(marker) != 1 for marker in (header, start, end)):
        raise ValueError("Unsupported upstream paper downloader")
    dockerfile = dockerfile.replace(header, header.replace(
        "RUN ", "RUN --mount=type=cache,id=orbit-arxiv-pdfs,target=/var/cache/orbit-arxiv,sharing=locked ", 1))
    dockerfile = dockerfile.replace(start,
        '    cache_key="$(printf \'%s\' "$url" | sha256sum | cut -d \' \' -f 1)"\n'
        '    cached="/var/cache/orbit-arxiv/$cache_key"\n'
        '    if [ ! -s "$cached" ]; then\n')
    return dockerfile.replace(end,
        '            -O "$cached.part" "$url"\n'
        '        test "$(head -c 5 "$cached.part")" = "%PDF-"\n'
        '        mv "$cached.part" "$cached"\n'
        '    fi\n'
        '    test "$(head -c 5 "$cached")" = "%PDF-"\n'
        '    cp "$cached" "$paper"\n')


def offline_verifier(script: str) -> str:
    """Use preinstalled pinned packages; retain the official pre/post processing and verdict."""
    lines, replaced = [], 0
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith(("apt-get update", "apt-get install -y curl",
                                "curl -LsSf https://astral.sh/uv/", "source $HOME/.local/bin/env")):
            continue
        if stripped == "uvx" or stripped.startswith(("uvx ", "--with ")):
            continue
        if stripped.startswith("pytest "):
            line = line.replace("pytest ", "python3 -m pytest ", 1)
            replaced += 1
        lines.append(line)
    if replaced != 1:
        raise ValueError("Unsupported verifier launcher; inspect its execution contract")
    return "\n".join(lines) + "\n"


def prepare(source: Path, output: Path, pi: Path, apt_mirror: str | None = None,
            pip_index: str | None = None) -> dict:
    source, output, pi = source.resolve(), output.resolve(), pi.resolve()
    if output.exists():
        raise ValueError("Use a new study directory; existing studies are never overwritten")
    commit = command(["git", "-C", source, "rev-parse", "HEAD"])
    if commit != UPSTREAM_COMMIT:
        raise ValueError("Benchmark source must match the preregistered upstream commit")
    if command(["git", "-C", source, "status", "--porcelain"]):
        raise ValueError("Benchmark source has local changes")
    tasks = []
    for family in FAMILIES:
        for number in range(1, 7):
            task_id = f"{family}-{number}"
            directory = source / "tasks" / family / task_id
            required = (directory / "instruction.md", directory / "environment/Dockerfile", directory / "tests/test.sh")
            if not all(p.is_file() for p in required):
                raise ValueError(f"Incomplete task download: {task_id}")
            verifier_available = (directory / "tests/test_outputs.py").is_file()
            if not verifier_available and task_id != "weighted-gdp-calculation-2":
                raise ValueError(f"Unexpected missing verifier: {task_id}")
            env = tree(directory / "environment", exclude_skills=True)
            verifier = tree(directory / "tests")
            script = (directory / "tests/test.sh").read_text()
            dependencies = sorted(set(re.findall(r"--with\s+([\w.=-]+)", script)))
            if not any(dep.startswith("pytest==") for dep in dependencies):
                dependencies.append("pytest==8.4.1")
            if not any(dep.startswith("pytest-json-ctrf==") for dep in dependencies):
                dependencies.append("pytest-json-ctrf==0.3.5")
            dockerfile = strip_skills((directory / "environment/Dockerfile").read_text())
            if family == "organize-messy-files":
                dockerfile = cache_arxiv_downloads(dockerfile)
            if apt_mirror:
                if not re.fullmatch(r"https?://[A-Za-z0-9./:_-]+", apt_mirror):
                    raise ValueError("APT mirror must be a plain HTTP(S) URL without credentials")
                hostname = urlparse(apt_mirror).hostname
                mirror_setup = ("RUN sed -i 's|http://ports.ubuntu.com/ubuntu-ports|" + apt_mirror.rstrip("/")
                                + "|g' /etc/apt/sources.list.d/ubuntu.sources\n"
                                + f"RUN echo 'Acquire::http::Proxy::{hostname} \"DIRECT\";' "
                                + "> /etc/apt/apt.conf.d/80orbit-mirror\n")
                dockerfile = dockerfile.replace("FROM ubuntu:24.04\n", "FROM ubuntu:24.04\n" + mirror_setup, 1)
            dockerfile += ("\nRUN apt-get update && apt-get install -y --no-install-recommends "
                           "file ca-certificates && rm -rf /var/lib/apt/lists/*\n")
            dockerfile += "RUN pip3 install --break-system-packages " + " ".join(dependencies) + "\n"
            if pip_index:
                if not re.fullmatch(r"https://[A-Za-z0-9./:_-]+", pip_index):
                    raise ValueError("Python index must be a plain HTTPS URL without credentials")
                dockerfile = dockerfile.replace("RUN pip3 install ", f"RUN pip3 install --index-url {pip_index} ")
            dockerfile += "WORKDIR /root\n"
            prompt = (directory / "instruction.md").read_text()
            tasks.append({"task_id": task_id, "family": family, "instance": number,
                          "split": "history" if number <= 3 else "test",
                          "source_relative": str(directory.relative_to(source)),
                          "prompt_sha256": digest(directory / "instruction.md"),
                          "environment_files": env, "verifier_files": verifier,
                          "environment_digest": object_digest(env),
                          "verifier_digest": object_digest(verifier),
                          "verifier_available": verifier_available,
                          "verifier_launcher": offline_verifier(script),
                          "dockerfile": dockerfile, "prompt": prompt})
    output.mkdir(parents=True)
    for task in tasks:
        path = output / "tasks/prompts" / (task["task_id"] + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(task.pop("prompt"))
    draft = {"schema_version": "orbit-artificial-study-v1", "status": "prepared", "frozen": False,
             "source": str(source), "benchmark_commit": commit, "apt_mirror": apt_mirror, "pip_index": pip_index,
             "orbit_commit": command(["git", "-C", REPOSITORY, "rev-parse", "HEAD"]),
             "pi": str(pi), "pi_version": command([pi, "--version"]),
             "provider": "kimi-coding", "model": "k3", "thinking": "max", "memory": "off",
             "context_limit": 1048576, "temperature": "provider default; adaptive thinking",
             "seed": 20261003, "max_turns": 200, "hard_timeout_seconds": 3600,
             "workers": 2, "container_memory": "3500m", "container_cpus": "2",
             "token_budget": None, "arms": list(ARMS), "tasks": tasks,
             "paired_tie_rule": "Both fail: tie; pass wins; both pass: lower total tokens wins; exact equality: tie",
             "information_policy": "identical task data; tools offline; no verifier/solution during execution",
             "adaptation_policy": "same history bundle; history-only reusable assets; frozen before any test",
             "llm_prompt": "Analyze the provided historical agent trajectories and create a concise reusable "
             "skill that can help the agent perform future unseen tasks more effectively. Use only information "
             "contained in the histories. Do not introduce external domain knowledge, benchmark solutions, "
             "hidden-test information, or task-specific answers. Keep the skill concise and generalizable.",
             "metric_policy": "input + output + cacheRead + cacheWrite; never add reasoning twice; unknown "
             "usage is not zero; adaptation separate from online; all failed runs retained"}
    save(output / "study-draft.json", draft)
    with (output / "tasks/task_manifest.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["task_id", "family", "split", "prompt_sha256", "environment_digest", "verifier_digest"])
        for task in tasks:
            writer.writerow([task[k] for k in ("task_id", "family", "split", "prompt_sha256",
                                               "environment_digest", "verifier_digest")])
    # Same prompts can accompany different inputs; report overlap, do not silently alter the split.
    overlap = [{"history": h["task_id"], "test": t["task_id"],
                "same_prompt": h["prompt_sha256"] == t["prompt_sha256"],
                "same_environment": h["environment_digest"] == t["environment_digest"]}
               for h in tasks if h["split"] == "history" for t in tasks if t["split"] == "test"
               and h["family"] == t["family"]]
    save(output / "tasks/split-overlap.json", overlap)
    return draft


def verify_source(study: dict) -> None:
    source = Path(study["source"])
    for task in study["tasks"]:
        directory = source / task["source_relative"]
        if digest(directory / "instruction.md") != task["prompt_sha256"]:
            raise ValueError(f"Prompt changed: {task['task_id']}")
        if tree(directory / "environment", exclude_skills=True) != task["environment_files"]:
            raise ValueError(f"Task inputs changed: {task['task_id']}")
        if tree(directory / "tests") != task["verifier_files"]:
            raise ValueError(f"Verifier changed: {task['task_id']}")


def build(output: Path, docker: str) -> None:
    study = read(output / "study-draft.json")
    verify_source(study)
    index_file = output / "image-index.json"
    images = read(index_file) if index_file.exists() else {}
    build_order = ("offer-letter-generator", "weighted-gdp-calculation", "financial-analysis", "organize-messy-files")
    for task in sorted(study["tasks"], key=lambda t: (build_order.index(t["family"]), t["instance"])):
        key = object_digest({"files": task["environment_files"], "dockerfile": task["dockerfile"]})
        tag = "orbit-benchmark:" + key[:20]
        if key in images:
            if command([docker, "image", "inspect", "--format", "{{.Id}}", images[key]["id"]]) != images[key]["id"]:
                raise ValueError("Previously built image is missing")
            continue
        context = output / "build" / key
        context.mkdir(parents=True, exist_ok=True)
        src = Path(study["source"]) / task["source_relative"] / "environment"
        for relative in task["environment_files"]:
            if relative == "Dockerfile":
                continue
            destination = context / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(src / relative, destination)
        (context / "Dockerfile").write_text(task["dockerfile"])
        (context / ".dockerignore").write_text("build.log\n")
        print(f"Building {task['task_id']} ({tag})", flush=True)
        build_args = []
        if proxy := os.environ.get("ORBIT_BUILD_PROXY"):
            build_args = ["--build-arg", f"HTTP_PROXY={proxy}", "--build-arg", f"HTTPS_PROXY={proxy}"]
        if study.get("pip_index"):
            build_args += ["--build-arg", "NO_PROXY=" + urlparse(study["pip_index"]).hostname]
        with (context / "build.log").open("w") as log:
            subprocess.run([docker, "build", "--progress=plain", *build_args, "-t", tag, str(context)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        info = json.loads(command([docker, "image", "inspect", tag]))[0]
        images[key] = {"id": info["Id"], "tag": tag, "architecture": info["Architecture"],
                       "build_task": task["task_id"]}
        save(index_file, images)
        print(f"Built {task['task_id']}: {info['Id']}", flush=True)
    mapping = {}
    for task in study["tasks"]:
        key = object_digest({"files": task["environment_files"], "dockerfile": task["dockerfile"]})
        mapping[task["task_id"]] = images[key]
    save(output / "task-images.json", mapping)


def freeze(output: Path, docker: str = "docker") -> dict:
    if (output / "benchmark_manifest.json").exists():
        raise ValueError("Study already frozen")
    study = read(output / "study-draft.json")
    images = read(output / "task-images.json")
    preflight = read(output / "container-preflight.json")
    if set(preflight) != set(FAMILIES) or not all(p["status"] == "passed" for p in preflight.values()):
        raise ValueError("All four task families must pass container/verifier preflight")
    for result in preflight.values():
        if result.get("runtime_files") != {n: digest(MODULE / n) for n in ("runner.py", "docker-tools.ts")}:
            raise ValueError("Runtime changed since preflight")
    assets = read(output / "personalization-preflight.json")
    if assets.get("status") != "passed" or not assets.get("readonly_verified") or not assets.get("hook_events"):
        raise ValueError("Read-only personalization and hook preflight must pass")
    if assets.get("runtime_files") != {n: digest(MODULE / n) for n in ("runner.py", "docker-tools.ts")}:
        raise ValueError("Runtime changed since personalization preflight")
    if set(images) != {t["task_id"] for t in study["tasks"]}:
        raise ValueError("Missing task images")
    verify_source(study)
    configs = [read(output / "preflight" / family / "model.json") for family in FAMILIES]
    if not all(config == configs[0] for config in configs):
        raise ValueError("Preflight model configurations differ")
    runtime_files = ("study.py", "runner.py", "docker-tools.ts")
    docker_info = json.loads(command([docker, "info", "--format", "{{json .}}"] ))
    environment = {"host": platform.platform(), "python": platform.python_version(),
                   "docker": {k: docker_info.get(k) for k in ("ServerVersion", "OperatingSystem", "Architecture",
                                                             "NCPU", "MemTotal", "DockerRootDir", "Driver")}}
    study.update(status="frozen", frozen=True, images=images,
                 environment=environment, harness_commit=command(["git", "-C", REPOSITORY, "rev-parse", "HEAD"]),
                 model_config=configs[0], adapter_files={name: digest(MODULE / name) for name in runtime_files},
                 planned_adaptation_files=code_digests(),
                 preflight_sha256=digest(output / "container-preflight.json"),
                 personalization_preflight_sha256=digest(output / "personalization-preflight.json"))
    save(output / "benchmark_manifest.json", study)
    (output / "benchmark_manifest.sha256").write_text(digest(output / "benchmark_manifest.json") + "\n")
    return study


def load_frozen(output: Path) -> dict:
    path = output / "benchmark_manifest.json"
    if digest(path) != (output / "benchmark_manifest.sha256").read_text().strip():
        raise ValueError("Frozen manifest changed")
    study = read(path)
    if not study["frozen"] or any(digest(MODULE / name) != value for name, value in study["adapter_files"].items()):
        raise ValueError("Runner changed after freeze; use a new study")
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "build", "freeze"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--pi", type=Path, default=Path(shutil.which("pi") or "pi"))
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--apt-mirror", help="Optional signed Ubuntu Ports mirror, recorded before freezing")
    parser.add_argument("--pip-index", help="Optional HTTPS Python package mirror, recorded before freezing")
    args = parser.parse_args()
    if args.stage == "prepare":
        if args.source is None:
            parser.error("prepare requires --source")
        prepare(args.source, args.study, args.pi, args.apt_mirror, args.pip_index)
    elif args.stage == "build":
        build(args.study, args.docker)
    else:
        freeze(args.study, args.docker)


if __name__ == "__main__":
    main()
