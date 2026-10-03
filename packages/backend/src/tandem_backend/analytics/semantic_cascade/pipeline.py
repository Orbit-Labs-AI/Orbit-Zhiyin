"""Validate one shared observation and attach only exact-input local cache entries."""

import copy
import json
import time
from collections import Counter
from dataclasses import asdict

from pydantic import ValidationError

from ..common import task_uid
from .candidates import (
    DEFAULT_BUDGET,
    Budget,
    batches,
    cache_identity,
    digest,
    source_stamp,
    source_text,
)
from .schema import (
    EFFORT,
    MAX_RESPONSE_BYTES,
    MODEL,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    BatchResult,
    Observation,
)


def validate_observation(item, candidate):
    observation = Observation.model_validate(item)
    if (observation.session_uid, observation.event_uid) != (
        candidate["session_uid"],
        candidate["event_uid"],
    ):
        raise ValueError("observation references another message")
    text = candidate["text"]
    quotes = [c.quote for c in observation.controls]
    quotes += [observation.intent_quote] if observation.intent_quote else []
    quotes += [observation.feedback.quote] if observation.feedback else []
    if any(q not in text for q in quotes):
        raise ValueError("observation quotation is absent from direct source text")
    from ..instruction.extraction import CONDITION, _clauses
    from ..instruction.structure import FILE
    from ..outcome_subjective.extraction import _HYPOTHETICAL, _META_REQUEST

    clauses = list(_clauses(text))
    for control in observation.controls:
        if not any(control.quote in clause for clause in clauses):
            raise ValueError("control quotation is narrative or crosses directive boundaries")
        if CONDITION.search(FILE.sub("", control.quote)) and not control.condition:
            raise ValueError("conditional directive lost its condition")
    if observation.feedback and (
        _HYPOTHETICAL.search(observation.feedback.quote)
        or _META_REQUEST.search(text)
        or any(v in observation.feedback.quote for v in ("?", "？"))
    ):
        raise ValueError("feedback quotation is hypothetical, metalinguistic or a question")
    if observation.target_event_uid is not None:
        target = next(
            (c for c in candidate["context"] if c["event_uid"] == observation.target_event_uid),
            None,
        )
        if (
            target is None
            or target["seq"] >= candidate["seq"]
            or not candidate["task_uid"]
            or target["task_uid"] != candidate["task_uid"]
        ):
            raise ValueError("target is not in preceding same-task context")
    return observation.model_dump()


