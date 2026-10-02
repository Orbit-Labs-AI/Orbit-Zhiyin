"""Validated boundaries shared by connectors, storage, HTTP and the Mac client."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Feature(Contract):
    feature: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=256)
    weight: float = Field(default=1, gt=0, le=10)
    origin: Literal["declared", "extracted", "curated"] = "extracted"
    evidence: str = Field(default="", max_length=500)


ResourceType = Literal[
    "skill", "plugin", "marketplace", "mcp_server", "hook", "subagent", "command",
    "rule", "workflow", "guide", "output_style", "lsp_server", "model", "benchmark",
]


class Resource(Contract):
    item_id: str = Field(min_length=1, max_length=1000)
    type: ResourceType
    name: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=12000)
    url: str = Field(max_length=2000)
    body: str = Field(default="", max_length=250000)
    body_policy: Literal["metadata", "licensed"] = "metadata"
    license: str | None = None
    agents: list[str] = Field(default_factory=list, max_length=30)
    language: str = "any"
    status: Literal["active", "deprecated", "deleted"] = "active"
    official: bool = False
    difficulty: int = Field(default=2, ge=1, le=4)
    version: str | None = None
    commit_sha: str | None = None
    repo_id: str | None = None
    repo_path: str | None = None
    features: list[Feature] = Field(default_factory=list, max_length=200)
    manifest: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    popularity: dict = Field(default_factory=dict)
    install: dict = Field(default_factory=dict)
    risk: list[str] = Field(default_factory=list, max_length=30)
    components: list[str] = Field(default_factory=list, max_length=1000)


class Record(Contract):
    native_id: str = Field(min_length=1, max_length=1000)
    resource: Resource
    raw: dict = Field(default_factory=dict)


class SourceSpec(Contract):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    kind: Literal["bundle", "github", "mcp", "models_dev", "litellm", "swe_bench", "gemini", "clawhub", "local"]
    url: str
    enabled: bool = True
    priority: int = Field(default=50, ge=0, le=100)
    refresh_seconds: int = Field(default=86400, ge=60)
    config: dict = Field(default_factory=dict)


class Page(Contract):
    records: list[Record]
    checkpoint: dict = Field(default_factory=dict)
    complete: bool
    mode: Literal["full", "incremental"] = "full"
    revision: str | None = None
    watermark: str | None = None


class MatchRequest(Contract):
    text: str = Field(default="", max_length=8000)
    features: list[Feature] = Field(default_factory=list, max_length=100)
    types: list[ResourceType] = Field(default_factory=list, max_length=20)
    agents: list[str] = Field(default_factory=list, max_length=30)
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    language: str | None = None
    max_difficulty: int = Field(default=4, ge=1, le=4)
    excluded_ids: list[str] = Field(default_factory=list, max_length=1000)
    purpose: Literal["library", "recommendation"] = "library"
    problem_id: str | None = None
    problem_type: str | None = None
    scene: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    profile_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)
    per_route: int = Field(default=100, ge=10, le=500)
    model_id: str | None = None
    prefix: bool = False  # Treat the last >=3-char query token as a prefix (type-ahead).


class LocalItem(BaseModel):
    """A user/AI-generated item; must carry a passing AI self-check before entering the catalog."""
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    kind: Literal["skill", "hook", "subagent", "command", "rule", "workflow"]
    name: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=12000)
    body: str = Field(min_length=1, max_length=250000)
    agents: list[str] = Field(default_factory=list, max_length=30)
    features: list[Feature] = Field(default_factory=list, max_length=100)
    template_id: str | None = Field(default=None, max_length=200)
    template_version: str | None = Field(default=None, max_length=100)
    job_id: str | None = Field(default=None, max_length=200)
    self_check: dict | None = None
    manifest: dict = Field(default_factory=dict)
    install: dict = Field(default_factory=dict)


class SyncRequest(Contract):
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    max_pages: int = Field(default=10000, ge=1, le=10000)
    force: bool = False
    concurrency: int = Field(default=3, ge=1, le=8)
    offline: bool = False  # Answer only from the local HTTP cache (no network).
    ttl: int | None = Field(default=None, ge=0, le=7 * 86400)  # Seconds a cached response is trusted unrevalidated.
