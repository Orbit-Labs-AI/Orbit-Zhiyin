"""Recommendation engine entry (RC-03/04/05/15/17): recall → gates → score → slate → narrate.

`build_slate(inputs, memory)` is pure over its arguments (RecInputs + Memory) so
the store can cache by inputs digest and re-run it cheaply on label/exposure changes.
"""

from __future__ import annotations

from collections.abc import Callable

from . import narrate
from .ranking import gates as gate_mod
from .ranking import rank as rank_mod
from .ranking import slate as slate_mod

ENGINE_VERSION = "rec-engine-v2"
INTERNAL = ("kb", "item", "prior", "cost", "requirements", "gates_hint", "explain_hints")


def _timed(fn: Callable) -> Callable:
    try:
        from ..platform import timed
        return timed("recommend.build_slate")(fn)
    except Exception:  # platform area optional until wired; never break ranking over telemetry
        return fn


def _default_recall() -> Callable | None:
    try:
        from .recall.multi import recall_all
        return recall_all
    except ImportError:
        return None


def _links(raw: dict) -> dict:
    kb = raw.get("kb") or {}
    remedy = kb.get("remedy") or kb
    return {"kb_id": kb.get("id"), "pairs_with": list(remedy.get("pairs_with") or []),
            "conflicts_with": list(remedy.get("conflicts_with") or []),
            "content_hash": (raw.get("item") or {}).get("content_hash")}


def _cand(raw: dict, gates: dict, score: dict) -> dict:
    cand = {k: v for k, v in raw.items() if k not in INTERNAL}
    cand["level"] = gates["level"]
    cand["gates"] = {k: gates[k] for k in ("passed", "checks", "reasons")}
    cand["score"] = score
    cand["rank"] = None
    cand["links"] = _links(raw)
    cand["basis"] = rank_mod.basis(raw)
    return cand


def _compact(cand: dict) -> dict:
    """Gated candidates keep only what「为什么没推荐」and EV-05 need."""
    problem = cand.get("problem") or {}
    source = cand.get("source") or {}
    return {"rec_key": cand["rec_key"], "kind": cand.get("kind"), "dim": cand.get("dim"),
            "level": cand.get("level"), "title": cand.get("title"),
            "problem_id": problem.get("problem_id"), "problem_type": problem.get("type"),
            "source": {"origin": source.get("origin"), "item_id": source.get("item_id")},
            "gates": cand["gates"], "score": cand["score"], "rank": None, "excluded": "gated"}


def _status(inputs: dict, problems: list, ranked: list[dict]) -> str:
    if not ranked:
        if ((inputs.get("sessions") or {}).get("main") or 0) < 5:
            return "insufficient_evidence"
        return "no_matching"
    if all(c["basis"] == "generic" for c in ranked):
        return "cold_start"
    return "ready"


def rank_candidates(raws: list[dict], inputs: dict, memory: dict, *, limit: int = 30) -> tuple[list, list, list]:
    """Gate, score and select; returns (ranked, passing_unranked, gated) Cand lists."""
    max_fusion = max((r.get("fusion") or 0 for r in raws), default=0) or None
    by_key, passing, gated = {}, [], []
    for raw in raws:
        gates = gate_mod.check(raw, inputs, memory)
        score = rank_mod.score(raw, gates, inputs, memory, max_fusion=max_fusion)
        cand = _cand(raw, gates, score)
        if gates["passed"]:
            cand["explain"] = narrate.explain(raw, raw.get("problem"), gates)
            by_key.setdefault(cand["rec_key"], raw)
            passing.append(cand)
        else:
            gated.append(_compact(cand))
    ranked = slate_mod.select(passing, limit=limit)
    for cand in passing:
        cand["ui"] = narrate.ui(cand, inputs, by_key[cand["rec_key"]])
    rest = sorted((c for c in passing if c.get("rank") is None),
                  key=lambda c: (-c["score"]["priority"], c["rec_key"]))
    gated.sort(key=lambda c: (-c["score"]["priority"], c["rec_key"]))
    return ranked, rest, gated


def _empty(status: str, diagnostics: list) -> dict:
    return {"engine_version": ENGINE_VERSION, "kb_version": None, "catalog_generation": None, "status": status,
            "problems": [], "candidates": [], "routes": {}, "diagnostics": diagnostics}


@_timed
def build_slate(inputs: dict, memory: dict, *, catalog=None, recall: Callable | None = None) -> dict:
    """RecInputs + Memory → Slate (passing ranked 1..N, then passing-unranked and gated with rank None)."""
    recall = recall or _default_recall()
    if recall is None:
        return _empty("no_matching", [{"source": "recall", "status": "unavailable"}])
    rr = recall(inputs, memory, catalog=catalog)
    ranked, rest, gated = rank_candidates(rr.get("candidates") or [], inputs, memory)
    problems = rr.get("problems") or []
    return {"engine_version": ENGINE_VERSION, "kb_version": rr.get("kb_version"),
            "catalog_generation": rr.get("catalog_generation"), "status": _status(inputs, problems, ranked),
            "problems": problems, "candidates": ranked + rest + gated, "routes": rr.get("routes") or {},
            "diagnostics": rr.get("diagnostics") or []}
