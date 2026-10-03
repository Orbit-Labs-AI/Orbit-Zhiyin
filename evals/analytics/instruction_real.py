"""Opt-in real-data E2E: reparse an existing frozen ledger, CLI, live localhost API.

All derived records stay in the supplied local output directory. The source ledger
is opened read-only. This is operational validation, not an independent quality label.
"""

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

from orbit_backend.analytics.instruction import instruction_text
from orbit_backend.models import stable_id


def validate(source_ledger, codex_home, output):
    if not source_ledger.is_file():
        raise ValueError("An existing frozen source ledger is required")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "real.sqlite"
    if target.resolve() == source_ledger.resolve() or target.exists():
        raise ValueError("Use a fresh output directory; do not overwrite an existing ledger")
    with sqlite3.connect(source_ledger.resolve().as_uri() + "?mode=ro", uri=True) as source:
        policies = source.execute("SELECT source_root,data FROM sample_policies ORDER BY source_root").fetchall()
        policy = next((json.loads(data) for root, data in policies if Path(root).resolve() == codex_home.resolve()), None)
        if not policy or not policy.get("before"):
            raise ValueError("A matching existing snapshot cutoff is required")
        with sqlite3.connect(target) as destination:
            source.backup(destination)
            # Force the ordinary importer to actually reparse native files.
            destination.execute("UPDATE imports SET signature='instruction-e2e-reparse'")
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "packages/backend/src")}
    timings = {}

    def command(name, *args):
        start = time.perf_counter()
        result = subprocess.run([sys.executable, "-m", "orbit_backend", "--db", str(target), *args],
                                env=environment, capture_output=True, text=True, check=True, timeout=180)
        timings[name] = round(time.perf_counter() - start, 4)
        (output / (name + ".log")).write_text(result.stdout + result.stderr)
        return result.stdout

    imported = json.loads(command("import", "import", "--codex-home", str(codex_home)))
    assert imported["import"]["imported"] > 0
    assert imported["import"]["sample_policy"] == policy
    result_path = output / "analytics.json"
    command("cli", "analytics", "--display-timezone", "Asia/Shanghai", "--no-text",
            "--output", str(result_path))
    result = json.loads(result_path.read_text())
    family = result["instruction"]
    with sqlite3.connect(target) as conn:
        events = {row[0]: json.loads(row[1]) for row in conn.execute("SELECT id,data FROM events")}
        sessions = {row[0]: json.loads(row[1]) for row in conn.execute("SELECT id,data FROM sessions")}
    assert family["records"], "No confirmed human messages in this snapshot"
    assert family["summary"]["message_n"] == result["effective_samples"]["human_messages"]
    for record in family["records"]:
        source_event = events[record["event_uid"]]
        assert source_event["details"]["origin"] == "human"
        assert sessions[record["session_uid"]]["analytics_metadata"]["kind"] == "main"
        assert record["session_uid"] not in policy["exclude"]
        normalized = instruction_text(source_event["text"])
        for constraint in record["constraints"]:
            assert constraint["text"] in normalized
            assert constraint["event_uid"] == record["event_uid"]
    # Pre-bind an ephemeral loopback port and pass the socket to uvicorn, avoiding a race.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    child_code = ("import sys,uvicorn; from orbit_backend.api import create_app; "
                  "uvicorn.run(create_app(sys.argv[1]), fd=int(sys.argv[2]), log_level='error')")
    with (output / "api.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-c", child_code, str(target), str(listener.fileno())],
                                  env=environment, pass_fds=(listener.fileno(),), stdout=log, stderr=log)
        listener.close()
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        client.get("/health").raise_for_status()
                        break
                    except (httpx.HTTPError, OSError):
                        if time.monotonic() >= deadline or server.poll() is not None:
                            raise RuntimeError("Local API did not become healthy") from None
                        time.sleep(.05)
                start = time.perf_counter()
                response = client.get("/v1/analytics/instruction", params={"display_timezone": "Asia/Shanghai"})
                response.raise_for_status()
                timings["http_instruction"] = round(time.perf_counter() - start, 4)
                assert response.json()["instruction"] == family
                sid = family["records"][0]["session_uid"]
                detail = client.get(f"/v1/analytics/sessions/{sid}")
                detail.raise_for_status()
                expected = next(s["instruction"] for s in result["sessions"] if s["session_uid"] == sid)
                assert detail.json()["session"]["instruction"] == expected
                excluded = client.get("/v1/analytics/instruction", params={"excluded_session_uids": sid})
                excluded.raise_for_status()
                assert all(r["session_uid"] != sid for r in excluded.json()["instruction"]["records"])
                bounded = client.get("/v1/analytics/instruction", params={"until_ts": 1})
                bounded.raise_for_status()
                assert bounded.json()["instruction"]["summary"]["message_n"] == 0
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    summary = {
        "status": "passed", "snapshot_before_utc": policy["before"],
        "excluded_sessions": len(policy["exclude"]), "sample_policy_unchanged": True,
        "source_ledger_read_only": True,
        "source_counts": imported["stored"],
        "reparsed_sessions": imported["import"]["imported"],
        "instruction": family["summary"], "timings_seconds": timings,
        "checked": ["native reimport", "SQLite provenance", "CLI JSON", "live HTTP API",
                    "session detail", "session exclusion", "time boundary"],
        "sample_digest": stable_id(sorted(events)),
         "positive_real_messages": family["summary"]["effective_n"],
        "limitation": "Operational/evidence integrity checks only; no independent human quality labels",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ledger", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.source_ledger, args.codex_home, args.output)
