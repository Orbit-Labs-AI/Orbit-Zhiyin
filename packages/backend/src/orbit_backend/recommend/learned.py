"""Retrieve a frozen, evidence-grounded procedure library without another model call.

External validation receipts are assertions by the caller, bound to candidate content.
They never imply that Orbit ran or independently checked the named evaluator.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter

from ..ai.pack import content_hash, now_ms
from ..ai.tasks_learning import KINDS, VERSION

STOP = set("a an and are as at be by can do for from how i in is it of on or that the this to use with you your".split())
DEFAULTS = {"top_k": 2, "min_support": 2, "min_score": .06, "dedup": True,
            "require_validation": True}


def terms(text):
    words = re.findall(r"[a-z][a-z0-9_+-]+|[\u4e00-\u9fff]{2,}", text.lower())
    return [w for w in words if w not in STOP]


def relevance(candidates, query):
    documents = [terms(" ".join([*c["keywords"], *c["keywords"], c["activation"], c["description"]]))
                 for c in candidates]
    df = Counter(word for doc in documents for word in set(doc))
    query_words = Counter(terms(query))

    def vector(words):
        return {word: (1 + math.log(count)) * (1 + math.log((len(documents) + 1) / (df[word] + 1)))
                for word, count in Counter(words).items()}

    q = vector(query_words.elements())
    qnorm = math.sqrt(sum(x * x for x in q.values()))
    scores = []
    for doc in documents:
        values = vector(doc)
        denom = qnorm * math.sqrt(sum(x * x for x in values.values()))
        scores.append(sum(value * q.get(word, 0) for word, value in values.items()) / denom if denom else 0.)
    return scores


def read_library(appdb, artifact_id):
    with appdb.read() as db:
        row = db.execute("SELECT artifact_id, payload, checks, content_hash, status FROM ai_artifact "
                         "WHERE artifact_id=? AND template_id=?", (artifact_id, VERSION)).fetchone()
    if row is None:
        raise KeyError(artifact_id)
    return {**dict(row), "payload": json.loads(row["payload"]), "checks": json.loads(row["checks"])}


def validation_state(candidate, receipts):
    selected = [r for r in receipts if r.get("candidate_id") == candidate["candidate_id"]
                and r.get("content_hash") == candidate["content_hash"]]
    if not selected:
        return "unvalidated"
    if any(r["candidate_passed"] is not True for r in selected):
        return "validation_failed"
    if not any(r.get("actual_usage") == "confirmed" for r in selected):
        return "usage_unconfirmed"
    improved = any(r["baseline_passed"] is False or (
        r.get("candidate_tokens") is not None and r.get("baseline_tokens_lower_bound") is not None
        and r["baseline_tokens_lower_bound"] > 0
        and r["candidate_tokens"] <= .9 * r["baseline_tokens_lower_bound"])
        for r in selected if r.get("actual_usage") == "confirmed")
    return "validated" if improved else "no_measured_headroom"


def record_validation(appdb, artifact_id, receipt):
    required = {"candidate_id", "content_hash", "split", "task_id", "run_digest", "model",
                "baseline_passed", "candidate_passed", "candidate_tokens", "baseline_tokens_lower_bound",
                "actual_usage", "usage_evidence_digest"}
    if not required <= receipt.keys() or receipt["split"] != "validation":
        raise ValueError("Only complete, explicitly labelled validation receipts are accepted")
    if not all(isinstance(receipt[k], bool) for k in ("baseline_passed", "candidate_passed")):
        raise ValueError("Unknown outcomes cannot validate a candidate")
    for key in ("candidate_tokens", "baseline_tokens_lower_bound"):
        number = receipt[key]
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float))
                                   or not math.isfinite(number) or number < 0):
            raise ValueError("Token counts must be finite nonnegative values or unknown")
    if not re.fullmatch(r"[a-f0-9]{64}", receipt["run_digest"]):
        raise ValueError("Validation must name a hashed external run receipt")
    if receipt["actual_usage"] not in ("confirmed", "not_observed", "unknown") or not re.fullmatch(
            r"[a-f0-9]{64}", receipt["usage_evidence_digest"]):
        raise ValueError("Validation needs a hashed usage audit, separate from skill activation")
    library = read_library(appdb, artifact_id)
    candidate = next((c for c in library["payload"]["candidates"]
                      if c["candidate_id"] == receipt["candidate_id"]), None)
    if candidate is None or candidate["content_hash"] != receipt["content_hash"]:
        raise ValueError("Receipt does not match immutable candidate content")
    row = {**receipt, "attestation": "caller_supplied_external_evaluation", "recorded_at": now_ms()}
    # Serialize updates with the AppDB writer so concurrent evaluations cannot overwrite receipts.
    with appdb.write() as db:
        current = json.loads(db.execute("SELECT checks FROM ai_artifact WHERE artifact_id=?",
                                       (artifact_id,)).fetchone()[0])
        existing = current.setdefault("validation_receipts", [])
        if not any(all(r.get(k) == receipt[k] for k in required) for r in existing):
            existing.append(row)
        db.execute("UPDATE ai_artifact SET checks=?, updated_at=? WHERE artifact_id=?",
                   (json.dumps(current, ensure_ascii=False), now_ms(), artifact_id))
    return row


def retrieve(library, query, *, capabilities, config=None):
    cfg = {**DEFAULTS, **(config or {})}
    if not 1 <= cfg["top_k"] <= 8 or not 1 <= cfg["min_support"] <= 8 or not 0 <= cfg["min_score"] <= 1:
        raise ValueError("Invalid retrieval limits")
    candidates = library["payload"]["candidates"]
    receipts = library["checks"].get("validation_receipts", [])
    scores = relevance(candidates, query)
    records = [{"candidate_id": c["candidate_id"], "kind": c["kind"], "name": c["name"],
                "score": round(score, 6), "support_sessions": c["support_sessions"],
                "evidence": c["evidence"], "content_hash": c["content_hash"], "decisions": []}
               for c, score in zip(candidates, scores, strict=True)]
    by_id = {r["candidate_id"]: r for r in records}
    stages = []
    active = sorted(candidates, key=lambda c: (-scores[candidates.index(c)], c["candidate_id"]))

    def stage(name, reasons):
        nonlocal active
        before, remaining = list(active), []
        for c in before:
            reason = reasons(c)
            by_id[c["candidate_id"]]["decisions"].append({"stage": name, "kept": reason is None,
                                                         "reason": reason})
            if reason is None:
                remaining.append(c)
        active = remaining
        counts = Counter(c["kind"] for c in active)
        stages.append({"stage": name, "input": len(before), "output": len(active),
                       "by_kind": {kind: counts[kind] for kind in KINDS}})

    stage("raw_candidates", lambda c: None)
    stage("scoring", lambda c: None)
    stage("evidence_threshold", lambda c: "insufficient_distinct_sessions"
          if c["support_sessions"] < cfg["min_support"] else None)
    stage("relevance_threshold", lambda c: "below_relevance_threshold"
          if by_id[c["candidate_id"]]["score"] < cfg["min_score"] else None)
    stage("compatibility", lambda c: "missing_capabilities:" + ",".join(sorted(set(c["requires"]) - set(capabilities)))
          if set(c["requires"]) - set(capabilities) else
          ("non_executable_proposal" if c["kind"] in ("hook", "mcp", "subagent") else None))
    stage("validation", lambda c: (None if validation_state(c, receipts) == "validated"
          else validation_state(c, receipts)) if cfg["require_validation"] else None)
    seen = set()

    def duplicate(c):
        # Exact procedure identity only; shared titles/triggers do not erase useful steps.
        key = content_hash({"kind": c["kind"], "procedure": [s["action"] for s in c["procedure"]],
                            "verification": c["verification"]})
        old = key in seen
        seen.add(key)
        return "duplicate_procedure" if old and cfg["dedup"] else None

    stage("deduplication", duplicate)
    selected = {c["candidate_id"] for c in active[:cfg["top_k"]]}
    stage("top_k", lambda c: None if c["candidate_id"] in selected else "cap:top_k")
    return {"library_id": library.get("artifact_id"), "library_content_hash": library.get("content_hash"),
            "query_digest": content_hash(query), "config": cfg, "candidates": active,
            "provisional": not cfg["require_validation"],
            "funnel": {"version": VERSION, "stages": stages, "candidates": records,
                       "injection": None, "activation": None, "actual_usage": None}}


def render(candidate):
    """Portable, reviewable instructions. No installation or generated code execution."""
    lines = ["---", "name: " + candidate["name"], "description: " + json.dumps(candidate["description"], ensure_ascii=False),
             "---", "", "# " + candidate["name"], "", "## When to use", candidate["activation"],
             "", "## Do not apply when", *["- " + v for v in candidate["avoid"]], "", "## Procedure"]
    lines += [f"{i}. {step['action']}" for i, step in enumerate(candidate["procedure"], 1)]
    lines += ["", "## Verify", *["- " + v for v in candidate["verification"]],
              "", "## Stop", candidate["termination"], "", "## Limits", *["- " + v for v in candidate["limitations"]]]
    return "\n".join(lines) + "\n"
