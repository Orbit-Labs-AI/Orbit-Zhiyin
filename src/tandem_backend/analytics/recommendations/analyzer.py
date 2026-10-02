"""Compatibility entry point; matching now lives in recommend.service."""

from .catalog import KINDS, TARGETS


def recommend_bottlenecks(analysis, target_agent="generic", catalog=None, policy=None, limit=6, kind=None):
    from ...recommend.service import recommend
    from ...recommend.sources.normalize import legacy_item

    if target_agent not in TARGETS or kind is not None and kind not in KINDS:
        raise ValueError("Unknown target_agent or resource kind")
    prepared, rejected = None, []
    if catalog is not None:
        prepared = []
        for resource in catalog:
            try:
                prepared.append(legacy_item(resource))
            except (ValueError, TypeError, KeyError):
                rejected.append({"resource_id": resource.get("id") if isinstance(resource, dict) else None,
                                 "reason": "invalid_legacy_resource"})
    result = recommend(analysis, context={"agent": target_agent}, catalog=prepared, policy=policy, limit=limit, kind=kind)
    result["excluded_resources"].extend(rejected)
    return result
