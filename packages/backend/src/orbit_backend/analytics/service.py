"""One feature engine for CLI, API, session rows and project aggregates.

Sections are computed lazily: an endpoint asks only for what it returns. Per-session rows
are pure functions of their own session tree, so they can be reused from ``session_result``
(see ``cache.py``) and recomputed in parallel; cross-session fields (tasks, preferences,
text coordinates) and global metadata are attached when rows are assembled.
"""

import json
import os
import pickle
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import asdict
from multiprocessing import get_context
from typing import Protocol

from orbit_data.coverage import dataset_coverage

from ..models import stable_id
from ..recommend.service import recommend as recommend_resources
from . import FEATURE_VERSION
from .common import human
from .context import AnalysisContext, Record
from .coverage import build_coverage_report
from .dictionary import FEATURES
from .features import activity, session_features, tool_summary, usage, workflow
from .inputs import AnalysisInputBundle, Scope, legacy_bundle, metadata
from .instruction import (
    INSTRUCTION_VERSION,
    extract_instruction_constraints,
    summarize_control_patterns,
)
from .outcome_subjective import aggregate_subjective_outcomes
from .preference import PREFERENCE_EVIDENCE_VERSION, PREFERENCE_VERSION
from .semantic import SemanticAnalysis, analyze_semantics
from .task.representation import representation
from .task.taxonomy import TAXONOMY_VERSION
from .work_graph import WorkIndex

# Endpoint sections, in the order of the complete result.
SECTIONS = (
    "overview",
    "sessions",
    "tools",
    "workflow",
    "projects",
    "text",
    "bottleneck_features",
    "tasks",
    "preferences",
    "instruction",
    "work_graph",
    "lexical",
    "statistics",
    "bottleneck_recommendations",
)
META = "meta"  # every remaining top-level key (scope, coverage, digests, samples ...)
SHARED_KEYS = (
    "input_contract",
    "feature_schema_version",
    "scope",
    "coverage",
    "versions",
    "sample_boundary",
    "selection",
    "effective_samples",
    "unknown_counts",
    "analysis_digest",
    "feature_dictionary",
    "source_coverage",
    "coverage_report",
)
LIMITATIONS = [
    "日志跨度不是实际工作时长",
    "词面纠偏和结构约束只是代理信号",
    "缺少事件不等于没有发生；未知保持 null",
    "聚类和坐标不带人格或任务成功含义",
]
# Sections whose value is the same with and without the text representation; a
# ``with_text=True`` computation also serves the ``with_text=False`` request of the scope.
TEXT_FREE_SECTIONS = (
    "overview",
    "tools",
    "workflow",
    "bottleneck_features",
    "tasks",
    "instruction",
    "lexical",
)


def _unknown_model_calls(model_calls) -> int | None:
    """Request rows whose usage cannot be attributed: invalid rows + conflicting request ids.

    Same rule as ``cost_time.tokens.prepare_requests`` (the basis of every usage metric), so
    the unknown count matches what the usage numbers actually dropped. ``None`` = no source.
    """
    if model_calls is None:
        return None
    from .cost_time.tokens import prepare_requests

    prepared = prepare_requests(model_calls)
    return prepared["invalid_request_rows"] + len(prepared["conflicting_request_ids"])


def text_variant_meta(meta: Record, content_digest, with_text: bool) -> Record:
    """``meta`` as the other ``with_text`` variant reports it (only the digest differs)."""
    from .products.contracts import rule_versions

    return {**meta, "analysis_digest": stable_id(content_digest, rule_versions(), with_text)}


# Row fields that depend on other sessions or on the whole selection; never cached per row.
CROSS_SESSION_FIELDS = (
    "coverage",
    "cluster_id",
    "novelty",
    "embedding_x",
    "embedding_y",
    "task_ids",
    "preference_ids",
    "preference_evidence_ids",
)
ENTITY = "_text_entity"  # private: the session's prompt text for the text representation
BOTTLENECK_COVERAGE = ("events", "tool_calls", "model_calls", "turns", "lineage")

# Parallel cold computation: only worth the process start-up for many misses.
PARALLEL_MIN_MISSES = 300
PARALLEL_CHUNK = 200
# Fewer idle cores than this and spawn/pickle overhead outweighs the parallel gain.
PARALLEL_MIN_WORKERS = 3
# Sections the parent computes while workers run the whole-selection jobs.
PARENT_FIRST = ("tools", "workflow", "overview", "instruction", "text", "projects")
# Observable counters (tests and the status endpoint): rows computed vs reused.
ROW_STATS: Counter = Counter()


class RowCache(Protocol):
    """Lookup/store hooks for materialized session rows (implemented in cache.py)."""

    def get(self, context: AnalysisContext, session_uids: list[str]) -> dict[str, Record]: ...

    def put(self, context: AnalysisContext, rows: dict[str, Record]) -> None: ...


def _row_sessions(context: AnalysisContext) -> list[Record]:
    """Rows exist for every selected session that is not a delegated child."""
    return [s for s in context.sessions if s.get("kind") not in ("subagent", "workflow_agent")]


