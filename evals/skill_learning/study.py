"""Prepare only preregistered development tasks; final test requires a freeze receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

MODULE = Path(__file__).resolve().parent
REPOSITORY = MODULE.parents[1]


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def command(args, **kwargs) -> str:
    return subprocess.check_output([str(arg) for arg in args], text=True, **kwargs).strip()


def tree(path: Path, *, exclude_skills: bool = False) -> dict:
    result = {}
    for file in sorted(path.rglob("*")):
        relative = file.relative_to(path)
        if exclude_skills and "skills" in relative.parts:
            continue
        if file.is_symlink():
            raise ValueError(f"Source symlinks are not supported: {file}")
        if file.is_file():
            result[str(relative)] = digest(file)
    return result


def strip_skills(dockerfile: str) -> str:
    lines = []
    for line in dockerfile.splitlines():
        if re.match(r"\s*COPY\s+skills\s+/root/\.[\w/-]+\s*$", line, re.I):
            continue
        if re.match(r"\s*(COPY|ADD)\b", line, re.I) and "skills" in line:
            raise ValueError(f"Unsupported upstream skills copy: {line}")
        lines.append(line)
    return "\n".join(lines) + "\n"


def with_apt_mirror(dockerfile: str, mirror: str | None) -> str:
    if mirror is None:
        return dockerfile
    if not re.fullmatch(r"https?://[A-Za-z0-9.:-]+", mirror):
        raise ValueError("APT mirror must be a bare HTTP(S) origin without credentials")
    setup = ('RUN for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do '
             '[ ! -f "$f" ] || sed -i '
             f"'s|http://deb.debian.org/debian|{mirror}/debian|g;"
             f"s|http://ports.ubuntu.com/ubuntu-ports|{mirror}/ubuntu-ports|g;"
             f"s|http://archive.ubuntu.com/ubuntu|{mirror}/ubuntu|g;"
             f"s|http://security.ubuntu.com/ubuntu|{mirror}/ubuntu|g' \"$f\"; done\n")
    return re.sub(r"(?m)^(FROM[^\n]*)\n", lambda m: m.group(0) + setup, dockerfile, count=1)


def offline_verifier(script: str) -> str:
    # Several upstream launchers wrap only the uv installer in this branch.
    # Removing individual lines would leave an empty `then` and a broken verifier.
    script = re.sub(r"(?ms)^if command -v curl[^\n]*; then\n"
                    r"\s*curl -LsSf https://astral\.sh/uv/[^\n]*\n"
                    r"\s*source \$HOME/\.local/bin/env\nelse\n"
                    r"\s*pip3 install --break-system-packages uv\nfi\n", "", script)
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
        raise ValueError("Unsupported verifier launcher: inspect before executing")
    result = "\n".join(lines) + "\n"
    subprocess.run(["bash", "-n"], input=result, text=True, check=True, capture_output=True)
    return result


def validate_protocol(protocol: dict) -> None:
    exposed = set(protocol["prior_exposed_families"])
    for family, splits in protocol["candidate_families"].items():
        if family in exposed:
            raise ValueError(f"Previously exposed family cannot be held out: {family}")
        seen = set()
        for name in ("history", "validation", "test"):
            instances = splits[name]
            if not instances or any(type(number) is not int or number < 1 for number in instances):
                raise ValueError(f"Invalid {name} instances for {family}")
            if len(set(instances)) != len(instances) or seen.intersection(instances):
                raise ValueError(f"Overlapping or duplicate splits for {family}")
            seen.update(instances)


def prepare(root: Path, source: Path, families: list[str], split: str, pip_index: str | None = None,
            apt_mirror: str | None = None) -> dict:
    protocol = read(root / "protocol.json")
    validate_protocol(protocol)
    commit = command(["git", "-C", source, "rev-parse", "HEAD"])
    if commit != protocol["source"]["commit"]:
        raise ValueError("Benchmark source revision differs from preregistration")
    if split == "test":
        receipt = read(root / "freeze.json")
        if command(["git", "-C", REPOSITORY, "status", "--porcelain"]):
            raise ValueError("Final test requires a clean frozen checkout")
        if receipt["code_commit"] != command(["git", "-C", REPOSITORY, "rev-parse", "HEAD"]):
            raise ValueError("Final test implementation is not the frozen commit")
        if digest(root / "protocol.json") != receipt["protocol_sha256"]:
            raise ValueError("Protocol changed after freeze")
        if set(families) != set(receipt["selected_families"]):
            raise ValueError("Final test families differ from freeze")
    path = root / "study.json"
    study = read(path) if path.exists() else {
        "schema_version": "orbit-skill-learning-study-v1", "source": str(source),
        "benchmark_commit": commit, "protocol_sha256": digest(root / "protocol.json"),
        "orbit_commit": command(["git", "-C", REPOSITORY, "rev-parse", "HEAD"]),
        "pi": str(Path.home() / ".local/bin/pi"), "provider": "kimi-coding", "model": "k3",
        "thinking": "max", "memory": "off", "context_limit": 1048576,
        "max_turns": 200, "hard_timeout_seconds": 3600, "workers": 2,
        "container_memory": "3500m", "container_cpus": "2", "tasks": [], "images": {},
        "metric_policy": "message_end input + output + cacheRead + cacheWrite; preserve missing usage",
        "pip_index": pip_index, "apt_mirror": apt_mirror,
    }
    for family in families:
        for number in protocol["candidate_families"][family][split]:
            task_id = f"{family}-{number}"
            if any(t["task_id"] == task_id for t in study["tasks"]):
                continue
            directory = source / "tasks" / family / task_id
            environment, verifier = tree(directory / "environment", exclude_skills=True), tree(directory / "tests")
            if not environment or not verifier or not (directory / "instruction.md").is_file():
                raise ValueError(f"Development task not downloaded: {task_id}")
            script = (directory / "tests/test.sh").read_text()
            dependencies = sorted(set(re.findall(r"--with\s+([\w.=-]+)", script)))
            for dep in ("pytest==8.4.1", "pytest-json-ctrf==0.3.5"):
                if not any(d.startswith(dep.split("==")[0] + "==") for d in dependencies):
                    dependencies.append(dep)
            dockerfile = strip_skills((directory / "environment/Dockerfile").read_text())
            dockerfile = with_apt_mirror(dockerfile, apt_mirror)
            workdirs = re.findall(r"(?m)^WORKDIR\s+(/\S+)\s*$", dockerfile)
            cwd = workdirs[-1] if workdirs else "/root"
            dockerfile += ("\nRUN apt-get update && apt-get install -y --no-install-recommends "
                           "file ca-certificates && rm -rf /var/lib/apt/lists/*\n")
            dockerfile += "RUN pip3 install --break-system-packages " + " ".join(dependencies) + f"\nWORKDIR {cwd}\n"
            if pip_index:
                if not re.fullmatch(r"https://[A-Za-z0-9./:_-]+", pip_index):
                    raise ValueError("Python index must be an HTTPS URL without credentials")
                dockerfile = re.sub(r"\b(pip3?) install\b",
                                   rf"\1 install --index-url {pip_index} --default-timeout 120", dockerfile)
            task = {"task_id": task_id, "family": family, "instance": number, "split": split,
                    "source_relative": str(directory.relative_to(source)), "working_directory": cwd,
                    "prompt_sha256": digest(directory / "instruction.md"),
                    "environment_files": environment, "verifier_files": verifier,
                    "environment_digest": object_digest(environment), "verifier_digest": object_digest(verifier),
                    "verifier_available": (directory / "tests/test_outputs.py").is_file(),
                    "verifier_launcher": offline_verifier(script), "dockerfile": dockerfile}
            prompt = root / "tasks/prompts" / f"{task_id}.md"
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_bytes((directory / "instruction.md").read_bytes())
            study["tasks"].append(task)
    study["pi_version"] = command([study["pi"], "--version"])
    save(path, study)
    return study


def build(root: Path, docker: str) -> None:
    study = read(root / "study.json")
    for task in study["tasks"]:
        key = object_digest({"files": task["environment_files"], "dockerfile": task["dockerfile"]})
        if task["task_id"] in study["images"]:
            continue
        # Identical environments share one immutable image. Rebuilding the same
        # tag can remove its previous image ID with containerd's image store.
        shared = next((image for image in study["images"].values()
                       if image["context_digest"] == key), None)
        if shared is not None:
            command([docker, "image", "inspect", shared["id"]])
            study["images"][task["task_id"]] = dict(shared)
            save(root / "study.json", study)
            continue
        context = root / "build" / key
        context.mkdir(parents=True, exist_ok=True)
        environment = Path(study["source"]) / task["source_relative"] / "environment"
        for relative, sha in task["environment_files"].items():
            if digest(environment / relative) != sha:
                raise ValueError("Task environment changed after preparation")
            dest = context / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(environment / relative, dest)
        (context / "Dockerfile").write_text(task["dockerfile"])
        tag = "orbit-skill-learning:" + key[:20]
        proxy = os.environ.get("ORBIT_BUILD_HTTP_PROXY")
        build_args = (["--build-arg", f"http_proxy={proxy}", "--build-arg", f"https_proxy={proxy}"]
                      if proxy else [])
        attempt = len(list(context.glob("build-*.log"))) + 1
        with (context / f"build-{attempt}.log").open("w") as log:
            subprocess.run([docker, "build", "--progress=plain", *build_args, "-t", tag, str(context)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        image = json.loads(command([docker, "image", "inspect", tag]))[0]
        study["images"][task["task_id"]] = {"id": image["Id"], "tag": tag, "context_digest": key}
        save(root / "study.json", study)
        print(json.dumps({"built": task["task_id"], "image": image["Id"]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "build"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--families", nargs="+")
    parser.add_argument("--split", choices=["history", "validation", "test"], default="validation")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--pip-index")
    parser.add_argument("--apt-mirror")
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.source or not args.families:
            parser.error("prepare requires --source and --families")
        study = prepare(args.root, args.source, args.families, args.split, args.pip_index, args.apt_mirror)
        print(json.dumps({"tasks": len(study["tasks"]), "split": args.split}))
    else:
        build(args.root, args.docker)


if __name__ == "__main__":
    main()
