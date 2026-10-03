"""Recommendation admission tiers for catalog items.

``curated``: a person labelled the item's friction/scene/dimension (``item_feature.origin='curated'``,
today only the Tandem KB and seeds). ``rule_admitted``: a fetched item that passed every automatic
rule below for one friction; nobody reviewed it, and the tier says so in every match row.
``reviewed_reject`` decisions in ``data/admission.v1.json`` (human spot checks of rule-admitted
items) remove an item from the rule tier; ``reviewed_accept`` marks a spot-checked pass.

Rules (all must hold; thresholds are product defaults, not calibrated against adoption data):
1. ``verification`` says the repository and the resource file were read (index.VERIFIED);
2. ``body_policy='licensed'``: the body is stored, so the friction evidence is the item's own text;
3. an extracted friction feature with weight >= ADMIT_FRICTION_WEIGHT;
4. static risk level <= ADMIT_MAX_RISK (risk.assess: 0 none, 1 low);
5. the type is one the recommender can install or apply (ADMIT_TYPES).
"""

import json
from functools import lru_cache
from importlib.resources import files

from .features import EXTRACTED_FRICTION_WEIGHT, HEAD_MASS

# features.extract: weight = mass/(mass+1) * EXTRACTED_FRICTION_WEIGHT, a name/summary mention adds
# HEAD_MASS (3), an early body mention 1. Requiring mass >= HEAD_MASS means the friction is stated in
# the item's name or summary, or mentioned at least three times in its first 2000 body characters;
# a single passing body mention (mass 1 -> 0.3) is not enough. Product default, uncalibrated.
ADMIT_FRICTION_WEIGHT = round(HEAD_MASS / (HEAD_MASS + 1) * EXTRACTED_FRICTION_WEIGHT, 3)
ADMIT_MAX_RISK = 1
ADMIT_TYPES = ("skill", "hook", "mcp_server", "rule", "command", "subagent", "workflow")
REVIEW_FILE = "data/admission.v1.json"


@lru_cache(maxsize=1)
def review_decisions() -> dict:
    """item_id -> "reviewed_accept" | "reviewed_reject" from the bundled review file."""
    data = json.loads(files("tandem_catalog").joinpath(REVIEW_FILE).read_text())
    out = {}
    for decision in data.get("decisions") or []:
        if decision.get("decision") in ("reviewed_accept", "reviewed_reject") and decision.get("item_id"):
            out[decision["item_id"]] = decision["decision"]
    return out


def rule_admits(*, verified: bool, body_policy: str, risk_level: int, kind: str, friction_weight: float) -> bool:
    return (verified and body_policy == "licensed" and risk_level <= ADMIT_MAX_RISK and kind in ADMIT_TYPES
            and friction_weight >= ADMIT_FRICTION_WEIGHT)
