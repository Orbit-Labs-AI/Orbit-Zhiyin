"""Read-through analysis cache: process LRU → analysis_section → lazy computation.

Keys
- ``request_key`` = H(normalized Scope, with_text, ALGO_VERSION, library versions).
- ``input_fp``    = H(projection run, global tables, fingerprints of candidate trees).
- session rows    = (root, scope_class, algo_version) with fp = H(tree_fp, row environment).

A changed input or version simply misses; nothing is served stale. Damaged entries raise.
Only canonical stores (``home/tandem.db``) are cached; legacy ``--db`` stores have no
fingerprints and are always computed.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path
from typing import Any

from tandem_data.analysis_fingerprint import Fingerprints, digest, fingerprints

from .context import AnalysisContext, Record
from .inputs import Scope

CACHE_FORMAT = "analysis-cache-v1"
SESSIONS = "sessions"
LRU_ENTRIES = 128
ROW_PAGE = 1000

_lru: OrderedDict[tuple, str] = OrderedDict()
_lru_lock = threading.Lock()


def algo_version() -> str:
    """H(FEATURE_VERSION, RULE_VERSIONS, INSTRUCTION/TAXONOMY/PREFERENCE versions, VECTOR_VERSION).

    Read at call time. Every version that enters ``analysis_digest`` is part of it, so a
    rule change never serves a cached section or row computed under the old rules.
    """
    from . import FEATURE_VERSION
    from . import instruction as instruction_module
    from . import preference as preference_module
    from .lexicon import LEXICON_VERSION
    from .products.contracts import RULE_VERSIONS
    from .task import representation as vectors
    from .task import taxonomy
    from .task.topics import TOPIC_VERSION

    return digest(
        CACHE_FORMAT,
        FEATURE_VERSION,
        dict(RULE_VERSIONS),
        instruction_module.INSTRUCTION_VERSION,
        taxonomy.TAXONOMY_VERSION,
        preference_module.PREFERENCE_VERSION,
        preference_module.PREFERENCE_EVIDENCE_VERSION,
        vectors.VECTOR_VERSION,
        TOPIC_VERSION,
        LEXICON_VERSION,
    )[:32]


def _libraries() -> dict[str, str]:
    names = ("tandem-backend", "tandem-data", "jieba", "numpy", "scipy", "scikit-learn")
    return {name: version(name) for name in names}


def supports_cache(store: Any) -> bool:
    home = getattr(store, "home", None)
    return isinstance(home, (str, Path)) and (Path(home) / "tandem.db").is_file()


def with_exclusions(scope: Scope, history) -> Scope:
    """Persisted exclusions join every analysis; caller-supplied ones keep their order."""
    persisted = [row["session_uid"] for row in history.exclusions()]
    extra = [uid for uid in persisted if uid not in scope.excluded_session_uids]
    if not extra:
        return scope
    return replace(scope, excluded_session_uids=[*scope.excluded_session_uids, *extra])


def request_key(scope: Scope, with_text: bool) -> str:
    return digest(CACHE_FORMAT, algo_version(), _libraries(), asdict(scope), bool(with_text))


def candidate_roots(fps: Fingerprints, scope: Scope) -> list[str]:
    """A superset of the trees this scope can select; extra trees only cause extra misses."""
    excluded = set(scope.excluded_session_uids)
    wanted_roots = None if scope.root_session_uids is None else set(scope.root_session_uids)
    sources = None if scope.source_ids is None else set(scope.source_ids)
    bounded = scope.from_ts is not None or scope.until_ts is not None
    roots = []
    for root, tree in fps.trees.items():
        if root in excluded or (wanted_roots is not None and root not in wanted_roots):
            continue
        if sources is not None and not sources & set(tree.source_ids):
            continue
        if bounded and not tree.untimed_events and tree.min_ts is not None:
            if scope.until_ts is not None and tree.min_ts >= scope.until_ts:
                continue
            if scope.from_ts is not None and tree.max_ts < scope.from_ts:
                continue
        roots.append(root)
    return roots


def scope_class(scope: Scope, tree) -> str:
    """``full`` when the whole tree is selected unfiltered; otherwise a hash of the filters."""
    bounded = scope.from_ts is not None or scope.until_ts is not None
    contained = (
        tree is not None
        and (not bounded or (tree.untimed_events == 0 and tree.min_ts is not None))
        and (scope.from_ts is None or tree.min_ts >= scope.from_ts)
        and (scope.until_ts is None or tree.max_ts < scope.until_ts)
    )
    excluded_members = (
        sorted(set(scope.excluded_session_uids) & set(tree.session_uids)) if tree else []
    )
    unfiltered = all(
        value is None
        for value in (
            scope.model_ids,
            scope.effort_raw,
            scope.project_ids,
            scope.agent_ids,
            scope.source_ids,
        )
    )
    if contained and unfiltered and not excluded_members:
        return "full"
    return "f:" + digest(
        scope.from_ts,
        scope.until_ts,
        scope.model_ids,
        scope.effort_raw,
        scope.project_ids,
        scope.agent_ids,
        scope.source_ids,
        excluded_members,
    )[:32]


def row_environment(context: AnalysisContext) -> str:
    """Everything outside the tree that per-session code reads (scope flags, coverage status)."""
    scope, bundle = context.scope, context.bundle
    unbounded = (
        scope.from_ts is None
        and scope.until_ts is None
        and scope.scene is None
        and scope.model_ids is None
        and scope.effort_raw is None
    )
    return digest(
        scope.display_timezone,
        scope.include_children,
        scope.scene,
        scope.from_ts,
        scope.until_ts,
        unbounded,
        bool(scope.excluded_session_uids) or not scope.include_children,
        {k: v.get("status") for k, v in bundle.coverage.items() if isinstance(v, dict)},
        bundle.versions.get("storage"),
        bundle.events is not None,
    )


class SessionRowStore:
    """RowCache backed by ``session_result``; valid while the tree fingerprint matches."""

    def __init__(self, history, fps: Fingerprints, algo: str):
        self.history, self.fps, self.algo = history, fps, algo
        self.root_of = fps.root_of()

    def _keys(self, context: AnalysisContext, sids: list[str]) -> dict[str, tuple[str, str]]:
        environment = row_environment(context)
        keys = {}
        for sid in sids:
            session = context.session_map.get(sid, {})
            root = self.root_of.get(sid) or session.get("root_uid")
            tree = self.fps.trees.get(root)
            if tree is None:
                continue  # unknown to the fingerprint: always recompute, never store
            keys[sid] = (scope_class(context.scope, tree), digest(tree.fp, environment))
        return keys

    def get(self, context: AnalysisContext, sids: list[str]) -> dict[str, Record]:
        by_class: dict[str, dict[str, str]] = {}
        for sid, (klass, fp) in self._keys(context, sids).items():
            by_class.setdefault(klass, {})[sid] = fp
        found = {}
        for klass, wanted in by_class.items():
            found.update(self.history.session_results(klass, self.algo, wanted))
        return found

    def put(self, context: AnalysisContext, rows: dict[str, Record]) -> None:
        by_class: dict[str, dict[str, tuple[str, Record]]] = {}
        for sid, (klass, fp) in self._keys(context, list(rows)).items():
            by_class.setdefault(klass, {})[sid] = (fp, rows[sid])
        for klass, items in by_class.items():
            self.history.put_session_results(klass, self.algo, items)


def _lru_get(key: tuple) -> Any:
    with _lru_lock:
        text = _lru.get(key)
        if text is not None:
            _lru.move_to_end(key)
    return None if text is None else json.loads(text)


def _lru_put(key: tuple, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    with _lru_lock:
        _lru[key] = text
        _lru.move_to_end(key)
        while len(_lru) > LRU_ENTRIES:
            _lru.popitem(last=False)


def clear_memory_cache() -> None:
    with _lru_lock:
        _lru.clear()


class AnalysisCache:
    """Serve analysis sections for one canonical store through the cache layers."""

    def __init__(self, store, *, history=None):
        from .history import history_for

        self.store = store
        self.home = str(Path(store.home).resolve())
        self.history = history or history_for(store)

    # ---- keys --------------------------------------------------------------------------

    def prepare(self, scope: Scope, with_text: bool) -> tuple[Scope, Fingerprints, str, str]:
        scope = with_exclusions(scope, self.history)
        fps = fingerprints(self.home)
        input_fp = fps.input_fp(candidate_roots(fps, scope))
        return scope, fps, request_key(scope, with_text), input_fp

    # ---- reads -------------------------------------------------------------------------

    def _read(self, key: str, input_fp: str, names: list[str]) -> dict[str, Any]:
        found, missing = {}, []
        for name in names:
            value = None if name == SESSIONS else _lru_get((self.home, key, input_fp, name))
            if value is None:
                missing.append(name)
            else:
                found[name] = value
        stored = self.history.sections(key, input_fp, missing)
        for name, value in stored.items():
            if name == SESSIONS:
                value = self._all_rows(key, input_fp)
            else:
                _lru_put((self.home, key, input_fp, name), value)
            found[name] = value
        return found

    def _all_rows(self, key: str, input_fp: str) -> list[Record]:
        rows, offset = [], 0
        while True:
            page = self.history.section_rows(key, input_fp, SESSIONS, offset=offset, limit=ROW_PAGE)
            rows.extend(page["items"])
            offset += ROW_PAGE
            if offset >= page["total"]:
                return rows

    # ---- computation -------------------------------------------------------------------

    def _compute(
        self,
        scope: Scope,
        fps: Fingerprints,
        key: str,
        input_fp: str,
        names: list[str],
        with_text: bool,
        engine: str,
    ) -> tuple[dict[str, Any], dict]:
        from .service import META, AnalysisSections, compose

        algo = algo_version()
        request = {"scope": asdict(scope), "with_text": with_text, "sections": names}
        run_id = self.history.start(engine, request, request_key=key, input_fp=input_fp)
        try:
            bundle = self.store.analysis_bundle(scope)
            context = AnalysisContext.select(bundle, scope)
            rows = SessionRowStore(self.history, fps, algo)
            builder = AnalysisSections(context, with_text, row_cache=rows)
            computed = {name: builder.section(name) for name in names}
            computed_at = int(time.time() * 1000)
            stored = {
                name: ({"meta": value, "computed_at": computed_at} if name == META else value)
                for name, value in computed.items()
            }
            row_items = None
            if SESSIONS in stored:
                row_items = {SESSIONS: [(r["session_uid"], r) for r in stored[SESSIONS]]}
                stored[SESSIONS] = {"rows": len(stored[SESSIONS])}
            self.history.put_sections(key, input_fp, stored, row_items)
            # The run snapshot has the public result shape (shared metadata at the top level),
            # like runs recorded by the uncached engine.
            sections = {name: value for name, value in computed.items() if name != META}
            self.history.complete(run_id, compose(computed[META], sections))
        except BaseException as error:
            try:
                self.history.fail(run_id, error)
            except Exception as storage_error:
                error.add_note(f"Recording the failure also failed: {type(storage_error).__name__}")
            raise
        self.history.prune(algo_version=algo)
        for name, value in stored.items():
            if name != SESSIONS:
                _lru_put((self.home, key, input_fp, name), value)
        stats = {"computed": builder.rows_computed, "reused": builder.rows_reused}
        return computed, {"computed_at": computed_at, "rows": stats, "run_id": run_id}

    def sections(
        self, scope: Scope, names: list[str], with_text: bool = False, *, engine: str = "features"
    ) -> Record:
        """Shared metadata plus the requested sections, with a ``freshness`` block."""
        from .service import META, SECTIONS, compose

        for name in names:
            if name not in SECTIONS:
                raise KeyError(f"Unknown analysis section: {name}")
        scope, fps, key, input_fp = self.prepare(scope, with_text)
        wanted = [META, *dict.fromkeys(names)]
        found = self._read(key, input_fp, wanted)
        missing = [name for name in wanted if name not in found]
        freshness = {
            "input_fp": input_fp,
            "algo_version": algo_version(),
            "request_key": key,
            "cache_hit": not missing,
        }
        if missing:
            if META not in missing:
                missing.insert(0, META)  # keep metadata and sections from the same computation
            computed, info = self._compute(scope, fps, key, input_fp, missing, with_text, engine)
            meta = computed[META]
            found.update({k: v for k, v in computed.items() if k != META})
            freshness.update(computed_at=info["computed_at"], rows=info["rows"])
        else:
            meta = found[META]["meta"]
            freshness["computed_at"] = found[META]["computed_at"]
        result = compose(meta, {name: found[name] for name in names})
        result["freshness"] = freshness
        return result

    def full(self, scope: Scope, with_text: bool = True) -> Record:
        from .service import SECTIONS

        return self.sections(scope, list(SECTIONS), with_text)

    def session_page(
        self, scope: Scope, *, offset: int = 0, limit: int = 50, with_text: bool = False
    ) -> Record:
        """Page stored session rows; computes only the sessions section on a miss."""
        result = self._ensure_sessions(scope, with_text)
        key, input_fp = result["freshness"]["request_key"], result["freshness"]["input_fp"]
        page = self.history.section_rows(key, input_fp, SESSIONS, offset=offset, limit=limit)
        result["sessions"], result["total"] = page["items"], page["total"]
        return result

    def session_row(self, scope: Scope, session_uid: str, *, with_text: bool = False):
        result = self._ensure_sessions(scope, with_text)
        key, input_fp = result["freshness"]["request_key"], result["freshness"]["input_fp"]
        row = self.history.section_row(key, input_fp, SESSIONS, session_uid)
        result["session"] = row
        return result

    def _ensure_sessions(self, scope: Scope, with_text: bool) -> Record:
        from .service import META, SECTIONS, compose

        scope, fps, key, input_fp = self.prepare(scope, with_text)
        stored = self.history.sections(key, input_fp, [META, SESSIONS])
        freshness = {
            "input_fp": input_fp,
            "algo_version": algo_version(),
            "request_key": key,
            "cache_hit": len(stored) == 2,
        }
        if len(stored) == 2:
            meta = stored[META]["meta"]
            freshness["computed_at"] = stored[META]["computed_at"]
        else:
            computed, info = self._compute(
                scope, fps, key, input_fp, [META, SESSIONS], with_text, "features"
            )
            meta = computed[META]
            freshness.update(computed_at=info["computed_at"], rows=info["rows"])
        result = {k: v for k, v in compose(meta, {}).items() if k not in SECTIONS}
        result["freshness"] = freshness
        return result

    def status(self, scope: Scope | None = None) -> Record:
        """Whether the default (or given) scope's first-screen sections are cached now."""
        from .service import META

        scope, _, key, input_fp = self.prepare(scope or Scope(), False)
        cached = self.history.sections(key, input_fp, [META])
        return {
            "input_fp": input_fp,
            "algo_version": algo_version(),
            "request_key": key,
            "cached": bool(cached),
            "computed_at": cached[META]["computed_at"] if cached else None,
        }
