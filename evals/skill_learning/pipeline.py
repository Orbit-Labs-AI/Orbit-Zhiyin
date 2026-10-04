"""Explicit native Pi sources through the real data, analytics, and recommendation APIs.

No model calls, installation, implicit source discovery, or catalog network sync.
Use one fresh output directory per selection; never mix held-out execution into history.
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient
from orbit_data.store import Store

from orbit_backend.services.gateway import Gateway
from orbit_backend.services.supervisor import SupervisorConfig

from .study import REPOSITORY, command, digest, read, save, tree


def response_json(response, expected=200):
    if response.status_code != expected:
        raise RuntimeError(f"API {response.request.url.path}: {response.status_code}: {response.text[:2000]}")
    return response.json()


def wait_for(fn, *, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result is not None:
            return result
        time.sleep(.2)
    raise TimeoutError("Pipeline stage did not complete")


def capture(sources: list[dict], output: Path, expected_sessions: int) -> dict:
    if expected_sessions < 1 or not sources or any(source.get("split") != "history" for source in sources):
        raise ValueError("Only explicitly selected history sources may enter this pipeline")
    if len({str(Path(source["root"]).resolve()) for source in sources}) != len(sources):
        raise ValueError("Duplicate history source")
    output.mkdir(parents=True, exist_ok=False)
    selection = [{**source, "files": tree(Path(source["root"]) / "sessions")} for source in sources]
    if any(not source["files"] for source in selection):
        raise ValueError("Each selected source must contain native Pi sessions")
    save(output / "selection.json", selection)
    os.environ["ORBIT_CATALOG_AUTOSYNC"] = "0"
    os.environ["ORBIT_INSTALL_HOME"] = str(output / "empty-install-home")
    token = "orbit-study-" + uuid.uuid4().hex
    gateway = Gateway(output / "data", discovery=lambda: [], prewarm_debounce_s=3600,
                      config=SupervisorConfig(light_timeout_s=120, heavy_timeout_s=240))
    gateway.platform.settings.put_flags({"maintenance": False, "notifications": False})
    started = time.monotonic()
    with TestClient(gateway.app(token=token, port=None), base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {token}"}) as client:
        source_ids = []
        for source in sources:
            configured = response_json(client.post("/v1/app/sources", json={
                "agent": "pi", "root": source["root"], "enabled": True}))
            source_ids.append(configured["id"])
        job = response_json(client.post("/v1/app/jobs", json={"kind": "import", "source_ids": source_ids}), 202)

        def import_done():
            current = response_json(client.get(f"/v1/app/jobs/{job['id']}"))
            return current if current["status"] not in ("queued", "running") else None

        imported = wait_for(import_done)
        save(output / "import-job.json", imported)
        if imported["status"] != "completed":
            raise ValueError("Native import did not complete; see import-job.json")
        storage = response_json(client.get("/v1/app/storage"))
        save(output / "storage.json", storage)
        if storage["tables"]["session"] != expected_sessions:
            raise ValueError("Imported session count differs from the explicit selection")

        def catalog_ready():
            status = response_json(client.get("/v1/catalog/status"))
            return status if status["first_sync"]["state"] != "pending" else None

        save(output / "catalog-status.json", wait_for(catalog_ready))

        def recommendations_ready():
            response = client.get("/v1/recommendations", params={"wait_ms": 3000, "include_gated": "true"})
            if response.status_code == 202:
                return None
            body = response_json(response)
            return body if body.get("run") else None

        recommendations = wait_for(recommendations_ready, timeout=300)
        save(output / "recommendations.json", recommendations)
        run_id = recommendations["run"]["run_id"]
        funnel = response_json(client.get(f"/v1/recommendations/runs/{run_id}/funnel"))
        save(output / "funnel.json", funnel)
        if funnel["status"] != "ready":
            raise ValueError("Recommendation funnel was not persisted")
        if funnel["funnel"]["upstream"]["history_ingestion"]["sessions"]["main"] != expected_sessions:
            raise ValueError("Analytics did not cover every selected history session")
    with Store(output / "data") as store:
        verified = store.verify()
    save(output / "verify.json", verified)
    if verified["integrity"] != "ok":
        raise ValueError("Canonical integrity check failed")
    if any(tree(Path(source["root"]) / "sessions") != source["files"] for source in selection):
        raise ValueError("History changed during import; preserve this attempt and select immutable inputs")
    summary = {"code_commit": command(["git", "-C", REPOSITORY, "rev-parse", "HEAD"]),
               "pipeline_sha256": digest(Path(__file__)),
               "working_tree_dirty": bool(command(["git", "-C", REPOSITORY, "status", "--porcelain"])),
               "status": "passed", "history_sessions": expected_sessions,
               "run_id": run_id, "engine_version": recommendations["run"]["engine_version"],
               "selected_kinds": dict(Counter(c["kind"] for c in recommendations["items"] if c.get("rank"))),
               "api_chain": ["source_selection", "native_import_job", "canonical_storage",
                             "analytics_worker", "recommendation_run", "persisted_funnel"],
               "model_calls": 0, "elapsed_seconds": round(time.monotonic() - started, 3)}
    save(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sessions", type=int, required=True)
    args = parser.parse_args()
    print(capture(read(args.selection), args.output, args.expected_sessions), flush=True)


if __name__ == "__main__":
    main()
