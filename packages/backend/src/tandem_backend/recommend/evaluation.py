"""Recommendation evaluation (EV-05, EV-05.1, EV-05.2, RC-09 / RC-17 contribution).

- ``time_split``: at each cutoff t the slate is built from inputs that end before t; a hit is
  a remedy the user adopted in ``[t, t + horizon)``. HitRate@3 / NDCG@3, optionally after an
  AI rerank (``engine_rerank`` drives the real ``rerank.fit`` task contract with any engine,
  e.g. ``FakeEngine``).
- ``ablation_report``: re-runs the replay with one gate neutralised (→ 'n/a'), one score term
  set to its neutral value, or one recall route dropped. Patching is in-process and
  temporary; the ranking code itself is never changed.
- ``exposure_report``: adoption / not-applicable / revert rates by remedy rule × surface
  from app.db (``rec_exposure`` + ``label`` + ``tracking``), on top of
  ``outcomes.metrics_ev05``.

A relevance target is an exact rec_key or a selector such as
``type=permission_friction&kind=permission_rule`` (problem type, kind, dim, source origin).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime
from unittest import mock

from .ranking import gates as gate_mod
from .ranking import rank as rank_mod

K = 3
DAY_MS = 86_400_000
HORIZON_DAYS = 14
EMPTY_MEMORY = {"now": 0, "state": {}, "labels": {}, "muted_kb_rules": [], "muted_problem_types": [],
                "weights": {}, "posteriors": {}, "level": None, "settings": {}}
# Neutral value per RC-04 score factor (EV-05.2 names: wilson_lo → confidence,
# prior_p → p_effective, setup_minutes → cost).
TERMS = {"benefit": 1., "confidence": 1., "p_effective": 1., "fit": 1., "cost": 0., "risk": 0.,
         "personal": 1., "decay": 1.}
# Contribution bundles: RC-09 = resource-library matching routes; RC-17 = personalisation
# (level gate, not-applicable memory, personal weights, exposure decay).
BUNDLES = {"RC-09": {"routes": ("catalog", "feature")},
           "RC-17": {"gates": ("audience_ok", "not_dismissed"), "terms": ("personal", "decay")}}
NA_RATE_MAX, NA_RATE_DOWNWEIGHT, MIN_SHOWN = .3, .5, 10


# --- relevance ------------------------------------------------------------------------

def parse_ts(value) -> int:
    """Epoch ms from int ms or ISO-8601 (``Z`` allowed)."""
    if isinstance(value, (int, float)):
        return int(value)
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)


def _fields(cand: dict) -> dict:
    problem = cand.get("problem") or {}
    return {"rec_key": cand.get("rec_key"), "type": problem.get("type") or cand.get("problem_type"),
            "kind": cand.get("kind"), "dim": cand.get("dim"), "origin": (cand.get("source") or {}).get("origin")}


def matches(target: str, cand: dict) -> bool:
    fields = _fields(cand)
    if "=" not in target:
        return target == fields["rec_key"]
    return all(fields.get(k) == v for k, v in (part.split("=", 1) for part in target.split("&")))


def gains(top: list[dict], relevant: dict[str, int]) -> list[int]:
    """Graded gain per position; each relevant target is credited once."""
    unused, out = dict(relevant), []
    for cand in top:
        hit = max((t for t in unused if matches(t, cand)), key=lambda t: unused[t], default=None)
        out.append(unused.pop(hit) if hit else 0)
    return out


def ndcg(gain: list[int], relevant: dict[str, int], k: int = K) -> float:
    dcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gain[:k]))
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.


def top_k(slate: dict, k: int = K) -> list[dict]:
    """Ranked cards in display order: AI ``display_rank`` when present, else ``rank``."""
    ranked = [c for c in slate.get("candidates") or [] if c.get("rank")]
    return sorted(ranked, key=lambda c: (c.get("display_rank") or c["rank"], c["rank"]))[:k]


# --- time-split replay (EV-05.1) -------------------------------------------------------

def _default_build() -> Callable:
    from .engine import build_slate
    return build_slate


def _sessions(cand: dict) -> int:
    problem = cand.get("problem") or {}
    return problem.get("sessions") or len((cand.get("evidence") or {}).get("session_uids") or [])


def _memory_at(t: int, user: dict, inputs: dict, build: Callable) -> dict:
    """Memory as of t: earlier adoptions are installed, earlier not-applicable labels stand."""
    adopted = [a["target"] for a in user.get("adoptions") or [] if parse_ts(a["ts"]) < t]
    declined = [lb for lb in user.get("labels") or [] if parse_ts(lb["ts"]) < t]
    memory = EMPTY_MEMORY | {"now": t} | (user.get("memory") or {})
    if not adopted and not declined:
        return memory
    state, labels = dict(memory["state"]), dict(memory["labels"])
    for cand in build(inputs, memory)["candidates"]:
        key = cand["rec_key"]
        if any(matches(target, cand) for target in adopted):
            state[key] = {"status": "installed", "install_id": f"replay:{key}"}
        for lb in declined:
            if matches(lb["target"], cand):
                state[key] = {"status": lb.get("label", "not_applicable"),
                              "last_evidence": _sessions(cand)}
                labels.setdefault(key, []).append({"label": lb.get("label", "not_applicable"),
                                                   "ts": parse_ts(lb["ts"])})
    return memory | {"state": state, "labels": labels}


def link_cases(users: list[dict], cases: list[dict]) -> list[dict]:
    """Resolve ``cutoff.case`` (a replay case id) to that case's inputs."""
    by_id = {c["id"]: c["inputs"] for c in cases}
    return [{**u, "cutoffs": [{**c, "inputs": c.get("inputs") or by_id[c["case"]]}
                              for c in u.get("cutoffs") or []]} for u in users]


