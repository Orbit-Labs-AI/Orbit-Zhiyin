"""UI products composed from the eight families, independent of recommendations."""

from dataclasses import asdict, replace
from typing import Any

from ...models import stable_id
from ..context import AnalysisContext
from ..history import recorded
from ..inputs import AnalysisInputBundle, Scope, legacy_bundle
from ..instruction import INSTRUCTION_VERSION
from ..service import analyze_context
from .contracts import PRODUCT_VERSION, RULE_VERSIONS
from .feedback import analyze_feedback
from .journey import interaction_habits, session_journey
from .lexical import compare_vocabulary
from .payload import compact
from .statistics import compare_distributions
from .summaries import feedback_associations, observed_languages, outcome_card, profile_history
from .tools import analyze_tools
from .trends import activity_series, comparison, resource_groups

Record = dict[str, Any]


def build_products(
    bundle: AnalysisInputBundle,
    scope: Scope | None = None,
    *,
    bucket: str = "day",
    with_text: bool = False,
) -> Record:
    """Build one inspectable snapshot; text embeddings are optional and never call a model."""
    context = AnalysisContext.select(bundle, scope or Scope())
    base = analyze_context(context, with_text=with_text, with_recommendations=False)
    instructions = base["instruction"]["records"] or []
    tasks = base["tasks"]["records"] or []
    feedback = analyze_feedback(
        context.events if bundle.events is not None else None,
        context.sessions,
        context.scope.display_timezone,
        context.event_status,
    )
    rows = []
    for session in base["sessions"]:
        rows.append(
            {
                "session_uid": session["session_uid"],
                "title": session.get("title"),
                "kind": session["kind"],
                "project_id": session.get("project_id"),
                "source_id": session.get("source_id"),
                "included_session_uids": session["included_session_uids"],
                "features": session["features"],
                "usage": session["usage"],
                "duration": session["bottleneck_features"]["cost_time"]["durations"],
                "journey": session_journey(
                    context, session, tasks, instructions, base["preferences"]["records"]
                ),
                "outcomes": outcome_card(
                    session["bottleneck_features"]["outcome"], session["subjective_outcomes"]
                ),
            }
        )
    projects = []
    for project in base["projects"]:
        projects.append(
            {
                key: value
                for key, value in project.items()
                if key not in ("bottleneck_features", "tools")
            }
        )
        projects[-1].update(
            tools=analyze_tools(project["bottleneck_features"]["respond"]),
            outcomes=project["bottleneck_features"]["outcome"],
        )
    versions = {
        **RULE_VERSIONS,
        "instruction": INSTRUCTION_VERSION,
        "features": base["feature_schema_version"],
    }
    digest = stable_id(base["analysis_digest"], versions, bucket, with_text)
    return {
        "schema_version": PRODUCT_VERSION,
        "analysis_digest": digest,
        "rules_versions": versions,
        **{
            key: base[key]
            for key in ("scope", "coverage", "coverage_report", "source_coverage", "versions", "sample_boundary")
        },
        "lexical": base["lexical"],
        "statistics": base["statistics"],
        "overview": {
            **base["overview"],
            "durations": base["bottleneck_features"]["cost_time"]["durations"],
        },
        "tools": analyze_tools(base["bottleneck_features"]["respond"]),
        "activity": activity_series(context, bucket),
        "feedback": feedback,
        "feedback_associations": feedback_associations(feedback, base["sessions"]),
        "profile": interaction_habits(context, instructions),
        "profile_history": profile_history(context, instructions),
        "languages": observed_languages(base["bottleneck_features"]["respond"]["tool_sequence"]),
        "tasks": base["tasks"],
        "preferences": base["preferences"],
        "instruction": base["instruction"],
        "topics": base["text"],
        "model_effort": resource_groups(context),
        "sessions": rows,
        "projects": projects,
        "configuration": {
            "status": bundle.coverage.get("inventory", {}).get("status", "unavailable"),
            "items": bundle.inventory,
            "scans": bundle.inventory_scans,
            "scope": "latest imported configuration observations before cutoff, separate from session membership",
            "meaning": "configuration is not proof of actual tool use; analysis never scans sources",
        },
        "context_capacity": {
            "status": "unavailable",
            "reason": "no normalized used/capacity observation contract",
        },
        "limitations": [
            *base["limitations"],
            "情绪只描述明确表达的规则候选，不代表心理状态",
            "任务阶段与推断关联保留候选身份；不能据此确认验收",
            "实时状态是最后一条记录的状态，不能证明进程仍存活",
            "四维画像只展示行为证据，尚未校准人格权重",
        ],
    }


