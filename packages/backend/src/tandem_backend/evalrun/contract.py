"""Contract between the eval runner and suite modules (EV-12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Check:
    id: str
    passed: bool
    value: float | None = None
    threshold: float | None = None
    detail: str = ""


@dataclass
class SuiteResult:
    suite: str
    checks: list[Check] = field(default_factory=list)
    skipped: str | None = None
    metrics: dict = field(default_factory=dict)

    @property
    def score(self) -> float | None:
        if self.skipped or not self.checks:
            return None
        return sum(c.passed for c in self.checks) / len(self.checks)


@dataclass
class EvalContext:
    tmp: Path
    home: Path | None = None
    params: dict = field(default_factory=dict)
    real: bool = False