def _check_no_leak(user_id: str, t: int, inputs: dict) -> None:
    last = (inputs.get("sessions") or {}).get("last_ts")
    if last is not None and parse_ts(last) >= t:
        raise ValueError(f"{user_id}: inputs at cutoff {t} include data from {last}")


def time_split(users: list[dict], *, build: Callable | None = None,
               rerank: Callable[[dict], None] | None = None, horizon_days: int = HORIZON_DAYS,
               k: int = K) -> dict:
    """users = [{id, cutoffs:[{t, inputs}], adoptions:[{ts, target, grade?}], labels?:[...]}].

    A cutoff without any adoption inside its horizon has no label and is skipped.
    ``repeat_na`` = a top-k card the user had already marked not applicable before t."""
    build = build or _default_build()
    rows = []
    for user in users:
        for cutoff in user.get("cutoffs") or []:
            t, inputs = parse_ts(cutoff["t"]), cutoff["inputs"]
            _check_no_leak(user["id"], t, inputs)
            end = t + horizon_days * DAY_MS
            relevant: dict[str, int] = {}
            for a in user.get("adoptions") or []:
                if t <= parse_ts(a["ts"]) < end:
                    relevant[a["target"]] = max(relevant.get(a["target"], 0), int(a.get("grade", 1)))
            if not relevant:
                continue
            memory = _memory_at(t, user, inputs, build)
            slate = build(inputs, memory)
            if rerank is not None:
                rerank(slate)
            top = top_k(slate, k)
            gain = gains(top, relevant)
            declined = {key for key, s in memory["state"].items() if s.get("status") == "not_applicable"}
            rows.append({"user": user["id"], "t": t, "top": [c["rec_key"] for c in top],
                         "hit": any(gain), "ndcg": round(ndcg(gain, relevant, k), 4),
                         "repeat_na": bool(declined & {c["rec_key"] for c in top}) if declined else None})
    return summarize(rows)


