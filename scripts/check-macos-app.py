#!/usr/bin/env python3
"""Smoke-check a built Orbit.app's frozen tandem-helper (no GUI needed, CI friendly).

    python3 scripts/check-macos-app.py [--app .local/macos-build/Orbit.app]

Starts ``tandem-helper gateway`` against a fresh temporary home (HOME is redirected too, so
agent discovery never sees real sessions), then checks: the {"port": N} handshake, /app and
/lite served without a token with the page CSP, the API rejecting a missing token, /v1/status
with the token, an analytics section answered by a frozen analysis worker (no 500 /
ImportError) after a synthetic Codex import through the frozen ingest worker, and a graceful
shutdown on SIGTERM. Uses only the standard library (plus the repo's synthetic fixture writer).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_synthetic():
    """Load the stdlib-only synthetic Codex writer by file path, without touching sys.path
    (it lives with the backend service tests; the frozen app has no copy of it)."""
    import importlib.util

    path = ROOT / "packages/backend/tests/services/synthetic.py"
    spec = importlib.util.spec_from_file_location("tandem_synthetic_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


write_codex_tree = _load_synthetic().write_codex_tree


def request(url: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict, bytes]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def check(condition: bool, label: str, detail: object = "") -> None:
    print(("ok   " if condition else "FAIL ") + label + (f"  {detail}" if detail != "" else ""),
          flush=True)
    if not condition:
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=ROOT / ".local/macos-build/Orbit.app")
    parser.add_argument("--keep", action="store_true", help="keep the temporary home")
    args = parser.parse_args()
    resources = args.app / "Contents/Resources"
    helper = resources / "backend/tandem-helper"
    check(helper.is_file() and os.access(helper, os.X_OK), "helper executable", helper)
    check((resources / "orbit.html").is_file(), "bundled UI", resources / "orbit.html")

    temp = Path(tempfile.mkdtemp(prefix="orbit-check-"))
    home, user = temp / "tandem", temp / "user"
    user.mkdir()
    token = secrets.token_hex(32)
    env = {k: v for k, v in os.environ.items() if not k.endswith("_HOME")}
    env.update(HOME=str(user), TANDEM_HOME=str(home), TANDEM_API_TOKEN=token)
    log = (temp / "helper.log").open("w")
    started = time.monotonic()
    proc = subprocess.Popen([str(helper), "gateway", "--home", str(home), "--port", "0",
                             "--assets", str(resources / "orbit.html")],
                            stdout=subprocess.PIPE, stderr=log, env=env, text=True)
    try:
        line = proc.stdout.readline()
        check(line.startswith("{"), "handshake line", line.strip())
        base = f"http://127.0.0.1:{json.loads(line)['port']}"
        for _ in range(240):
            status, _, body = request(base + "/v1/status", token)
            if status == 200:
                break
            time.sleep(0.25)
        check(status == 200, "/v1/status with token", f"{time.monotonic() - started:.1f}s")
        print("     state:", json.loads(body)["state"])
        for page in ("/app", "/lite"):
            status, headers, body = request(base + page)
            csp = {k.lower(): v for k, v in headers.items()}.get("content-security-policy", "")
            check(status == 200 and b"<html" in body.lower(), f"{page} without token",
                  f"{len(body)} bytes")
            check("'unsafe-inline'" in csp and "connect-src 'self'" in csp, f"{page} CSP")
            check(b"fonts.googleapis" not in body, f"{page} has no remote font link")
        status, _, _ = request(base + "/v1/status")
        check(status == 401, "API without token is rejected", status)
        codex = temp / "agents/codex"
        write_codex_tree(codex, 6)
        status, _, body = request(base + "/v1/app/sources", token,
                                  {"agent": "codex", "root": str(codex)})
        check(status == 200, "enable synthetic codex source", status)
        source = json.loads(body)["id"]
        status, _, body = request(base + "/v1/app/jobs", token,
                                  {"kind": "import", "source_ids": [source]})
        check(status == 202, "submit import job", status)
        job = json.loads(body)["id"]
        for _ in range(480):
            _, _, body = request(f"{base}/v1/app/jobs/{job}", token)
            if json.loads(body)["status"] not in ("queued", "running"):
                break
            time.sleep(0.25)
        state = json.loads(body)
        check(state["status"] == "completed", "import via frozen ingest worker",
              f"{state['status']} {json.dumps(state.get('result') or state.get('error'))[:200]}")
        for _ in range(60):
            status, _, body = request(base + "/v1/analytics/overview?wait_ms=3000", token)
            if status != 202:
                break
        check(status == 200 and b"ImportError" not in body, "analytics via frozen analysis worker",
              f"{status} {body[:160]!r}")
        check(json.loads(body).get("overview") is not None, "overview computed")
        _, _, body = request(base + "/v1/status", token)
        services = json.loads(body)["services"]
        print("     services:", json.dumps(services))
        for role in ("ingest", "analysis"):
            check(services[role]["restarts"] == 0 and services[role]["state"] not in
                  ("failed", "crashed", "degraded"), f"{role} worker healthy", services[role]["state"])
        check(proc.poll() is None, "gateway still running")
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            code = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = "killed"
        log.close()
        print("     exit:", code)
        errors = [ln for ln in (temp / "helper.log").read_text().splitlines()
                  if "Error" in ln or "Traceback" in ln]
        for line in errors[:20]:
            print("     log:", line)
        if not args.keep:
            import shutil

            shutil.rmtree(temp, ignore_errors=True)
        else:
            print("     home:", temp)
    # uvicorn re-raises the captured SIGTERM after its graceful shutdown, hence -15.
    check(code in (0, -signal.SIGTERM), "graceful shutdown on SIGTERM", code)
    check(not any("ModuleNotFoundError" in ln or "ImportError" in ln for ln in errors),
          "no import errors in helper log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
