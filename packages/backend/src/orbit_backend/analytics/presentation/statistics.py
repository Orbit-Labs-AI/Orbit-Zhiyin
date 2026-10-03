"""Selected-scope project inventory and observed-log time, never human work time."""

from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import isfinite
from statistics import mean, median
from zoneinfo import ZoneInfo

from .metrics import measure, unavailable

HOUR_MS = 3_600_000
SPAN_BASIS = "selected own-event last_ts-first_ts; includes idle gaps, not human work duration"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _datetime(value, zone):
    if not _number(value):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(zone)
    except (ValueError, OverflowError, OSError):
        return None


def _status(analysis, source):
    return analysis.get("coverage", {}).get(source, {}).get("status", "unavailable")


def _metric(value, unit, basis, status, unknown=0):
    if status in ("unavailable", "excluded"):
        result = unavailable("source_" + status, unit)
        result["status"] = status
        result["basis"] = basis
        return result
    return measure(value, unit, basis, status=status, unknown_n=unknown)


def project_identity_resolver(analysis):
    """Return a row -> (identity_kind, id) resolver; missing/ambiguous returns None."""
    aliases = defaultdict(set)
    for row in [*analysis.get("projects", []), *analysis.get("sessions", [])]:
        canonical, legacy = row.get("project_id"), row.get("legacy_project_id")
        if canonical is not None and legacy is not None:
            aliases[legacy].add(canonical)
    def resolve(row):
        canonical, legacy = row.get("project_id"), row.get("legacy_project_id")
        if canonical is not None:
            return "canonical", canonical
        if legacy is None:
            return None
        targets = aliases.get(legacy, set())
        if len(targets) > 1:
            return None
        return ("canonical", next(iter(targets))) if targets else ("legacy", legacy)

    return resolve


def _project_identity(analysis, rows):
    resolve = project_identity_resolver(analysis)
    identities, unassigned, ambiguous = set(), 0, 0
    for row in rows:
        identity = resolve(row)
        if identity is not None:
            identities.add(identity)
        elif row.get("legacy_project_id") is not None:
            ambiguous += 1
        else:
            unassigned += 1
    return identities, unassigned, ambiguous


def _union(intervals):
    total, end = 0, None
    for first, last in sorted(intervals):
        total += max(0, last - max(first, end if end is not None else first))
        end = max(last, end if end is not None else last)
    return total


DAY_MS = 24 * HOUR_MS


def _offset_ms(ts, zone):
    local = _datetime(ts, zone)
    return None if local is None else round(local.utcoffset().total_seconds() * 1000)


def _offset_changes(first, last, zone):
    """UTC instants in (first, last] where the zone's UTC offset changes.

    Scans day by day and bisects to the exact millisecond inside a day whose two ends
    differ. Real zones never change offset twice within 24 h (DST pairs are months apart),
    so a day step finds every change; half-hour changes (Australia/Lord_Howe) are exact.
    """
    changes, cursor, offset = [], first, _offset_ms(first, zone)
    while cursor < last:
        step = min(last, cursor + DAY_MS)
        after = _offset_ms(step, zone)
        if after != offset:
            low, high = cursor + 1, step
            while low < high:
                middle = (low + high) // 2
                if _offset_ms(middle, zone) == offset:
                    low = middle + 1
                else:
                    high = middle
            changes.append(low)
            offset = after
        cursor = step
    return changes