def summarize(rows: list[dict]) -> dict:
    n = len(rows) or 1
    na = [r["repeat_na"] for r in rows if r["repeat_na"] is not None]
    return {"hit_rate@3": round(sum(r["hit"] for r in rows) / n, 4),
            "ndcg@3": round(sum(r["ndcg"] for r in rows) / n, 4),
            "repeat_na@3": round(sum(na) / len(na), 4) if na else None,
            "cutoffs": len(rows), "per_cutoff": rows}


# --- AI rerank through the rerank.fit task contract -----------------------------------

class _TaskRunner:
    """Stands in for ``ai.service(gw)``: runs rerank.fit's prompt / validate / finalize
    against one engine, without app.db, consent or a job ledger."""

    def __init__(self, engine):
        self.engine = engine

    def run(self, task_id: str, slots: dict | None = None, scope=None, timeout: float = 60) -> dict:
        from ..ai.engines import EngineRequest
        from ..ai.generate import rerank as task

        pack = {"content": dict(slots or {})}
        spec = task.TASK
        result = self.engine.call(EngineRequest(system=spec["system"], prompt=spec["build_prompt"](pack),
                                                schema=spec["schema"], task_id=task_id,
                                                timeout_s=timeout))
        if result.error or result.output is None or spec["validate"](result.output, pack):
            out = spec["finalize"](spec["fallback"](pack, result.error or "invalid"), pack, "fallback")
        else:
            out = spec["finalize"](result.output, pack, self.engine.id)
        return {**out, "job_id": f"eval-{len(getattr(self.engine, 'requests', []))}"}


def engine_rerank(engine) -> Callable[[dict], None]:
    """``rerank`` hook for ``time_split``: the production ``runs.ai_rerank`` on this engine."""
    from types import SimpleNamespace

    from .runs import ai_rerank

    gw = SimpleNamespace(_ai=_TaskRunner(engine))
    return lambda slate: ai_rerank(gw, slate, {})


# --- ablation (EV-05.2, RC-09 / RC-17) ------------------------------------------------

def _na(raw, inputs, memory):
    return gate_mod.NA, ""


def _neutral_score(original: Callable, terms: tuple[str, ...]) -> Callable:
    """Recompute rank.score's priority with ``terms`` at their neutral value (RC-05 formula)."""

    def score(raw, gates, inputs, memory, *, max_fusion=None):
        s = original(raw, gates, inputs, memory, max_fusion=max_fusion)
        f = {**s, **{t: TERMS[t] for t in terms}}
        net = f["benefit"] * f["confidence"] * f["p_effective"] * f["fit"] / (1 + f["cost"]) - .1 * f["risk"]
        scale = f["personal"] * f["decay"]
        return {**f, "priority": round(100 * max(0., net) * scale, 2), "utility": round(net * scale, 6)}

    return score


@contextmanager
def ablated(*, gates: tuple[str, ...] = (), terms: tuple[str, ...] = (),
            routes: tuple[str, ...] = ()) -> Iterator[Callable]:
    """Yield a ``build(inputs, memory)`` with the named gates / terms / routes switched off."""
    unknown = (set(gates) - set(gate_mod.CHECKS)) | (set(terms) - set(TERMS))
    if unknown:
        raise ValueError(f"unknown ablation: {sorted(unknown)}")
    build = _default_build()
    with ExitStack() as stack:
        if gates:
            stack.enter_context(mock.patch.dict(gate_mod.CHECKS, dict.fromkeys(gates, _na)))
        if terms:
            stack.enter_context(mock.patch.object(rank_mod, "score", _neutral_score(rank_mod.score, terms)))
        if not routes:
            yield build
            return
        from .recall.multi import recall_all

        def recall(inputs, memory, catalog=None, **kw):
            rr = recall_all(inputs, memory, catalog=catalog, **kw)
            keep = [c for c in rr["candidates"] if set(c.get("routes") or {}) - set(routes)]
            return {**rr, "candidates": keep}

        yield lambda inputs, memory, **kw: build(inputs, memory, recall=recall, **kw)


