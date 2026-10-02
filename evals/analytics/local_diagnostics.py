"""Read a local canonical snapshot and print eight families plus every Skill decision."""

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tandem_backend.analytics.diagnostics import diagnostics, terminal_text
from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.service import analyze_store
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.service import recommend

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOME = ROOT / ".local/backend-nine-hour/p0-data"
DEFAULT_CATALOG = ROOT / "evals/recommendation/fixtures/reviewed-skills.json"


def snapshot_scope(home, days=7, *, from_ts=None, until_ts=None):
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    database = Path(home).resolve() / "tandem.db"
    if not database.is_file():
        raise ValueError("Provide an existing canonical data home with --home")
    if until_ts is None:
        with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
            latest = connection.execute("SELECT MAX(ts) FROM event").fetchone()[0]
        if latest is None:
            raise ValueError("No timestamped events in the selected canonical snapshot")
        until_ts = latest + 1
    from_ts = until_ts - days * 86400000 if from_ts is None else from_ts
    return Scope(display_timezone="Asia/Shanghai", from_ts=from_ts, until_ts=until_ts)


def run(home, output, catalog, scope):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("real-history outputs must remain under ignored .local/")
    envelope = json.loads(Path(catalog).read_text(encoding="utf-8"))
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version") != "recommendation-catalog-v1"
        or envelope.get("family") != "skills"
        or not isinstance(envelope.get("items"), list)
    ):
        raise ValueError("catalog must be a skills envelope with an explicit items list")
    loaded = load_catalog(items=envelope["items"])
    if any(item.family != "skills" for item in loaded.items):
        raise ValueError("catalog contains a non-Skill entry")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.perf_counter()
    analysis = analyze_store(CanonicalStore(home), scope, with_text=False)
    result = recommend(analysis, context={"agent": "codex"}, catalog=loaded.items, family="skills")
    report = diagnostics(analysis, result, loaded.items)
    report["run"] = {
        "elapsed_seconds": time.perf_counter() - started,
        "model_calls": 0,
        "source_rescan": False,
        "catalog_diagnostics": loaded.diagnostics,
        "window_basis": "explicit cutoff or most recent recorded event, not current clock",
    }
    for name, payload in (
        ("analytics", analysis),
        ("recommendations", result),
        ("diagnostics", report),
    ):
        (output / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (output / "terminal.txt").write_text(terminal_text(report) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--from-ts", type=int)
    parser.add_argument("--until-ts", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / ".local/feature-diagnostics" / (
        datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S-") + uuid4().hex[:8]
    )
    scope = snapshot_scope(args.home, args.days, from_ts=args.from_ts, until_ts=args.until_ts)
    report = run(args.home, output, args.catalog, scope)
    print(terminal_text(report))
    print(f"\n完整诊断和证据：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
