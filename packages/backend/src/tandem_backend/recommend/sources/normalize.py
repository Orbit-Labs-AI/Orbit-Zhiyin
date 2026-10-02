"""Convert known source records without treating source prose as capability truth."""

import json
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from ..contracts import RecommendationItem

CAPABILITY_RULES = {
    "scope_alignment": ("correction_density",),
    "requirements_memory": ("repeated_requirements",),
    "debugging": ("correction_density", "identical_retries", "tool_failures", "validation_failures"),
    "retry_control": ("identical_retries",),
    "tool_preflight": ("tool_failures",),
    "verification": ("correction_density", "validation_failures", "acceptance_evidence_gap"),
    "validation_visibility": ("acceptance_evidence_gap",),
    "context_budget": ("context_pressure",),
}
RULE_IDS = frozenset(rule for rules in CAPABILITY_RULES.values() for rule in rules)
LEGACY_FAMILIES = {"prompt": "rules_prompts", "skill": "skills", "hook": "hooks", "agent": "workflows"}
RESOURCE_FAMILIES = {
    "skill": "skills", "plugin": "plugins", "mcp_server": "mcp", "hook": "hooks",
    "subagent": "workflows", "workflow": "workflows", "guide": "workflows",
    "command": "rules_prompts", "rule": "rules_prompts", "output_style": "rules_prompts",
    "model": "model_configs",
}


def _safe_source_path(value):
    if value is None:
        return
    decoded = unquote(value)
    if (not decoded or decoded != decoded.strip() or "\\" in decoded or ":" in decoded
            or any(ord(char) < 32 for char in decoded)
            or PurePosixPath(decoded).is_absolute()
            or any(part in ("", ".", "..") for part in decoded.split("/"))):
        raise ValueError("unsafe_source_path")


