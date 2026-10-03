"""Periodic shell producers on the maintenance thread (SIM-05, SIM-06, SET-21):

* ``source_watch`` (hourly): a discovered (agent, root) that is not configured and holds
  transcripts → one ``new_source`` notification per root, ever.
* ``weekly_report`` (checked hourly): after local Monday 09:00, once per ISO week, freeze
  last week's report through the export package and notify ``weekly``. Skipped when the
  ``weekly_report`` setting is false (checked first, on any day). While any section is
  still ``computing`` or ``unavailable`` (cold start on Monday morning) nothing is saved or
  notified and the next hourly check retries; only after ``WEEKLY_RETRY_HOURS`` of retries
  is the report frozen with what exists (missing sections say so) instead of never.

Both are registered with ``Maintenance.register`` and can be triggered by hand through
``POST /v1/platform/maintenance/run {"task": "source_watch" | "weekly_report"}``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from .producers import already_sent, emit

HOUR_S = 3600
WEEKLY_HOUR = 9
WEEKLY_SECTIONS = ("overview", "metrics", "tools", "friction", "recommendations")
# 24 hourly checks: a cold full analysis takes minutes (supervisor heavy budget caps one task
# at 900 s), so a day is ample; a section still missing after that is not transient.
WEEKLY_RETRY_HOURS = 24
PENDING = ("computing", "unavailable")


def week_key(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def weekly_due(now_local: datetime, last_key: str | None) -> str | None:
    """The ISO week key to run now, or None: due once Monday 09:00 of the current ISO week
    has passed and that week has not run yet (a missed week runs on the next check)."""
    monday = (now_local - timedelta(days=now_local.isoweekday() - 1)).replace(
        hour=WEEKLY_HOUR, minute=0, second=0, microsecond=0)
    if now_local < monday:
        return None
    key = week_key(now_local)
    return None if last_key == key else key


def last_weekly_key(gw) -> str | None:
    try:
        with gw.appdb.read() as db:
            row = db.execute("SELECT dedupe_key FROM notification WHERE type = 'weekly' "
                             "AND dedupe_key LIKE 'weekly:%' ORDER BY dedupe_key DESC "
                             "LIMIT 1").fetchone()
    except Exception:  # noqa: BLE001
        return None
    return row[0].split(":", 1)[1] if row else None


def sha8(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def source_watch(gw) -> dict:
    from .onboarding import scan

    configured = {(s["agent"], s["root"]) for s in gw.state.snapshot()["sources"].values()}
    new = []
    for item in gw.discovery():
        agent, root = item["agent"], item["root"]
        if (agent, root) in configured:
            continue
        key = f"new_source:{sha8(root)}"
        if already_sent(gw, key):
            continue
        found = scan(agent, root)
        if not found["est_sessions"]:
            continue
        emit(gw, {"type": "new_source", "key": key, "title": "发现新的数据来源",
                  "body": f"{agent}：{found['est_sessions']} 个会话文件，可在设置中启用。",
                  "payload": {"agent": agent, "root": root, "files": found["files"]}})
        new.append({"agent": agent, "root": root, "files": found["files"]})
    return {"checked": len(configured), "new": new}


def _export():
    from ..exporting import report, snapshots

    return report, snapshots


def weekly_report(gw, now_local: datetime | None = None) -> dict:
    now_local = now_local or datetime.now().astimezone()
    key = weekly_due(now_local, last_weekly_key(gw))
    # The setting outranks the schedule: a disabled report says "disabled" on any day,
    # not "not_due" on Monday morning or after this week already ran.
    if gw.state.snapshot()["settings"].get("weekly_report", True) is False:
        return {"skipped": "disabled", **({"week": key} if key else {})}
    if key is None:
        return {"skipped": "not_due"}
    report, snapshots = _export()
    monday = (now_local - timedelta(days=now_local.isoweekday() - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    start, end = monday - timedelta(days=7), monday
    scope = report.build_scope({"from_ts": int(start.timestamp() * 1000),
                                "until_ts": int(end.timestamp() * 1000)})
    wanted = getattr(report, "DEFAULT_SECTIONS", WEEKLY_SECTIONS)
    sections = [s for s in wanted if s in report.SECTION_IDS]
    result = report.assemble(gw, sections, scope)
    pending = sorted({s["id"] for s in result.get("sections") or [] if s.get("status") in PENDING})
    due_at = monday.replace(hour=WEEKLY_HOUR)
    if pending and now_local < due_at + timedelta(hours=WEEKLY_RETRY_HOURS):
        # Nothing saved, nothing notified: weekly_due stays true and the next check retries.
        return {"skipped": "computing", "week": key, "sections": pending}
    result["week"] = key
    from ..services.sections import rules_digest

    kind = "report"  # report_snapshot has no 'weekly' kind; the notification marks the week
    snapshot_id = snapshots.save(gw.appdb, kind, scope, result["scope_hash"], result,
                                 rules_digest())
    emit(gw, {"type": "weekly", "key": f"weekly:{key}", "title": "每周报告已生成",
              "body": f"{start:%m-%d} 至 {(end - timedelta(days=1)):%m-%d}",
              "payload": {"snapshot_id": snapshot_id, "week": key}})
    return {"week": key, "snapshot_id": snapshot_id, "kind": kind}


def register(gw) -> None:
    maintenance = getattr(getattr(gw, "platform", None), "maintenance", None)
    if maintenance is None or not hasattr(maintenance, "register"):
        return
    maintenance.register("source_watch", lambda: source_watch(gw), HOUR_S)
    maintenance.register("weekly_report", lambda: weekly_report(gw), HOUR_S)
