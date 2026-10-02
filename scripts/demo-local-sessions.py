"""Explicitly authorized local acceptance through the same API used by the Mac App."""

import argparse
import json
import secrets
import time
from pathlib import Path

from fastapi.testclient import TestClient
from tandem_data.discovery import inputs
from tandem_data.store import Store

from tandem_backend.app_api import create_desktop_app

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real",
        action="store_true",
        required=True,
        help="Explicit authorization to read local session samples",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="An ignored/private directory outside every Agent source root",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_hex(32)
    app = create_desktop_app(output / "data", token, ROOT / "prototypes/advance/tandem-demo.html")
    results, used, selected, ids = [], set(), {}, []
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        sources = client.get("/v1/app/discovery").json()["items"]
        for source in sources:
            agent = source["agent"]
            if agent in used:
                continue
            root = Path(source["root"])
            files = [
                i.path
                for i in inputs(agent, root)
                if i.role == "transcript"
                and i.path.stat().st_size <= 16 * 1024 * 1024
                and i.path.stat().st_mtime < time.time() - 120
            ]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            if not files:
                continue
            response = client.post("/v1/app/sources", json={"agent": agent, "root": str(root)})
            response.raise_for_status()
            key = response.json()["id"]
            ids.append(key)
            selected[key] = [str(p) for p in files[:2]]
            used.add(agent)
        response = client.post(
            "/v1/app/jobs", json={"source_ids": ids, "files_by_source": selected}
        )
        response.raise_for_status()
        job = response.json()
        deadline = time.monotonic() + 600
        last = None
        while job["status"] in ("queued", "running"):
            if time.monotonic() > deadline:
                client.post("/v1/app/jobs/" + job["id"] + "/cancel")
                raise TimeoutError("Local sample import exceeded ten minutes")
            time.sleep(0.5)
            job = client.get("/v1/app/jobs/" + job["id"]).json()
            progress = job.get("progress", {})
            label = (progress.get("agent"), progress.get("stage"), progress.get("completed"))
            if label != last:
                print(json.dumps({"status": job["status"], "progress": progress}), flush=True)
                last = label
        state = client.get("/v1/app/state").json()
        client.patch("/v1/app/settings", json={"onboarded": True, "recent_days": 0})
        with Store(output / "data") as storage:
            verification = storage.verify()
            for row in storage.db.execute(
                "SELECT s.agent,s.source_id,COUNT(DISTINCT e.event_uid) AS events,COUNT(DISTINCT e.session_uid) AS sessions FROM source s LEFT JOIN session t USING(source_id) LEFT JOIN event e USING(session_uid) GROUP BY s.source_id"
            ):
                results.append(dict(row))
        report = {
            "boundary": "Explicit local samples: up to two primary transcripts per Agent, <=16 MiB each, idle for >=120 seconds. Not a full import.",
            "job": job,
            "storage": state["storage"],
            "sources": results,
            "verification": verification,
            "unavailable": sorted(
                set(("codex", "claude_code", "dsh", "pi", "hermes", "opencode", "kimi")) - used
            ),
        }
        path = output / "results.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        path.chmod(0o600)
        print(
            json.dumps(
                {
                    "status": job["status"],
                    "sources": results,
                    "verification": verification,
                    "report": str(path),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