def normalize_item(record, family=None):
    """Validate a unified item, including JSON values nested in family extensions."""
    payload = record.model_dump(mode="json") if isinstance(record, RecommendationItem) else record
    # model_construct and nested Any values must not bypass the JSON boundary.
    json.dumps(payload, allow_nan=False)
    item = RecommendationItem.model_validate(payload)
    if family is not None and item.family != family:
        raise ValueError("family_mismatch")
    if not item.identity.id.strip() or not item.identity.name.strip():
        raise ValueError("empty_identity")
    lists = [item.target_task.tags, item.trigger.tags, item.trigger.rule_ids,
             item.capability.tags, item.requirements.tools, item.requirements.software,
             item.requirements.resources, item.compatibility.os, item.compatibility.languages,
             item.compatibility.frameworks, item.risk_permission.required_permissions]
    if any(any(not value.strip() for value in values) or len(set(values)) != len(values) for values in lists):
        raise ValueError("invalid_tag_list")
    if any(rule not in RULE_IDS for rule in item.trigger.rule_ids):
        raise ValueError("unknown_trigger_rule")
    if any(rule not in RULE_IDS for rule in item.expected_effect.targets):
        raise ValueError("unknown_effect_target")
    _safe_source_path(item.source.source_path)
    for key, length in (("verified_sha", 40), ("blob_sha", 40), ("content_sha256", 64)):
        value = getattr(item.source, key)
        if value is not None and not re.fullmatch(rf"[a-f0-9]{{{length}}}", value):
            raise ValueError("invalid_source_pin")
    if item.source.url is not None:
        parsed = urlsplit(item.source.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid_source_url")
        if item.source.origin == "github" and parsed.hostname != "github.com":
            raise ValueError("invalid_github_source")
    return item.model_copy(deep=True)


def legacy_item(resource):
    """Adapt the existing reviewed bottleneck catalogue, retaining its exact pins."""
    from ...analytics.recommendations.catalog import rejection_reason

    reason = rejection_reason(resource)
    if reason:
        raise ValueError(reason)
    rules = sorted({rule for capability in resource["capabilities"] for rule in CAPABILITY_RULES[capability]})
    source = {key: resource[key] for key in (
        "url", "source_path", "verified_sha", "blob_sha", "content_sha256",
        "verification", "verified_at", "license") if key in resource}
    source.update(origin="local" if resource["origin"] == "project_template" else "github", status="verified")
    # These are summaries/templates, not invented executable hook or model configs.
    family_features = {"legacy_template": True}
    if resource["kind"] == "agent":
        family_features["template_type"] = "agent_role"
    return normalize_item({
        "identity": {"id": resource["id"], "name": resource["name"], "version": resource.get("verified_sha")},
        "family": LEGACY_FAMILIES[resource["kind"]], "legacy_kind": resource["kind"],
        "target_task": {"text": resource["summary"]},
        "trigger": {"rule_ids": rules},
        "capability": {"text": resource["summary"], "tags": resource["capabilities"]},
        "expected_effect": {"targets": dict.fromkeys(rules, 1.0)},
        "compatibility": {"agents": resource["compatibility"]},
        "friction": {"setup_cost": {"low": 0.0, "medium": 0.4, "high": 0.7}[resource["effort"]]},
        "evidence_quality": {"status": "reviewed", "score": 1.0, "reviewed_by": "tandem-bundled-catalog"},
        "source": source, "family_features": family_features,
        "action": {"setup_steps": resource["setup_steps"], "preview": resource["preview"],
                   "trial": resource["trial"], "limitations": resource["limitations"]},
    })


def catalog_resource(record):
    """Stage a future tandem_catalog Resource as draft without importing that package.

    Only curated, controlled feature keys become matching metadata. README body,
    extracted features, popularity and install instructions are not authoritative.
    A separate review must establish source integrity and capability evidence.
    """
    if not isinstance(record, dict) or record.get("type") not in RESOURCE_FAMILIES:
        raise ValueError("unsupported_catalog_resource")
    json.dumps(record, allow_nan=False)
    features = record.get("features", [])
    if not isinstance(features, list):
        raise ValueError("invalid_resource_features")
    capabilities, triggers, tasks, effects = set(), set(), set(), set()
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("invalid_resource_feature")
        if feature.get("origin") != "curated":
            continue
        key, value = feature.get("feature"), feature.get("value")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("invalid_curated_feature")
        if key == "capability" and value in CAPABILITY_RULES:
            capabilities.add(value)
        elif key in ("trigger", "rule_id") and value in RULE_IDS:
            triggers.add(value)
        elif key == "expected_effect" and value in RULE_IDS:
            effects.add(value)
        elif key in ("target_task", "task"):
            tasks.add(value)
    agents = record.get("agents", [])
    if not isinstance(agents, list) or any(not isinstance(agent, str) or not agent.strip() for agent in agents):
        raise ValueError("invalid_resource_agents")
    status = {"active": "draft", "deprecated": "deprecated", "deleted": "unavailable"}.get(record.get("status", "active"))
    if status is None:
        raise ValueError("invalid_resource_status")
    url = record.get("url")
    return normalize_item({
        "identity": {"id": record.get("item_id"), "name": record.get("name"), "version": record.get("version")},
        "family": RESOURCE_FAMILIES[record["type"]],
        "target_task": {"tags": sorted(tasks)}, "trigger": {"rule_ids": sorted(triggers)},
        "capability": {"tags": sorted(capabilities)},
        "expected_effect": {"targets": dict.fromkeys(sorted(effects), 1.0)},
        "compatibility": {"agents": dict.fromkeys(agents, "unknown")},
        "source": {"origin": "registry", "status": status, "url": url or None,
                   "source_path": record.get("repo_path"), "verified_sha": record.get("commit_sha"),
                   "license": record.get("license")},
        "family_features": {"upstream_resource_type": record["type"]},
        "action": {"limitations": ["上游目录记录仅已接收；来源、能力和环境兼容性仍需审核，不能直接安装。"]},
    })