def run_cascade(events, main_ids, provider, budget=DEFAULT_BUDGET):
    fingerprint, candidates, skipped = cache_identity(events, main_ids, budget)
    entries, calls, reasons, failures = [], [], Counter(s["reason"] for s in skipped), 0
    for index, batch in enumerate(batches(candidates, budget)):
        if index >= budget.max_calls or failures >= budget.max_failures:
            reasons[
                "call_budget_exhausted" if index >= budget.max_calls else "provider_circuit_open"
            ] += len(batch)
            continue
        try:
            response, usage = provider(batch, budget)
            if isinstance(response, str):
                if len(response.encode()) > MAX_RESPONSE_BYTES:
                    raise ValueError("response byte budget exceeded")
                response = json.loads(response)
            parsed = BatchResult.model_validate(response)
            by_id = {(c["session_uid"], c["event_uid"]): c for c in batch}
            ids = [(o.session_uid, o.event_uid) for o in parsed.observations]
            if len(ids) != len(set(ids)) or set(ids) != set(by_id):
                raise ValueError("response must cover each batch message exactly once")
            validated = [
                validate_observation(o.model_dump(), by_id[o.session_uid, o.event_uid])
                for o in parsed.observations
            ]
            for item in validated:
                source = by_id[item["session_uid"], item["event_uid"]]
                entries.append({"source": source, "observation": item})
            calls.append(
                {
                    "index": index,
                    "status": "parsed",
                    "message_count": len(batch),
                    "input_digest": digest(batch),
                    "usage": usage,
                }
            )
        except (ValueError, ValidationError, TimeoutError, OSError, RuntimeError) as exc:
            failures += 1
            reason = (
                "provider_timeout"
                if isinstance(exc, TimeoutError)
                else "provider_or_schema_failure"
            )
            reasons[reason] += len(batch)
            calls.append(
                {
                    "index": index,
                    "status": reason,
                    "message_count": len(batch),
                    "input_digest": digest(batch),
                    "error_type": type(exc).__name__,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": MODEL,
        "reasoning_effort": EFFORT,
        "budget": asdict(budget),
        "input_fingerprint": fingerprint,
        "generated_at": round(time.time() * 1000),
        "entries": entries,
        "calls": calls,
        "diagnostics": {
            "candidate_messages": len(candidates),
            "parsed_messages": len(entries),
            "skipped_messages": len(skipped),
            "unknown_reasons": dict(sorted(reasons.items())),
            "inference_semantics": "model inferred; not human reviewed or calibrated",
            "generation_token_cap": None,
            "token_limit_reason": "CLI exposes no verified server-side output-token cap",
        },
    }


def attach_cache(events, main_ids, cache):
    """Reject stale/model/schema/scope mismatches as a unit; never mutate the input."""
    if (
        cache.get("schema_version") != SCHEMA_VERSION
        or cache.get("prompt_version") != PROMPT_VERSION
        or cache.get("model") != MODEL
        or cache.get("reasoning_effort") != EFFORT
    ):
        raise ValueError("semantic cache version or model mismatch")
    budget = Budget(**cache["budget"])
    fingerprint, candidates, _ = cache_identity(events, main_ids, budget)
    if fingerprint != cache.get("input_fingerprint"):
        raise ValueError("semantic cache does not match this selected history")
    by_id = {(c["session_uid"], c["event_uid"]): c for c in candidates}
    validated = {}
    for entry in cache["entries"]:
        source = entry["source"]
        key = (source["session_uid"], source["event_uid"])
        if key in validated or source != by_id.get(key):
            raise ValueError("duplicate or stale semantic cache source")
        item = validate_observation(entry["observation"], source)
        times = [r["ts"] for r in [source, *source["context"]]]
        validated[key] = {
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "model": MODEL,
            "reasoning_effort": EFFORT,
            "source": source,
            "observation": item,
            "available_at": max(times) if times and None not in times else None,
            "generated_at": cache["generated_at"],
        }
    projected = []
    for event in events:
        row = {**event, "attrs": dict(event.get("attrs", {}))}
        row["attrs"].pop("semantic_cascade", None)
        if (key := (event["session_uid"], event["event_uid"])) in validated:
            row["attrs"]["semantic_cascade"] = validated[key]
        projected.append(row)
    return projected


def observation_for(event, lookup=None, until_ts=None):
    """Consumer validation keeps direct calls as conservative as the shared pipeline."""
    envelope = event.get("attrs", {}).get("semantic_cascade")
    if not isinstance(envelope, dict):
        return None
    try:
        if (
            envelope["schema_version"] != SCHEMA_VERSION
            or envelope["prompt_version"] != PROMPT_VERSION
            or envelope["model"] != MODEL
            or envelope["reasoning_effort"] != EFFORT
        ):
            return None
        source = envelope["source"]
        if {k: source[k] for k in source_stamp(event)} != source_stamp(event) or source[
            "text"
        ] != source_text(event):
            return None
        if source["text_truncated"] or len(source["text"]) > 2000:
            return None
        if source["input_digest"] != digest(
            {k: v for k, v in source.items() if k != "input_digest"}
        ):
            return None
        times = [r["ts"] for r in [source, *source["context"]]]
        if envelope["available_at"] != (max(times) if times and None not in times else None):
            return None
        if until_ts is not None and (
            envelope["available_at"] is None or envelope["available_at"] >= until_ts
        ):
            return None
        if lookup is not None:
            for prior in source["context"]:
                row = lookup.get((event["session_uid"], prior["event_uid"]))
                if row is None or source_stamp(row) != {k: prior[k] for k in source_stamp(row)}:
                    return None
                if row["seq"] >= event["seq"] or task_uid(row) != task_uid(event):
                    return None
        item = validate_observation(envelope["observation"], source)
        return {
            **copy.deepcopy(item),
            "available_at": envelope["available_at"],
            "source": "semantic_model",
            "model": MODEL,
            "reasoning_effort": EFFORT,
            "generated_at": envelope["generated_at"],
            "evidence_event_uids": [
                event["event_uid"],
                *[c["event_uid"] for c in source["context"]],
            ],
            "input_digest": source["input_digest"],
        }
    except (KeyError, TypeError, ValueError, ValidationError):
        return None