def session_row_core(context: AnalysisContext, s: Record) -> Record:
    """Compute one session row from its own tree only; the result is cacheable.

    Global coverage and cross-session fields are attached later by ``assemble_row``.
    """
    bundle, scope = context.bundle, context.scope
    sid = s["session_uid"]
    calls, model_calls = context.calls, context.model_calls
    main_ids = context.main_ids
    supported, event_status = context.supported_kinds, context.event_status
    complete_models = bundle.coverage.get("model_calls", {}).get("status") == "available"
    groups, call_groups, children = context.event_groups, context.call_groups, context.children
    instruction_available = bundle.events is not None
    included = {sid} | (children[sid] if scope.include_children else set())
    own = groups[sid]
    root_events = [e for member in sorted(included) for e in groups[member]]
    context_events = context.tree_context_events(included)
    root_calls = (
        None if calls is None else [c for member in sorted(included) for c in call_groups[member]]
    )
    data = session_features(
        s,
        own,
        root_calls,
        main_ids,
        supported,
        event_status,
        scope.display_timezone,
        with_workflow=False,
    )
    data["workflow"] = workflow(root_events + context_events, root_calls, main_ids, supported)
    data["usage"] = usage(
        None if model_calls is None else context.members(included, "models"),
        root_events,
        context.tree_sessions(included),
        scope,
        complete_models,
    )
    tool_status = bundle.coverage.get("tool_calls", {}).get("status", "partial")
    # Partial dataset coverage is about pairing quality of observed calls; a session whose
    # own calls were read and are empty observed zero calls (null is for unavailable data).
    data["tools"] = tool_summary(
        root_calls, "available" if root_calls == [] and tool_status == "partial" else tool_status
    )
    # Instruction records are per human message, so the session's own records equal the
    # session's slice of a global extraction.
    records = extract_instruction_constraints(own, main_ids=main_ids)
    data["instruction"] = {
        "schema_version": INSTRUCTION_VERSION,
        "records": records if instruction_available else None,
        "summary": summarize_control_patterns(records, source_available=instruction_available),
    }
    families = dict(context.families(included))
    families.pop("source_coverage", None)  # global coverage, re-attached on assembly
    data["bottleneck_features"] = families
    prompts = [e for e in own if human(e, main_ids) and e.get("text")]
    entity = None
    if prompts:
        # Session text is available only after its last contributing prompt.
        # If any prompt is unclocked, temporal novelty is unavailable.
        ts = (
            max(e["ts"] for e in prompts) if all(e.get("ts") is not None for e in prompts) else None
        )
        entity = {"entity_id": sid, "text": "\n".join(e["text"] for e in prompts), "ts": ts}
    return {**s, **data, "included_session_uids": sorted(included), ENTITY: entity}


def _chunk_bundle(context: AnalysisContext, sids: list[str]) -> tuple:
    """Pickle only the trees of one chunk for a worker process."""
    wanted = set(sids)
    for sid in sids:
        if context.scope.include_children:
            wanted |= context.children[sid]
    sessions = [s for s in context.sessions if s["session_uid"] in wanted]

    def pick(rows: list[Record] | None) -> list[Record] | None:
        return None if rows is None else [r for r in rows if r["session_uid"] in wanted]

    bundle = context.bundle
    sub = AnalysisInputBundle(
        sessions,
        None if bundle.events is None else pick(context.events),
        pick(context.calls),
        pick(context.model_calls),
        bundle.coverage,
        versions=bundle.versions,
    )
    diagnostics = {"context_events": pick(context.diagnostics["context_events"])}
    return (sub, context.scope, sessions, pick(context.events), diagnostics, sids)


def _compute_chunk(payload: tuple) -> dict[str, Record]:
    """Worker entry point: rebuild a tree-local context and compute its rows."""
    bundle, scope, sessions, events, diagnostics, sids = payload
    # Rows were projected by the parent; session rows never read the task index itself.
    projected = WorkIndex(None, events, bundle.tool_calls, bundle.model_calls, {}, {}, {})
    context = AnalysisContext(
        bundle, scope, sessions, events, bundle.tool_calls, bundle.model_calls, diagnostics, projected
    )
    return {sid: session_row_core(context, context.session_map[sid]) for sid in sids}


# Each spawned worker holds its chunk's trees on top of the parent's whole selection, so
# memory grows with the worker count while the speed-up flattens after a few processes.
DEFAULT_MAX_WORKERS = 4


def _idle_cores() -> int:
    """Cores not already claimed by runnable work: ``cpu_count - 1-minute load``.

    On a busy machine spawned workers only time-slice with the existing load while
    paying start-up and pickling, so the serial path is faster there.
    """
    cpus = os.cpu_count() or 1
    try:
        load = os.getloadavg()[0]
    except (AttributeError, OSError):  # platforms without a load average
        return cpus
    return max(1, min(cpus, int(cpus - load)))


