"""Strict observations with quotations; inferred labels never grant authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "semantic-observation-v1"
PROMPT_VERSION = "bounded-semantic-v1"
MODEL = "gpt-6.1-sol"
EFFORT = "medium"
MAX_RESPONSE_BYTES = 65536

VALUES = {
    "requested_autonomy": {"ask_first", "explicit", "scoped"},
    "execution_order": {"plan_first", "discuss_first", "execute_first"},
    "verification_requirements": {"requested"},
    "allowed_scope": {"restricted"},
    "prohibited_actions": {"prohibited"},
    "acceptance_criteria": {"criterion"},
    "format_requirements": {"format"},
    "tool_requirements": {"tool"},
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Arguments(Strict):
    response_form: Literal["command_only", "table", "list", "json", "markdown"] | None
    detail: Literal["concise", "detailed"] | None
    execution_environment: Literal["project_root", "venv"] | None
    acceptance_requirement: Literal["directly_runnable", "checks_pass"] | None


class Control(Strict):
    feature: Literal[
        "requested_autonomy",
        "execution_order",
        "verification_requirements",
        "allowed_scope",
        "prohibited_actions",
        "acceptance_criteria",
        "format_requirements",
        "tool_requirements",
    ]
    value: str = Field(min_length=1, max_length=40)
    quote: str = Field(min_length=1, max_length=500)
    targets: list[str] = Field(max_length=8)
    condition: str | None = Field(max_length=500)
    arguments: Arguments

    @model_validator(mode="after")
    def grounded_arguments(self):
        if self.value not in VALUES[self.feature]:
            raise ValueError("invalid feature/value pair")
        if any(not v or len(v) > 160 or v not in self.quote for v in self.targets):
            raise ValueError("targets must occur in the quoted directive")
        if self.condition is not None and (not self.condition or self.condition not in self.quote):
            raise ValueError("condition must occur in the quoted directive")
        if (
            self.arguments.response_form or self.arguments.detail
        ) and self.feature != "format_requirements":
            raise ValueError("response arguments belong to format_requirements")
        if self.arguments.execution_environment and self.feature != "allowed_scope":
            raise ValueError("execution environment belongs to allowed_scope")
        if self.arguments.acceptance_requirement and self.feature != "acceptance_criteria":
            raise ValueError("acceptance argument belongs to acceptance_criteria")
        return self


class Feedback(Strict):
    acceptance: Literal["accepted", "rejected", "partial", "mixed"] | None
    completion: bool | None
    rework: bool
    reason: str | None = Field(max_length=300)
    quote: str = Field(min_length=1, max_length=500)


class Observation(Strict):
    session_uid: str = Field(min_length=1, max_length=200)
    event_uid: str = Field(min_length=1, max_length=200)
    intents: list[Literal["request", "clarification", "correction", "feedback", "other"]] = Field(
        max_length=5
    )
    intent_quote: str | None = Field(max_length=500)
    target_event_uid: str | None = Field(max_length=200)
    friction_types: list[Literal["understanding", "scope", "execution", "verification"]] = Field(
        max_length=4
    )
    controls: list[Control] = Field(max_length=8)
    feedback: Feedback | None
    abstention_reason: str | None = Field(max_length=300)

    @model_validator(mode="after")
    def label_evidence(self):
        if self.intents and not self.intent_quote:
            raise ValueError("intent labels require a quotation")
        if self.friction_types and "correction" not in self.intents:
            raise ValueError("friction requires a correction observation")
        if self.feedback and "feedback" not in self.intents:
            raise ValueError("feedback requires feedback intent")
        return self


class BatchResult(Strict):
    observations: list[Observation] = Field(max_length=8)
