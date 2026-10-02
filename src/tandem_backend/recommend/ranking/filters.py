"""Reject known incompatibilities without treating missing context as agreement."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from ..contracts import RecommendationContext, RecommendationItem


@dataclass(frozen=True)
class FilterDecision:
    eligible: bool
    compatibility: str
    pending_requirements: list[str]
    reasons: list[str]


def _names(values: list[str]) -> set[str]:
    return {value.strip().casefold() for value in values if value.strip()}


def _os_name(value: str) -> str:
    name = value.strip().casefold()
    return {"win32": "windows", "win": "windows", "darwin": "macos",
            "mac": "macos", "osx": "macos", "wsl": "linux"}.get(name, name)


def _hex(value: str | None, length: int) -> bool:
    return bool(value and re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value))


def _verified_source(item: RecommendationItem) -> bool:
    source = item.source
    if source.status != "verified" or not _hex(source.content_sha256, 64):
        return False
    if source.origin != "github":
        return True
    try:
        url = urlsplit(source.url or "")
    except ValueError:
        return False
    path = source.source_path or ""
    safe_path = (bool(path) and not PurePosixPath(path).is_absolute()
                 and "\\" not in path and all(part not in {"", ".", ".."} for part in path.split("/")))
    repository_url = (url.scheme == "https" and url.netloc == "github.com"
                      and not url.query and not url.fragment
                      and bool(re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", url.path)))
    license_name = (source.license or "").strip().casefold()
    return bool(repository_url and safe_path and _hex(source.verified_sha, 40)
                and license_name not in {"", "unknown", "noassertion", "unlicensed", "none"}
                and (source.blob_sha is None or _hex(source.blob_sha, 40)))


def filter_item(item: RecommendationItem, context: RecommendationContext) -> FilterDecision:
    """Unknown prerequisites remain pending; supplied inventories are complete lists.

    An eligible item with pending requirements is a context-gathering suggestion,
    never an assertion that installation or execution is possible.
    """
    reasons: list[str] = []
    pending: list[str] = []
    compatibility = item.compatibility.agents.get(context.agent, "unknown")
    if compatibility == "unsupported":
        reasons.append(f"incompatible_agent:{context.agent}")
    elif compatibility == "unknown":
        pending.append(f"agent:{context.agent}")

    if item.compatibility.os:
        if context.os is None:
            pending.append("os")
        elif _os_name(context.os) not in {_os_name(os) for os in item.compatibility.os}:
            reasons.append(f"incompatible_os:{context.os}")

    for kind, accepted, current in (("languages", item.compatibility.languages, context.languages),
                                    ("frameworks", item.compatibility.frameworks, context.frameworks)):
        if accepted:
            if current is None:
                pending.append(kind)
            elif not _names(accepted) & _names(current):
                reasons.append(f"incompatible_{kind}")

    if context.installed_resources is not None:
        installed = _names(context.installed_resources)
        identity = item.identity.id.casefold()
        versioned = f"{identity}@{item.identity.version}".casefold()
        if identity in installed or (item.identity.version and versioned in installed):
            reasons.append(f"already_installed:{item.identity.id}")

    inventories = (("tools", item.requirements.tools, context.tools),
                   ("software", item.requirements.software, context.software),
                   ("resources", item.requirements.resources, context.installed_resources))
    for kind, required, available in inventories:
        if available is None:
            pending.extend(f"{kind}:{name}" for name in sorted(_names(required)))
        else:
            reasons.extend(f"missing_{kind}:{name}" for name in sorted(_names(required) - _names(available)))

    required_permissions = _names(item.risk_permission.required_permissions)
    denied = _names(context.denied_permissions)
    reasons.extend(f"permission_denied:{name}" for name in sorted(required_permissions & denied))
    if context.permissions is None:
        pending.extend(f"permission:{name}" for name in sorted(required_permissions - denied))
    else:
        reasons.extend(f"permission_not_allowed:{name}"
                       for name in sorted(required_permissions - _names(context.permissions) - denied))

    if not _verified_source(item):
        reasons.append(f"unverified_source:{item.source.status}")
    if item.evidence_quality.status != "reviewed":
        reasons.append("unreviewed_evidence")
    elif not (item.evidence_quality.reviewed_by or "").strip():
        reasons.append("missing_evidence_reviewer")
    if (not item.action.preview.strip() or not item.action.trial.strip()
            or not item.action.setup_steps or not all(step.strip() for step in item.action.setup_steps)):
        reasons.append("missing_action")

    return FilterDecision(not reasons, compatibility, sorted(set(pending)), sorted(set(reasons)))
