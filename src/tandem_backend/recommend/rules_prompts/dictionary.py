"""Metadata for rules, prompts and persistent instructions."""

from pydantic import Field

from ..contracts import Contract


class ItemFeatures(Contract):
    scope: str | None = None
    instruction_type: str | None = None
    positive_constraint: list[str] = Field(default_factory=list)
    negative_constraint: list[str] = Field(default_factory=list)
    persistence: str | None = None
    token_overhead: int | None = Field(default=None, ge=0)
    target_behavior: list[str] = Field(default_factory=list)
