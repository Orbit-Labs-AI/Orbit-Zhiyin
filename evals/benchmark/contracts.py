"""Frozen temporal samples and comparable execution measurements."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Method = Literal["no_recommendation", "generic", "raw_history_llm", "ours", "oracle"]
METHODS = ("no_recommendation", "generic", "raw_history_llm", "ours", "oracle")
NONE_ACTION = "no_intervention"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Episode(Contract):
    task_uid: str
    root_session_uids: list[str] = Field(min_length=1)
    project_id: str | None
    start_ts: int
    end_ts: int | None
    human_event_uids: list[str] = Field(min_length=1)
    boundary_quality: Literal["explicit", "native", "explicit_boundary", "candidate"]
    goal_observed: bool
    review_status: Literal["unreviewed", "independent_human_reviewed"] = "unreviewed"
    checkpoint_status: Literal["missing", "verified_exact"] = "missing"

    @model_validator(mode="after")
    def identity_and_order(self):
        for values in (self.root_session_uids, self.human_event_uids):
            if any(not value for value in values) or len(set(values)) != len(values):
                raise ValueError("Task evidence identities must be nonempty and unique")
        if self.end_ts is not None and self.end_ts < self.start_ts:
            raise ValueError("Task cannot end before it starts")
        return self


class TemporalSample(Contract):
    schema_version: Literal["temporal-sample-v1"] = "temporal-sample-v1"
    sample_id: str
    user_id: str
    variant: str = Field(default="correct_history", min_length=1, max_length=100)
    anchor_ts: int
    history_days: int = Field(ge=1, le=365)
    history_from_ts: int
    history_until_ts: int
    future_task_limit: int = Field(ge=1, le=100)
    future_until_ts: int
    future_tasks: list[Episode]
    observed_until_ts: int
    future_complete: bool

    @model_validator(mode="after")
    def windows(self):
        if self.history_until_ts != self.anchor_ts:
            raise ValueError("History must end at the recommendation anchor")
        if self.history_from_ts != self.anchor_ts - self.history_days * 86400000:
            raise ValueError("History window length differs from history_days")
        if not self.anchor_ts < self.future_until_ts <= self.anchor_ts + 72 * 3600000:
            raise ValueError("Future window must fit within 72 hours")
        if len(self.future_tasks) > self.future_task_limit:
            raise ValueError("Future task count exceeds the frozen limit")
        if len({task.task_uid for task in self.future_tasks}) != len(self.future_tasks):
            raise ValueError("Repeated messages cannot inflate the future task sample")
        if any(
            not self.anchor_ts <= task.start_ts < self.future_until_ts for task in self.future_tasks
        ):
            raise ValueError("A future task lies outside the future start window")
        if (
            self.future_complete
            and len(self.future_tasks) < self.future_task_limit
            and self.observed_until_ts < self.future_until_ts
        ):
            raise ValueError("A right-censored future window is not complete")
        return self


class Budget(Contract):
    total_tokens: int = Field(gt=0)
    turns: int = Field(gt=0)
    tool_calls: int = Field(gt=0)
    wall_ms: int = Field(gt=0)


class TaskReview(Contract):
    schema_version: Literal["benchmark-task-review-v1"] = "benchmark-task-review-v1"
    task_uid: str
    reviewer_id: str = Field(min_length=1, max_length=200)
    source: Literal["independent_human"]
    boundary_correct: bool
    meaningful_goal: bool
    evidence_event_uids: list[str] = Field(min_length=1)
    checkpoint_digest: Digest
    check_definition_digest: Digest
    available_at: int


class ExecutionRecord(Contract):
    schema_version: Literal["benchmark-execution-v1"] = "benchmark-execution-v1"
    sample_id: str
    task_uid: str
    action_id: str
    method: Method
    purpose: Literal["method_comparison", "action_sweep"] = "method_comparison"
    seed: int = Field(ge=0)
    source: Literal["paired_execution", "historical_observation", "constructed_execution"]
    checkpoint_digest: Digest | None = None
    task_input_digest: Digest | None = None
    environment_digest: Digest | None = None
    check_definition_digest: Digest | None = None
    intervention_digest: Digest | None = None
    run_log_digest: Digest | None = None
    model_id: str
    reasoning_effort: str
    budget: Budget
    passed: bool | None
    input_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    recommendation_tokens: int | None = Field(default=None, ge=0)
    turns: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)
    wall_ms: int | None = Field(default=None, ge=0)
    termination: Literal["completed", "budget_exhausted", "error", "cancelled", "unknown"]
    recommendation_anchor_ts: int

    @property
    def total_tokens(self):
        buckets = [
            self.input_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
            self.output_tokens,
            self.recommendation_tokens,
        ]
        return sum(buckets) if all(v is not None for v in buckets) else None

    @property
    def comparable_signature(self):
        return (
            self.checkpoint_digest,
            self.task_input_digest,
            self.environment_digest,
            self.check_definition_digest,
            self.model_id,
            self.reasoning_effort,
            tuple(self.budget.model_dump().items()),
            self.seed,
        )

    @property
    def measurement_complete(self):
        return (
            self.passed is not None
            and self.total_tokens is not None
            and self.turns is not None
            and self.tool_calls is not None
            and self.wall_ms is not None
            and self.termination not in ("unknown", "cancelled")
        )

    @property
    def provenance_complete(self):
        return all(
            (
                self.checkpoint_digest,
                self.task_input_digest,
                self.environment_digest,
                self.check_definition_digest,
                self.intervention_digest,
                self.run_log_digest,
            )
        )

    @property
    def pass_at_budget(self):
        if not self.measurement_complete:
            return None
        return (
            self.passed
            and self.termination == "completed"
            and self.total_tokens <= self.budget.total_tokens
            and self.turns <= self.budget.turns
            and self.tool_calls <= self.budget.tool_calls
            and self.wall_ms <= self.budget.wall_ms
        )
