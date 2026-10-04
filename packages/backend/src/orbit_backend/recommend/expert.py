"""Bounded expert advice and query expansion over aggregate recommendation evidence.

Uses the existing consent-aware AI service. No sessions, messages, source code or install
payloads are read here. AI queries are hints; deterministic gates remain authoritative.
"""

from concurrent.futures import ThreadPoolExecutor

from .engine import rank_candidates
from .funnel import Funnel
from .ranking import hygiene
from .ranking import slate as slate_policy
from .recall.catalog_route import _normalise_catalog, from_item

MAX_PROBLEMS, MAX_QUERIES, MAX_NEW_CARDS = 6, 3, 2
TIMEOUT_S = 25


def enrich(gw, slate: dict, inputs: dict, memory: dict, catalog, scope: dict) -> None:
    from ..ai import service

    problems = {p["problem_id"]: p for p in slate.get("problems") or []
                if p.get("status") == "active" and p.get("problem_id")}
    problems = dict(list(problems.items())[:MAX_PROBLEMS])
    if not problems:
        return
    cards = [c for c in slate.get("candidates") or [] if c.get("rank") and (c.get("gates") or {}).get("passed")]
    slots = {"problems": [{k: p.get(k) for k in
                           ("problem_id", "type", "dimension", "sessions", "weekly_count")} for p in problems.values()],
             "profile": {"features": [{"feature": "tag", "value": str(key)[:80], "weight": value}
                                       for key, value in list(((inputs.get("profile") or {}).get("tags") or {}).items())[:12]]}
             if isinstance((inputs.get("profile") or {}).get("tags"), dict) else {"features": []},
             "candidates": [{"candidate_id": c["rec_key"], "kind": c.get("kind"),
                             "title": str(c.get("title") or "")[:150], "summary": str(c.get("summary") or "")[:300]}
                            for c in cards[:10]]}
    diagnostics = slate.setdefault("diagnostics", [])
    observed = {"status": "requested", "suggestions": [], "queries": []}
    if slate.get("funnel") is not None:
        slate["funnel"]["upstream"]["expert"] = observed
    try:
        result = service(gw).run("recommend.expert", slots=slots, scope=scope, timeout=TIMEOUT_S)
        body = result.get("result") or {}
        if not isinstance(body, dict):
            raise ValueError("invalid_expert_result")
    except Exception as exc:  # Optional AI must never prevent saving the deterministic slate.
        observed.update(status="unavailable", reason=type(exc).__name__)
        diagnostics.append({"source": "recommend.expert", "status": "unavailable", "reason": type(exc).__name__})
        return
    suggestions = []
    observed.update(status=result.get("status", "ok"), job_id=result.get("job_id"))
    for index, suggestion in enumerate(body.get("suggestions") or []):
        reason = None
        if not isinstance(suggestion, dict):
            observed["suggestions"].append({"index": index, "kept": False, "reason": "invalid_schema"})
            continue
        pid = suggestion.get("problem_id")
        if index >= 3:
            reason = "suggestion_limit"
        elif pid not in problems:
            reason = "unknown_problem"
        elif suggestion.get("kind") not in {"skill", "hook", "prompt", "workflow"}:
            reason = "unsupported_advice_kind"
        elif pid not in (suggestion.get("evidence_ids") or []):
            reason = "missing_problem_evidence"
        observed["suggestions"].append({"index": index, "kind": suggestion.get("kind"),
                                        "problem_id": pid, "evidence_ids": suggestion.get("evidence_ids"),
                                        "kept": reason is None, "reason": reason or "draft_advice_not_installed",
                                        "score": None})
        if reason is not None:
            continue
        advice = {**suggestion, "draft": True, "effect_status": "unmeasured", "job_id": result.get("job_id")}
        card = next((c for c in cards if (c.get("problem") or {}).get("problem_id") == pid), None)
        if card is not None:
            card.setdefault("expert_advice", []).append(advice)
        else:
            suggestions.append(advice)
    diagnostics.append({"source": "recommend.expert", "status": result.get("status", "ok"),
                        "reason": "draft_advice_not_installed", "unattached_advice": suggestions})
    if catalog is None:
        return
    queries = [q for q in (body.get("queries") or [])[:MAX_QUERIES]
               if isinstance(q, dict) and q.get("problem_id") in problems and isinstance(q.get("text"), str) and q["text"].strip()]
    if not queries:
        return
    from orbit_catalog.contracts import MatchRequest

    pool = ThreadPoolExecutor(max_workers=MAX_QUERIES, thread_name_prefix="orbit-expert-recall")
    requests = [MatchRequest(text=q["text"][:500], purpose="library", problem_type=problems[q["problem_id"]]["type"],
                             agents=[a for a, n in (inputs.get("agents") or {}).items() if n > 0], limit=5, audit=True)
                for q in queries]
    existing = {c["rec_key"] for c in slate.get("candidates") or []}
    raw = []
    try:
        futures = [pool.submit(catalog.match, request) for request in requests]
        for q, future in zip(queries, futures, strict=True):
            query_audit = {"problem_id": q["problem_id"], "query": q["text"][:500], "decisions": []}
            observed["queries"].append(query_audit)
            try:
                response = future.result(timeout=2)
            except Exception as exc:
                query_audit.update(status="unavailable", reason=type(exc).__name__)
                diagnostics.append({"source": "expert.recall", "status": "unavailable", "reason": type(exc).__name__})
                continue
            problem = problems[q["problem_id"]]
            query_audit.update(status="ok", filter_audit=response.get("filter_audit"),
                               returned_count=len(response.get("items") or []))
            for row in response.get("items") or []:
                item = _normalise_catalog(row)
                reason = "invalid_catalog_item" if item is None else None
                if item is not None and "catalog:" + item["item_id"] in existing:
                    reason = "already_recalled"
                if reason is None and not any(
                    f.get("feature") == "friction" and f.get("value") == problem["type"]
                    and f.get("origin") == "curated" for f in row.get("matched_features") or []
                ):
                    reason = "no_curated_remedy_evidence"
                query_audit["decisions"].append({"item_id": row.get("item_id"), "kind": row.get("type"),
                                                 "score": row.get("score"), "kept": reason is None,
                                                 "reason": reason, "evidence": row.get("matched_features")})
                if reason is not None:
                    continue
                # Free-text similarity is not proof of a remedy. Require reviewed friction.
                cand = from_item(item, problem, inputs, match_basis="catalog_feature")
                cand["routes"] = {"expert_query": {"rank": row.get("rank"), "raw": row.get("score")}}
                cand["ai_query"] = {"text": q["text"][:500], "job_id": result.get("job_id")}
                existing.add(cand["rec_key"])
                raw.append(cand)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    expansion = Funnel(inputs, list(problems.values()), {})
    ranked, _, gated = rank_candidates(raw, inputs, memory, limit=MAX_NEW_CARDS, audit=expansion)
    # Expansion occupies spare slots; it cannot displace the deterministic evidence slate.
    room = min(MAX_NEW_CARDS, max(0, 30 - len(cards)))
    accepted, decisions = [], []
    for card in ranked:
        current = cards + accepted
        same_problem = [c for c in current if (c.get("problem") or {}).get("problem_id") ==
                        (card.get("problem") or {}).get("problem_id")]
        family = hygiene.family(card)
        reasons = [name for name, hit in (
            ("cap:expert_room", len(accepted) >= room),
            ("cap:problem", len(same_problem) >= slate_policy.PER_PROBLEM),
            ("same_dimension", any(c.get("dim") == card.get("dim") for c in same_problem)),
            ("duplicate_title", any(hygiene.norm_title(c.get("title")) == hygiene.norm_title(card.get("title")) for c in current)),
            ("cap:kind", sum(c.get("kind") == card.get("kind") for c in current) >= slate_policy.KIND_CAPS.get(card.get("kind"), 30)),
            ("cap:family", family and sum(hygiene.family(c) == family for c in current) >= slate_policy.FAMILY_CAP),
        ) if hit]
        decisions.append((card, not reasons, reasons))
        if reasons:
            continue
        card["rank"] = len(cards) + len(accepted) + 1
        accepted.append(card)
    expansion.record("spare_slot_selection", decisions)
    if slate.get("funnel") is not None:
        slate["funnel"]["candidates"].update(expansion.candidates)
        slate["funnel"]["stages"].extend({**stage, "stage": "expert_" + stage["stage"]}
                                         for stage in expansion.stages)
    original = slate["candidates"]
    slate["candidates"] = ([c for c in original if c.get("rank")] + accepted
                           + [c for c in original if not c.get("rank")] + gated)
    slate.setdefault("routes", {})["expert_query"] = len(raw)
