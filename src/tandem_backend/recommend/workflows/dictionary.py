"""Workflow and agent-role templates share one family."""

from pydantic import Field

from ..contracts import Contract


class ItemFeatures(Contract):
    steps: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    checkpoints: list[str] = Field(default_factory=list)
    human_in_loop: bool | None = None
    failure_recovery: str | None = None
    entry_condition: str | None = None
    exit_condition: str | None = None
