"""Bounded expert advice and query expansion over aggregate recommendation evidence.

Uses the existing consent-aware AI service. No sessions, messages, source code or install
payloads are read here. AI queries are hints; deterministic gates remain authoritative.
"""

from concurrent.futures import ThreadPoolExecutor

from .engine import rank_candidates
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
    try:
        result = service(gw).run("recommend.expert", slots=slots, scope=scope, timeout=TIMEOUT_S)
        body = result.get("result") or {}
        if not isinstance(body, dict):
            raise ValueError("invalid_expert_result")
    except Exception as exc:  # Optional AI must never prevent saving the deterministic slate.
        diagnostics.append({"source": "recommend.expert", "status": "unavailable", "reason": type(exc).__name__})
        return
    suggestions = []
    for suggestion in (body.get("suggestions") or [])[:3]:
        if not isinstance(suggestion, dict):
            continue
        pid = suggestion.get("problem_id")
        if pid not in problems or suggestion.get("kind") not in {"skill", "hook", "prompt", "workflow"}:
            continue
        if pid not in (suggestion.get("evidence_ids") or []):
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
                             agents=[a for a, n in (inputs.get("agents") or {}).items() if n > 0], limit=5)
                for q in queries]
    existing = {c["rec_key"] for c in slate.get("candidates") or []}
    raw = []
    try:
        futures = [pool.submit(catalog.match, request) for request in requests]
        for q, future in zip(queries, futures, strict=True):
            try:
                response = future.result(timeout=2)
            except Exception as exc:
                diagnostics.append({"source": "expert.recall", "status": "unavailable", "reason": type(exc).__name__})
                continue
            problem = problems[q["problem_id"]]
            for row in response.get("items") or []:
                item = _normalise_catalog(row)
                if item is None or "catalog:" + item["item_id"] in existing:
                    continue
                # Free-text similarity is not proof of a remedy. Require reviewed friction.
                if not any(f.get("feature") == "friction" and f.get("value") == problem["type"]
                           and f.get("origin") == "curated" for f in row.get("matched_features") or []):
                    continue
                cand = from_item(item, problem, inputs, match_basis="catalog_feature")
                cand["routes"] = {"expert_query": {"rank": row.get("rank"), "raw": row.get("score")}}
                cand["ai_query"] = {"text": q["text"][:500], "job_id": result.get("job_id")}
                existing.add(cand["rec_key"])
                raw.append(cand)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    ranked, _, gated = rank_candidates(raw, inputs, memory, limit=MAX_NEW_CARDS)
    # Expansion occupies spare slots; it cannot displace the deterministic evidence slate.
    room = min(MAX_NEW_CARDS, max(0, 30 - len(cards)))
    accepted = []
    for card in ranked:
        current = cards + accepted
        same_problem = [c for c in current if (c.get("problem") or {}).get("problem_id") ==
                        (card.get("problem") or {}).get("problem_id")]
        family = hygiene.family(card)
        if (len(accepted) >= room or len(same_problem) >= slate_policy.PER_PROBLEM
                or any(c.get("dim") == card.get("dim") for c in same_problem)
                or any(hygiene.norm_title(c.get("title")) == hygiene.norm_title(card.get("title")) for c in current)
                or sum(c.get("kind") == card.get("kind") for c in current) >= slate_policy.KIND_CAPS.get(card.get("kind"), 30)
                or (family and sum(hygiene.family(c) == family for c in current) >= slate_policy.FAMILY_CAP)):
            continue
        card["rank"] = len(cards) + len(accepted) + 1
        accepted.append(card)
    original = slate["candidates"]
    slate["candidates"] = ([c for c in original if c.get("rank")] + accepted
                           + [c for c in original if not c.get("rank")] + gated)
    slate.setdefault("routes", {})["expert_query"] = len(raw)