def _max_workers() -> int:
    limit = os.environ.get("ORBIT_ANALYSIS_WORKERS")  # "0"/"1" disables process workers
    if limit and limit.isdigit():
        return int(limit)
    return max(1, min(_idle_cores(), DEFAULT_MAX_WORKERS))


# Above this many selected events the pool is skipped: every worker unpickles its chunk's
# trees next to the parent's whole selection, and on a real home (30 days ≈ 450k events)
# the process tree peaked at 16 GB for a ~2x speed-up of the row step only.
PARALLEL_MAX_EVENTS = 150_000


def _parallel_max_events() -> int:
    value = os.environ.get("ORBIT_ANALYSIS_PARALLEL_MAX_EVENTS")
    return int(value) if value and value.isdigit() else PARALLEL_MAX_EVENTS


def _wants_parallel(misses: int, parallel: bool | None, events: int = 0) -> bool:
    if parallel is None:
        if misses < PARALLEL_MIN_MISSES or events > _parallel_max_events():
            return False
        limit = os.environ.get("ORBIT_ANALYSIS_WORKERS")
        floor = 2 if limit and limit.isdigit() else PARALLEL_MIN_WORKERS
        return _max_workers() >= floor
    return parallel


def _context_blob(context: AnalysisContext) -> bytes:
    """Pickle the whole selection once; several whole-selection jobs share the bytes."""
    return pickle.dumps(
        (
            context.bundle,
            context.scope,
            context.sessions,
            context.events,
            context.calls,
            context.model_calls,
            context.diagnostics,
            context.work_index,
        ),
        protocol=pickle.HIGHEST_PROTOCOL,
    )


def _whole_selection_job(blob: bytes, job: str, scopes: list[tuple[str, ...]] | None = None):
    """Worker entry point for one cross-session piece computed from the whole selection.

    Every job is a pure function of the selection, so the worker result equals the
    serial result; the parent only stores it where the lazy section would have.
    """
    context = AnalysisContext(*pickle.loads(blob))
    if job == "families":
        return context.families(set(context.session_map))
    if job == "scoped_families":
        return {key: context.families(set(key)) for key in scopes or []}
    if job == "semantic":
        return analyze_semantics(context)
    if job == "lexical":
        from .products.lexical import lexical_analysis

        return lexical_analysis(context)
    raise ValueError(f"Unknown analysis job: {job}")