def _product_store(
    store: Any,
    scope: Scope | None = None,
    *,
    bucket: str = "day",
    with_text: bool = False,
    compare_previous: bool = False,
) -> Record:
    """Read canonical data and optionally compare an equal-length preceding window."""
    scope = scope or Scope()
    bundle = (
        store.analysis_bundle(scope) if hasattr(store, "analysis_bundle") else legacy_bundle(store)
    )
    result = build_products(bundle, scope, bucket=bucket, with_text=with_text)
    result["comparison"] = None
    if compare_previous:
        if scope.from_ts is None or scope.until_ts is None:
            raise ValueError("上期比较需要明确的 from_ts 和 until_ts")
        previous_scope = replace(
            scope, from_ts=scope.from_ts - (scope.until_ts - scope.from_ts), until_ts=scope.from_ts
        )
        previous_bundle = (
            store.analysis_bundle(previous_scope) if hasattr(store, "analysis_bundle") else bundle
        )
        previous = build_products(previous_bundle, previous_scope, bucket=bucket, with_text=False)
        result["comparison"] = comparison(result, previous)
        result["comparison"]["distributions"] = compare_distributions(
            result["statistics"], previous["statistics"]
        )
        result["comparison"]["vocabulary"] = compare_vocabulary(
            result["lexical"], previous["lexical"]
        )
        # Retain the full baseline, not only differences, to make the comparison reproducible.
        result["comparison"]["baseline"] = previous
        current_run = result["versions"].get("projection_run_id")
        previous_run = previous["versions"].get("projection_run_id")
        if current_run != previous_run:
            raise ValueError("分析期间数据版本已变化，请重试以获得同一快照的上期比较")
    result["request"] = {
        "scope": asdict(scope),
        "bucket": bucket,
        "with_text": with_text,
        "compare_previous": compare_previous,
    }
    return result


def analyze_product_store(
    store: Any,
    scope: Scope | None = None,
    *,
    bucket: str = "day",
    with_text: bool = False,
    compare_previous: bool = False,
) -> Record:
    """Persist every public product calculation, including its full comparison baseline."""
    scope = scope or Scope()
    request = {
        "scope": asdict(scope),
        "bucket": bucket,
        "with_text": with_text,
        "compare_previous": compare_previous,
    }
    return recorded(
        store,
        "products",
        request,
        lambda: compact(_product_store(
            store, scope, bucket=bucket, with_text=with_text, compare_previous=compare_previous
        )),
        reuse=True,
    )


def compare_scopes(store: Any, first: Scope, second: Scope) -> Record:
    """Persist a complete comparison between two explicit project/source/time selections."""

    def compute() -> Record:
        left, right = _product_store(store, first), _product_store(store, second)
        if left["versions"].get("projection_run_id") != right["versions"].get("projection_run_id"):
            raise ValueError("分析期间数据版本已变化，请重试")
        return compact({
            "schema_version": "analysis-comparison-v1",
            "first_scope": asdict(first),
            "second_scope": asdict(second),
            "analysis_digest": stable_id(left["analysis_digest"], right["analysis_digest"]),
            "distributions": compare_distributions(left["statistics"], right["statistics"]),
            "vocabulary": compare_vocabulary(left["lexical"], right["lexical"]),
            "first": left,
            "second": right,
        })

    return recorded(
        store, "comparison", {"first": asdict(first), "second": asdict(second)}, compute
    )


def session_page(product: Record, *, query: str = "", offset: int = 0, limit: int = 50) -> Record:
    """Search and page by last observed activity with deterministic tie breaking."""
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("offset must be nonnegative and limit must be 1–200")
    query = query.casefold().strip()
    names = {p["project_id"]: p.get("name") or "" for p in product["projects"]}
    rows = [
        row
        for row in product["sessions"]
        if not query
        or query
        in " ".join(
            str(v or "")
            for v in (row.get("title"), row.get("project_id"), names.get(row.get("project_id")))
        ).casefold()
    ]
    rows.sort(key=lambda row: (-(row["features"].get("last_observed_ts") or 0), row["session_uid"]))
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "items": rows[offset : offset + limit],
    }
