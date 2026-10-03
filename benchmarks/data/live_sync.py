"""Live-sync import probe on synthetic sources: what an import does while agents keep writing.

    uv run python -m benchmarks.data.live_sync --preset med --minutes 8 --output .local/benchmarks/live-sync.json

Generates fictional Claude Code / pi / DSH sources (``synthetic.py``), a Codex root with a
``state_5.sqlite`` index, and one Claude subagent whose parent transcript is missing (the
shape that disabled session closures in v0.0.2). Starts the source gateway on a temporary
``TANDEM_HOME``, enables every source, turns on ``sync_mode=live`` and starts the
onboarding import; meanwhile one thread appends to a Claude transcript every 2 s and one
updates a Codex ``threads`` row every second, and a reader polls ``/v1/sessions`` and
``/v1/status`` once per second. The JSON report counts, per job, how often each stage
started (``reset_projection`` = rebuild attempts), the projection scope, the duration, the
read answers (503 / stale / fresh), the WAL size and leftover spill directories
(docs/development/import-pipeline.md §8). Nothing reads the local agent directories.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from benchmarks.analytics.synthetic import write_codex_sources

from .synthetic import generate


def build_sources(out: Path, preset: str, codex_sessions: int) -> dict[str, Path]:
    generate(out / "gen", preset)
    src = out / "gen" / "sources"
    roots = {"claude_code": src / "claude_code", "pi": src / "pi", "dsh": src / "dsh"}
    for sub in sorted(roots["claude_code"].glob("projects/*/*/subagents")):
        parent = sub.parent.with_suffix(".jsonl")
        if parent.exists():
            parent.unlink()  # The subagent's parent session is gone (cleaned up upstream).
            break
    staging = out / "codex-staging"
    write_codex_sources(staging, codex_sessions, 7)
    codex = out / "codex"
    (codex / "sessions").mkdir(parents=True)
    for root in sorted(staging.glob("source-*")):
        for path in sorted((root / "sessions").glob("*.jsonl")):
            shutil.move(str(path), codex / "sessions" / path.name)
    shutil.rmtree(staging)
    now = int(time.time())
    with sqlite3.connect(codex / "state_5.sqlite") as db:
        db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, "
                   "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, source TEXT NOT NULL, "
                   "model_provider TEXT NOT NULL, cwd TEXT NOT NULL, title TEXT NOT NULL, "
                   "archived INTEGER NOT NULL DEFAULT 0, model TEXT)")
        for path in sorted((codex / "sessions").glob("*.jsonl")):
            db.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,0,?)",
                       (path.stem, str(path), now - 3600, now - 60, "cli", "synthetic",
                        "/synthetic/project", f"Synthetic thread {path.stem}", "synthetic-model"))
    roots["codex"] = codex
    return roots


class Gateway:
    def __init__(self, home: Path, log: Path):
        self.token = secrets.token_hex(24)
        env = {**os.environ, "TANDEM_API_TOKEN": self.token}
        env.pop("TANDEM_HOME", None)
        self.log = log.open("ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tandem_backend.services", "gateway", "--home", str(home),
             "--port", "0"], stdout=subprocess.PIPE, stderr=self.log, env=env)
        self.port = json.loads(self.proc.stdout.readline())["port"]

    def call(self, method: str, path: str, body=None, timeout: float = 60):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return response.status, dict(response.headers), json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, dict(error.headers), json.loads(raw) if raw else None
            except ValueError:
                return error.code, dict(error.headers), None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            return 0, {}, {"error": {"code": type(error).__name__}}

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()


def follow_events(gw: Gateway, frames: list, stop: threading.Event, started: float) -> None:
    request = urllib.request.Request(f"http://127.0.0.1:{gw.port}/v1/events?topics=job,data",
                                     headers={"Authorization": f"Bearer {gw.token}"})
    while not stop.is_set():
        try:
            with urllib.request.urlopen(request) as stream:
                event, data = None, []
                for raw in stream:
                    if stop.is_set():
                        return
                    line = raw.decode(errors="replace").rstrip("\n")
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].strip())
                    elif not line:
                        if event and data:
                            frames.append({"t": round(time.monotonic() - started, 2),
                                           "event": event, "data": json.loads("\n".join(data))})
                        event, data = None, []
        except (urllib.error.URLError, ConnectionError, ValueError):
            stop.wait(1)


def poll_reads(gw: Gateway, home: Path, reads: list, stop: threading.Event) -> None:
    while not stop.is_set():
        status, headers, body = gw.call("GET", "/v1/sessions?limit=1", timeout=30)
        _, _, state = gw.call("GET", "/v1/status", timeout=30)
        wal = home / "tandem.db-wal"
        reads.append({
            "status": status,
            "code": (body or {}).get("error", {}).get("code") if isinstance(body, dict) else None,
            "freshness": headers.get("x-tandem-freshness") or headers.get("X-Tandem-Freshness"),
            "projection": state.get("projection") if isinstance(state, dict) else None,
            "wal": wal.stat().st_size if wal.exists() else 0})
        stop.wait(1.0)


def append_claude(root: Path, stop: threading.Event) -> None:
    target = sorted(root.glob("projects/*/*.jsonl"))[-1]
    template = next(json.loads(line) for line in reversed(target.read_text().splitlines())
                    if line.strip() and json.loads(line).get("uuid"))
    parent = template["uuid"]
    while not stop.wait(2.0):
        row = {**template, "uuid": str(uuid.uuid4()), "parentUuid": parent,
               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}
        parent = row["uuid"]
        with target.open("a") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def update_codex(root: Path, stop: threading.Event) -> None:
    while not stop.wait(1.0):
        try:
            with sqlite3.connect(root / "state_5.sqlite", timeout=5) as db:
                db.execute("UPDATE threads SET updated_at=updated_at+1 WHERE id=(SELECT id FROM "
                           "threads ORDER BY updated_at DESC LIMIT 1)")
        except sqlite3.Error:
            pass


def summarize(frames: list, reads: list, jobs: list, home: Path) -> dict:
    per: dict[str, dict] = collections.OrderedDict()
    for frame in frames:
        if frame["event"] != "job":
            continue
        data = frame["data"]
        job = per.setdefault(data["id"], {"entries": collections.Counter(), "last": None,
                                          "scopes": collections.Counter(), "attempts": 0})
        progress = data.get("progress") or {}
        stage = progress.get("stage")
        if stage and stage != job["last"]:
            job["entries"][stage] += 1
            if stage == "reset_projection" and progress.get("scope"):
                job["scopes"][progress["scope"]] += 1
        job["last"] = stage or job["last"]
        job["attempts"] = max(job["attempts"], progress.get("attempt") or 0)
    report = []
    for job in sorted(jobs, key=lambda j: j["created_at"]):
        seen = per.get(job["id"], {"entries": {}, "scopes": {}, "attempts": 0})
        took = ((job["finished_at"] - job["started_at"]) / 1000
                if job.get("finished_at") and job.get("started_at") else None)
        report.append({"origin": job["origin"], "status": job["status"], "seconds": took,
                       "captures": seen["entries"].get("capture", 0),
                       "rebuild_attempts": seen["entries"].get("reset_projection", 0),
                       "scopes": dict(seen["scopes"]), "max_attempt": seen["attempts"]})
    sync = [j for j in report if j["origin"] == "sync" and j["seconds"] is not None]
    codes = collections.Counter(f"{r['status']}:{r['code'] or r['freshness']}" for r in reads)
    wal = home / "tandem.db-wal"
    return {
        "jobs": report,
        "sync_jobs": len(sync),
        "sync_median_seconds": sorted(j["seconds"] for j in sync)[len(sync) // 2] if sync else None,
        "sync_rebuild_attempts": [j["rebuild_attempts"] for j in sync],
        "partial_jobs": sum(j["status"] == "partial" for j in report),
        "reads": dict(codes), "reads_total": len(reads),
        "projection_states": dict(collections.Counter(r["projection"] for r in reads)),
        "wal_max_mb": round(max((r["wal"] for r in reads), default=0) / 2**20, 1),
        "wal_end_mb": round((wal.stat().st_size if wal.exists() else 0) / 2**20, 1),
        "spill_dirs_left": sorted(p.name for p in home.glob("import-*")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preset", default="med", choices=("small", "med", "full"))
    parser.add_argument("--codex-sessions", type=int, default=300)
    parser.add_argument("--minutes", type=float, default=8.0)
    parser.add_argument("--recent-days", type=int, default=90)
    parser.add_argument("--work", type=Path, default=None, help="kept work directory")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    work = args.work or Path(tempfile.mkdtemp(prefix="tandem-live-sync-"))
    try:
        roots = build_sources(work / "sources", args.preset, args.codex_sessions)
        home = work / "home"
        gw = Gateway(home, work / "gateway.log")
        frames, reads, stop = [], [], threading.Event()
        started = time.monotonic()
        threads = [threading.Thread(target=follow_events, args=(gw, frames, stop, started), daemon=True),
                   threading.Thread(target=poll_reads, args=(gw, home, reads, stop), daemon=True)]
        try:
            ids = [gw.call("POST", "/v1/app/sources", {"agent": agent, "root": str(root)})[2]["id"]
                   for agent, root in roots.items()]
            gw.call("PATCH", "/v1/app/settings", {"sync_mode": "live", "onboarded": True,
                                                  "recent_days": args.recent_days})
            for thread in threads:
                thread.start()
            gw.call("POST", "/v1/app/jobs", {"kind": "import", "source_ids": ids})
            writers = [threading.Thread(target=append_claude, args=(roots["claude_code"], stop), daemon=True),
                       threading.Thread(target=update_codex, args=(roots["codex"], stop), daemon=True)]
            for thread in writers:
                thread.start()
            time.sleep(args.minutes * 60)
            jobs = gw.call("GET", "/v1/app/jobs?limit=100")[2] or []
        finally:
            stop.set()
            gw.stop()
        report = {"preset": args.preset, "codex_sessions": args.codex_sessions,
                  "minutes": args.minutes, **summarize(frames, reads, jobs, home)}
    finally:
        if args.work is None:
            shutil.rmtree(work, ignore_errors=True)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
