"""Validate supplied recommendation JSON without reading user history or fetching."""

import argparse
import json

from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.contracts import RecommendationContext
from tandem_backend.recommend.families import prepare_item
from tandem_backend.recommend.ranking.filters import filter_item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Directory containing the seven family JSON envelopes")
    parser.add_argument("--agent", default="generic")
    args = parser.parse_args()
    loaded = load_catalog(directory=args.directory)
    rows = []
    for item in loaded.items:
        try:
            item, family_pending = prepare_item(item)
            decision = filter_item(item, RecommendationContext(agent=args.agent))
            rows.append({"resource_id": item.identity.id, "family": item.family, "eligible": decision.eligible,
                         "reasons": decision.reasons,
                         "pending_requirements": sorted(set(family_pending + decision.pending_requirements))})
        except ValueError:
            rows.append({"resource_id": item.identity.id, "family": item.family, "eligible": False,
                         "reasons": ["invalid_family_features"]})
    print(json.dumps({"catalog_digest": loaded.digest, "accepted": len(loaded.items), "items": rows,
                      "diagnostics": loaded.diagnostics}, ensure_ascii=False, indent=2))
    return int(any(d["reason"] not in {"missing", "empty", "draft"} for d in loaded.diagnostics)
               or any("invalid_family_features" in r["reasons"] for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
