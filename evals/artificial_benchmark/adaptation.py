"""History-only Orbit and direct-LLM adaptation, frozen before held-out execution."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import yaml
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store

from tandem_backend import features
from tandem_backend.ai import pack as packs
from tandem_backend.ai.errors import CallFailed
from tandem_backend.ai.generate import tasks as generation
from tandem_backend.analytics.inputs import Scope
from tandem_backend.appdb import AppDB
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.features.service import FeatureService
from tandem_backend.install.errors import PlanError
from tandem_backend.install.plan import _ai_payload, _kb_spec, build_spec
from tandem_backend.recommend import section
from tandem_backend.recommend.engine import build_slate
from tandem_backend.recommend.store import memory
from tandem_backend.services.sections import ResultMemo

from .runner import agent_directory, events_from, summarize_events
from .study import code_digests, digest, load_frozen, object_digest, read, save, tree


def model_call(study: dict, output: Path, system: str, prompt: str, credentials: Path) -> str:
    """Same isolated Pi/Kimi model, no tools; prompt on stdin avoids argv size limits."""
    output.mkdir(parents=True, exist_ok=False)
    agent = output / "agent"
    save(output / "model.json", agent_directory(agent, credentials, study))
    (output / "system.md").write_text(system)
    (output / "prompt.md").write_text(prompt)
    args = [study["pi"], "--mode", "json", "--print", "--provider", study["provider"],
            "--model", study["model"], "--thinking", study["thinking"], "--offline",
            "--no-extensions", "--no-skills", "--no-context-files", "--no-prompt-templates",
            "--no-themes", "--no-approve", "--no-tools", "--system-prompt", system,
            "--session-dir", str(output / "sessions")]
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1", "PI_TELEMETRY": "0"}
    start = time.monotonic()
    try:
        with (output / "events.jsonl").open("w") as stdout, (output / "stderr.log").open("w") as stderr:
            process = subprocess.Popen(args, cwd=output, env=env, stdin=subprocess.PIPE,
                                       stdout=stdout, stderr=stderr, text=True, start_new_session=True)
            try:
                process.communicate(prompt, timeout=study["hard_timeout_seconds"])
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
    finally:
        (agent / "auth.json").unlink(missing_ok=True)
    result = summarize_events(events_from(output / "events.jsonl"))
    result.update(exit_code=process.returncode, wall_time_seconds=time.monotonic() - start)
    save(output / "trajectory.json", result)
    if process.returncode or result["last_stop_reason"] != "stop":
        raise CallFailed(f"Adaptation model call did not complete: {output}")
    return result["final_answer"]


def unfence(text: str) -> str:
    text = text.strip()
    match = re.fullmatch(r"```(?:markdown|md|json)?\s*\n(.*)\n```", text, re.S)
    return (match.group(1) if match else text).strip() + "\n"


def skill_metadata(text: str) -> dict:
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise ValueError("Skill lacks YAML frontmatter")
    front = yaml.safe_load(text.split("---", 2)[1])
    if not isinstance(front, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(front.get("name", ""))):
        raise ValueError("Invalid skill name")
    if not isinstance(front.get("description"), str) or not front["description"].strip():
        raise ValueError("Skill needs a nonempty description")
    return {"name": front["name"], "description": front["description"]}


def add_spec(assets: Path, manifest: dict, spec: dict) -> str:
    """Translate existing product payloads, without writing new advice ourselves."""
    kind, payload = spec["kind"], spec["payload"]
    if kind in ("rule", "command"):
        manifest["instructions"].append(payload["text"])
        return "system_instruction"
    if kind == "skill":
        name = payload["name"]
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise ValueError("Invalid skill directory")
        for file in payload["files"]:
            path = assets / "skills" / name / file["rel"]
            if not path.resolve().is_relative_to((assets / "skills" / name).resolve()):
                raise ValueError("Skill path escapes personalization")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file["text"])
        main = assets / "skills" / name / "SKILL.md"
        manifest["skills"].append({**skill_metadata(main.read_text()), "path": str(main.relative_to(assets))})
        return "pi_skill"
    if kind == "hook":
        script = payload.get("script") or {}
        if not script.get("text") or not re.fullmatch(r"[A-Za-z0-9._@-]+", script.get("name", "")):
            return "unavailable_nonbundled_hook"
        folder = assets / "hooks" / spec["id"]
        folder.mkdir(parents=True, exist_ok=False)
        (folder / script["name"]).write_text(script["text"])
        config = None
        for file in payload.get("extra_files") or []:
            if not re.fullmatch(r"[A-Za-z0-9._@-]+", file["name"]):
                raise ValueError("Invalid hook asset path")
            (folder / file["name"]).write_text(file["text"])
            if file["name"].endswith(".config.json"):
                config = file["name"]
        if config is None:
            raise ValueError("Bundled hook has no config")
        events = [b["event"] for b in payload.get("event_bindings", [])]
        if set(events) - {"PreToolUse", "PostToolUse", "Stop"}:
            return "unavailable_pi_hook_event"
        manifest["hooks"].append({"id": spec["id"], "script": str((folder / script["name"]).relative_to(assets)),
                                  "config": str((folder / config).relative_to(assets)), "events": events})
        return "pi_hook_adapter"
    return "unavailable_in_fixed_pi_runtime"


class GenerationContext:
    template = "v1"

    def __init__(self, study, directory, credentials, pack, params):
        self.study, self.directory, self.credentials, self.pack, self.params = study, directory, credentials, pack, params
        self.calls, self.stages = 0, []
        directory.mkdir(parents=True)

    def stage(self, *args):
        self.stages.append(list(args))
        save(self.directory / "stages.json", self.stages)

    def log(self, message):
        self.stage("log", message)

    def call(self, *, prompt, validate):
        feedback = ""
        for _ in range(2):
            self.calls += 1
            text = model_call(self.study, self.directory / f"call-{self.calls:02}", generation.SYSTEM,
                              prompt + feedback, self.credentials)
            try:
                value = json.loads(unfence(text))
                errors = validate(value, self.pack)
            except (ValueError, TypeError) as error:
                errors = [str(error)]
            if not errors:
                return value
            feedback = "\nReturn valid JSON and correct these validation errors:\n" + "\n".join(errors)
        raise CallFailed("Generation failed the product slot validator")


def ours(study: dict, output: Path, credentials: Path) -> None:

    folder = output / "adaptation/ours"
    folder.mkdir(parents=True, exist_ok=False)
    home = folder / "data"
    imported = []
    started = time.monotonic()
    with Store(home) as store:
        service = ImportService(store)
        for task in study["tasks"]:
            if task["split"] != "history":
                continue
            # Each generated history folder exposes only its own sessions/ to the native connector.
            source = output / "history" / task["task_id"]
            result = service.import_source(ImportRequest("pi", source))
            imported.append(result)
            save(folder / "import.json", imported)
            if not result["files"] or result["capture_errors"] or result["skipped_files"] or result["cancelled"]:
                raise ValueError("Native Pi history import incomplete")
        verification = store.verify()
        save(folder / "verify.json", verification)
        if verification["integrity"] != "ok":
            raise ValueError("Canonical history integrity check failed")
    canonical = CanonicalStore(home)
    appdb = AppDB(home / "app.db")
    feature_service = FeatureService(home, appdb, lambda: {"data_rev": 1, "inventory_rev": 0})
    features.bind(feature_service)
    try:
        inputs = section.compute(canonical, Scope(), {}, ResultMemo())
        inputs["scope"] = asdict(Scope())
        inputs["scope_hash"] = object_digest(inputs["scope"])
        inputs["inventory"] = []  # The measured Pi configuration is intentionally clean.
        if inputs["sessions"]["main"] != 12 or set(inputs["agents"]) != {"pi"}:
            raise ValueError("Orbit analysis must contain exactly the 12 Pi history sessions")
        with appdb.read() as conn:
            rec_memory = memory(conn, int(time.time() * 1000), {"ai_generate": True})
        slate = build_slate(inputs, rec_memory, features=features)
        save(folder / "recommend-inputs.json", inputs)
        save(folder / "slate.json", slate)
        save(folder / "profile.json", features.profile(inputs["scope"]))
        assets = folder / "assets"
        assets.mkdir()
        manifest = {"instructions": [], "skills": [], "hooks": []}
        coverage = []
        for card in sorted(slate["candidates"], key=lambda c: (c.get("rank") or 10_000, c["rec_key"])):
            row = {"rec_key": card["rec_key"], "kind": card["kind"], "rank": card.get("rank"),
                   "status": "not_selected", "gates": card.get("gates")}
            coverage.append(row)
            if card.get("rank") is None or not card.get("gates", {}).get("passed"):
                continue
            kind = card["kind"]
            if kind == "model":
                row["status"] = "excluded_fixed_kimi_k3_max"
                continue
            if kind in ("permission_rule", "builtin"):
                row["status"] = "not_applicable_no_permission_prompts"
                continue
            if kind in ("workflow", "prompt"):
                if card.get("unfilled_slots"):
                    row["status"] = "unavailable_unfilled_product_slots"
                    row["unfilled_slots"] = card["unfilled_slots"]
                    continue
                text = "\n".join(line for line, _ in card.get("file") or [])
                if text:
                    manifest["instructions"].append(text)
                    row["status"] = f"{kind}_instruction"
                else:
                    row["status"] = "unavailable_empty_product_snippet"
                continue
            if kind == "generate":
                task_id = card["generate"]["task_id"]
                gen_kind = task_id.split(".")[1]
                spec = generation.TASKS[task_id]
                params = {"session_uids": card["evidence"]["session_uids"], "candidate": {
                    "evidence_session_uids": card["evidence"]["session_uids"],
                    "top_signal_event_uids": card["generate"].get("evidence_ids", [])}}
                pack = packs.build(spec, reads=canonical.connect, appdb=appdb, home=home, scope=inputs["scope"],
                                   goal=card["summary"], goal_source="candidate", params=params)
                gen_dir = folder / "generation" / str(card["rank"])
                ctx = GenerationContext(study, gen_dir, credentials, pack, params)
                save(gen_dir / "pack.json", pack)
                generated = spec["run"](ctx, pack)
                save(gen_dir / "artifact.json", generated)
                artifact = generated["artifact"]
                if artifact["status"] == "blocked":
                    row["status"] = "product_generation_blocked"
                    continue
                install_spec = {"id": artifact["name"], "kind": gen_kind,
                                "payload": _ai_payload(gen_kind, artifact["payload"], artifact["files"])}
            else:
                try:
                    install_spec = _kb_spec(card)
                except PlanError as error:
                    row["status"] = "unavailable_product_payload"
                    row["reason"] = str(error)
                    continue
            if install_spec is None:
                item_id = (card.get("source") or {}).get("item_id")
                if (card.get("source") or {}).get("origin") == "catalog" and item_id:
                    try:
                        install_spec, status = build_spec({"type": "catalog", "id": item_id},
                            appdb=appdb, cache_dir=folder / "resource-cache", allow_network=True)
                    except PlanError as error:
                        row.update(status="unavailable_product_catalog", reason=str(error))
                        continue
                    if status["status"] != "ready":
                        row.update(status="unavailable_" + status["status"], source=install_spec.get("source"))
                        continue
                    row["source"] = install_spec.get("source")
                else:
                    row["status"] = "unavailable_no_materialized_payload"
                    continue
            row["status"] = add_spec(assets, manifest, install_spec)
        save(assets / "manifest.json", manifest)
        save(folder / "coverage.json", coverage)
        save(folder / "summary.json", {"wall_time_seconds": time.monotonic() - started,
              "engine": slate["engine_version"], "status": slate["status"],
              "instructions": len(manifest["instructions"]), "skills": len(manifest["skills"]),
              "hooks": len(manifest["hooks"]), "catalog": "product bundled seeds; no personal catalog or feedback"})
    finally:
        features.bind(None)
        appdb.close()


def llm(study: dict, output: Path, credentials: Path) -> None:
    folder = output / "adaptation/llm"
    folder.mkdir(parents=True, exist_ok=False)
    prompt = study["llm_prompt"] + "\n\nReturn only a SKILL.md with YAML name and description frontmatter.\n\n"
    prompt += (output / "history_bundle.json").read_text()
    text = unfence(model_call(study, folder / "generation", "You distill reusable guidance from historical trajectories.",
                             prompt, credentials))
    assets = folder / "assets"
    assets.mkdir()
    manifest = {"instructions": [], "skills": [], "hooks": []}
    metadata = skill_metadata(text)
    add_spec(assets, manifest, {"kind": "skill", "payload": {"name": metadata["name"],
              "files": [{"rel": "SKILL.md", "text": text}]}})
    save(assets / "manifest.json", manifest)


def run(output: Path, credentials: Path) -> None:
    study = load_frozen(output)
    if (output / "test").exists():
        raise ValueError("Adaptation cannot read or follow held-out runs")
    bundle = read(output / "history_bundle.json")
    if object_digest(bundle) != read(output / "history_bundle.digest.json")["sha256"]:
        raise ValueError("History bundle changed")
    if len(bundle["histories"]) != 12:
        raise ValueError("Need all 12 histories including failures")
    for function, arm in ((ours, "ours"), (llm, "llm")):
        if not (output / "adaptation" / arm / "assets/manifest.json").exists():
            function(study, output, credentials)
    freeze = {"history_bundle_sha256": digest(output / "history_bundle.json"),
              "adapter_files": code_digests(), "arms": {
                  arm: tree(output / "adaptation" / arm / "assets") for arm in ("ours", "llm")}}
    save(output / "adaptation/frozen.json", freeze)
    (output / "adaptation/frozen.sha256").write_text(digest(output / "adaptation/frozen.json") + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--pi-config", type=Path, default=Path.home() / ".pi/agent")
    args = parser.parse_args()
    run(args.study.resolve(), args.pi_config.resolve())


if __name__ == "__main__":
    main()
