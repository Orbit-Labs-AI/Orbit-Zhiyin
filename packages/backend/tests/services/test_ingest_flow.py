"""Phased import through the ingest worker, SSE delivery and reads during import."""

from __future__ import annotations

import statistics
import threading
import time

from conftest import SESSIONS, SSEReader, add_codex, fast_config, run_job, wait_for, wait_job


def _p99(values):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]


def test_phased_import_publishes_batches_over_sse_with_resume(live_server, codex_root):
    server = live_server(fast_config())
    reader = SSEReader(server.base, topics="job,data")
    with server.client() as http:
        source = add_codex(http, codex_root)
        job = run_job(http, "import", [source], phase="auto")
        done = wait_job(http, job["id"])
        assert done["status"] == "completed", done
        assert [r["phase"] for r in done["results"]] == ["head", "window", "rest"]
        assert [p["phase"] for p in done["published"]] == ["head", "window", "rest"]
        revs = [p["data_rev"] for p in done["published"]]
        assert revs == sorted(set(revs)) and len(revs) == 3
        assert done["published"][0]["counts"]["sessions"] == 50
        assert done["published"][-1]["counts"]["sessions"] == SESSIONS
        status = http.get("/v1/status").json()
        assert status["state"] == "ready" and status["data_rev"] == revs[-1]
        assert status["counts"]["sessions"] == SESSIONS
        page = http.get("/v1/sessions", params={"limit": 10})
        assert page.status_code == 200 and len(page.json()) == 10
        assert page.headers["x-total-count"] == str(SESSIONS)

    wait_for(lambda: len(reader.events("data.published")) >= 3, 10, message="published frames")
    published = reader.events("data.published")
    assert [f["data"]["phase"] for f in published] == ["head", "window", "rest"]
    assert [f["data"]["data_rev"] for f in published] == revs
    statuses = [f["data"]["status"] for f in reader.events("job")]
    assert statuses[0] == "queued" and "running" in statuses and statuses[-1] == "completed"
    reader.close()

    # Resume from the first frame: every later frame arrives once, in order, no gaps.
    first, seen = reader.frames[0]["id"], [f["id"] for f in reader.frames]
    assert seen[-1] < 1000  # Progress is coalesced; one import does not flood the buffer.
    resumed = SSEReader(server.base, topics="job,data", last_event_id=first)
    wait_for(lambda: [f.get("id") for f in resumed.frames] == seen[1:], 10,
             message=f"resume {first} {seen} {resumed.frames[:3]}")
    resumed.close()


def test_concurrent_reads_during_import_never_fail(live_server, codex_root):
    server = live_server(fast_config(plan={"rest_chunk": 2}))
    with server.client() as http:
        source = add_codex(http, codex_root)
        first = run_job(http, "import", [source], phase="head")
        assert wait_job(http, first["id"])["status"] == "completed"

    def read(client, results, durations):
        started = time.perf_counter()
        response = client.get("/v1/sessions", params={"limit": 50})
        durations.append(time.perf_counter() - started)
        results.append((response.status_code, response.headers.get("retry-after"),
                        response.headers.get("x-tandem-freshness")))

    def burst(count, results, durations):
        threads = []
        with server.client(limits=__import__("httpx").Limits(max_connections=32)) as client:
            for _ in range(count):
                thread = threading.Thread(target=read, args=(client, results, durations))
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join()

    baseline, baseline_ms = [], []
    burst(100, baseline, baseline_ms)
    assert {code for code, *_ in baseline} == {200}

    with server.client() as http:
        job = run_job(http, "import", [source], phase="auto")
        during, during_ms, rounds = [], [], 0
        while rounds < 3 or http.get(f"/v1/app/jobs/{job['id']}").json()["status"] in (
                "queued", "running"):
            burst(100, during, during_ms)
            rounds += 1
        done = wait_job(http, job["id"])
    assert done["status"] == "completed"
    assert len(done["published"]) >= 2  # window plus several rest chunks.
    codes = {code for code, *_ in during}
    assert codes <= {200, 503}, codes
    assert all(retry for code, retry, _ in during if code == 503)
    assert len(during) >= 300
    base_p99, during_p99 = _p99(baseline_ms), _p99(during_ms)
    # Reads share no lock with the writer: p99 stays in the same range as before import.
    assert during_p99 <= max(3 * base_p99, base_p99 + 0.25), (base_p99, during_p99,
                                                              statistics.median(during_ms))
