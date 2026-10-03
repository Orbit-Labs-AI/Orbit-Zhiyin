"""Recommendation persistence in ``app.db`` (pure functions over a sqlite3 connection).

Callers hold ``gw.appdb.write()`` / ``gw.appdb.read()``; nothing here opens connections.
Runs are reused by ``(scope_hash, inputs_digest)``; candidates keep full cards for the
top passed rows and compact cards for gated rows (EV-05 denominator, "why not shown").
``rec_state`` is the per-``rec_key`` memory (frequency cap, snooze, mute, installed).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections import defaultdict

from .ranking.rank import clamp_personal

HOUR = 3_600_000
DAY = 24 * HOUR
SNOOZE_MS = 14 * DAY
VIEW_DEDUPE_MS = 6 * HOUR
GATED_DROP = ("ui", "explain", "trial", "track", "file")
HIDDEN = {"installed", "not_applicable", "muted"}
RUN_JSON = ("scope", "problems", "routes", "diagnostics")
TRACK_SUCCESS = ("positive",)
TRACK_FAILURE = ("negative", "guardrail_hit", "reverted")


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def candidate_id(run_id: str, rec_key: str) -> str:
    return hashlib.sha256(f"{run_id}|{rec_key}".encode()).hexdigest()[:16]


def _run(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    run = dict(row)
    for key in RUN_JSON:
        run[key] = json.loads(run[key]) if run[key] else None
    return run


def _card(row: sqlite3.Row) -> dict:
    card = json.loads(row["card"])
    card["candidate_id"] = row["candidate_id"]
    card["run_id"] = row["run_id"]
    return card


# -- runs --------------------------------------------------------------------------------

def insert_run(conn: sqlite3.Connection, run: dict, cands: list[dict]) -> list[str]:
    """Write one run and its candidates; a forced rerun with the same digest replaces the
    old unpinned run (a pinned one keeps living under a suffixed digest)."""
    conn.execute("UPDATE rec_run SET inputs_digest = inputs_digest || ':' || run_id "
                 "WHERE scope_hash=? AND inputs_digest=? AND pinned=1",
                 (run["scope_hash"], run["inputs_digest"]))
    old = conn.execute("SELECT run_id FROM rec_run WHERE scope_hash=? AND inputs_digest=?",
                       (run["scope_hash"], run["inputs_digest"])).fetchall()
    _delete_runs(conn, [r[0] for r in old])
    empty = {"scope": {}, "routes": {}, "problems": [], "diagnostics": []}
    values = {**run, **{k: dumps(run.get(k) or empty[k]) for k in RUN_JSON}}
    columns = ("run_id", "scope_hash", "scope", "inputs_digest", "data_rev", "inventory_rev",
               "engine_version", "kb_version", "catalog_generation", "memory_rev", "status",
               "problems", "routes", "diagnostics", "created_at", "duration_ms", "pinned")
    conn.execute(f"INSERT INTO rec_run ({','.join(columns)}) VALUES "
                 f"({','.join('?' * len(columns))})",
                 [values.get(c, 0 if c == "pinned" else None) for c in columns])
    ids, rows, seen = [], [], set()
    for cand in cands:
        key = cand["rec_key"]
        if key in seen:
            continue
        seen.add(key)
        passed = bool((cand.get("gates") or {}).get("passed", True))
        card = cand if passed else {k: v for k, v in cand.items() if k not in GATED_DROP}
        cid = candidate_id(run["run_id"], key)
        problem = cand.get("problem") or {}
        rows.append((cid, run["run_id"], key, problem.get("key"), cand.get("kind") or "rule",
                     cand.get("dim") or "rule", cand.get("level"), cand.get("audience_min"),
                     cand.get("title") or key, cand.get("rank") if passed else None,
                     float((cand.get("score") or {}).get("priority") or 0), int(passed),
                     dumps(card), run["created_at"]))
        ids.append(cid)
    conn.executemany("INSERT INTO rec_candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return ids


def _delete_runs(conn: sqlite3.Connection, run_ids: list[str]) -> None:
    for run_id in run_ids:
        conn.execute("DELETE FROM rec_candidate WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM rec_run WHERE run_id=?", (run_id,))


def latest_run(conn: sqlite3.Connection, scope_hash: str) -> dict | None:
    return _run(conn.execute("SELECT * FROM rec_run WHERE scope_hash=? ORDER BY created_at DESC,"
                             " rowid DESC LIMIT 1", (scope_hash,)).fetchone())


def find_run(conn: sqlite3.Connection, scope_hash: str, inputs_digest: str) -> dict | None:
    return _run(conn.execute("SELECT * FROM rec_run WHERE scope_hash=? AND inputs_digest=?",
                             (scope_hash, inputs_digest)).fetchone())


def get_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    return _run(conn.execute("SELECT * FROM rec_run WHERE run_id=?", (run_id,)).fetchone())


def list_runs(conn: sqlite3.Connection, scope_hash: str, limit: int = 20) -> list[dict]:
    out = []
    for row in conn.execute("SELECT run_id, created_at, status, engine_version, pinned FROM "
                            "rec_run WHERE scope_hash=? ORDER BY created_at DESC, rowid DESC "
                            "LIMIT ?", (scope_hash, limit)).fetchall():
        tops = conn.execute("SELECT title FROM rec_candidate WHERE run_id=? AND passed=1 "
                            "ORDER BY rank LIMIT 3", (row["run_id"],)).fetchall()
        n = conn.execute("SELECT count(*) FROM rec_candidate WHERE run_id=? AND passed=1",
                         (row["run_id"],)).fetchone()[0]
        out.append({**dict(row), "pinned": bool(row["pinned"]), "n_passed": n,
                    "top": [t[0] for t in tops]})
    return out


def prune(conn: sqlite3.Connection, scope_hash: str, keep: int = 20) -> int:
    """Delete the oldest unpinned runs beyond ``keep`` (pinned runs never count or go)."""
    old = conn.execute("SELECT run_id FROM rec_run WHERE scope_hash=? AND pinned=0 "
                       "ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?",
                       (scope_hash, keep)).fetchall()
    _delete_runs(conn, [r[0] for r in old])
    return len(old)


def pin_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute("UPDATE rec_run SET pinned=1 WHERE run_id=?", (run_id,))


# -- candidates --------------------------------------------------------------------------

def candidates(conn: sqlite3.Connection, run_id: str, *, passed: bool = True,
               dim: str | None = None, level: int | None = None, audience: int | None = None,
               limit: int = 30, problem_ids: list[str] | None = None) -> list[dict]:
    where, params = ["run_id=?", "passed=?"], [run_id, int(passed)]
    if problem_ids:
        # Gated cards are compacted to a top-level problem_id; passing ones keep the problem.
        where.append("COALESCE(json_extract(card, '$.problem.problem_id'), "
                     "json_extract(card, '$.problem_id')) IN (SELECT value FROM json_each(?))")
        params.append(dumps(list(problem_ids)))
    if dim:
        where.append("dim=?")
        params.append(dim)
    if level is not None:
        where.append("level=?")
        params.append(level)
    if audience is not None:
        where.append("COALESCE(audience_min, 0) <= ?")
        params.append(audience)
    order = "rank IS NULL, rank, priority DESC" if passed else "priority DESC"
    rows = conn.execute(f"SELECT candidate_id, run_id, card FROM rec_candidate WHERE "
                        f"{' AND '.join(where)} ORDER BY {order} LIMIT ?",
                        (*params, limit)).fetchall()
    return [_card(r) for r in rows]


def counts(conn: sqlite3.Connection, run_id: str, now: int) -> dict[str, int]:
    """Passing cards of a run by state: pending (visible), installed, not_applicable, snoozed."""
    out = {"pending": 0, "installed": 0, "not_applicable": 0, "snoozed": 0}
    rows = conn.execute("SELECT s.status, s.snooze_until FROM rec_candidate c LEFT JOIN rec_state s "
                        "ON s.rec_key = c.rec_key WHERE c.run_id=? AND c.passed=1", (run_id,)).fetchall()
    for status, snooze_until in rows:
        if status in ("installed", "not_applicable"):
            out[status] += 1
        elif status == "snoozed" and (snooze_until or 0) > now:
            out["snoozed"] += 1
        elif status != "muted":
            out["pending"] += 1
    return out


def dim_counts(conn: sqlite3.Connection, run_id: str) -> dict[str, int]:
    return dict(conn.execute("SELECT dim, count(*) FROM rec_candidate WHERE run_id=? AND "
                             "passed=1 GROUP BY dim", (run_id,)).fetchall())


def candidate(conn: sqlite3.Connection, cid: str) -> dict | None:
    row = conn.execute("SELECT candidate_id, run_id, card FROM rec_candidate WHERE "
                       "candidate_id=?", (cid,)).fetchone()
    return _card(row) if row else None


def candidate_row(conn: sqlite3.Connection, cid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT candidate_id, run_id, rec_key, kind, dim, priority, card FROM "
                        "rec_candidate WHERE candidate_id=?", (cid,)).fetchone()


def by_keys(conn: sqlite3.Connection, run_id: str, rec_keys: list[str | dict]) -> list[dict]:
    """Cards of `run_id` for `rec_keys` in order. Entries may be bare keys (KB remedy
    alternatives) or the `{rec_key, title, ...}` stubs the slate folds same-dim cards into."""
    rec_keys = [k.get("rec_key") if isinstance(k, dict) else k for k in rec_keys or []]
    rec_keys = list(dict.fromkeys(k for k in rec_keys if isinstance(k, str) and k))
    if not rec_keys:
        return []
    rows = conn.execute("SELECT candidate_id, run_id, card, rec_key FROM rec_candidate WHERE "
                        "run_id=? AND rec_key IN (SELECT value FROM json_each(?))",
                        (run_id, dumps(rec_keys))).fetchall()
    found = {r["rec_key"]: {**_card(r), "rec_key": r["rec_key"]} for r in rows}
    return [found[k] for k in rec_keys if k in found]


# -- state, exposures, labels -----------------------------------------------------------

def states(conn: sqlite3.Connection, rec_keys: list[str] | None = None) -> dict[str, dict]:
    if rec_keys is None:
        rows = conn.execute("SELECT * FROM rec_state").fetchall()
    else:
        rows = conn.execute("SELECT * FROM rec_state WHERE rec_key IN "
                            "(SELECT value FROM json_each(?))", (dumps(rec_keys),)).fetchall()
    return {r["rec_key"]: dict(r) for r in rows}


def visible(state: dict | None, now: int) -> bool:
    if not state:
        return True
    if state["status"] in HIDDEN:
        return False
    return not (state["status"] == "snoozed" and (state.get("snooze_until") or 0) > now)


def _state(conn: sqlite3.Connection, rec_key: str) -> dict:
    row = conn.execute("SELECT * FROM rec_state WHERE rec_key=?", (rec_key,)).fetchone()
    return dict(row) if row else {"rec_key": rec_key, "status": "candidate", "snooze_until": None,
                                  "shown_count": 0, "first_shown_at": None,
                                  "last_shown_at": None, "last_evidence": None,
                                  "install_id": None, "updated_at": 0}


def _save_state(conn: sqlite3.Connection, state: dict, now: int) -> dict:
    state["updated_at"] = max(now, (state.get("updated_at") or 0) + 1)
    conn.execute("INSERT OR REPLACE INTO rec_state VALUES (?,?,?,?,?,?,?,?,?)",
                 (state["rec_key"], state["status"], state["snooze_until"], state["shown_count"],
                  state["first_shown_at"], state["last_shown_at"], state["last_evidence"],
                  state["install_id"], state["updated_at"]))
    return state


def _apply(state: dict, action: str, ts: int) -> None:
    if action == "install":
        state["status"] = "installed"
    elif action in ("dismiss", "not_applicable"):
        state["status"] = "not_applicable"
    elif action == "snooze":
        state["status"], state["snooze_until"] = "snoozed", ts + SNOOZE_MS
    elif action == "mute":
        state["status"] = "muted"


def record_exposure(conn: sqlite3.Connection, cid: str, surface: str, position: int | None,
                    action: str, now: int) -> dict:
    """Log one exposure; a ``view`` counts once per (rec_key, surface) per 6 h."""
    row = candidate_row(conn, cid)
    if row is None:
        raise KeyError(cid)
    state = _state(conn, row["rec_key"])
    if action == "view":
        recent = conn.execute("SELECT 1 FROM rec_exposure WHERE rec_key=? AND surface=? AND "
                              "action='view' AND ts > ? LIMIT 1",
                              (row["rec_key"], surface, now - VIEW_DEDUPE_MS)).fetchone()
        if recent:
            return state
        state["shown_count"] += 1
        state["first_shown_at"] = state["first_shown_at"] or now
        state["last_shown_at"] = now
        if state["status"] == "candidate":
            state["status"] = "shown"
        problem = json.loads(row["card"]).get("problem") or {}
        # Session count, the unit gates/rank compare against (evidence_changed ≥ 20 %).
        state["last_evidence"] = problem.get("sessions", state["last_evidence"])
    conn.execute("INSERT INTO rec_exposure (ts, run_id, candidate_id, rec_key, surface, position,"
                 " priority, action) VALUES (?,?,?,?,?,?,?,?)",
                 (now, row["run_id"], cid, row["rec_key"], surface, position, row["priority"],
                  action))
    _apply(state, action, now)
    return _save_state(conn, state, now)


def add_label(conn: sqlite3.Connection, target_kind: str, target_id: str, label: str,
              reason: str | None = None, *, rec_key: str | None = None, labeler: str = "user",
              now: int) -> tuple[str, dict]:
    """Insert a label and apply its effect on ``rec_state``; returns (label_id, effect)."""
    if rec_key is None and target_kind == "candidate":
        row = candidate_row(conn, target_id)
        rec_key = row["rec_key"] if row else None
    label_id = secrets.token_hex(8)
    conn.execute("INSERT INTO label VALUES (?,?,?,?,?,?,?,?,NULL)",
                 (label_id, target_kind, target_id, rec_key, labeler, label, reason, now))
    effect = {"hidden_until": None, "status": None}
    if rec_key and label in ("not_applicable", "snooze", "mute"):
        state = _state(conn, rec_key)
        _apply(state, label, now)
        _save_state(conn, state, now)
        effect = {"hidden_until": state["snooze_until"] if label == "snooze" else None,
                  "status": state["status"]}
    return label_id, effect


def undo_label(conn: sqlite3.Connection, label_id: str, now: int) -> bool:
    row = conn.execute("SELECT rec_key FROM label WHERE label_id=? AND undone_at IS NULL",
                       (label_id,)).fetchone()
    if row is None:
        return conn.execute("SELECT 1 FROM label WHERE label_id=?", (label_id,)).fetchone() \
            is not None
    conn.execute("UPDATE label SET undone_at=? WHERE label_id=?", (now, label_id))
    if row["rec_key"]:
        replay_state(conn, row["rec_key"], now)
    return True


def replay_state(conn: sqlite3.Connection, rec_key: str, now: int) -> dict:
    """Rebuild a rec_key's status from its exposures and remaining labels."""
    state = _state(conn, rec_key)
    state["status"] = "shown" if state["shown_count"] else "candidate"
    state["snooze_until"] = None
    if state["install_id"]:
        state["status"] = "installed"
    events = conn.execute(
        "SELECT ts, action FROM rec_exposure WHERE rec_key=? AND action IN "
        "('install','dismiss','snooze') UNION ALL SELECT ts, label FROM label WHERE rec_key=? "
        "AND undone_at IS NULL AND label IN ('not_applicable','snooze','mute') ORDER BY 1",
        (rec_key, rec_key)).fetchall()
    for ts, action in events:
        _apply(state, action, ts)
    return _save_state(conn, state, now)


