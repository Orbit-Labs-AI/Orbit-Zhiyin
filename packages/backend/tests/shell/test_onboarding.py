"""GET /v1/shell/onboarding over a synthetic Codex tree and a real gateway import."""

from __future__ import annotations

import math
import time

from synthetic import write_codex_tree

FILES = 40


def wait_for(predicate, timeout: float, interval: float, message: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {message}")


def test_estimates_then_import_progress(gateway_factory, tmp_path):
    root = tmp_path / "agents" / "codex"
    written = write_codex_tree(root, FILES)
    discovered = [{"agent": "codex", "root": str(root)}]
    client, _ = gateway_factory(discovery=lambda: discovered)

    before = client.get("/v1/shell/onboarding").json()
    assert before["state"] == "onboarding"
    assert before["settings"] == {"onboarded": False, "onboarding_step": 0,
                                  "recent_days": 90}
    (source,) = before["sources"]
    assert source["est_sessions"] == FILES == source["files"] and source["estimate"] is True
    assert source["status"] == "available" and source["enabled"] is False
    mtimes = [int(p.stat().st_mtime * 1000) for p in written]
    assert (source["earliest_mtime"], source["latest_mtime"]) == (min(mtimes), max(mtimes))
    assert before["totals"] == {"files": FILES, "est_sessions": FILES}
    stages = {s["id"]: s for s in before["progress"]["stages"]}
    assert list(stages) == ["backfill", "stats", "semantic", "persona"]
    assert stages["backfill"]["status"] == "pending" and before["progress"]["job_id"] is None
    assert before["semantic"]["enabled"] is False and before["semantic"]["mode"] == "stats"
    assert stages["semantic"]["status"] == "skipped"
    assert before["persona"] is None and before["recs"] is None

    configured = client.post("/v1/app/sources", json={"agent": "codex", "root": str(root)})
    assert configured.status_code == 200
    job = client.post("/v1/app/jobs", json={"kind": "import",
                                            "source_ids": [source["id"]]}).json()
    seen: list[tuple] = []

    def finished():
        body = client.get("/v1/shell/onboarding").json()
        stage = body["progress"]["stages"][0]
        if stage["done"] is not None:
            seen.append((stage["note"], stage["done"], stage["total"]))
        return body if stage["status"] in ("done", "error") else None

    after = wait_for(finished, timeout=90, interval=0.02, message="import done")
    assert after["progress"]["job_id"] == job["id"]
    backfill = after["progress"]["stages"][0]
    assert backfill["status"] == "done" and backfill["done"] == backfill["total"]
    # Counters restart per import stage (prepare, map, …) and only grow within one.
    for note in {n for n, _, _ in seen}:
        done = [d for n, d, _ in seen if n == note]
        assert done == sorted(done), note
    assert any(total for _, _, total in seen)
    assert after["state"] == "ready"
    assert after["sources"][0]["enabled"] is True

    semantic = {s["id"]: s for s in after["progress"]["stages"]}["semantic"]
    assert after["semantic"]["enabled"] is False  # Stats mode: no model calls.
    assert semantic["status"] == "skipped" and semantic["total"] > 0
    assert after["semantic"]["est_calls"] == math.ceil(semantic["total"] / 8)
    persona = {s["id"]: s for s in after["progress"]["stages"]}["persona"]
    assert persona["status"] in ("skipped", "running", "done")
