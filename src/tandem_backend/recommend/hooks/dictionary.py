"""A hook describes event / condition / action, not executable source."""

from typing import Literal

from pydantic import Field

from ..contracts import Contract


class ItemFeatures(Contract):
    event: str | None = None
    condition: str | None = None
    action: str | None = None
    pre_or_post: Literal["pre", "post"] | None = None
    blocking: bool | None = None
    deterministic_or_prompt: Literal["deterministic", "prompt"] | None = None
    runtime_overhead_ms: float | None = Field(default=None, ge=0)
    failure_behavior: str | None = None