def labels_for(conn: sqlite3.Connection, rec_key: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT label_id, target_kind, target_id, label, reason, labeler, ts, undone_at FROM "
        "label WHERE rec_key=? ORDER BY ts DESC LIMIT 50", (rec_key,)).fetchall()]


def exposure_summary(conn: sqlite3.Connection, rec_key: str) -> dict:
    count, last = conn.execute("SELECT count(*), max(ts) FROM rec_exposure WHERE rec_key=?",
                               (rec_key,)).fetchone()
    return {"count": count, "last_ts": last}


# -- memory ------------------------------------------------------------------------------

def _weight(useful: int, not_applicable: int, not_useful: int) -> float:
    n = useful + not_applicable + not_useful
    value = 1 + 0.5 * (useful - 0.5 * not_applicable - not_useful) / (n + 5)
    return round(clamp_personal(value), 4)


def memory(conn: sqlite3.Connection, now: int, settings: dict | None = None) -> dict:
    """Memory consumed by the engine: state, labels, mutes, personal weights, posteriors."""
    settings = settings or {}
    state = {}
    for key, row in states(conn).items():
        # Exposure counts stay out of the engine (see ``memory_rev``); ``read_decay`` applies
        # the frequency decay when cards are served.
        entry = {k: row[k] for k in ("status", "snooze_until", "last_evidence", "install_id")}
        if entry["status"] == "shown" or (
                entry["status"] == "snoozed" and (entry["snooze_until"] or 0) <= now):
            entry["status"] = "candidate"
        state[key] = entry
    labels: dict[str, list] = defaultdict(list)
    muted_problems: set[str] = set()
    counts = {"kind": defaultdict(lambda: [0, 0, 0]), "dim": defaultdict(lambda: [0, 0, 0])}
    posteriors: dict[str, dict] = defaultdict(lambda: {"alpha": 0.0, "beta": 0.0})
    rows = conn.execute(
        "SELECT l.target_kind, l.target_id, l.rec_key, l.label, l.reason, l.ts, c.kind, c.dim "
        "FROM label l LEFT JOIN (SELECT rec_key, kind, dim, max(created_at) FROM rec_candidate "
        "GROUP BY rec_key) c ON c.rec_key = l.rec_key WHERE l.undone_at IS NULL ORDER BY l.ts"
    ).fetchall()
    slot = {"useful": 0, "not_applicable": 1, "not_useful": 2}
    for row in rows:
        if row["target_kind"] == "problem" and row["label"] == "mute":
            muted_problems.add(row["target_id"].split(":", 1)[0])
        if not row["rec_key"]:
            continue
        labels[row["rec_key"]].append({"label": row["label"], "reason": row["reason"],
                                       "ts": row["ts"]})
        if row["label"] in slot:
            for axis in ("kind", "dim"):
                if row[axis]:
                    counts[axis][row[axis]][slot[row["label"]]] += 1
        if row["label"] == "useful":
            posteriors[row["rec_key"]]["alpha"] += 1
        elif row["label"] == "not_useful":
            # A revert also sets tracking.effect_status='reverted' (counted below), so the revert
            # label itself adds 1: total weight 2 for a revert, 1 for a plain "not useful".
            posteriors[row["rec_key"]]["beta"] += 1
    # Tracked outcomes update the Beta posterior symmetrically: a measured improvement is a success,
    # a measured regression / guardrail breach / revert is a failure (same unit weight as a label).
    for rec_key, status, count in conn.execute(
            "SELECT rec_key, effect_status, count(*) FROM tracking WHERE effect_status IN (?, ?, ?, ?) "
            "GROUP BY rec_key, effect_status", (*TRACK_SUCCESS, *TRACK_FAILURE)).fetchall():
        posteriors[rec_key]["alpha" if status in TRACK_SUCCESS else "beta"] += count
    return {
        "now": now, "state": state, "labels": dict(labels),
        "muted_kb_rules": sorted(k.removeprefix("kb:") for k, s in state.items()
                                 if k.startswith("kb:") and s["status"] == "muted"),
        "muted_problem_types": sorted(muted_problems),
        "weights": {axis: {k: _weight(*v) for k, v in values.items()}
                    for axis, values in counts.items()},
        "posteriors": dict(posteriors), "level": settings.get("level"),
        "settings": {"ai_generate": bool(settings.get("ai_generate", False))},
    }


