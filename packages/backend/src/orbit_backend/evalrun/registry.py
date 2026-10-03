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
        return {"id": suite_id, "title": suite_id, "ev": [],
                "description": f"import failed: {type(exc).__name__}: {exc}"}
    doc = (module.__doc__ or "").strip().split("\n\n")[0]
    return {"id": module.ID, "title": module.TITLE, "ev": list(module.EV),
            "description": " ".join(doc.split())}


def list_suites() -> list[dict]:
    return [describe(suite_id) for suite_id in ids()]