def _spawn_pool(workers: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(workers, mp_context=get_context("spawn"))


def _release_pool(executor: ProcessPoolExecutor) -> None:
    # Every future has been collected; do not block on idle workers exiting.
    executor.shutdown(wait=False)


def compute_row_cores(
    context: AnalysisContext,
    sids: list[str],
    *,
    parallel: bool | None = None,
    executor: ProcessPoolExecutor | None = None,
) -> dict[str, Record]:
    """Compute rows serially, or by root chunks in spawned processes when there are many.

    ``executor`` lets a caller share one pool with other whole-selection jobs.
    """
    parallel = executor is not None or _wants_parallel(
        len(sids), parallel, len(context.events or ())
    )
    ROW_STATS["computed"] += len(sids)
    if parallel and len(sids) > 1:
        chunks = [sids[i : i + PARALLEL_CHUNK] for i in range(0, len(sids), PARALLEL_CHUNK)]
        own = executor is None
        try:
            pool = _spawn_pool(max(1, min(len(chunks), _max_workers()))) if own else executor
            try:
                results = pool.map(_compute_chunk, [_chunk_bundle(context, c) for c in chunks])
                cores = {}
                for result in results:
                    cores.update(result)
            finally:
                if own:
                    _release_pool(pool)
            ROW_STATS["parallel_chunks"] += len(chunks)
            return cores
        except (OSError, RuntimeError) as error:  # BrokenProcessPool is a RuntimeError
            ROW_STATS["parallel_fallbacks"] += 1
            ROW_STATS[f"parallel_error:{type(error).__name__}"] += 1
    session_map = context.session_map
    return {sid: session_row_core(context, session_map[sid]) for sid in sids}


def assemble_row(
    core: Record,
    coverage: Record,
    source_coverage: Record,
    semantic: SemanticAnalysis | None,
    semantic_available: bool,
    projection: Record | None,
) -> Record:
    """Attach selection-wide fields to a cached or fresh row without mutating it."""
    sid = core["session_uid"]
    row = {k: v for k, v in core.items() if k != ENTITY}
    row["bottleneck_features"] = {**core["bottleneck_features"], "source_coverage": source_coverage}
    row["coverage"] = coverage
    row.update(cluster_id=None, novelty=None, embedding_x=None, embedding_y=None)
    if semantic is None:
        row.update(task_ids=None, preference_ids=None, preference_evidence_ids=None)
    else:
        row["task_ids"] = semantic.task_ids[sid] if semantic_available else None
        row["preference_ids"] = semantic.preference_ids[sid] if semantic_available else None
        row["preference_evidence_ids"] = (
            semantic.preference_evidence_ids[sid] if semantic_available else None
        )
    row.update({k: v for k, v in (projection or {}).items() if k != "entity_id"})
    return row


def _project_rows(
    context: AnalysisContext, rows: list[Record], instruction_groups: dict, tool_status: str
) -> list[Record]:
    """Recompute project denominators instead of averaging session rates.

    One pass assigns every event/call to its project (O(E)), instead of scanning all
    events once per project.
    """
    bundle, scope = context.bundle, context.scope
    sessions, events, calls, model_calls = (
        context.sessions,
        context.events,
        context.calls,
        context.model_calls,
    )
    main_ids = context.main_ids
    event_status = context.event_status
    complete_models = bundle.coverage.get("model_calls", {}).get("status") == "available"
    instruction_available = bundle.events is not None
    by_project = defaultdict(list)
    for r in rows:
        by_project[(r.get("project_id"), r.get("legacy_project_id"))].append(r)
    owner = {}
    for key, rs in by_project.items():
        for r in rs:
            for sid in r["included_session_uids"]:
                owner.setdefault(sid, key)

    def split(records: Iterable[Record] | None) -> dict | None:
        if records is None:
            return None
        grouped = defaultdict(list)
        for record in records:
            key = owner.get(record["session_uid"])
            if key is not None:
                grouped[key].append(record)
        return grouped

    project_events, project_calls = split(events), split(calls)
    project_models, project_sessions = split(model_calls), split(sessions)
    names = {
        (p.get("project_id"), p.get("legacy_project_id")): p.get("name")
        for p in bundle.projects or []
    }
    projects = []
    for (pid, legacy), rs in sorted(by_project.items(), key=lambda pair: str(pair[0])):
        key = (pid, legacy)
        ids = {sid for r in rs for sid in r["included_session_uids"]}
        pcs = None if project_calls is None else project_calls.get(key, [])
        pe = project_events.get(key, [])
        ph = sum(human(e, main_ids) for e in pe)
        pu = sum(r["unknown_counts"]["human_origin"] for r in rs)
        projects.append(
            {
                "project_id": pid,
                "legacy_project_id": legacy,
                "name": names.get(key),
                "identity_quality": "canonical" if pid is not None else "legacy_path",
                "session_count": len(rs),
                "main_session_count": sum(r["kind"] == "main" for r in rs),
                "human_message_count": ph if ph or not pu else None,
                "effective_samples": {"human_messages": ph},
                "unknown_counts": {"human_origin": pu},
                "turn_count": len(
                    {(e["session_uid"], e["turn_uid"]) for e in pe if e.get("turn_uid")}
                )
                or None,
                "correction_signal_count": sum(
                    r["features"]["correction_signal_count"] or 0 for r in rs
                )
                if ph
                else None,
                "subjective_outcomes": aggregate_subjective_outcomes(
                    [r["subjective_outcomes"] for r in rs], event_status
                ),
                "activity_rhythm": activity([s for s in sessions if s["session_uid"] in ids], pe,
                    pcs, None if model_calls is None else context.members(ids, "models"),
                    main_ids & ids, scope) if bundle.events is not None else None,
                "tools": tool_summary(pcs, tool_status),
                "usage": usage(
                    None if project_models is None else project_models.get(key, []),
                    pe,
                    project_sessions.get(key, []),
                    scope,
                    complete_models,
                ),
                "bottleneck_features": context.families(ids),
                "instruction": summarize_control_patterns(
                    [record for r in rs for record in instruction_groups[r["session_uid"]]],
                    source_available=instruction_available,
                ),
                "cluster_distribution": dict(
                    Counter(str(r["cluster_id"]) for r in rs if r["cluster_id"] is not None)
                ),
            }
        )
    return projects


class AnalysisSections:
    """Lazily computed sections of one analysis request; each piece is computed once."""

    def __init__(
        self,
        context: AnalysisContext,
        with_text: bool = True,
        *,
        row_cache: RowCache | None = None,
        parallel: bool | None = None,
    ):
        self.context = context
        self.with_text = with_text
        self.row_cache = row_cache
        self.parallel = parallel
        self.rows_computed = 0
        self.rows_reused = 0
        self._memo: dict[str, object] = {}
        # Cold parallel computation (see ``_start_jobs``): futures by memo name.
        self._executor: ProcessPoolExecutor | None = None
        self._jobs: dict[str, Future] = {}
        self._row_futures: list[Future] | None = None

    def _once(self, name: str, compute: Callable[[], object]):
        if name not in self._memo:
            future = self._jobs.pop(name, None)
            self._memo[name] = compute() if future is None else self._collect(future, compute)
        return self._memo[name]

    # ---- cold parallel computation --------------------------------------------------

    @staticmethod
    def _collect(future: Future, fallback: Callable[[], object]):
        """A worker result, or the serial computation if the worker pool failed."""
        try:
            return future.result()
        except Exception as error:  # a real computation error re-raises from the fallback
            ROW_STATS["parallel_fallbacks"] += 1
            ROW_STATS[f"parallel_error:{type(error).__name__}"] += 1
            return fallback()

    def _row_plan(self) -> tuple[list[str], dict[str, Record], list[str]]:
        def compute():
            sids = [s["session_uid"] for s in _row_sessions(self.context)]
            cached = self.row_cache.get(self.context, sids) if self.row_cache else {}
            return sids, cached, [sid for sid in sids if sid not in cached]

        return self._once("row_plan", compute)

    def _start_jobs(self, names: list[str]) -> None:
        """On a cold run, compute row chunks and whole-selection pieces in worker processes.

        Workers start on the slowest independent pieces (global families, semantic
        extraction, lexical analysis) while the parent assembles the rest; results are
        collected where the lazy sections would have computed them.
        """
        if self._executor is not None or "cores" in self._memo:
            return
        _, _, missing = self._row_plan()
        events = len(self.context.events or ())
        if not _wants_parallel(len(missing), self.parallel, events) or len(missing) < 2:
            return
        whole = []
        if "bottleneck_features" in names:
            whole.append(("families", "families"))
        if {"sessions", "tasks", "preferences"} & set(names):
            whole.append(("semantic", "semantic"))
        if "lexical" in names:
            whole.append(("section:lexical", "lexical"))
        if "projects" in names:
            whole.append(("project_families", "scoped_families"))
        chunks = [missing[i : i + PARALLEL_CHUNK] for i in range(0, len(missing), PARALLEL_CHUNK)]
        try:
            self._executor = _spawn_pool(max(1, min(len(chunks) + len(whole), _max_workers())))
            if whole:
                blob = _context_blob(self.context)
                for name, job in whole:
                    scopes = self._project_scopes() if job == "scoped_families" else None
                    self._jobs[name] = self._executor.submit(
                        _whole_selection_job, blob, job, scopes
                    )
            self._row_futures = [
                self._executor.submit(_compute_chunk, _chunk_bundle(self.context, chunk))
                for chunk in chunks
            ]
        except (OSError, RuntimeError) as error:
            ROW_STATS["parallel_fallbacks"] += 1
            ROW_STATS[f"parallel_error:{type(error).__name__}"] += 1
            self._finish_jobs()

    def _finish_jobs(self) -> None:
        if self._executor is not None:
            for future in [*self._jobs.values(), *(self._row_futures or [])]:
                future.cancel()
            self._jobs, self._row_futures = {}, None
            _release_pool(self._executor)
            self._executor = None

    def _fresh_rows(self, missing: list[str]) -> dict[str, Record]:
        futures, self._row_futures = self._row_futures, None
        if futures is None:
            return compute_row_cores(self.context, missing, parallel=self.parallel)
        ROW_STATS["computed"] += len(missing)
        try:
            cores = {}
            for future in futures:
                cores.update(future.result())
            ROW_STATS["parallel_chunks"] += len(futures)
            return cores
        except Exception as error:
            ROW_STATS["parallel_fallbacks"] += 1
            ROW_STATS[f"parallel_error:{type(error).__name__}"] += 1
            session_map = self.context.session_map
            return {sid: session_row_core(self.context, session_map[sid]) for sid in missing}

    def _project_scopes(self) -> list[tuple[str, ...]]:
        """Predicted project member sets, mirroring ``_project_rows`` grouping.

        A wrong prediction only wastes worker time: lookups are by exact member set.
        """
        context, members = self.context, defaultdict(set)
        for s in _row_sessions(context):
            sid = s["session_uid"]
            included = {sid} | (context.children[sid] if context.scope.include_children else set())
            members[(s.get("project_id"), s.get("legacy_project_id"))] |= included
        return [tuple(sorted(ids)) for ids in members.values()]

    def _seed_project_families(self) -> None:
        future = self._jobs.pop("project_families", None)
        if future is not None:
            for key, value in self._collect(future, dict).items():
                self.context.seed_families(set(key), value)

    def _all_families(self) -> Record:
        ids = set(self.context.session_map)
        future = self._jobs.pop("families", None)
        if future is not None:
            self.context.seed_families(
                ids, self._collect(future, lambda: self.context.families(ids))
            )
        return self.context.families(ids)

    # ---- shared building blocks -----------------------------------------------------

    @property
    def events_available(self) -> bool:
        return self.context.bundle.events is not None

    @property
    def main_ids(self) -> set[str]:
        return self._once(
            "main_ids",
            lambda: {s["session_uid"] for s in self.context.sessions if s.get("kind") == "main"},
        )

    @property
    def cores(self) -> list[Record]:
        """Session row cores in selection order, reused from the row cache when valid."""

        def compute():
            sids, cached, missing = self._row_plan()
            fresh = self._fresh_rows(missing)
            self.rows_computed, self.rows_reused = len(fresh), len(sids) - len(fresh)
            ROW_STATS["reused"] += self.rows_reused
            if self.row_cache and fresh:
                self.row_cache.put(self.context, fresh)
            return [cached.get(sid) or fresh[sid] for sid in sids]

        return self._once("cores", compute)

    @property
    def semantic(self) -> SemanticAnalysis:
        return self._once("semantic", lambda: analyze_semantics(self.context))

    @property
    def instruction_records(self) -> list[Record]:
        def compute():
            cores = sorted(self.cores, key=lambda core: core["session_uid"])
            return [r for core in cores for r in core["instruction"]["records"] or []]

        return self._once("instruction_records", compute)

    @property
    def instruction_groups(self) -> dict[str, list[Record]]:
        def compute():
            groups = defaultdict(list)
            for record in self.instruction_records:
                groups[record["session_uid"]].append(record)
            return groups

        return self._once("instruction_groups", compute)

    @property
    def instruction_summary(self) -> Record:
        return self._once(
            "instruction_summary",
            lambda: summarize_control_patterns(
                self.instruction_records, source_available=self.events_available
            ),
        )

    @property
    def all_tools(self) -> Record:
        bundle = self.context.bundle
        return self._once(
            "all_tools",
            lambda: tool_summary(
                self.context.calls, bundle.coverage.get("tool_calls", {}).get("status", "partial")
            ),
        )

    @property
    def all_workflow(self) -> Record:
        def compute():
            if not self.events_available:
                return {"status": "unavailable", "transitions": None, "sequences": None}
            context = self.context
            return workflow(
                context.events + context.diagnostics["context_events"],
                context.calls,
                self.main_ids,
                context.supported_kinds,
            )

        return self._once("all_workflow", compute)

    @property
    def human_count(self) -> int:
        return self._once(
            "human_count", lambda: sum(human(e, self.main_ids) for e in self.context.events)
        )

    @property
    def unknown_origin(self) -> int:
        return self._once(
            "unknown_origin",
            lambda: sum(core["unknown_counts"]["human_origin"] for core in self.cores),
        )

    @property
    def meta(self) -> Record:
        """Scope, coverage, digests and sample counts shared by every section."""

        def compute():
            context, bundle, scope = self.context, self.context.bundle, self.context.scope
            diagnostics = context.diagnostics
            meta = metadata(bundle, scope, diagnostics)
            # Source coverage is retained separately from row counts in this selection.
            meta["source_coverage"] = meta["coverage"]
            meta["coverage"] = {k: dict(v) for k, v in bundle.coverage.items()}
            for name, items in (
                ("sessions", context.sessions),
                ("events", context.events if bundle.events is not None else None),
                ("tool_calls", context.calls),
                ("model_calls", context.model_calls),
            ):
                meta["coverage"].setdefault(name, {"status": "unavailable"})["rows"] = (
                    len(items) if items is not None else None
                )
            unknown_origin, human_count = self.unknown_origin, self.human_count
            meta["coverage"]["human_origin"] = {
                **meta["coverage"].get("human_origin", {}),
                **dataset_coverage(
                    human_count if bundle.events is not None else None,
                    reason_counts={"human_origin_unknown": unknown_origin},
                ),
                "unknown_rows": unknown_origin,
            }
            excluded_count = sum(diagnostics["excluded_sessions"].values())
            meta["coverage"]["sample_exclusions"] = dataset_coverage(
                excluded_count,
                excluded=bool(excluded_count),
                reason_counts=diagnostics["excluded_sessions"],
            )
            if bundle.events is None:
                meta["coverage"]["human_origin"] = {
                    **dataset_coverage(None, reasons=["events_unavailable"]),
                    "unknown_rows": None,
                }
            calls, model_calls = context.calls, context.model_calls
            digest = stable_id(
                bundle.versions.get("content_digest"),
                asdict(scope),
                FEATURE_VERSION,
                INSTRUCTION_VERSION,
                TAXONOMY_VERSION,
                PREFERENCE_VERSION,
                PREFERENCE_EVIDENCE_VERSION,
            )
            from .products.contracts import rule_versions

            methods = rule_versions()
            self.content_digest = digest  # lets the cache derive the other text variant
            meta.update(
                {
                    "feature_schema_version": FEATURE_VERSION,
                    "feature_dictionary": FEATURES,
                    "analysis_digest": stable_id(digest, methods, self.with_text),
                    "effective_samples": {
                        "main_sessions": len(self.main_ids),
                        "human_messages": human_count,
                        "tools": len(calls) if calls is not None else None,
                        "text_sessions": sum(core[ENTITY] is not None for core in self.cores),
                    },
                    "unknown_counts": {
                        "human_origin": unknown_origin,
                        "session_kind": sum(
                            s.get("kind") == "unknown" for s in context.sessions
                        ),
                        "timestamp": diagnostics["time_unknown_events"],
                        "model_calls": _unknown_model_calls(model_calls),
                    },
                    "limitations": list(LIMITATIONS),
                    "inventory": bundle.inventory,
                    "inventory_scans": bundle.inventory_scans,
                    "analysis_methods": methods,
                    "coverage_report": build_coverage_report(meta["coverage"]),
                }
            )
            return meta

        return self._once("meta", compute)

    @property
    def source_coverage(self) -> Record:
        coverage = self.context.bundle.coverage
        return {k: coverage.get(k, {"status": "unavailable"}) for k in BOTTLENECK_COVERAGE}

    @property
    def text(self) -> Record:
        def compute():
            entities = [core[ENTITY] for core in self.cores if core[ENTITY] is not None]
            text = (
                representation(entities)
                if self.with_text
                else {"status": "excluded", "coordinates": None, "reason": "调用方禁用文本表示"}
            )
            text["correction_terms"] = dict(
                Counter(
                    term
                    for core in self.cores
                    for signal in core["correction_signals"]
                    for term in signal["terms"]
                )
            )
            return text

        return self._once("text", compute)

    def _projections(self) -> dict[str, Record]:
        if not self.with_text:
            return {}
        return {p["entity_id"]: p for p in self.text.get("coordinates") or []}

    def rows(self, *, semantic: bool) -> list[Record]:
        """Rows before the events-unavailable masking (used by project aggregates)."""

        def compute():
            projections = self._projections()
            analysis = self.semantic if semantic else None
            coverage, source = self.meta["coverage"], self.source_coverage
            return [
                assemble_row(
                    core,
                    coverage,
                    source,
                    analysis,
                    self.events_available,
                    projections.get(core["session_uid"]),
                )
                for core in self.cores
            ]

        return self._once(f"rows:{semantic}", compute)

    def published_rows(self, *, semantic: bool = True) -> list[Record]:
        """Rows as returned; unavailable events mask event-derived fields."""

        def compute():
            rows = self.rows(semantic=semantic)
            if self.events_available:
                return rows
            masked = []
            for row in rows:
                features = {
                    k: (v if k == "tool_call_count" else None) for k, v in row["features"].items()
                }
                masked.append(
                    {
                        **row,
                        "features": features,
                        "prompt_structure": None,
                        "subjective_outcome_candidates": None,
                        "workflow": None,
                    }
                )
            return masked

        return self._once(f"published:{semantic}", compute)

    # ---- sections ---------------------------------------------------------------------

    def _overview(self) -> Record:
        context, bundle, scope = self.context, self.context.bundle, self.context.scope
        events, sessions = context.events, context.sessions
        cores, human_count, unknown_origin = self.cores, self.human_count, self.unknown_origin
        correction = sum(core["features"]["correction_signal_count"] or 0 for core in cores)
        counts = {
            "sessions": len(sessions),
            "main_sessions": len(self.main_ids),
            "session_kind_unknown": sum(s.get("kind") == "unknown" for s in sessions),
            "human_messages": human_count if human_count or not unknown_origin else None,
            "human_origin_unknown": unknown_origin,
            "events": len(events),
            "turns": len({(e["session_uid"], e["turn_uid"]) for e in events if e.get("turn_uid")})
            or None,
            "correction_signals": correction if human_count else None,
            "correction_signal_rate": correction / human_count if human_count else None,
        }
        languages = Counter()
        for core in cores:
            languages.update({v["language"]: v["count"] for v in core["language_signals"]})
        rhythm = activity(
            sessions, events, context.calls, context.model_calls, self.main_ids, scope
        )
        if bundle.events is None:
            counts.update(events=None, human_messages=None, turns=None, correction_signals=None)
            rhythm = None
        complete_models = bundle.coverage.get("model_calls", {}).get("status") == "available"
        all_tools = self.all_tools
        return {
            "instruction": self.instruction_summary,
            "counts": counts,
            "usage": usage(context.model_calls, events, sessions, scope, complete_models),
            "activity_rhythm": rhythm,
            "subjective_outcomes": aggregate_subjective_outcomes(
                [core["subjective_outcomes"] for core in cores], context.event_status
            ),
            "top_tools": (all_tools["by_tool"] or [])[:10]
            if all_tools["by_tool"] is not None
            else None,
            "top_languages": [
                {"language": k, "count": n, "basis": "file_extension_in_human_text"}
                for k, n in languages.most_common()
            ]
            if bundle.events is not None and (human_count or not unknown_origin)
            else None,
        }

    def _preferences(self) -> Record:
        """Preference evidence reuses the optional session clusters of the text section."""
        preferences = self.semantic.preferences
        if preferences.get("evidence") is None:
            return preferences
        projections = self._projections()
        return {
            **preferences,
            "evidence": [
                {**item, "cluster_id": projections.get(item["session_uid"], {}).get("cluster_id")}
                for item in preferences["evidence"]
            ],
        }

    def _statistics(self) -> Record:
        from .products.statistics import statistical_analysis

        base = {
            "sessions": self.published_rows(semantic=False),
            "bottleneck_features": self.section("bottleneck_features"),
        }
        return statistical_analysis(self.context, base)

    def _builders(self) -> dict[str, Callable[[], object]]:
        def lexical():
            from .products.lexical import lexical_analysis

            return lexical_analysis(self.context)

        return {
            "overview": self._overview,
            "sessions": lambda: self.published_rows(semantic=True),
            "tools": lambda: {
                **self.all_tools,
                "transitions": self.all_workflow["transitions"],
            },
            "workflow": lambda: self.all_workflow,
            "projects": lambda: self._seed_project_families()
            or _project_rows(
                self.context,
                self.rows(semantic=False),
                self.instruction_groups,
                self.all_tools["status"],
            ),
            "text": lambda: self.text,
            "bottleneck_features": self._all_families,
            "tasks": lambda: self.semantic.tasks,
            "preferences": self._preferences,
            "instruction": lambda: {
                "schema_version": INSTRUCTION_VERSION,
                "records": self.instruction_records if self.events_available else None,
                "summary": self.instruction_summary,
            },
            "work_graph": self._work_graph,
            "lexical": lexical,
            "statistics": self._statistics,
            "bottleneck_recommendations": lambda: recommend_resources(
                self.full(with_recommendations=False)
            ),
        }

    def _work_graph(self) -> Record:
        from .work_graph.graph import build_work_graph

        context = self.context
        families = context.families(set(context.session_map))
        return build_work_graph(context.work_index, context.sessions, families["respond"],
                                families["outcome"], self.instruction_records,
                                self.semantic.preferences["evidence"], event_status=context.event_status,
                                context_events=context.diagnostics["context_events"],
                                interaction=families["interaction"])

    def section(self, name: str):
        """Compute one section (and only its dependencies)."""
        if name == META:
            return self.meta
        if name not in SECTIONS:
            raise KeyError(f"Unknown analysis section: {name}")
        return self._once(f"section:{name}", self._builders()[name])

    def full(self, with_recommendations: bool = True) -> Record:
        """The complete result, identical to the historical single-pass engine."""
        names = [n for n in SECTIONS if with_recommendations or n != "bottleneck_recommendations"]
        if self._executor is None and "cores" not in self._memo:
            self._start_jobs(names)
            try:
                # Parent-side sections first, so worker results are ready when needed.
                for name in sorted(names, key=_parent_first):
                    self.section(name)
            finally:
                self._finish_jobs()
        return compose(self.meta, {name: self.section(name) for name in names})


def _parent_first(name: str) -> int:
    return PARENT_FIRST.index(name) if name in PARENT_FIRST else len(PARENT_FIRST)


def compose(meta: Record, sections: dict) -> Record:
    """Merge shared metadata and sections into the public result shape."""
    return {**meta, **sections}


def analyze_bundle(
    bundle: AnalysisInputBundle,
    scope: Scope | None = None,
    with_text: bool = True,
    *,
    with_recommendations: bool = True,
) -> Record:
    """Compute all eight families; optional recommendation work stays at the boundary."""
    scope = scope or Scope()
    context = AnalysisContext.select(bundle, scope)
    return analyze_context(context, with_text, with_recommendations=with_recommendations)


def analyze_context(
    context: AnalysisContext, with_text: bool = True, *, with_recommendations: bool = True
) -> Record:
    """Compose family results from an already selected, indexed request."""
    return AnalysisSections(context, with_text).full(with_recommendations)


def analyze_store(store, scope: Scope | None = None, with_text: bool = True) -> Record:
    """Adapt canonical or legacy storage before entering the pure analysis engine.

    Canonical stores go through the read-through cache; legacy ``--db`` stores, which have
    no fingerprints, are computed and recorded as before.
    """
    from .cache import AnalysisCache, supports_cache

    scope = scope or Scope()
    if supports_cache(store):
        return AnalysisCache(store).full(scope, with_text)
    from .history import recorded

    def compute():
        bundle = (
            store.analysis_bundle(scope)
            if hasattr(store, "analysis_bundle")
            else legacy_bundle(store)
        )
        return analyze_bundle(bundle, scope, with_text)

    return recorded(store, "features", {"scope": asdict(scope), "with_text": with_text}, compute)


def analyze_sections(
    store, scope: Scope | None, sections: Iterable[str], with_text: bool = False
) -> Record:
    """Only the requested sections plus shared metadata (cached for canonical stores)."""
    from .cache import AnalysisCache, supports_cache

    scope = scope or Scope()
    sections = list(sections)
    if supports_cache(store):
        return AnalysisCache(store).sections(scope, sections, with_text)
    result = analyze_store(store, scope, with_text)
    return {**{k: v for k, v in result.items() if k not in SECTIONS}, **{
        name: result[name] for name in sections
    }}


def boundary_summary(boundary: Record | None) -> Record | None:
    """Sample boundary without the per-file list: count + digest stay O(1) in every section.

    The file list itself is served page by page from ``/v1/analytics/sample_files``.
    """
    if not boundary or "files" not in boundary:
        return boundary
    files = boundary["files"] or []
    summary = {k: v for k, v in boundary.items() if k != "files"}
    # Canonical JSON: str(dict) would depend on key order (fresh vs. history-cached results).
    canonical = json.dumps(files, sort_keys=True, ensure_ascii=False, default=str)
    return {**summary, "file_count": len(files), "files_digest": stable_id(canonical)}


def response_section(result: Record, key: str) -> Record:
    """Attach shared scope and coverage metadata to an API section."""
    shared = {k: result[k] for k in SHARED_KEYS}
    if "freshness" in result:
        shared["freshness"] = result["freshness"]
    shared["sample_boundary"] = boundary_summary(shared["sample_boundary"])
    return {**shared, key: result[key]}
