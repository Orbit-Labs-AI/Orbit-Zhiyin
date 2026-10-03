"""Partial offline family catalogues with per-record diagnostics and stable digests."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from .contracts import CATALOG_VERSION, FAMILIES, CatalogEnvelope, RecommendationItem
from .sources.normalize import legacy_item, normalize_item

MAX_FILE_BYTES = 8_000_000


@dataclass(frozen=True)
class CatalogLoad:
    items: list[RecommendationItem]
    diagnostics: list[dict]
    digest: str


def _reject_constant(value):
    raise ValueError("non_finite_json")


def _unique_keys(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate_json_key")
        output[key] = value
    return output


def _diagnostic(source, reason, *, index=None, resource_id=None, errors=None):
    result = {"source": source, "reason": reason}
    if index is not None:
        result["index"] = index
    if resource_id is not None:
        result["resource_id"] = resource_id
    if errors:
        result["fields"] = [{"path": list(error["loc"]), "type": error["type"]} for error in errors]
    return result


def _identity(record):
    if isinstance(record, RecommendationItem):
        return record.identity.id
    identity = record.get("identity") if isinstance(record, dict) else None
    uid = identity.get("id") if isinstance(identity, dict) else None
    return uid if isinstance(uid, str) else None


def load_catalog(directory=None, items=None, include_legacy=True):
    """Load a complete or partial catalogue; explicit inputs never fall back to seeds.

    ``directory`` uses seven versioned family envelopes. ``items`` accepts unified
    item records/models. Omission uses bundled family files and reviewed legacy
    resources; passing an empty list deliberately produces an empty catalogue.
    """
    if directory is not None and items is not None:
        raise ValueError("Pass either directory or items, not both")
    if not isinstance(include_legacy, bool):
        raise ValueError("include_legacy must be a boolean")
    diagnostics, records = [], []
    if items is not None:
        if not isinstance(items, list):
            raise ValueError("items must be a list")
        records = [(item, None, "provided", index) for index, item in enumerate(items)]
    else:
        base = Path(directory) if directory is not None else files("orbit_backend").joinpath("data/recommend")
        for family in FAMILIES:
            path = base.joinpath(family + ".json")
            source = str(path)
            try:
                if not path.is_file():
                    diagnostics.append(_diagnostic(source, "missing"))
                    continue
                with path.open("rb") as handle:
                    raw = handle.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError("catalog_file_too_large")
                payload = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant, object_pairs_hook=_unique_keys)
                if not isinstance(payload, dict) or payload.get("schema_version") != CATALOG_VERSION:
                    raise ValueError("unsupported_catalog_schema")
                if "items" not in payload:
                    raise ValueError("missing_catalog_items")
                envelope = CatalogEnvelope.model_validate(payload)
                if envelope.family != family:
                    raise ValueError("family_mismatch")
                if not envelope.items:
                    diagnostics.append(_diagnostic(source, "empty"))
                records.extend((item, family, source, index) for index, item in enumerate(envelope.items))
            except ValidationError as exc:
                diagnostics.append(_diagnostic(source, "invalid_envelope", errors=exc.errors(include_input=False)))
            except (OSError, UnicodeError, ValueError, RecursionError) as exc:
                reason = str(exc) if type(exc) is ValueError else "unreadable_or_invalid_json"
                diagnostics.append(_diagnostic(source, reason))
        if directory is None and include_legacy:
            from ..analytics.recommendations.catalog import load_catalog as load_legacy

            for index, resource in enumerate(load_legacy()):
                try:
                    records.append((legacy_item(resource), None, "legacy-reviewed-seed", index))
                except (ValueError, TypeError, KeyError):
                    diagnostics.append(_diagnostic("legacy-reviewed-seed", "invalid_legacy_resource", index=index))

    # Count identities before validation: a malformed conflicting record may not
    # quietly change which version wins. All copies of a duplicate are excluded.
    counts = Counter(uid for record, _, _, _ in records if (uid := _identity(record)) is not None)
    accepted = []
    for record, family, source, index in records:
        uid = _identity(record)
        if uid is not None and counts[uid] > 1:
            diagnostics.append(_diagnostic(source, "duplicate_identity", index=index, resource_id=uid))
            continue
        try:
            item = normalize_item(record, family)
        except ValidationError as exc:
            diagnostics.append(_diagnostic(source, "invalid_item", index=index, resource_id=uid, errors=exc.errors(include_input=False)))
        except (ValueError, TypeError, OverflowError, RecursionError):
            diagnostics.append(_diagnostic(source, "invalid_item", index=index, resource_id=uid))
        else:
            accepted.append(item)
            if item.evidence_quality.status != "reviewed" or item.source.status == "draft":
                diagnostics.append(_diagnostic(source, "draft", index=index, resource_id=uid))
    accepted.sort(key=lambda item: item.identity.id)
    canonical = json.dumps([item.model_dump(mode="json") for item in accepted], ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return CatalogLoad(accepted, diagnostics, hashlib.sha256(canonical.encode()).hexdigest())
