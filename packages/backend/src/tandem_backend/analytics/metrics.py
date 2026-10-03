"""AN-01 metric engine: named metrics over root sessions, with ``group_by`` and buckets.

Unit = one root session row (subagents fold into their root). Every metric returns
the ``stats`` metric object; ratios are pooled ``Σk / Σn`` and never averaged per
session. Each session contributes to exactly one group (missing keys go to
``"unknown"``), so grouped counts always add up to the overall value.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .common import human
from .context import AnalysisContext
from .signals import SignalLayer, build_signal_layer
from .signals.dictionary import RULES_VERSION, SIGNAL_KINDS
from .signals.inventory import first_request_tokens
from .stats import count, median, proportion

Record = dict[str, Any]
GROUP_BY = ("agent", "source", "project", "model", "effort", "day", "week")
BUCKETS = ("day", "week")
UNKNOWN = "unknown"


@dataclass
class Unit:
    session_uid: str
    keys: dict[str, str]
    facts: Record
    human_messages: int | None
    calls: list[Record] | None
    resident_tokens: int | None


@dataclass(frozen=True)
class MetricSpec:
    kind: str  # count | proportion | median
    meaning: str
    extract: Callable[[Unit], Any]
    basis: str = "measured"
    denominator: str | None = None


def _calls_status(unit: Unit, status: str) -> int | None:
    if unit.calls is None:
        return None
    return sum(c.get("tool_result_status") == status for c in unit.calls)


def _session_rate(kind: str) -> Callable[[Unit], tuple[int, int] | None]:
    opportunity = SIGNAL_KINDS[kind]["opportunity"]

    def extract(unit: Unit):
        value = unit.facts["signals_summary"].get(kind)
        has = unit.facts["opportunities"].get(opportunity)
        if value is None or has is None:
            return None
        return (int(value > 0), 1) if has else (0, 0)
    return extract


def _tool_failure(unit: Unit):
    failed, ok = _calls_status(unit, "failed"), _calls_status(unit, "success")
    return None if failed is None else (failed, failed + ok)


def _correction(unit: Unit):
    value = unit.facts["signals_summary"].get("correction")
    if value is None or unit.human_messages is None:
        return None
    return value, unit.human_messages


def _completed(unit: Unit):
    known = unit.facts["outcome"] != "unknown"
    return int(unit.facts["outcome"] == "completed"), int(known)


def _verify_pass(unit: Unit):
    if unit.facts["verify_ran"] is None:
        return None
    if not unit.facts["verify_ran"] or unit.facts["verify_pass"] is None:
        return 0, 0
    return int(unit.facts["verify_pass"]), 1


METRICS: dict[str, MetricSpec] = {
    "sessions": MetricSpec("count", "根会话数（子代理并入根）", lambda u: 1),
    "human_messages": MetricSpec("count", "确认真人消息数", lambda u: u.human_messages),
    "tool_calls": MetricSpec("count", "工具调用数", lambda u: None if u.calls is None else len(u.calls)),
    "tool_failure_rate": MetricSpec("proportion", "失败调用 / 已知成功+失败调用", _tool_failure,
                                    denominator="已知结果的工具调用"),
    "correction_rate": MetricSpec("proportion", "纠偏消息 / 确认真人消息", _correction, "proxy",
                                  "确认真人消息"),
    "completed_rate": MetricSpec("proportion", "outcome=completed / outcome≠unknown", _completed,
                                 denominator="结果已知的会话"),
    "verify_pass_rate": MetricSpec("proportion", "最后一次验证通过 / 有已执行验证的会话",
                                   _verify_pass, denominator="有已执行验证的会话"),
    "autonomy_steps_median": MetricSpec("median", "每会话自主步数中位数的中位数",
                                        lambda u: u.facts["autonomy_steps"]),
    "resident_tokens_median": MetricSpec("median", "首个模型请求输入侧 token（未缓存+缓存读写）的中位数",
                                         lambda u: u.resident_tokens, "estimated"),
    "unknown_outcome_sessions": MetricSpec("count", "结果为 unknown 的会话数",
                                           lambda u: int(u.facts["outcome"] == "unknown")),
}
for _kind, _spec in SIGNAL_KINDS.items():
    METRICS[f"{_kind}_session_rate"] = MetricSpec(
        "proportion", f"出现 {_kind} 的会话 / 有机会发生的会话", _session_rate(_kind),
        _spec["basis"], f"opportunity={_spec['opportunity']}")
METRICS["edit_without_verify_rate"] = METRICS["missing_verification_session_rate"]


def _calendar(ts: int | None, tz: ZoneInfo, grain: str) -> str:
    if ts is None:
        return UNKNOWN
    day = datetime.fromtimestamp(ts / 1000, UTC).astimezone(tz).date()
    if grain == "week":
        day -= timedelta(days=day.weekday())
    return day.isoformat()


def _dominant(rows: list[Record], field: str) -> str:
    values = Counter(r.get(field) for r in rows if r.get(field) is not None)
    return sorted(values.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0] if values else UNKNOWN


def build_units(context: AnalysisContext, layer: SignalLayer) -> list[Unit]:
    tz = ZoneInfo(context.scope.display_timezone)
    tokens = first_request_tokens(context) or {}
    units = []
    for view in layer.views:
        sid, s, facts = view.session_uid, view.session, layer.facts[view.session_uid]
        models = [m for member in view.member_ids for m in context.model_groups.get(member, [])]
        keys = {"agent": s.get("agent") or s.get("source_agent") or UNKNOWN,
                "source": s.get("source_id") or UNKNOWN,
                "project": s.get("project_id") or s.get("legacy_project_id") or UNKNOWN,
                "model": _dominant(models, "model_id"), "effort": _dominant(models, "effort_raw"),
                "day": _calendar(s.get("started_at"), tz, "day"),
                "week": _calendar(s.get("started_at"), tz, "week")}
        humans = None if view.events is None else sum(
            human(e, view.main_ids) for e in view.events)
        units.append(Unit(sid, keys, facts, humans, view.calls, tokens.get(sid)))
    return units


def aggregate(spec: MetricSpec, units: list[Unit]) -> Record:
    values = [spec.extract(u) for u in units]
    unknown_n = sum(v is None for v in values)
    known = [v for v in values if v is not None]
    if spec.kind == "count":
        out = count(sum(known) if known else None, n=len(known) if known else None, basis=spec.basis)
    elif spec.kind == "proportion":
        out = proportion(sum(k for k, _ in known) if known else None,
                         sum(n for _, n in known) if known else None, basis=spec.basis)
    else:
        out = median(known if known or not units else None, basis=spec.basis)
    return {**out, "unknown_n": unknown_n}


def _grouped(units: list[Unit], key: str) -> list[tuple[str, list[Unit]]]:
    groups = defaultdict(list)
    for u in units:
        groups[u.keys[key]].append(u)
    return sorted(groups.items(), key=lambda kv: (kv[0] == UNKNOWN, kv[0]))


def metrics(context: AnalysisContext, result: Record | None = None,
            metric: list[str] | None = None, bucket: str | None = None,
            group_by: str | None = None, *, layer: SignalLayer | None = None) -> Record:
    """Compute ``metric[]`` overall, per ``group_by`` value and per calendar ``bucket``."""
    names = list(metric or ["sessions"])
    unknown = [n for n in names if n not in METRICS]
    if unknown:
        raise ValueError(f"未知指标：{', '.join(unknown)}")
    if bucket is not None and bucket not in BUCKETS:
        raise ValueError("bucket 只能是 day 或 week")
    if group_by is not None and group_by not in GROUP_BY:
        raise ValueError(f"group_by 只能是 {'/'.join(GROUP_BY)}")
    layer = layer or build_signal_layer(context, result)
    units = build_units(context, layer)
    out = {}
    for name in names:
        spec = METRICS[name]
        entry = {"kind": spec.kind, "meaning": spec.meaning, "denominator": spec.denominator,
                 "overall": aggregate(spec, units)}
        if group_by:
            entry["groups"] = [{"key": k, **aggregate(spec, us)} for k, us in _grouped(units, group_by)]
        if bucket:
            entry["series"] = [{"bucket": k, **aggregate(spec, us)} for k, us in _grouped(units, bucket)]
        out[name] = entry
    return {"unit": "root_session", "units": len(units), "group_by": group_by, "bucket": bucket,
            "display_timezone": context.scope.display_timezone, "rules_version": RULES_VERSION,
            "metrics": out}
