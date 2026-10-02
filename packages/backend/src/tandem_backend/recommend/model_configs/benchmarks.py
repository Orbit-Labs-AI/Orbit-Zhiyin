"""Named benchmark observations; never compare raw scores across benchmarks."""

from pydantic import Field

from ..contracts import Contract


class BenchmarkObservation(Contract):
    benchmark: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    score: float
    scale: str = Field(min_length=1)
    date: str = Field(min_length=1)
    source: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    harness: str = Field(min_length=1)
