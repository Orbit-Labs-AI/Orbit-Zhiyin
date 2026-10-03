"""Bundle composition is distinct from evidence of its effect."""

from pydantic import Field

from ..contracts import Contract


class ItemFeatures(Contract):
    included_skills: list[str] = Field(default_factory=list)
    included_mcp: list[str] = Field(default_factory=list)
    included_hooks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
