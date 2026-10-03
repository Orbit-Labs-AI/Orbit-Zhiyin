"""Model recommendations require a model, reasoning configuration and harness."""

from pydantic import Field

from ..contracts import Contract
from .benchmarks import BenchmarkObservation


class ItemFeatures(Contract):
    model: str | None = None
    reasoning_effort: str | None = None
    agent_harness: str | None = None
    context_window: int | None = Field(default=None, ge=1)
    benchmark_source: str | None = None
    benchmark_date: str | None = None
    benchmark_observations: list[BenchmarkObservation] = Field(default_factory=list)
    latency_ms: float | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    token_usage: int | None = Field(default=None, ge=0)
