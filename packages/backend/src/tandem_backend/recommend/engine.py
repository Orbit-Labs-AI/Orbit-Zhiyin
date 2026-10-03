"""Recommendation engine entry (RC-03/04/05/15/17): recall → gates → score → slate → narrate.

`build_slate(inputs, memory)` is pure over its arguments (RecInputs + Memory) so
the store can cache by inputs digest and re-run it cheaply on label/exposure changes.
"""

from __future__ import annotations

from collections.abc import Callable

from . import narrate
from .ranking import gates as gate_mod
from .ranking import hygiene
from .ranking import rank as rank_mod
from .ranking import slate as slate_mod

ENGINE_VERSION = "rec-engine-v2"
NO_BENEFIT = "没有可估算的收益"
NET_NON_POSITIVE = "net_non_positive"
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
    cand["basis"] = "catalog_only" if hygiene.catalog_only(raw) else rank_mod.basis(raw)
    if cand["basis"] == "catalog_only":
        cand["bucket"] = hygiene.LIBRARY_LABEL
    return cand


def _compact(cand: dict) -> dict:
    """Gated candidates keep only what「为什么没推荐」and EV-05 need."""
    problem = cand.get("problem") or {}
    source = cand.get("source") or {}
    return {"rec_key": cand["rec_key"], "kind": cand.get("kind"), "dim": cand.get("dim"),
            "level": cand.get("level"), "title": cand.get("title"),
            "problem_id": problem.get("problem_id"), "problem_type": problem.get("type"),
            "source": {"origin": source.get("origin"), "item_id": source.get("item_id")},
            "gates": cand["gates"], "score": cand["score"], "rank": None,
            "excluded": cand.get("excluded") or "gated"}


def _demote(cand: dict, reason: str) -> dict:
    """A passing card hygiene keeps off the slate is stored like a gated one (passed=0)."""
    gates = cand["gates"]
    cand["gates"] = {**gates, "passed": False, "reasons": [*gates.get("reasons", []), reason]}
    cand["excluded"] = cand.get("excluded") or reason
    return _compact(cand)


def _status(inputs: dict, problems: list, ranked: list[dict]) -> str:
    if not ranked:
        if ((inputs.get("sessions") or {}).get("main") or 0) < 5:
            return "insufficient_evidence"
        return "no_matching"
    if all(c["basis"] in ("generic", "catalog_only") for c in ranked):
        return "cold_start"
    return "ready"


def rank_candidates(raws: list[dict], inputs: dict, memory: dict, *, limit: int = 30) -> tuple[list, list, list]:
    """Gate, score and select; returns (ranked, passing_unranked, gated) Cand lists."""
    max_fusion = max((r.get("fusion") or 0 for r in raws), default=0) or None
    by_key, passing, gated = {}, [], []
    for raw in raws:
        gates = gate_mod.check(raw, inputs, memory)
        score = rank_mod.score(raw, gates, inputs, memory, max_fusion=max_fusion)
        if gates["passed"] and score["benefit"] <= 0:  # nothing to gain is not a recommendation
            gates = {**gates, "passed": False, "reasons": [*gates["reasons"], NO_BENEFIT]}
        elif gates["passed"] and score["utility"] <= 0:  # risk/cost outweigh the expected value
            gates = {**gates, "passed": False, "reasons": [*gates["reasons"], NET_NON_POSITIVE]}
        cand = _cand(raw, gates, score)
        if gates["passed"]:
            cand["explain"] = narrate.explain(raw, raw.get("problem"), gates)
            by_key.setdefault(cand["rec_key"], raw)
            passing.append(cand)
        else:
            if NET_NON_POSITIVE in gates["reasons"]:
                cand["excluded"] = NET_NON_POSITIVE
            gated.append(_compact(cand))
    for cand in [c for c in passing if c["basis"] == "catalog_only" and not hygiene.profile_overlap(by_key[c["rec_key"]])]:
        passing.remove(cand)
        gated.append(_demote(cand, "catalog_no_overlap"))
    passing, dupes = hygiene.dedupe(passing)
    gated += [_demote(c, "duplicate") for c in dupes]
    ranked = slate_mod.select(passing, limit=limit)
    values = hygiene.slot_values(raws, inputs)
    for cand in passing:
        hygiene.scrub(cand, values)
        cand["ui"] = narrate.ui(cand, inputs, by_key[cand["rec_key"]])
        hygiene.scrub(cand, values)
    rest = sorted((c for c in passing if c.get("rank") is None and c["basis"] != "catalog_only"),
                  key=slate_mod.order_key)
    gated += [_demote(c, "cap:catalog_only") for c in passing if c.get("rank") is None and c["basis"] == "catalog_only"]
    gated.sort(key=slate_mod.order_key)
    return ranked, rest, gated


def _empty(status: str, diagnostics: list) -> dict:
    return {"engine_version": ENGINE_VERSION, "kb_version": None, "catalog_generation": None, "status": status,
            "problems": [], "candidates": [], "routes": {}, "diagnostics": diagnostics}


@_timed
def build_slate(inputs: dict, memory: dict, *, catalog=None, recall: Callable | None = None, features=None) -> dict:
    """RecInputs + Memory → Slate (passing ranked 1..N, then passing-unranked and gated with rank None).

    ``features`` (the features module API) adds the profile × catalog feature route and
    replaces ``inputs.profile`` with the live profile for scoring."""
    recall = recall or _default_recall()
    if recall is None:
        return _empty("no_matching", [{"source": "recall", "status": "unavailable"}])
    rr = recall(inputs, memory, catalog=catalog, **({"features": features} if features is not None else {}))
    if rr.get("profile") is not None:
        inputs = {**inputs, "profile": rr["profile"]}
    ranked, rest, gated = rank_candidates(rr.get("candidates") or [], inputs, memory)
    problems = rr.get("problems") or []
    return {"engine_version": ENGINE_VERSION, "kb_version": rr.get("kb_version"),
            "catalog_generation": rr.get("catalog_generation"), "status": _status(inputs, problems, ranked),
            "problems": problems, "candidates": ranked + rest + gated, "routes": rr.get("routes") or {},
            "diagnostics": rr.get("diagnostics") or []}
