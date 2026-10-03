"""Accuracy labelling in the terminal (EV-02.1) and the label precision summary (EV-02).

``orbit label`` walks the newest recommendation run: each candidate (or problem) shows its
title, problem type and up to three evidence snippets read from orbit.db, redacted with
``privacy.redact`` and cut to 300 characters around the matched term (marked 【…】).
Answers go to the recommend ``label`` table as ``confirm`` / ``inaccurate``.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from ..privacy import redact
from ..profiling.analysis import wilson_interval
from ..recommend import store as rec_store
from ..recommend.outcomes import _group

MIN_LABELS = 30
SNIPPET = 300
KEYS = {"c": "confirm", "i": "inaccurate", "s": "skip", "q": "quit"}


# -- EV-02 summary -------------------------------------------------------------------------

def summary(conn: sqlite3.Connection, days: int = 90, now: int | None = None) -> dict:
    """Precision = confirm / (confirm + inaccurate) per target kind (candidates per rec_key
    family, as in /v1/recommendations/metrics), with a Wilson interval once n >= 30."""
    now = now or int(time.time() * 1000)
    since = now - days * 86_400_000
    counts: dict[tuple, dict] = defaultdict(lambda: {"confirm": 0, "inaccurate": 0})
    for kind, rec_key, label in conn.execute(
            "SELECT target_kind, rec_key, label FROM label WHERE undone_at IS NULL AND ts >= ? "
            "AND label IN ('confirm','inaccurate')", (since,)):
        rule = _group(rec_key) if kind == "candidate" and rec_key else None
        counts[(kind, rule)][label] += 1
    rows = []
    for (kind, rule), c in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        n = c["confirm"] + c["inaccurate"]
        enough = n >= MIN_LABELS
        lo, hi = wilson_interval(c["confirm"], n) if enough else (None, None)
        rows.append({"target_kind": kind, "rule_id": rule, "n_labeled": n,
                     "n_confirm": c["confirm"], "n_inaccurate": c["inaccurate"],
                     "precision": round(c["confirm"] / n, 4) if enough else None,
                     "lo": lo, "hi": hi, "status": "ok" if enough else "insufficient"})
    return {"rows": rows, "total_labels": sum(r["n_labeled"] for r in rows)}


# -- EV-02.1 targets -------------------------------------------------------------------------

def targets(conn: sqlite3.Connection, kind: str, labeler: str = "user") -> list[dict]:
    """Unlabelled targets of the newest rec_run: {target_id, rec_key, title, type, terms, event_ids}."""
    run = conn.execute("SELECT run_id, problems FROM rec_run ORDER BY created_at DESC LIMIT 1").fetchone()
    if run is None:
        return []
    problems = {p.get("key"): p for p in json.loads(run["problems"] or "[]") if isinstance(p, dict)}
    out = []
    if kind == "problem":
        for key, p in problems.items():
            if key:
                out.append(_target(key, None, p.get("reason") or key, p))
    else:
        for card in rec_store.candidates(conn, run["run_id"], limit=500):
            problem = {**(card.get("problem") or {}), **problems.get((card.get("problem") or {}).get("key"), {})}
            out.append(_target(card["candidate_id"], card.get("rec_key"), card.get("title") or "",
                               problem, card))
    done = {r[0] for r in conn.execute(
        "SELECT target_id FROM label WHERE target_kind=? AND labeler=? AND undone_at IS NULL "
        "AND label IN ('confirm','inaccurate')", (kind, labeler))}
    done_keys = {r[0] for r in conn.execute(
        "SELECT rec_key FROM label WHERE target_kind='candidate' AND labeler=? AND rec_key IS NOT "
        "NULL AND undone_at IS NULL AND label IN ('confirm','inaccurate')", (labeler,))}
    return [t for t in out if t["target_id"] not in done
            and not (kind == "candidate" and t["rec_key"] in done_keys)]


def _target(target_id: str, rec_key: str | None, title: str, problem: dict,
            card: dict | None = None) -> dict:
    evidence = problem.get("evidence") or (card or {}).get("evidence") or {}
    event_ids = evidence.get("event_ids") if isinstance(evidence, dict) else None
    terms = [problem.get("key")] + [v for v in (problem.get("vars") or {}).values() if isinstance(v, str)]
    return {"target_id": target_id, "rec_key": rec_key, "title": title,
            "type": problem.get("type") or "—", "event_ids": list(event_ids or []),
            "terms": [t for t in terms if t and len(t) >= 2]}


def snippets(orbit_db: Path, event_ids: list[str], terms: list[str], limit: int = 3) -> list[str]:
    if not event_ids or not orbit_db.is_file():
        return []
    conn = sqlite3.connect(orbit_db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        ids = event_ids[:50]
        rows = dict(conn.execute(f"SELECT event_uid, text FROM event WHERE event_uid IN "
                                 f"({','.join('?' * len(ids))}) AND text IS NOT NULL", ids).fetchall())
    finally:
        conn.close()
    return [mark(redact(rows[i]), terms) for i in ids if rows.get(i)][:limit]


def mark(text: str, terms: list[str], width: int = SNIPPET) -> str:
    """Cut ``text`` to ``width`` characters around the first matched term and bracket it."""
    text = " ".join(text.split())
    hit = min(((text.lower().find(t.lower()), t) for t in terms if t.lower() in text.lower()),
              default=None)
    if hit is None:
        return text if len(text) <= width else text[:width - 1] + "…"
    at, term = hit
    start = max(0, min(at - (width - len(term)) // 2, len(text) - width))
    window = text[start:start + width]
    rel = at - start
    window = f"{window[:rel]}【{window[rel:rel + len(term)]}】{window[rel + len(term):]}"
    return ("…" if start else "") + window + ("…" if start + width < len(text) else "")


def label_loop(appdb, orbit_db: Path, *, kind: str = "candidate", limit: int = 20,
               labeler: str = "user", input_fn: Callable[[str], str] = input,
               out=None, now: Callable[[], int] | None = None) -> dict:
    """Interactive loop; ``input_fn`` is injectable so tests run without a tty."""
    now = now or (lambda: int(time.time() * 1000))
    with appdb.read() as conn:
        todo = targets(conn, kind, labeler)[:limit]
    tally = {"shown": 0, "confirm": 0, "inaccurate": 0, "skip": 0}
    if not todo:
        print("没有待标注的条目（最新一次推荐运行里都已标注，或还没有推荐运行）。", file=out)
        return tally
    for index, target in enumerate(todo, 1):
        tally["shown"] += 1
        print(f"\n[{index}/{len(todo)}] {target['title']}\n  问题类型：{target['type']}", file=out)
        texts = snippets(orbit_db, target["event_ids"], target["terms"])
        for text in texts:
            print(f"  · {text}", file=out)
        if not texts:
            print("  （没有可显示的证据原文）", file=out)
        answer = _ask(input_fn)
        if answer == "quit":
            tally["shown"] -= 1
            break
        tally[answer] += 1
        if answer != "skip":
            with appdb.write() as conn:
                rec_store.add_label(conn, kind, target["target_id"], answer, None,
                                    rec_key=target["rec_key"], labeler=labeler, now=now())
    print(f"\n已标注 确认 {tally['confirm']}、不准确 {tally['inaccurate']}，跳过 {tally['skip']}。",
          file=out)
    return tally


def _ask(input_fn) -> str:
    while True:
        try:
            key = input_fn("  c 确认 / i 不准确 / s 跳过 / q 退出 > ").strip().lower()[:1]
        except EOFError:
            return "quit"
        if key in KEYS:
            return KEYS[key]
