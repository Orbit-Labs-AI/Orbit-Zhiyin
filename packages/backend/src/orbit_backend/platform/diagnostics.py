"""Diagnostics bundle: a redacted, local zip the user can attach to a bug report.

Contains environment facts, health, job outcomes, revisions, metric summaries, storage and
the redacted log tail. Never session text, project names, prompts, environment variables
or absolute paths; source ids are referenced by a short hash.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform as pyplatform
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__
from . import logs, storage
from .health import health

SECRET_KEY = re.compile(r"token|key|secret|authorization|password", re.I)
PATH = re.compile(r"(?:~/|(?<![\w.~])/(?!v1/))(?:[^\s\"'/,;]+/)+[^\s\"',;]*")
# The import log's ``path`` field is relative to the source root, which PATH does not match;
# Claude Code's relative paths still spell the project folder (projects/-Users-<name>-<project>/).
PATH_FIELD = re.compile(r'("path"\s*:\s*")((?:[^"\\]|\\.)+)(")')
KEEP_EXPORTS = 5
LOG_BYTES = 1024 * 1024
README = """Orbit diagnostics bundle
=========================

Created locally by Orbit; nothing was uploaded. Share it only if you choose to.

diagnostics.json  app/OS version, hardware summary, settings (no secrets), health checks,
                  worker states, outcomes of the last 100 jobs (kind/status/duration/error
                  code), data revisions, schema versions, metric summaries, storage usage.
health.json       the health report on its own.
metrics.csv       local performance metrics of the last 24 hours (only if telemetry is on).
logs/orbit.log   the end of the local log (at most 1 MB), redacted.

Not included: session or conversation text, prompts, file contents, project names,
environment variables, tokens or keys. Paths under your home folder are shown as "~",
source folders only as short hashes.
"""


def _home_prefixes(platform) -> list[str]:
    prefixes = {str(Path.home()), str(platform.home)}
    return sorted(prefixes, key=len, reverse=True)


def redact_obj(obj, prefixes: list[str] | None = None):
    prefixes = prefixes if prefixes is not None else [str(Path.home())]
    if isinstance(obj, dict):
        return {k: "<redacted>" if isinstance(k, str) and SECRET_KEY.search(k) and v
                else redact_obj(v, prefixes) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [redact_obj(v, prefixes) for v in obj]
    if isinstance(obj, str):
        for prefix in prefixes:
            if prefix in obj:
                obj = obj.replace(prefix, "~")
        return logs.redact(obj)
    return obj


def scrub_paths(text: str) -> str:
    """Free-text log lines may name projects in paths: keep only a short hash."""
    text = PATH_FIELD.sub(lambda m: f"{m.group(1)}<path#{_short(m.group(2))}>{m.group(3)}", text)
    return PATH.sub(lambda m: f"<path#{_short(m.group(0))}>", text)


def _short(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:8]


def _jobs(gw) -> list[dict]:
    out = []
    state = getattr(gw, "state", None)
    for job in (state.jobs() if state is not None else [])[:100]:
        started, finished = job.get("started_at"), job.get("finished_at")
        error = job.get("error") or {}
        out.append({"kind": job.get("kind"), "status": job.get("status"),
                    "phase": job.get("phase"), "origin": job.get("origin"),
                    "created_at": job.get("created_at"),
                    "duration_ms": finished - started if started and finished else None,
                    "error_code": error.get("code") if isinstance(error, dict) else None,
                    "sources": [_short(str(s)) for s in job.get("source_ids") or []]})
    return out


def _memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def collect(platform) -> dict:
    gw = platform.gw
    with platform.appdb.read() as db:
        schema = {row[0]: {"sha256": row[1][:12], "applied_at": row[2]}
                  for row in db.execute("SELECT module, sha256, applied_at FROM module_schema")}
    revisions = gw.revisions.snapshot() if hasattr(gw, "revisions") else {}
    revisions = {k: revisions.get(k) for k in ("data_rev", "inventory_rev", "projection",
                                               "published_at")}
    body = {
        "generated_at": int(datetime.now(UTC).timestamp() * 1000),
        "app": {"version": __version__, "python": sys.version.split()[0],
                "macos": pyplatform.mac_ver()[0] or None, "system": pyplatform.system(),
                "arch": pyplatform.machine(), "cpus": os.cpu_count(),
                "memory_bytes": _memory_bytes(), "frozen": bool(getattr(sys, "frozen", False))},
        "home": str(platform.home),
        "settings": {"telemetry": platform.settings.get("telemetry"),
                     "flags": platform.settings.get("flags")},
        "health": health(platform),
        "jobs": _jobs(gw),
        "revisions": {**revisions, "platform": platform.revisions.snapshot()},
        "module_schema": schema,
        "metrics": platform.telemetry.query(None, 3600, "total")["series"]
        if platform.telemetry.enabled else [],
        "storage": storage.latest_report(platform.appdb),
        "log_tail": [scrub_paths(line) for line in logs.tail(platform.home, 200)],
    }
    return redact_obj(body, _home_prefixes(platform))


def _metrics_csv(platform) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["name", "tags", "count", "avg", "p50", "p95", "p99", "max"])
    if platform.telemetry.enabled:
        for s in platform.telemetry.query(None, 86_400, "total")["series"]:
            writer.writerow([s["name"], json.dumps(s["tags"], ensure_ascii=False), s["count"],
                             s["avg"], s["p50"], s["p95"], s["p99"], s["max"]])
    return out.getvalue()


def _log_text(platform, prefixes: list[str]) -> str:
    lines = logs.tail(platform.home, 100_000, max_bytes=LOG_BYTES)
    return "\n".join(scrub_paths(redact_obj(line, prefixes)) for line in lines) + "\n"


def prune_exports(home: Path, keep: int = KEEP_EXPORTS) -> int:
    directory = home / "exports"
    files = sorted(directory.glob("diagnostics-*.zip"), key=lambda p: p.stat().st_mtime,
                   reverse=True) if directory.is_dir() else []
    for old in files[keep:]:
        old.unlink(missing_ok=True)
    return max(0, len(files) - keep)


def export(platform) -> dict:
    prefixes = _home_prefixes(platform)
    body = collect(platform)
    directory = platform.home / "exports"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = directory / f"diagnostics-{stamp}.zip"
    entries = {
        "README.txt": README,
        "diagnostics.json": json.dumps(body, ensure_ascii=False, indent=2, default=str),
        "health.json": json.dumps(body["health"], ensure_ascii=False, indent=2, default=str),
        "metrics.csv": _metrics_csv(platform),
        "logs/orbit.log": _log_text(platform, prefixes),
    }
    partial = path.with_suffix(".zip.partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, text in entries.items():
            bundle.writestr(name, text)
    os.replace(partial, path)
    os.chmod(path, 0o600)
    data = path.read_bytes()
    prune_exports(platform.home)
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "files": list(entries)}
