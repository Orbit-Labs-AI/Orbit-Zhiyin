"""Exercise a read-only skill volume and the original product hook through Pi."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from tandem_backend.ai.generate.templates import get

from .adaptation import add_spec
from .runner import create_container, one_run, runtime_digests
from .study import object_digest, read, save


def run(root: Path, docker: str, credentials: Path) -> None:
    saved = root / "personalization-preflight.json"
    if saved.exists():
        previous = read(saved)
        if previous.get("status") == "passed" and previous.get("runtime_files") == runtime_digests():
            return
    study = read(root / "study-draft.json")
    task = next(t for t in study["tasks"] if t["task_id"] == "offer-letter-generator-1")
    key = object_digest({"files": task["environment_files"], "dockerfile": task["dockerfile"]})
    study["images"] = {task["task_id"]: read(root / "image-index.json")[key]}
    probe = uuid.uuid4().hex[:8]
    assets = root / "setup-assets" / probe
    assets.mkdir(parents=True, exist_ok=False)
    manifest = {"instructions": [], "skills": [], "hooks": []}
    skill = ("---\nname: container-probe\ndescription: Use for container tool preflight and alpha to beta file roundtrips.\n"
             "---\nUse the read, bash, write and edit tools to verify file roundtrips.\n")
    add_spec(assets, manifest, {"kind": "skill", "payload": {"name": "container-probe", "files": [
        {"rel": "SKILL.md", "text": skill}]}})
    template = get("retry-breaker")
    add_spec(assets, manifest, {"id": "retry-breaker", "kind": "hook", "payload": {
        "script": {"name": template.script_name, "text": template.body},
        "extra_files": [{"name": "retry-breaker.config.json", "text": json.dumps(template.defaults)}],
        "event_bindings": template.events}})
    save(assets / "manifest.json", manifest)
    name = create_container(docker, study, task, assets)
    try:
        check = subprocess.run([docker, "exec", name, "bash", "-c",
                                "echo changed > /opt/orbit-personalization/manifest.json"],
                               capture_output=True, text=True)
        if check.returncode == 0 or "Read-only file system" not in check.stderr:
            raise ValueError("Personalization assets must be read-only inside the task container")
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)
        subprocess.run([docker, "volume", "rm", name + "-assets"], capture_output=True)
    output = root / "personalization-preflight" / probe
    result = one_run(study, task, output, docker, credentials, preflight=True, assets=assets)
    entries = [json.loads(line) for path in (output / "sessions").rglob("*.jsonl")
               for line in path.read_text().splitlines()]
    hooks = [e for e in entries if e.get("customType") == "orbit.benchmark.hook"]
    if not hooks:
        raise ValueError("Pi did not dispatch product hook events")
    save(saved, {"status": result["status"], "readonly_verified": True, "hook_events": len(hooks),
                 "runtime_files": runtime_digests(), "probe": probe})
    print(json.dumps(read(saved)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    parser.add_argument("--pi-config", type=Path, default=Path.home() / ".pi/agent")
    args = parser.parse_args()
    run(args.study.resolve(), args.docker, args.pi_config.resolve())


if __name__ == "__main__":
    main()
