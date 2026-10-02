"""Fetch public Skill sources explicitly, then export and smoke-test them locally."""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.service import recommend
from tandem_backend.recommend.sources.normalize import catalog_resource
from tandem_catalog.contracts import MatchRequest
from tandem_catalog.search import eligibility
from tandem_catalog.service import CatalogService
from tandem_catalog.sync import CatalogSync

from .demo import synthetic_bundle

SKILL_SOURCES = ("anthropic-skills", "claude-plugins", "openai-plugins", "awesome-copilot")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(home, sources, *, fetch=False, force=False, query="测试 debugging", limit=5, max_pages=10000):
    """Use the existing connectors; fetched metadata remains unreviewed drafts."""
    home = Path(home).resolve()
    sources = sorted(set(sources))
    if not sources or set(sources) - set(SKILL_SOURCES):
        raise ValueError("Select at least one supported Skill source")
    if force and not fetch:
        raise ValueError("--force requires --fetch")
    request = MatchRequest(text=query, types=["skill"], source_ids=sources, limit=limit)
    service = CatalogService(home / "catalog.db")
    try:
        if fetch:
            enabled = {s["source_id"] for s in service.store.sources() if s["enabled"]}
            if set(sources) - enabled:
                raise ValueError("A selected source is disabled; enable it explicitly before fetching")
            results = []
            for source in sources:
                print(f"Fetching {source} ...", file=sys.stderr, flush=True)
                results.extend(CatalogSync(service.store, service.http).sync(
                    [source], force=force, max_pages=max_pages))
                write_json(home / "sync.json", results)
            if any(r["status"] not in {"completed", "not_due"} for r in results):
                raise ValueError("Source sync failed or paused; inspect sync.json and retry --fetch")
            unhealthy = [s["source_id"] for s in service.store.sources() if s["source_id"] in sources
                         and (not s["completed_at"] or s["error"])]
            if unhealthy:
                raise ValueError("Selected sources have no successful snapshot or a failed refresh: "
                                 + ", ".join(unhealthy) + "; inspect sync.json")

        verification = service.store.verify()
        write_json(home / "verify.json", verification)
        if not verification["ok"]:
            raise ValueError("Catalog integrity check failed; inspect verify.json")
        where, params = eligibility(request)
        with service.store.connect(readonly=True) as conn:
            ids = [row[0] for row in conn.execute(
                "SELECT i.item_id FROM catalog_item i WHERE " + where + " ORDER BY i.item_id", params)]
        if not ids:
            raise ValueError("No fetched Skills in this catalog; run this script with --fetch first")
        details = [service.store.detail(uid) for uid in ids]
        # Keep the licensed source body, fixed revision and provenance; omit duplicate chunks.
        records = [{key: detail[key] for key in ("resource", "version_id", "content_hash", "sources")}
                   for detail in details]
        write_json(home / "skills.raw.json", {
            "schema_version": "catalog-skills-export-v1", "exported_at": datetime.now(UTC).isoformat(),
            "source_ids": sources, "items": records,
        })
        drafts = [catalog_resource(row["resource"]).model_dump(mode="json") for row in records]
        directory = home / "recommend"
        write_json(directory / "skills.json", {
            "schema_version": "recommendation-catalog-v1", "family": "skills", "items": drafts,
        })
        loaded = load_catalog(directory=directory, include_legacy=False)
        write_json(home / "ingestion.json", {"accepted": len(loaded.items), "diagnostics": loaded.diagnostics})
        if len(loaded.items) != len(drafts) or any(
            d["reason"] not in {"missing", "empty", "draft"} for d in loaded.diagnostics
        ):
            raise ValueError("Draft export failed recommendation ingestion; inspect ingestion.json")

        search = service.match(request)
        write_json(home / "search.json", search)
        analysis = analyze_bundle(synthetic_bundle(), with_text=False)
        result = recommend(analysis, context={"agent": "codex"}, family="skills", catalog_directory=directory)
        write_json(home / "recommendation.json", result)
        write_json(home / "synthetic-baseline.json", analysis["bottleneck_recommendations"])
        if not search["items"]:
            raise ValueError("The query returned no Skills; inspect search.json or change --query")
        if not analysis["bottleneck_recommendations"]["recommendations"]:
            raise ValueError("Synthetic recommendation baseline produced no cards")
        counts = Counter(source["source_id"] for row in records for source in row["sources"]
                         if source["source_id"] in sources and source["status"] == "active")
        summary = {
            "status": "ok", "skill_count": len(records), "by_source": {source: counts[source] for source in sources},
            "source_snapshots": [{key: s[key] for key in ("source_id", "revision", "completed_at", "error")}
                                 for s in service.store.sources() if s["source_id"] in sources],
            "accepted_drafts": len(loaded.items), "search_hits": len(search["items"]),
            "recommendation_status": result["status"], "recommendation_count": len(result["recommendations"]),
            "synthetic_baseline_count": len(analysis["bottleneck_recommendations"]["recommendations"]),
            "review_status": "draft: source retrieval does not establish reviewed capabilities or trial readiness",
            "output": str(home),
        }
        write_json(home / "summary.json", summary)
        return summary
    finally:
        service.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".local/skill-catalog"))
    parser.add_argument("--source", action="append", choices=SKILL_SOURCES, help="Repeat to select sources; default: all four")
    parser.add_argument("--fetch", action="store_true", help="Explicitly fetch the selected public sources")
    parser.add_argument("--force", action="store_true", help="Ignore refresh interval; requires --fetch")
    parser.add_argument("--max-pages", type=int, default=10000)
    parser.add_argument("--query", default="测试 debugging")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        summary = run(args.home, args.source or SKILL_SOURCES, fetch=args.fetch, force=args.force,
                      query=args.query, limit=args.limit, max_pages=args.max_pages)
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