def memory_rev(conn: sqlite3.Connection) -> str:
    """Labels plus the decision part of ``rec_state``; views are excluded so browsing never
    reruns the engine or burns the run history."""
    last, count = conn.execute("SELECT max(ts), count(*) FROM label WHERE undone_at IS NULL"
                               ).fetchone()
    rows = conn.execute("SELECT rec_key, CASE status WHEN 'shown' THEN 'candidate' ELSE status "
                        "END, snooze_until, install_id FROM rec_state WHERE status NOT IN "
                        "('candidate','shown') OR install_id IS NOT NULL ORDER BY rec_key"
                        ).fetchall()
    digest = hashlib.sha256(json.dumps([list(r) for r in rows]).encode()).hexdigest()[:12]
    return f"{last or 0}:{count}:{digest}"


def read_decay(state: dict | None, card: dict) -> float:
    """RC-17 exposure decay 0.85^(shown−1), floor 0.5, applied when serving; resets on
    install or a ≥ 20 % evidence change since the last view."""
    if not state or state.get("install_id"):
        return 1.0
    last = state.get("last_evidence")
    sessions = (card.get("problem") or {}).get("sessions")
    if last is not None and sessions is not None and abs(sessions - last) / max(last, 1) >= .2:
        return 1.0
    return max(.5, .85 ** max(0, (state.get("shown_count") or 0) - 1))


