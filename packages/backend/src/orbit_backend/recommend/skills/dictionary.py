"""Skill-specific authored metadata; scripts/assets are references, never run."""

from pydantic import Field

from ..contracts import Contract


class ItemFeatures(Contract):
    invocation_condition: str | None = None
    workflow_steps: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    side_effect: list[str] = Field(default_factory=list)