def replay_cases(cases: list[dict], build: Callable, k: int = K) -> dict:
    """Static replay over ``{id, inputs, memory?, relevant}`` cases (EV-05.1 v0)."""
    rows = []
    for case in cases:
        top = top_k(build(case["inputs"], EMPTY_MEMORY | (case.get("memory") or {})), k)
        gain = gains(top, case["relevant"])
        rows.append({"user": case["id"], "t": None, "top": [c["rec_key"] for c in top], "hit": any(gain),
                     "ndcg": round(ndcg(gain, case["relevant"], k), 4), "repeat_na": None})
    return summarize(rows)


def _metrics(cases: list[dict], users: list[dict], build: Callable) -> dict:
    replay, split = replay_cases(cases, build), time_split(users, build=build)
    return {"replay.hit_rate@3": replay["hit_rate@3"], "replay.ndcg@3": replay["ndcg@3"],
            "split.hit_rate@3": split["hit_rate@3"], "split.ndcg@3": split["ndcg@3"],
            "split.repeat_na@3": split["repeat_na@3"]}


def _verdict(delta: dict) -> str:
    """Switching the part off → keep (only hurts), hurts (only helps), mixed, or no_effect
    (EV-05.2: nothing moves, a removal candidate). A higher repeat_na counts as a loss."""
    signs = [v for m, v in delta.items() if v and "repeat_na" not in m]
    signs.append(-(delta.get("split.repeat_na@3") or 0))
    down, up = any(v < 0 for v in signs), any(v > 0 for v in signs)
    return {(True, False): "keep", (False, True): "hurts", (True, True): "mixed"}.get((down, up), "no_effect")


def ablation_report(cases: list[dict], users: list[dict]) -> dict:
    """Deltas (ablated − baseline) for every gate, score term and RC-09 / RC-17 bundle."""
    with ablated() as build:
        base = _metrics(cases, users, build)
    plan = ([("gate", g, {"gates": (g,)}) for g in gate_mod.CHECKS]
            + [("term", t, {"terms": (t,)}) for t in TERMS]
            + [("bundle", name, spec) for name, spec in BUNDLES.items()])
    rows = []
    for kind, name, spec in plan:
        with ablated(**spec) as build:
            got = _metrics(cases, users, build)
        delta = {m: None if got[m] is None or base[m] is None else round(got[m] - base[m], 4) for m in base}
        rows.append({"kind": kind, "name": name, "delta": delta, "verdict": _verdict(delta)})
    return {"baseline": base, "rows": rows}


# --- exposure metrics (EV-05) ---------------------------------------------------------

def exposure_report(conn, days: int = 90, now: int | None = None) -> dict:
    """Rates by remedy rule × surface; groups shown fewer than 10 times only report n."""
    from .outcomes import metrics_ev05

    rows, flagged = [], []
    for row in metrics_ev05(conn, days, now):
        small = row["shown"] < MIN_SHOWN
        out = {"remedy_rule": row["group"], "surface": row["surface"], "n": row["shown"],
               **{k: row[k] for k in ("opened", "installed", "not_applicable", "reverted")},
               **{k: None if small else row[k] for k in ("adoption_rate", "na_rate", "revert_rate")}}
        if not small and (row["na_rate"] or 0) > NA_RATE_DOWNWEIGHT:
            flagged.append(row["group"])  # RC-10 rule-level downweight + RC-01 revision list
        rows.append(out)
    rated = [r for r in rows if r["na_rate"] is not None]
    worst = max((r["na_rate"] for r in rated), default=None)
    return {"rows": rows, "rated_groups": len(rated), "max_na_rate": worst,
            "na_rate_ok": worst is None or worst <= NA_RATE_MAX, "downweight": sorted(set(flagged))}