def _allocate_wall(start, end, totals):
    """Add the wall-clock interval [start, end) (local epoch ms) to ``totals`` by hour."""
    days, remainder = divmod(end - start, DAY_MS)
    if days:
        for hour in range(24):
            totals[hour] += days * HOUR_MS
    cursor, stop = start + days * DAY_MS, end
    while cursor < stop:  # at most 25 hour pieces
        boundary = min(stop, (cursor // HOUR_MS + 1) * HOUR_MS)
        totals[(cursor % DAY_MS) // HOUR_MS] += boundary - cursor
        cursor = boundary
    return remainder


def _span_hours(intervals, zone, status, unknown):
    """Observed session spans summed per local wall-clock hour.

    Arithmetic, not per-hour stepping: each interval is cut only where the UTC offset
    changes; within a constant-offset piece the local hour is ((t + offset) mod 24 h) // 1 h,
    so whole days add 60 min to every hour and only the < 1 day remainder is walked hour by
    hour. Cost is O(intervals + days scanned for offset changes), independent of span length.
    """
    basis = "sum of selected own-session spans by local hour; concurrent spans count separately"
    result = {"unit": "minute", "basis": basis, "unknown_n": unknown,
              "meaning": "会话日志跨度估计，包含离开/等待时间与并行重叠，不是人工工时。",
              "display_timezone": zone.key}
    if not intervals or status in ("excluded", "unavailable"):
        return {**result, "status": status if status == "excluded" else "unavailable",
                "rows": None, "reason": "no_observed_session_bounds"}
    lo, hi = min(f for f, _ in intervals), max(last for _, last in intervals)
    if _offset_ms(lo, zone) is None or _offset_ms(hi, zone) is None:
        return {**result, "status": "unavailable", "rows": None,
                "reason": "span_outside_calendar_range"}
    changes = _offset_changes(lo, hi, zone)
    totals = Counter()
    for first, last in intervals:
        cursor = first
        index = bisect_right(changes, first)
        while cursor < last:
            end = min(last, changes[index]) if index < len(changes) else last
            offset = _offset_ms(cursor, zone)
            _allocate_wall(cursor + offset, end + offset, totals)
            cursor, index = end, index + 1
    return {**result, "status": "partial" if status == "partial" or unknown else status,
            "rows": [{"hour": hour, "minutes": totals[hour] / 60_000} for hour in range(24)],
            "known_span_minutes": sum(totals.values()) / 60_000}


def _scoped_rhythm(analysis, rows, global_scope):
    candidate = analysis.get("overview", {}).get("activity_rhythm")
    if global_scope or candidate is None:
        return candidate
    # The service explicitly substitutes the project's rhythm. Confirm its scope,
    # so passing the whole analysis plus a subset cannot leak a global heatmap.
    pairs = {(row.get("project_id"), row.get("legacy_project_id")) for row in rows}
    if len(pairs) != 1:
        return None
    pair = next(iter(pairs))
    ids = {row["session_uid"] for row in rows}
    expected_ids = {row["session_uid"] for row in analysis.get("sessions", [])
                    if (row.get("project_id"), row.get("legacy_project_id")) == pair}
    if ids != expected_ids:
        return None
    for project in analysis.get("projects", []):
        if ((project.get("project_id"), project.get("legacy_project_id")) == pair
                and project.get("activity_rhythm") == candidate):
            return candidate
    return None


def _weekday_hour(analysis, rows, global_scope):
    """Do not multiply independent weekday/hour marginals to invent a heatmap."""
    source = (_scoped_rhythm(analysis, rows, global_scope) or {}).get("human_messages")
    joint = source.get("by_weekday_hour") if source else None
    status = _status(analysis, "events")
    if joint is None or status in ("unavailable", "excluded"):
        return {**unavailable("joint_message_weekday_hour_not_observed", "human_message"), "rows": None}
    values = {}
    for key, value in joint.items():
        if isinstance(value, dict):
            values.update({(int(key), int(hour)): count for hour, count in value.items()})
        else:
            weekday, hour = key.split(":")
            values[(int(weekday), int(hour))] = value
    origin_unknown = (analysis.get("overview", {}).get("counts", {}).get("human_origin_unknown", 0)
                      if global_scope else sum(row.get("unknown_counts", {}).get("human_origin", 0) or 0 for row in rows))
    unknown = (source.get("time_unknown_n", 0) or 0) + (origin_unknown or 0)
    measurable = sum(values.values()) > 0 or (status == "available" and not unknown)
    return {"status": "partial" if unknown or status == "partial" else status,
            "unit": "human_message", "basis": "confirmed human messages; local ISO weekday 1=Monday",
            "unknown_n": unknown, "rows": [
                {"weekday": day, "hour": hour, "count": values.get((day, hour), 0) if measurable else None}
                for day in range(1, 8) for hour in range(24)]}


def _sum_feature(rows, key, status, unit, *, unknown_key=None):
    values, unknown_sessions, missing_sessions, unknown_evidence = [], 0, 0, 0
    for row in rows:
        value = row.get("features", {}).get(key)
        if _number(value):
            values.append(value)
        else:
            missing_sessions += 1
        row_unknown = (row.get("unknown_counts", {}).get(unknown_key, 0) or 0) if unknown_key else 0
        unknown_evidence += row_unknown
        unknown_sessions += not _number(value) or bool(row_unknown)
    value = sum(values) if values or not rows else None
    result = _metric(value, unit, "sum of selected own-session " + key, status, unknown_sessions)
    result.update(unknown_unit="session with missing count or unknown contributing evidence",
                  missing_session_n=missing_sessions, unknown_evidence_n=unknown_evidence)
    return result


def _average(numerator, denominator, unit, basis, status, unknown=0, **metadata):
    value = numerator / denominator if numerator is not None and denominator else None
    result = _metric(value, unit, basis, status, unknown)
    result.update(numerator=numerator, denominator=denominator, **metadata)
    return result


def _averages(rows, main_n, event_status, session_status, unknown_kind):
    main_rows = [row for row in rows if row.get("kind") == "main"]
    dates, dated_sessions, unknown_sessions, missing_dates = set(), 0, 0, 0
    for row in main_rows:
        features = row.get("features", {})
        observed = features.get("observed_event_dates")
        if observed:
            dates.update(observed)
            dated_sessions += 1
        elif observed is None:
            missing_dates += 1
        unclocked = features.get("time_unknown_event_count", row.get("unknown_counts", {}).get("event_time", 0)) or 0
        unknown_sessions += observed is None or bool(unclocked)
    status = (event_status if event_status in ("unavailable", "excluded") else session_status
              if session_status in ("unavailable", "excluded") else
              "partial" if "partial" in (event_status, session_status) else "available")
    messages = _sum_feature(main_rows, "user_message_count", event_status, "human_message",
                            unknown_key="human_origin")
    message_status = (status if status in ("unavailable", "excluded") or messages["status"] == "available"
                      else messages["status"])
    active_days = len(dates) if dates or not missing_dates else None
    return {
        "human_messages_per_main_session": _average(
            messages["value"], main_n, "human_message/main_session",
            "observed confirmed human messages / selected confirmed main sessions; unknown messages are not imputed",
            message_status, (messages.get("unknown_n") or 0) + unknown_kind,
            denominator_unit="main_session", unknown_unit="main/unknown-kind session with missing or uncertain human messages"),
        "sessions_per_active_date": _average(
            dated_sessions if dates else None, active_days, "main_session/local_date",
            "main sessions with own dated events / distinct local dates containing those main-session events; never calendar span days",
            status, unknown_sessions + unknown_kind, denominator_unit="local_date",
            unknown_unit="main/unknown-kind session with unavailable or incomplete event dates"),
    }


def _statistics(analysis, selected_rows, *, global_scope):
    rows = list({row["session_uid"]: row for row in selected_rows}.values())
    source_counts = analysis.get("overview", {}).get("counts", {})
    session_status, event_status = _status(analysis, "sessions"), _status(analysis, "events")
    zone = ZoneInfo(analysis.get("scope", {}).get("display_timezone", "UTC"))
    own_ids = {row["session_uid"] for row in rows}
    included_ids = own_ids | {sid for row in rows for sid in row.get("included_session_uids", [])}
    main_n = sum(row.get("kind") == "main" for row in rows)
    unknown_kind = sum(row.get("kind") not in ("main", "subagent", "workflow_agent") for row in rows)
    session_n = source_counts.get("sessions", len(included_ids)) if global_scope else len(included_ids)
    if global_scope:
        main_n = source_counts.get("main_sessions", main_n)
        unknown_kind = source_counts.get("session_kind_unknown", unknown_kind)
    child_n = max(0, session_n - main_n - unknown_kind)
    omitted_n = max(0, session_n - len(rows))
    identities, unassigned, ambiguous = _project_identity(analysis, rows)
    count_basis = "selected session identities; subagent includes workflow_agent"
    counts = {key: _metric(value, unit, count_basis, session_status, unknown) for key, value, unit, unknown in (
        ("projects", len(identities), "project", unassigned + ambiguous + omitted_n),
        ("unassigned_project_sessions", unassigned, "session", omitted_n),
        ("ambiguous_project_sessions", ambiguous, "session", omitted_n),
        ("sessions", session_n, "session", 0),
        ("main_sessions", main_n, "main_session", unknown_kind),
        ("subagent_sessions", child_n, "subagent_or_workflow_session", unknown_kind),
        ("unknown_kind_sessions", unknown_kind, "session", 0),
    )}
    counts["projects"]["basis"] = "distinct canonical project, else unambiguous legacy alias, else legacy project; missing and ambiguous identities excluded"
    for name, feature, unit, unknown_key in (
        ("turns", "turn_count", "turn", "turn_identity"),
        ("human_messages", "user_message_count", "human_message", "human_origin"),
        ("assistant_messages", "assistant_message_count", "assistant_message", None),
        ("events", "total_event_count", "event", None),
    ):
        counts[name] = _sum_feature(rows, feature, event_status, unit, unknown_key=unknown_key)
        if omitted_n and name != "human_messages":
            if counts[name]["unknown_n"] is not None:
                counts[name]["unknown_n"] += omitted_n
            if counts[name]["status"] == "available":
                counts[name]["status"] = "partial"
        if global_scope and name in source_counts:
            unknown = (source_counts.get("human_origin_unknown", 0) if name == "human_messages" else
                       sum(row.get("unknown_counts", {}).get("turn_identity", 0) for row in rows)
                       if name == "turns" else 0)
            counts[name] = _metric(source_counts[name], unit, "selected-scope feature aggregate", event_status, unknown)
    counts["tool_calls"] = _sum_feature(rows, "tool_call_count", _status(analysis, "tool_calls"), "tool_call")
    counts["tool_calls"]["basis"] = "selected root tool counts including selected children; no child-row double count"
    if global_scope:
        totals = (analysis.get("tools", {}).get("totals") or {})
        if "call_count" in totals:
            counts["tool_calls"] = _metric(totals["call_count"], "tool_call", "selected tool call aggregate",
                                           _status(analysis, "tool_calls"))

    firsts, lasts, intervals, starts, event_dates = [], [], [], Counter(), set()
    unknown_dates, unknown_events, missing_bounds = omitted_n, 0, omitted_n
    time_unknown, date_unknown = omitted_n, omitted_n
    for row in rows:
        feature = row.get("features", {})
        first, last = feature.get("first_observed_ts"), feature.get("last_observed_ts")
        first_dt, last_dt = _datetime(first, zone), _datetime(last, zone)
        if first_dt:
            firsts.append(first)
            starts[first_dt.date().isoformat()] += 1
        if last_dt:
            lasts.append(last)
        if first_dt and last_dt and last >= first:
            intervals.append((first, last))
        else:
            missing_bounds += 1
        dates = feature.get("observed_event_dates")
        if dates is None:
            unknown_dates += 1
        else:
            event_dates.update(dates)
        unclocked = feature.get("time_unknown_event_count", row.get("unknown_counts", {}).get("event_time", 0)) or 0
        unknown_events += unclocked
        time_unknown += not (first_dt and last_dt and last >= first) or bool(unclocked)
        date_unknown += dates is None or bool(unclocked)
    first, last = min(firsts, default=None), max(lasts, default=None)
    spans = [end - start for start, end in intervals]
    time_metrics = {key: _metric(value, unit, basis, event_status, time_unknown) for key, value, unit, basis in (
        ("first_observed_ts", first, "unix_ms", "first selected own event; not session creation"),
        ("last_observed_ts", last, "unix_ms", "last selected own event; not session completion"),
        ("observed_log_span_ms", last - first if first is not None and last is not None and last >= first else None, "ms", "last observed event minus first; includes gaps"),
        ("observed_session_span_sum_ms", sum(spans) if spans else None, "ms", SPAN_BASIS + "; sum counts concurrent overlaps"),
        ("observed_session_span_mean_ms", mean(spans) if spans else None, "ms", SPAN_BASIS + "; arithmetic mean"),
        ("observed_session_span_median_ms", median(spans) if spans else None, "ms", SPAN_BASIS + "; median"),
        ("observed_session_span_union_ms", _union(intervals) if intervals else None, "ms", SPAN_BASIS + "; overlap counted once"),
        ("known_span_sessions", len(spans), "session", "sessions with both selected event boundaries; a single point has span zero"),
        ("unknown_span_sessions", missing_bounds, "session", "missing own selected event boundaries, including omitted child rows"),
    )}
    for metric in time_metrics.values():
        metric["unknown_unit"] = "session with missing bounds or any unclocked own event"
    time_metrics["unclocked_events"] = _metric(unknown_events, "event", "own selected events without valid timestamps",
                                              event_status, omitted_n)
    if global_scope and not event_dates and unknown_dates:
        rhythm = analysis.get("overview", {}).get("activity_rhythm") or {}
        for source in ("human_messages", "tool_calls", "model_requests"):
            event_dates.update((rhythm.get(source) or {}).get("by_day", {}))
    active_value = len(event_dates) if event_dates or not unknown_dates else None
    activity = {
        "active_dates": _metric(active_value, "local_date", "distinct selected observed event dates; fallback activity dates form a lower bound",
                                event_status, date_unknown),
        "daily_session_starts": {
            "status": "partial" if time_unknown or event_status == "partial" else event_status,
            "unit": "session", "basis": "first selected own event per session; not actual session creation",
            "unknown_n": session_n - len(firsts), "calendar": "observed_dates_only",
            "rows": [{"date": day, "count": value} for day, value in sorted(starts.items())]
                    if event_status not in ("unavailable", "excluded") else None,
        },
        "observed_span_by_hour": _span_hours(intervals, zone, event_status, time_unknown),
        "message_weekday_hour": _weekday_hour(analysis, rows, global_scope),
    }
    averages = _averages(rows, main_n, event_status, session_status, unknown_kind)
    return {"counts": counts, "time": time_metrics, "activity": activity, "averages": averages,
            "display_timezone": zone.key,
            "project_identity": {"canonical_n": sum(kind == "canonical" for kind, _ in identities),
                                 "legacy_only_n": sum(kind == "legacy" for kind, _ in identities),
                                 "unassigned_group_is_project": False},
            "population": "selected own-session feature rows; omitted children are counted but their time is unknown",
            "meaning": "所有时间是所选日志观测边界；单点跨度 0 不代表工作耗时为 0。"}


def build_statistics(analysis):
    """Overview inventory and time metrics for the already-selected analysis result."""
    return _statistics(analysis, analysis.get("sessions", []), global_scope=True)


def project_statistics(analysis, selected_session_rows):
    """Project metrics from own selected rows; never borrow parent time for children."""
    return _statistics(analysis, selected_session_rows, global_scope=False)
