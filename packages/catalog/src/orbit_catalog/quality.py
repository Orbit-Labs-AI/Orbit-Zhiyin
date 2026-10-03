"""Versioned documentation/source evidence rubric; never an effectiveness or security score."""

import json
import re

VERSION = "catalog-quality-v1"
VERIFIED = {"repository_and_skill_read", "repository_and_source_read"}
UNKNOWN_LICENSES = {"", "unknown", "noassertion", "none", "other", "repository_specific"}


def assess(row) -> dict:
    """Score five observable metadata dimensions equally, with explicit missing evidence.

    Official origin is reported separately: being official is not proof of compatibility,
    correctness, safety, or a measured user benefit. The rubric is a product heuristic.
    """
    row = dict(row)
    agents = row.get("agents") or []
    if isinstance(agents, str):
        agents = json.loads(agents)
    dimensions = {
        "source_read": row.get("verification") in VERIFIED,
        "license_declared": str(row.get("license") or "").casefold() not in UNKNOWN_LICENSES,
        "body_available": row.get("body_policy") == "licensed" and (row.get("body_len") or 0) > 0,
        "compatibility_listed": bool(agents),
        "source_version_recorded": bool(row.get("version") or re.search(
            r"github\.com/[^/]+/[^/]+/blob/[0-9a-f]{40}/", row.get("url") or "")),
    }
    score = sum(dimensions.values()) / len(dimensions)
    return {"version": VERSION, "score": score,
            "level": "documented" if score >= .8 else "partial" if score >= .4 else "sparse",
            "meaning": "metadata_completeness_not_effectiveness", "dimensions": dimensions,
            "missing": [key for key, present in dimensions.items() if not present],
            "official": bool(row.get("official")), "effect_status": "unmeasured",
            "security_status": "not_audited"}
