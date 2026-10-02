"""Versioned contracts for catalogue ingestion and deterministic matching."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Family = Literal["rules_prompts", "skills", "plugins", "mcp", "hooks", "model_configs", "workflows"]
FAMILIES = ("rules_prompts", "skills", "plugins", "mcp", "hooks", "model_configs", "workflows")
Unit = Annotated[float, Field(ge=0, le=1)]
CATALOG_VERSION = "recommendation-catalog-v1"
RESULT_VERSION = "recommendation-pipeline-v1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Identity(Contract):
    id: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=300)
    version: str | None = None


class TextTags(Contract):
    text: str = Field(default="", max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=200)


class Trigger(TextTags):
    rule_ids: list[str] = Field(default_factory=list, max_length=100)


class ExpectedEffect(Contract):
    # Weights express intervention relevance, NOT observed improvement amounts.
    targets: dict[str, Unit] = Field(default_factory=dict)
    status: Literal["unmeasured"] = "unmeasured"


class Requirements(Contract):
    tools: list[str] = Field(default_factory=list)
    software: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)


class Compatibility(Contract):
    agents: dict[str, Literal["native", "manual", "adaptation_required", "unsupported", "unknown"]] = Field(default_factory=dict)
    os: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)


class Friction(Contract):
    setup_cost: Unit = .5
    runtime_cost: Unit = 0.


class RiskPermission(Contract):
    level: Unit = 0.
    required_permissions: list[str] = Field(default_factory=list)


class EvidenceQuality(Contract):
    status: Literal["draft", "reviewed"] = "draft"
    score: Unit = 0.
    reviewed_by: str | None = None


class SourceMetadata(Contract):
    origin: Literal["local", "github", "registry", "benchmark"] = "local"
    status: Literal["draft", "verified", "stale", "deprecated", "unavailable", "revoked"] = "draft"
    url: str | None = None
    source_path: str | None = None
    verified_sha: str | None = None
    blob_sha: str | None = None
    content_sha256: str | None = None
    verification: str | None = None
    verified_at: str | None = None
    license: str | None = None


class Action(Contract):
    setup_steps: list[str] = Field(default_factory=list)
    preview: str = ""
    trial: str = ""
    limitations: list[str] = Field(default_factory=list)


class RecommendationItem(Contract):
    schema_version: Literal["recommendation-item-v1"] = "recommendation-item-v1"
    identity: Identity
    family: Family
    target_task: TextTags = Field(default_factory=TextTags)
    trigger: Trigger = Field(default_factory=Trigger)
    capability: TextTags = Field(default_factory=TextTags)
    expected_effect: ExpectedEffect = Field(default_factory=ExpectedEffect)
    requirements: Requirements = Field(default_factory=Requirements)
    compatibility: Compatibility = Field(default_factory=Compatibility)
    friction: Friction = Field(default_factory=Friction)
    risk_permission: RiskPermission = Field(default_factory=RiskPermission)
    evidence_quality: EvidenceQuality = Field(default_factory=EvidenceQuality)
    source: SourceMetadata = Field(default_factory=SourceMetadata)
    family_features: dict[str, Any] = Field(default_factory=dict)
    action: Action = Field(default_factory=Action)
    legacy_kind: Literal["skill", "agent", "hook", "prompt"] | None = None


class CatalogEnvelope(Contract):
    schema_version: Literal["recommendation-catalog-v1"] = CATALOG_VERSION
    family: Family
    # Entries are validated individually, so one malformed entry can be diagnosed.
    items: list[Any] = Field(default_factory=list, max_length=10000)


class RecommendationContext(Contract):
    agent: str = Field(default="generic", min_length=1)
    model: str | None = None
    os: str | None = None
    languages: list[str] | None = None
    frameworks: list[str] | None = None
    repository: str | None = None
    tools: list[str] | None = None
    software: list[str] | None = None
    installed_resources: list[str] | None = None
    permissions: list[str] | None = None
    denied_permissions: list[str] = Field(default_factory=list)


class Evidence(Contract):
    kind: str
    session_uid: str
    id: str
    task_uid: str | None = None


class RecommendationState(Contract):
    root_session_uid: str
    scope: dict[str, Any] = Field(default_factory=dict)
    analysis_digest: str | None = None
    task_state: dict[str, Any] = Field(default_factory=dict)
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    interaction_state: dict[str, Any] = Field(default_factory=dict)
    outcome_state: dict[str, Any] = Field(default_factory=dict)
    cost_state: dict[str, Any] = Field(default_factory=dict)
    preference_state: dict[str, Any] = Field(default_factory=dict)
    context_state: RecommendationContext = Field(default_factory=RecommendationContext)
    bottleneck_vector: dict[str, Unit] = Field(default_factory=dict)
    task_text: str = ""
    problem_text: str = ""
    desired_effect_text: str = ""
    signals: list[dict[str, Any]] = Field(default_factory=list)


class Candidate(Contract):
    item_id: str
    route_scores: dict[str, float] = Field(default_factory=dict)
    route_ranks: dict[str, int] = Field(default_factory=dict)
    fusion_score: float = 0.


class RecommendationResult(Contract):
    schema_version: Literal["recommendation-pipeline-v1"] = RESULT_VERSION
    status: str
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    signals: list[dict[str, Any]] = Field(default_factory=list)
    assessments: list[dict[str, Any]] = Field(default_factory=list)
    states: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)
    ranking_policy: dict[str, Any] = Field(default_factory=dict)
    target_agent: str = "generic"
    kind: str | None = None
    family: Family | None = None
    catalog_digest: str = ""
    analysis_digest: str | None = None
    scope: dict[str, Any] | None = None
    excluded_resources: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class RankingPolicy(Contract):
    task_weight: Unit = .10
    trigger_weight: Unit = .20
    effect_weight: Unit = .25
    context_weight: Unit = .10
    evidence_weight: Unit = .20
    fusion_weight: Unit = .15
    friction_weight: Unit = .10
    risk_weight: Unit = .15
    mmr_lambda: Unit = .8
    rrf_k: int = Field(default=60, ge=1, le=1000)
    per_route: int = Field(default=50, ge=1, le=500)

    @field_validator("task_weight", "trigger_weight", "effect_weight", "context_weight", "evidence_weight",
                     "fusion_weight", "friction_weight", "risk_weight", "mmr_lambda", mode="before")
    @classmethod
    def no_bool_weights(cls, value):
        if isinstance(value, bool):
            raise ValueError("Boolean is not a weight")
        return value
