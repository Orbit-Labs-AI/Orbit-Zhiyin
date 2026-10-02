"""Install tracking and before/after outcomes (EV-07) plus funnel metrics (EV-05).

``register_tracking`` is called by the install module after apply: baseline is the 28 days
before install, follow-up windows are 7 d and 28 d. Proportions (share of sessions with a
problem) use the Newcombe hybrid score interval; per-session means use a Welch normal
interval. n < ``min_sessions`` on either side is ``insufficient``; a guardrail rising more
than 20 % with a CI above zero is ``guardrail_hit``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict

from . import store

DAY = store.DAY
Z = 1.96
TRACK_LAYERS = ("triggered", "mechanical", "guardrail")
GUARDRAIL = {"metric": "tool_failures_per_session", "layer": "guardrail", "direction": "down"}
MEAN_FIELDS = {"readonly_prompts_per_session": "readonly_prompts",
               "tool_failures_per_session": "tool_failures", "tokens_per_session": "tokens"}


# -- registration ------------------------------------------------------------------------

def default_metrics(kind: str, problem_type: str | None) -> list[dict]:
    if kind == "permission_rule":
        primary = {"metric": "readonly_prompts_per_session", "layer": "mechanical"}
    elif kind == "removal":
        primary = {"metric": "tokens_per_session", "layer": "mechanical"}
    elif problem_type:
        primary = {"metric": f"problem_session_rate:{problem_type}", "layer": "behavioral"}
    else:
        primary = {"metric": "tool_failures_per_session", "layer": "behavioral"}
    return [{**primary, "direction": "down"}]


def _track_metrics(track: dict) -> list[dict]:
    out = []
    for layer in TRACK_LAYERS:
        value = track.get(layer)
        for item in value if isinstance(value, list) else [value] if value else []:
            metric = item.get("metric") if isinstance(item, dict) else item
            if isinstance(metric, str) and _supported(metric):
                direction = item.get("direction", "down") if isinstance(item, dict) else "down"
                out.append({"metric": metric, "layer": layer, "direction": direction})
    return out


def _supported(metric: str) -> bool:
    return metric in MEAN_FIELDS or metric.startswith("problem_session_rate:")


def register_tracking(appdb, install_id: str, candidate_id: str,
                      installed_at: int | None = None) -> str:
    import time

    installed_at = installed_at or int(time.time() * 1000)
    tracking_id = hashlib.sha256(install_id.encode()).hexdigest()[:16]
    with appdb.write() as conn:
        existing = conn.execute("SELECT tracking_id FROM tracking WHERE install_id=?",
                                (install_id,)).fetchone()
        if existing:
            return existing[0]
        row = store.candidate_row(conn, candidate_id)
        if row is None:
            raise KeyError(candidate_id)
        card = json.loads(row["card"])
        problem = card.get("problem") or {}
        track = card.get("track") or {}
        metrics = _track_metrics(track)
        for metric in default_metrics(row["kind"], problem.get("type")):
            if not any(m["layer"] != "guardrail" for m in metrics):
                metrics.insert(0, metric)
        if not any(m["metric"] == GUARDRAIL["metric"] for m in metrics):
            metrics.append(dict(GUARDRAIL))
        target = card.get("target") or {}
        scope_filter = ({"project_id": target["project_id"]}
                        if target.get("scope") == "project" and target.get("project_id") else {})
        conn.execute(
            "INSERT INTO tracking (tracking_id, install_id, candidate_id, rec_key, problem_type,"
            " problem_key, kind, registered_at, baseline_from, baseline_to, follow_days,"
            " extend_days, scope_filter, metrics) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tracking_id, install_id, candidate_id, row["rec_key"], problem.get("type"),
             problem.get("key"), row["kind"], installed_at, installed_at - 28 * DAY,
             installed_at, int(track.get("follow_days") or 7),
             int(track.get("extend_days") or 28), store.dumps(scope_filter),
             store.dumps(metrics)))
        store.pin_run(conn, row["run_id"])
        state = store._state(conn, row["rec_key"])
        state["status"], state["install_id"] = "installed", install_id
        store._save_state(conn, state, installed_at)
    return tracking_id


def mark_reverted(appdb, install_id: str, at: int) -> bool:
    with appdb.write() as conn:
        row = conn.execute("SELECT candidate_id, rec_key FROM tracking WHERE install_id=?",
                           (install_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE tracking SET reverted_at=?, effect_status='reverted' "
                     "WHERE install_id=?", (at, install_id))
        store.add_label(conn, "candidate", row["candidate_id"], "not_useful", "reverted",
                        rec_key=row["rec_key"], labeler="system", now=at)
        state = store._state(conn, row["rec_key"])
        state["status"] = "not_applicable"  # Do not recommend a reverted item again.
        store._save_state(conn, state, at)
    return True


# -- statistics --------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe(k_after: int, n_after: int, k_before: int, n_before: int,
             z: float = Z) -> tuple[float, float, float]:
    """Hybrid score interval (Newcombe 1998, method 10) for p_after - p_before."""
    p1, p2 = k_after / n_after, k_before / n_before
    l1, u1 = wilson(k_after, n_after, z)
    l2, u2 = wilson(k_before, n_before, z)
    d = p1 - p2
    return (d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2),
            d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def welch(after: list[float], before: list[float], z: float = Z) -> tuple[float, float, float]:
    def var(values, mean):
        return sum((v - mean) ** 2 for v in values) / (len(values) - 1) if len(values) > 1 else 0.0

    ma, mb = sum(after) / len(after), sum(before) / len(before)
    se = math.sqrt(var(after, ma) / len(after) + var(before, mb) / len(before))
    d = ma - mb
    return d, d - z * se, d + z * se


def _metric(metric: str, days: list[dict]) -> tuple[float, list | tuple]:
    if metric.startswith("problem_session_rate:"):
        problem = metric.split(":", 1)[1]
        k = sum(1 for d in days if problem in (d.get("problems") or ()))
        return (k / len(days) if days else 0.0), (k, len(days))
    values = [float(d.get(MEAN_FIELDS[metric]) or 0) for d in days]
    return (sum(values) / len(values) if values else 0.0), values


def compute(tracking: dict, session_days: list[dict], now: int) -> list[dict]:
    """Outcome rows for every window that has fully elapsed."""
    scope_filter = _json(tracking.get("scope_filter"), {})
    days = [d for d in session_days if d.get("started_at") is not None
            and (not scope_filter.get("project_id")
                 or d.get("project_id") == scope_filter["project_id"])]
    installed = tracking["baseline_to"]
    before = [d for d in days if tracking["baseline_from"] <= d["started_at"] < installed]
    rows = []
    for window, span in (("7d", tracking["follow_days"]), ("28d", tracking["extend_days"])):
        end = installed + span * DAY
        if now < end:
            continue
        after = [d for d in days if installed <= d["started_at"] < end]
        for spec in _json(tracking["metrics"], []):
            if not _supported(spec["metric"]):
                continue
            b_value, b_raw = _metric(spec["metric"], before)
            a_value, a_raw = _metric(spec["metric"], after)
            lo = hi = None
            insufficient = (len(before) < tracking["min_sessions"]
                            or len(after) < tracking["min_sessions"])
            if not insufficient:
                if isinstance(b_raw, tuple):
                    _, lo, hi = newcombe(a_raw[0], a_raw[1], b_raw[0], b_raw[1])
                else:
                    _, lo, hi = welch(a_raw, b_raw)
            status = "insufficient" if insufficient else "ok"
            if (status == "ok" and spec["layer"] == "guardrail" and a_value > 1.2 * b_value
                    and lo is not None and lo > 0):
                status = "guardrail_hit"
            rows.append({"window": window, "metric": spec["metric"], "layer": spec["layer"],
                         "direction": spec.get("direction", "down"),
                         "before": round(b_value, 6), "after": round(a_value, 6),
                         "lo": None if lo is None else round(lo, 6),
                         "hi": None if hi is None else round(hi, 6),
                         "n_before": len(before), "n_after": len(after), "status": status})
    return rows


def effect_status(tracking: dict, rows: list[dict], now: int) -> str:
    if tracking.get("reverted_at"):
        return "reverted"
    if now < tracking["baseline_to"] + tracking["follow_days"] * DAY or not rows:
        return "tracking"
    window = "28d" if any(r["window"] == "28d" for r in rows) else "7d"
    current = [r for r in rows if r["window"] == window]
    primary = next((r for r in current if r["layer"] != "guardrail"), None)
    if primary is None or primary["status"] == "insufficient":
        return "insufficient"
    up = primary.get("direction") == "up"
    better = primary["lo"] > 0 if up else primary["hi"] < 0
    worse = primary["hi"] < 0 if up else primary["lo"] > 0
    if any(r["status"] == "guardrail_hit" for r in current) or worse:
        return "negative"
    return "positive" if better else "neutral"


def refresh(conn, inputs: dict, now: int, *, horizon_days: int = 35) -> int:
    """Recompute outcomes of recent trackings whose baseline lies inside ``inputs``."""
    sessions = inputs.get("sessions") or {}
    session_days = (inputs.get("facts") or {}).get("session_days") or []
    until = (inputs.get("scope") or {}).get("until_ts")
    updated = 0
    for row in conn.execute("SELECT * FROM tracking WHERE reverted_at IS NULL AND "
                            "registered_at >= ?", (now - horizon_days * DAY,)).fetchall():
        tracking = dict(row)
        first = sessions.get("first_ts")
        if first is None or first > tracking["baseline_from"]:
            if now >= tracking["baseline_to"] + tracking["follow_days"] * DAY:
                scope_filter = _json(tracking["scope_filter"], {})
                scope_filter["confounders"] = ["scope_too_short"]
                conn.execute("UPDATE tracking SET effect_status='insufficient', scope_filter=? "
                             "WHERE tracking_id=?",
                             (store.dumps(scope_filter), tracking["tracking_id"]))
            continue
        rows = compute(tracking, session_days, min(now, until) if until else now)
        for r in rows:
            conn.execute("INSERT OR REPLACE INTO rec_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (tracking["install_id"], r["window"], r["metric"], r["layer"],
                          r["before"], r["after"], r["lo"], r["hi"], r["n_before"],
                          r["n_after"], r["status"], now))
        conn.execute("UPDATE tracking SET effect_status=? WHERE tracking_id=?",
                     (effect_status(tracking, rows, now), tracking["tracking_id"]))
        updated += 1
    return updated


def outcome(conn, install_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM tracking WHERE install_id=?", (install_id,)).fetchone()
    if row is None:
        return None
    windows: dict[str, list] = defaultdict(list)
    for r in conn.execute('SELECT "window", metric, layer, before, after, lo, hi, n_before, '
                          'n_after, status FROM rec_outcome WHERE install_id=? ORDER BY '
                          '"window", metric', (install_id,)).fetchall():
        item = dict(r)
        windows[item.pop("window")].append(item)
    scope_filter = _json(row["scope_filter"], {})
    return {"install_id": install_id, "tracking_id": row["tracking_id"],
            "candidate_id": row["candidate_id"], "rec_key": row["rec_key"],
            "effect_status": row["effect_status"], "registered_at": row["registered_at"],
            "reverted_at": row["reverted_at"], "metrics": _json(row["metrics"], []),
            "confounders": scope_filter.get("confounders", []),
            "windows": [{"window": w, "metrics": windows[w]} for w in ("7d", "28d")
                        if w in windows]}


def metrics_ev05(conn, days: int = 90, now: int | None = None) -> list[dict]:
    """Funnel per (kb id or rec_key family, surface): shown → opened → installed."""
    import time

    now = now or int(time.time() * 1000)
    since = now - days * DAY
    counts: dict[tuple, dict] = defaultdict(lambda: dict.fromkeys(
        ("shown", "opened", "installed", "not_applicable", "reverted"), 0))
    last_surface: dict[str, str] = {}
    field = {"view": "shown", "open": "opened", "preview": "opened", "install": "installed",
             "dismiss": "not_applicable"}
    for rec_key, surface, action in conn.execute(
            "SELECT rec_key, surface, action FROM rec_exposure WHERE ts >= ? ORDER BY ts",
            (since,)):
        last_surface[rec_key] = surface
        if action in field:
            counts[(_group(rec_key), surface)][field[action]] += 1
    for (rec_key,) in conn.execute(
            "SELECT rec_key FROM label WHERE rec_key IS NOT NULL AND undone_at IS NULL AND "
            "label='not_applicable' AND ts >= ?", (since,)):
        counts[(_group(rec_key), last_surface.get(rec_key, "A7"))]["not_applicable"] += 1
    for (rec_key,) in conn.execute("SELECT rec_key FROM tracking WHERE reverted_at >= ?",
                                   (since,)):
        counts[(_group(rec_key), last_surface.get(rec_key, "A7"))]["reverted"] += 1
    rows = []
    for (group, surface), c in sorted(counts.items()):
        shown = c["shown"]
        rows.append({"group": group, "surface": surface, **c,
                     "adoption_rate": round(c["installed"] / shown, 4) if shown else None,
                     "na_rate": round(c["not_applicable"] / shown, 4) if shown else None,
                     "revert_rate": (round(c["reverted"] / c["installed"], 4)
                                     if c["installed"] else None)})
    return rows


def _group(rec_key: str) -> str:
    return rec_key if rec_key.startswith("kb:") else rec_key.split(":", 1)[0]


def _json(value, default):
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value