def apply_decay(cards: list[dict], states_by_key: dict[str, dict]) -> list[dict]:
    """Stable re-order: a card's display position is stretched by 1/decay (at most doubled)."""
    for card in cards:
        card.setdefault("score", {})["decay"] = round(
            read_decay(states_by_key.get(card["rec_key"]), card), 4)
    # Base order: AI display order (rerank.fit) when present, else the slate's own order.
    cards = sorted(cards, key=lambda c: c.get("display_rank") or c.get("rank") or 10**6)
    order = {id(c): i for i, c in enumerate(cards)}
    return sorted(cards, key=lambda c: ((order[id(c)] + 1) / c["score"]["decay"], order[id(c)]))


# -- top snapshots -----------------------------------------------------------------------

def top_get(conn: sqlite3.Connection, surface: str, scope_hash: str) -> dict | None:
    row = conn.execute("SELECT * FROM rec_top WHERE surface=? AND scope_hash=?",
                       (surface, scope_hash)).fetchone()
    return {**dict(row), "rec_keys": json.loads(row["rec_keys"])} if row else None


def top_put(conn: sqlite3.Connection, surface: str, scope_hash: str, run_id: str,
            rec_keys: list[str], now: int) -> None:
    conn.execute("INSERT OR REPLACE INTO rec_top VALUES (?,?,?,?,?)",
                 (surface, scope_hash, run_id, dumps(rec_keys), now))
