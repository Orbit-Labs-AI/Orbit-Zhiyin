"""Suite discovery: every public module in ``evalrun/suites`` is one suite (EV-12).

A suite module defines ``ID``, ``TITLE``, ``EV`` (feature ids) and ``run(ctx)``; its
docstring's first paragraph is the description. Modules import lazily, so one suite with
a missing optional dependency never hides the others. Golden-metric suites (EV-01.2)
plug in the same way: add a module, nothing here changes.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from . import suites

# What a suite's score means (audit platform.md P1-14), so reports never present a
# self-consistency bar as an accuracy score:
# - regression_guard: constructed / synthetic cases whose bar is the currently measured result
#   (pipeline, probe: "any drop fails"; readability: hand-written contrasts; realtime: virtual
#   clock replay with 待验证 budgets; recommend / recommend_replay: synthetic fixtures + FakeEngine).
# - contract: invariants that must always hold over fakes (ledger rows add up, broken facets are
#   never stored, install revert is byte-identical, no planted secret leaves a pack).
# - agreement: comparison against another tool's numbers on the user's real data (insights);
#   its AGREE_SHARE threshold is still a placeholder (待验证).
# A suite module may set ``KIND`` itself; unknown suites are ``unclassified``.
KINDS = ("regression_guard", "contract", "agreement", "unclassified")
SUITE_KINDS = {
    "pipeline": "regression_guard", "probe": "regression_guard",
    "readability": "regression_guard", "realtime": "regression_guard",
    "recommend": "regression_guard", "recommend_replay": "regression_guard",
    "ai_ledger": "contract", "facet_quality": "contract", "install_roundtrip": "contract",
    "privacy": "contract", "insights": "agreement",
}


def kind(suite_id: str, module: ModuleType | None = None) -> str:
    value = getattr(module, "KIND", None) or SUITE_KINDS.get(suite_id, "unclassified")
    return value if value in KINDS else "unclassified"


def ids() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(suites.__path__)
                  if not m.name.startswith("_"))


def get(suite_id: str) -> ModuleType:
    if suite_id not in ids():
        raise ValueError(f"unknown suite: {suite_id}")
    return importlib.import_module(f"{suites.__name__}.{suite_id}")


def describe(suite_id: str) -> dict:
    try:
        module = get(suite_id)
    except ValueError:
        raise
    except Exception as exc:  # A broken suite still shows up, with the reason.
        return {"id": suite_id, "title": suite_id, "ev": [], "kind": kind(suite_id),
                "description": f"import failed: {type(exc).__name__}: {exc}"}
    doc = (module.__doc__ or "").strip().split("\n\n")[0]
    return {"id": module.ID, "title": module.TITLE, "ev": list(module.EV),
            "kind": kind(module.ID, module), "description": " ".join(doc.split())}


def list_suites() -> list[dict]:
    return [describe(suite_id) for suite_id in ids()]
