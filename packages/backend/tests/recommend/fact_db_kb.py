"""Hand-built tool_call rows that trigger each KB coverage fact (section._kb_facts)."""

from __future__ import annotations

import json
import sqlite3

MIN = 60_000
DAY = 86_400_000
T0 = 1_780_000_000_000

SCHEMA = """
CREATE TABLE project (project_id TEXT PRIMARY KEY, paths TEXT DEFAULT '[]');
CREATE TABLE tool_call (call_uid TEXT PRIMARY KEY, session_uid TEXT, name TEXT, command_head TEXT,
  status TEXT, files TEXT DEFAULT '[]', started_at INTEGER, ended_at INTEGER, duration_ms INTEGER);
"""


def _bash(head, status="success", duration=None):
    return {"name": "Bash", "head": head, "status": status, "duration": duration}


def _edit(path="src/main.ts"):
    return {"name": "Edit", "files": [path]}


# session prefix -> (project, overlapping?, calls)
SCENARIOS = {
    "review": ("proj-r", False, [_bash("gh pr view 12"), _edit(), _bash("gh pr checks 12"), _edit(),
                                 _bash("gh pr review 12"), _edit()]),
    "parallel": ("proj-p", True, [_bash("git status"), _edit("src/app.ts"), _edit("src/app.ts")]),
    "readonly": ("proj-o", False, [{"name": "Read", "files": [f"src/f{i}.py"]} for i in range(22)]),
    "workflow": ("proj-w", False, [_bash("git pull"), _bash("npm test"), _bash("git add -A"),
                                   _bash("git commit -m wip"), _bash("git push")]),
    "build": ("proj-b", False, [*[_edit(f"paper/sec{i}.tex") for i in range(6)],
                                _bash("latexmk -pdf main.tex", status="failed")]),
    "poll": ("proj-q", False, [_bash("python train.py", duration=20 * MIN),
                               *[_bash("tail -n 50 train.log") for _ in range(5)]]),
    "deploy": ("proj-d", False, [_bash("vercel deploy --prod"), _bash("wrangler deploy")]),
}


def build(path, per_scenario: int = 4) -> list[dict]:
    """Write the db and return the analysis-style root rows (session_uid, project_id, started_at)."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    roots, slot = [], 0
    for name, (project, overlap, calls) in SCENARIOS.items():
        conn.execute("INSERT INTO project VALUES (?, ?)", (project, json.dumps([f"/work/{name}-app"])))
        for i in range(per_scenario):
            uid = f"{name}-{i}"
            start = T0 + slot * DAY + (i * 5 * MIN if overlap else i * DAY)
            # Readonly sessions span 40 minutes and parallel ones 20 minutes; the rest a minute per call.
            step = {"readonly": 2 * MIN, "parallel": 10 * MIN}.get(name, MIN)
            for j, call in enumerate(calls):
                begin = start + j * step
                conn.execute(
                    "INSERT INTO tool_call VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"{uid}-{j}", uid, call["name"], call.get("head"), call.get("status", "success"),
                     json.dumps(call.get("files", [])), begin, begin + (call.get("duration") or MIN // 2),
                     call.get("duration")))
            roots.append({"session_uid": uid, "project_id": project, "started_at": start})
        slot += per_scenario + 1
    conn.commit()
    conn.close()
    return roots

