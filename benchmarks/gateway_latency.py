"""Gateway latency on synthetic Codex sessions (never reads real agent homes).

Starts a real gateway (uvicorn on 127.0.0.1, both workers as subprocesses) over a
temporary directory, imports N synthetic sessions through the phased ingest job, then
measures p50/p95 of: /v1/status, a direct session page, a cached analytics snapshot
and a 304 revalidation. Thresholds are the p95 budgets of app-services.md §4.5.

    uv run python -m benchmarks.gateway_latency --sessions 300 --repeats 200
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import socket
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from orbit_backend.services.gateway import Gateway

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "benchmark-token-0123456789abcdefghij"
THRESHOLDS_MS = {"status": 20, "session_page": 30, "snapshot_hit": 100, "not_modified": 5}


def _synthetic():
    path = ROOT / "packages/backend/tests/services/synthetic.py"
    spec = importlib.util.spec_from_file_location("orbit_synthetic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _percentiles(samples: list[float]) -> dict:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {"p50": round(statistics.median(ordered), 3), "p95": round(p95, 3),
            "max": round(ordered[-1], 3), "n": len(ordered)}


def _measure(http: httpx.Client, repeats: int, path: str, *, expect: int = 200,
             **kwargs) -> list[float]:
    http.get(path, **kwargs)  # warm route and connection
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        response = http.get(path, **kwargs)
        samples.append((time.perf_counter() - started) * 1000)
        if response.status_code != expect:
            raise RuntimeError(f"{path} returned {response.status_code}: {response.text[:200]}")
    return samples


def run(sessions: int, repeats: int, directory: Path) -> dict:
    root = directory / "agents" / "codex"
    _synthetic().write_codex_tree(root, sessions, spacing_hours=3)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    gateway = Gateway(directory / "home", discovery=lambda: [], prewarm_debounce_s=3600)
    server = uvicorn.Server(uvicorn.Config(gateway.app(token=TOKEN, port=port),
                                           log_level="warning", access_log=False,
                                           timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    results: dict = {}
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=300,
                          headers={"Authorization": f"Bearer {TOKEN}"}) as http:
            results["status_no_db"] = _percentiles(_measure(http, repeats, "/v1/status"))
            source = http.post("/v1/app/sources", json={"agent": "codex", "root": str(root)})
            started = time.perf_counter()
            job = http.post("/v1/app/jobs", json={"kind": "import",
                                                  "source_ids": [source.json()["id"]]}).json()
            first_publish = None
            while True:
                job = http.get(f"/v1/app/jobs/{job['id']}").json()
                if first_publish is None and job.get("published"):
                    first_publish = time.perf_counter() - started
                if job["status"] not in ("queued", "running"):
                    break
                time.sleep(0.1)
            if job["status"] != "completed":
                raise RuntimeError(f"import ended {job['status']}: {job.get('error')}")
            results["import"] = {"seconds": round(time.perf_counter() - started, 3),
                                 "first_publish_seconds": round(first_publish or 0, 3),
                                 "batches": [p["phase"] for p in job["published"]]}
            results["status"] = _percentiles(_measure(http, repeats, "/v1/status"))
            results["session_page"] = _percentiles(
                _measure(http, repeats, "/v1/sessions", params={"limit": 50}))
            results["event_page"] = _percentiles(_measure(
                http, repeats,
                f"/v1/sessions/{http.get('/v1/sessions', params={'limit': 1}).json()[0]['id']}"
                "/events", params={"limit": 100}))
            started = time.perf_counter()
            while (response := http.get("/v1/analytics/overview",
                                        params={"wait_ms": 3000})).status_code == 202:
                pass
            results["overview_cold_seconds"] = round(time.perf_counter() - started, 3)
            results["snapshot_hit"] = _percentiles(_measure(http, repeats,
                                                            "/v1/analytics/overview"))
            tag = response.headers["etag"]
            results["not_modified"] = _percentiles(_measure(
                http, repeats, "/v1/analytics/overview", expect=304,
                headers={"If-None-Match": tag}))
            while http.get("/v1/analytics/sessions", params={"limit": 50, "wait_ms": 3000}
                           ).status_code == 202:
                pass
            results["analytics_session_page"] = _percentiles(_measure(
                http, repeats, "/v1/analytics/sessions", params={"limit": 50}))
    finally:
        gateway.bus.close()
        server.should_exit = True
        thread.join(30)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sessions", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=200)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", help="exit 1 when a p95 budget fails")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="orbit-gateway-bench-") as directory:
        results = run(args.sessions, args.repeats, Path(directory))
    checks = {name: {"p95_ms": results[name]["p95"], "budget_ms": budget,
                     "ok": results[name]["p95"] <= budget}
              for name, budget in THRESHOLDS_MS.items()}
    report = {"benchmark": "gateway_latency", "sessions": args.sessions,
              "repeats": args.repeats, "python": platform.python_version(),
              "machine": platform.machine(), "platform": platform.platform(),
              "timing": "client wall time over loopback HTTP keep-alive, ms",
              "results": results, "budgets": checks}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    return 1 if args.strict and not all(c["ok"] for c in checks.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
