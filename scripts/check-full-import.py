"""Explicit full local acceptance: all discovered roots, no sample or size filters."""

import argparse
import json
import secrets
import time
from pathlib import Path

from fastapi.testclient import TestClient
from tandem_data.discovery import inputs
from tandem_data.store import Store, readonly_connection

from tandem_backend.app_api import create_desktop_app

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    path.chmod(0o600)


def wait_job(client, response, report, output, label):
    response.raise_for_status()
    job = response.json()
    last, last_print = None, 0
    while job["status"] in ("queued", "running"):
        time.sleep(1)
        job = client.get("/v1/app/jobs/" + job["id"]).json()
        progress = job.get("progress", {})
        stage = (progress.get("agent"), progress.get("stage"))
        if stage != last or time.monotonic() - last_print > 20:
            print(
                json.dumps(
                    {"pass": label, "status": job["status"], "progress": progress},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            report[label] = job
            save(output / "results.json", report)
            last, last_print = stage, time.monotonic()
    report[label] = job
    save(output / "results.json", report)
    print(
        json.dumps(
            {"pass": label, "status": job["status"], "results": job.get("results")},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return job


def coverage(home, manifest):
    rows = []
    with readonly_connection(home / "tandem.db") as db:
        db.execute("BEGIN")
        for source in manifest:
            key = source["id"]
            captured = {
                r[0]
                for r in db.execute(
                    "SELECT relative_path FROM source_file WHERE source_id=?", (key,)
                )
            }
            expected = {f["relative_path"] for f in source["files"]}
            now = {
                str(f.path.relative_to(source["root"]))
                for f in inputs(source["agent"], Path(source["root"]))
            }
            raw = db.execute(
                "SELECT COUNT(*) FROM file_record JOIN raw_record USING(record_uid) JOIN source_file USING(file_id) WHERE source_id=?",
                (key,),
            ).fetchone()[0]
            sessions = db.execute(
                "SELECT COUNT(*) FROM session WHERE source_id=?", (key,)
            ).fetchone()[0]
            events = db.execute(
                "SELECT COUNT(*) FROM event JOIN session USING(session_uid) WHERE source_id=?",
                (key,),
            ).fetchone()[0]
            issues = [
                dict(r)
                for r in db.execute(
                    "SELECT stage,code,COUNT(*) AS count FROM ingest_issue WHERE source_id=? AND COALESCE(json_extract(detail,'$.status'),'')<>'resolved' GROUP BY stage,code",
                    (key,),
                )
            ]
            rows.append(
                {
                    "agent": source["agent"],
                    "root": source["root"],
                    "source_id": key,
                    "discovered_before": len(expected),
                    "captured_files": len(captured),
                    "missing_initial_files": sorted(expected - captured),
                    "missing_current_files": sorted(now - captured),
                    "new_files_during_run": sorted(now - expected),
                    "removed_during_run": sorted(expected - now),
                    "current_raw_records": raw,
                    "sessions": sessions,
                    "events": events,
                    "issues": issues,
                }
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    home = output / "data"
    token = secrets.token_hex(32)
    app = create_desktop_app(home, token, ROOT / "prototypes/advance/tandem-demo.html")
    report = (
        json.loads((output / "results.json").read_text())
        if args.verify_only
        else {
            "boundary": "All allowlisted files in every discovered supported root. No count/size/age filter; each file is a consistent captured snapshot. Live agents may append after capture.",
            "started_at": time.time(),
        }
    )
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        manifest, ids = [], []
        if args.verify_only:
            manifest = json.loads((output / "manifest.json").read_text())
            report["repair_jobs"] = [
                j
                for j in client.get("/v1/app/state").json()["jobs"].values()
                if j["kind"] == "rebuild"
            ]
        else:
            for source in client.get("/v1/app/discovery").json()["items"]:
                root = Path(source["root"])
                files = []
                for item in inputs(source["agent"], root):
                    stat = item.path.stat()
                    files.append(
                        {
                            "relative_path": str(item.path.relative_to(root)),
                            "role": item.role,
                            "size": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns,
                        }
                    )
                # Empty roots are recorded too; they are not confused with absent agents.
                response = client.post(
                    "/v1/app/sources", json={"agent": source["agent"], "root": source["root"]}
                )
                response.raise_for_status()
                ids.append(response.json()["id"])
                manifest.append({**source, "files": files})
            save(output / "manifest.json", manifest)
            report["discovered"] = [
                {
                    "agent": s["agent"],
                    "root": s["root"],
                    "files": len(s["files"]),
                    "bytes": sum(f["size"] for f in s["files"]),
                }
                for s in manifest
            ]
            save(output / "results.json", report)
            print(json.dumps({"sources": report["discovered"]}, ensure_ascii=False), flush=True)
        if not args.verify_only:
            first = wait_job(
                client,
                client.post("/v1/app/jobs", json={"source_ids": ids}),
                report,
                output,
                "full_import",
            )
            report["coverage"] = coverage(home, manifest)
            report["storage"] = client.get("/v1/app/storage").json()
            save(output / "results.json", report)
            # A second pass is necessary to exercise incremental recovery on live sources.
            if first["status"] == "completed":
                wait_job(
                    client,
                    client.post("/v1/app/jobs", json={"source_ids": ids}),
                    report,
                    output,
                    "incremental_rescan",
                )
        report["coverage"] = coverage(home, manifest)
        report["storage"] = client.get("/v1/app/storage").json()
        save(output / "results.json", report)
        print(
            json.dumps(
                {"stage": "verify", "tables": report["storage"]["tables"]}, ensure_ascii=False
            ),
            flush=True,
        )
        verify_print = [0]

        def verify_progress(value):
            if time.monotonic() - verify_print[0] > 15:
                print(json.dumps(value), flush=True)
                verify_print[0] = time.monotonic()

        with Store(home) as store:
            store.db.execute("BEGIN")
            report["verification"] = store.verify(progress=verify_progress)
            report["diagnostics"] = [
                dict(row)
                for row in store.db.execute(
                    "SELECT stage,code,COUNT(*) count FROM ingest_issue WHERE COALESCE(json_extract(detail,'$.status'),'')<>'resolved' GROUP BY stage,code"
                )
            ]
            report["inherited_context_rows"] = store.db.execute(
                "SELECT COUNT(*) FROM event WHERE json_extract(attrs,'$.context_type')='inherited_history'"
            ).fetchone()[0]
            store.db.execute("ROLLBACK")
        report["read_checks"] = {}
        for route in (
            "/health",
            "/v1/app/storage",
            "/v1/app/sessions?limit=50",
            "/v1/app/projects",
            "/v1/app/analysis?section=overview",
            "/v1/app/analysis?section=overview&agent=pi",
        ):
            response = client.get(route)
            report["read_checks"][route] = {"status_code": response.status_code}
            if "analysis" in route and response.status_code == 200:
                report["read_checks"][route]["analysis_mode"] = response.json().get(
                    "analysis_mode", "full_features"
                )
            if route.startswith("/v1/app/sessions") and response.status_code == 200:
                data = response.json()
                report["read_checks"][route].update(
                    total=data["total"], page_rows=len(data["items"])
                )
                if data["items"]:
                    sid = data["items"][0]["session_uid"]
                    report["read_checks"]["events"] = {
                        "status_code": client.get(
                            f"/v1/app/sessions/{sid}/events?limit=100"
                        ).status_code
                    }
        client.patch("/v1/app/settings", json={"onboarded": True, "recent_days": 0})
        report["snapshot_complete"] = bool(manifest) and all(
            not row["missing_initial_files"] for row in report["coverage"]
        )
        report["validation_status"] = (
            "passed"
            if report["snapshot_complete"]
            and report["verification"]["integrity"] == "ok"
            and report["verification"]["unparsed"] == 0
            and not any(row["stage"] == "capture" for row in report["diagnostics"])
            and all(check["status_code"] == 200 for check in report["read_checks"].values())
            else "partial"
        )
        report["finished_at"] = time.time()
        report["elapsed_seconds"] = round(report["finished_at"] - report["started_at"], 2)
        save(output / "results.json", report)
        print(
            json.dumps(
                {
                    "report": str(output / "results.json"),
                    "coverage": report["coverage"],
                    "verification": report["verification"],
                    "read_checks": report["read_checks"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0 if report["validation_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
