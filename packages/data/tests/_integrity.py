"""Logical digest and synthetic relation trees shared by the import-path tests.

The digest covers logical output only (L1 accounting, L2 events and links, L3 tables,
issues), never capture timestamps. After merging package (d) it should delegate to
``tandem_data.validation.integrity.logical_digest``.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from pathlib import Path

from tandem_data.contract import canonical

TIME_COLUMNS = {
    "captured_at",
    "last_scan_at",
    "completed_at",
    "detected_at",
    "observed_at",
    "discovered_at",
    "scanned_at",
}
TABLES = (
    "raw_record",
    "file_record",
    "record_location",
    "record_event",
    "event",
    "event_context",
    "session_identity",
    "session",
    "turn",
    "tool_call",
    "tool_call_event",
    "model_call",
    "usage_snapshot",
    "session_feature",
    "link",
    "project",
)
WATERMARK_KEYS = ("revision", "projected_revision", "source_sha256", "decoded_bytes", "records")


def _rows(db, sql):
    return sorted(canonical(list(row)) for row in db.execute(sql))


def table_digests(home) -> dict[str, str]:
    path = Path(home) / "tandem.db"
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        parts = {}
        for table in TABLES:
            columns = [
                row[1]
                for row in db.execute(f"PRAGMA table_info({table})")
                if row[1] not in TIME_COLUMNS
            ]
            parts[table] = _rows(db, f"SELECT {','.join(columns)} FROM {table}")
        issues = []
        for row in db.execute(
            "SELECT source_id,stage,code,severity,file_id,record_uid,detail FROM ingest_issue"
        ):
            detail = json.loads(row[6])
            detail.pop("resolved_at", None)
            issues.append(canonical([*row[:6], detail]))
        parts["ingest_issue"] = sorted(issues)
        files = []
        for row in db.execute(
            "SELECT file_id,source_id,relative_path,role,format,status,watermark FROM source_file"
        ):
            watermark = json.loads(row[6])
            files.append(canonical([*row[:6], [watermark.get(k) for k in WATERMARK_KEYS]]))
        parts["source_file"] = sorted(files)
        parts["source_revision"] = _rows(
            db, "SELECT revision_uid,file_id,revision,record_count FROM source_revision"
        )
    finally:
        db.close()
    return {
        name: hashlib.sha256("\n".join(rows).encode()).hexdigest() for name, rows in parts.items()
    }


def logical_digest(home) -> str:
    return hashlib.sha256(canonical(table_digests(home)).encode()).hexdigest()


def differing_tables(left, right) -> list[str]:
    a, b = table_digests(left), table_digests(right)
    return sorted(name for name in a if a[name] != b.get(name))


def assert_integrity(store) -> None:
    """verify(), an empty foreign_key_check and a consistent L1 ledger."""
    assert store.verify()["integrity"] == "ok"
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert (
        store.db.execute(
            "SELECT COUNT(*) FROM v_raw_record_ledger WHERE "
            "(disposition IN ('mapped','folded','replayed','duplicate') AND event_count=0) OR "
            "(disposition IN ('ignored','unparsed') AND event_count>0)"
        ).fetchone()[0]
        == 0
    )


def copy_home(store, target: Path) -> Path:
    """Consistent copy of a data directory for an in-place reference rebuild."""
    target.mkdir(parents=True)
    (target / "raw").mkdir()
    for blob in (store.home / "raw").iterdir():
        (target / "raw" / blob.name).write_bytes(blob.read_bytes())
    destination = sqlite3.connect(target / "tandem.db")
    with destination:
        store.db.backup(destination)
    destination.close()
    return target


# --- synthetic relation trees -------------------------------------------------

ISO = "2026-10-01T{:02d}:{:02d}:{:02d}.000Z"


def _iso(n):
    n %= 86_400
    return ISO.format(n // 3600, n // 60 % 60, n % 60)


def _dump(path: Path, rows, tail=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
    path.write_text(text + (tail or ""))


def claude_rows(sid, turns, rng, start=0, prefix=None):
    rows = []
    previous = prefix
    for k in range(start, start + turns):
        common = {"sessionId": sid, "cwd": f"/fixture/{sid[:4]}", "version": "2.1.0"}
        user = {
            **common,
            "type": "user",
            "uuid": f"{sid}-u{k}",
            "parentUuid": previous,
            "timestamp": _iso(k * 7),
            "message": {
                "role": "user",
                "content": f"请处理第 {k} 项 " + "细节 " * rng.randrange(1, 9),
            },
        }
        assistant = {
            **common,
            "type": "assistant",
            "uuid": f"{sid}-a{k}",
            "parentUuid": f"{sid}-u{k}",
            "timestamp": _iso(k * 7 + 2),
            "message": {
                "id": f"{sid}-r{k}",
                "model": "fixture-model",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "检查中" * rng.randrange(1, 5)},
                    {
                        "type": "tool_use",
                        "id": f"{sid}-c{k}",
                        "name": "Bash",
                        "input": {"command": f"ls {k}"},
                    },
                ],
                "usage": {
                    "input_tokens": 100 + k,
                    "output_tokens": 7,
                    "cache_read_input_tokens": 50,
                    "cache_creation_input_tokens": 1,
                },
            },
        }
        result = {
            **common,
            "type": "user",
            "uuid": f"{sid}-o{k}",
            "parentUuid": f"{sid}-a{k}",
            "timestamp": _iso(k * 7 + 4),
            "toolUseResult": {"stdout": "ok", "stderr": ""},
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"{sid}-c{k}",
                        "content": "ok " * k,
                        "is_error": False,
                    }
                ],
            },
        }
        rows += [user, assistant, result]
        previous = f"{sid}-o{k}"
    if rng.random() < 0.2:
        rows.append({**common, "type": "fixture-unknown", "uuid": f"{sid}-x{start}"})
    return rows


def pi_rows(sid, turns, rng, parent=None, start=0):
    rows = [
        {"type": "session", "id": sid, "version": 3, "timestamp": _iso(1), "cwd": "/fixture/pi"}
    ]
    if parent:
        rows[0]["parentSession"] = parent
    previous = None
    for k in range(start, start + turns):
        rows += [
            {
                "type": "message",
                "id": f"u{k}",
                "parentId": previous,
                "timestamp": _iso(k * 5),
                "message": {
                    "role": "user",
                    "content": f"任务 {k} " + "说明 " * rng.randrange(1, 6),
                },
            },
            {
                "type": "message",
                "id": f"a{k}",
                "parentId": f"u{k}",
                "timestamp": _iso(k * 5 + 1),
                "message": {
                    "role": "assistant",
                    "provider": "fixture",
                    "model": "fixture-model",
                    "content": [
                        {"type": "text", "text": "好的"},
                        {
                            "type": "toolCall",
                            "id": f"c{k}",
                            "name": "bash",
                            "arguments": {"command": "pwd"},
                        },
                    ],
                    "usage": {"input": 90, "output": 4, "cacheRead": 80, "cacheWrite": 0},
                },
            },
            {
                "type": "message",
                "id": f"o{k}",
                "parentId": f"a{k}",
                "timestamp": _iso(k * 5 + 2),
                "message": {
                    "role": "toolResult",
                    "toolCallId": f"c{k}",
                    "toolName": "bash",
                    "isError": False,
                    "content": [{"type": "text", "text": "/fixture"}],
                },
            },
        ]
        previous = f"o{k}"
    return rows


def dsh_rows(sid, turns, rng, parent=None, seed=None, origin=None, version=4):
    rows = [
        {
            "type": "session",
            "id": sid,
            "version": version,
            "createdAt": 1790000000000,
            "cwd": "/fixture/dsh",
        }
    ]
    if parent:
        rows[0]["parentSession"] = parent
        rows[0]["origin"] = origin or "fork"
    seq = 0
    if seed:
        rows[0]["seedLength"] = len(seed)
        for row in seed:
            rows.append(row)
            seq += 1

    def add(typ, data):
        nonlocal seq
        rows.append({"type": typ, "seq": seq, "time": 1790000000000 + seq * 100, "data": data})
        seq += 1

    for k in range(1, turns + 1):
        add("turn/start", {"turn": k})
        add(
            "user/message",
            {
                "role": "user",
                "source": {"kind": "user"},
                "content": [
                    {"type": "text", "text": f"第 {k} 步 " + "要求 " * rng.randrange(1, 5)}
                ],
            },
        )
        add(
            "assistant/message",
            {
                "turn": k,
                "step": 1,
                "message": {
                    "role": "assistant",
                    "source": {"provider": "fixture", "model": "fixture-model"},
                    "content": [{"type": "text", "text": "执行"}],
                },
                "usage": {
                    "inputTokens": 90,
                    "outputTokens": 3,
                    "cacheReadTokens": 70,
                    "cacheWriteTokens": 0,
                },
            },
        )
        add(
            "tool/call",
            {
                "turn": k,
                "callId": f"c{k}",
                "name": "bash",
                "arguments": json.dumps({"command": "make"}),
            },
        )
        add(
            "tool/result",
            {
                "turn": k,
                "message": {
                    "role": "tool",
                    "toolCallId": f"c{k}",
                    "isError": False,
                    "content": [{"type": "text", "text": "done"}],
                },
            },
        )
        add("turn/end", {"turn": k, "reason": {"kind": "completed"}})
    return rows


def build_relation_tree(folder: Path, sessions: int = 6, seed: int = 11) -> dict[str, Path]:
    """claude subagents and resume copies, pi forks, dsh generations, forks and subagents."""
    rng = random.Random(seed)
    roots = {agent: folder / agent for agent in ("claude_code", "pi", "dsh")}
    for s in range(sessions):
        sid = f"cc{s:03d}"
        main = claude_rows(sid, 2 + s % 3, rng)
        tail = '{"type":"user","uuid":"partial"' if s == 1 else None
        _dump(roots["claude_code"] / f"projects/p{s % 2}/{sid}.jsonl", main, tail)
        if s % 3 == 0:
            agent = claude_rows(sid, 1, rng, start=50, prefix=f"{sid}-a0")
            _dump(
                roots["claude_code"] / f"projects/p{s % 2}/{sid}/subagents/agent-a{s}.jsonl", agent
            )
            meta = roots["claude_code"] / f"projects/p{s % 2}/{sid}/subagents/agent-a{s}.meta.json"
            meta.write_text(json.dumps({"toolUseId": f"{sid}-c0", "spawnDepth": 1}))
        if s % 3 == 1:
            resumed = f"{sid}r"
            copied = [{**row, "sessionId": resumed} for row in main[:3]]
            more = claude_rows(resumed, 1, rng, start=20, prefix=main[2]["uuid"])
            _dump(roots["claude_code"] / f"projects/p{s % 2}/{resumed}.jsonl", copied + more)
        pid = f"pi{s:03d}"
        parent_rows = pi_rows(pid, 2 + s % 2, rng)
        _dump(roots["pi"] / f"sessions/p{s % 2}/{pid}.jsonl", parent_rows)
        if s % 3 == 2:
            child = pi_rows(f"{pid}f", 1, rng, parent=f"sessions/p{s % 2}/{pid}.jsonl", start=30)
            _dump(
                roots["pi"] / f"sessions/p{s % 2}/{pid}f.jsonl",
                [child[0], *parent_rows[1:4], *child[1:]],
            )
        did = f"dsh{s:03d}"
        parent = dsh_rows(did, 2, rng)
        _dump(roots["dsh"] / f"sessions/p/{did}/session.v4.jsonl", parent)
        if s % 2 == 0:
            _dump(
                roots["dsh"] / f"sessions/p/{did}/session.v3.jsonl",
                dsh_rows(did, 1, rng, version=3),
            )
        if s % 3 == 0:
            seed_rows = parent[1:4]
            _dump(
                roots["dsh"] / f"sessions/p/{did}f/session.v4.jsonl",
                dsh_rows(f"{did}f", 1, rng, parent=did, seed=seed_rows),
            )
        if s % 4 == 1:
            _dump(
                roots["dsh"] / f"sessions/p/{did}s/session.v4.jsonl",
                dsh_rows(f"{did}s", 1, rng, parent=did, origin="subagent"),
            )
    return roots


def mutate(roots: dict[str, Path], rng: random.Random, step: int) -> str:
    """One random append, rewrite, delete, rename or new file. Returns a description."""
    agent = rng.choice(sorted(roots))
    files = sorted(p for p in roots[agent].rglob("*.jsonl") if p.is_file())
    if not files:
        return "noop"
    target = rng.choice(files)
    action = rng.choices(
        ("append", "append", "append", "rewrite", "delete", "rename", "new"),
        k=1,
    )[0]
    lines = target.read_text().splitlines(keepends=True)
    complete = [line for line in lines if line.endswith("\n")]
    if action == "append":
        if agent == "claude_code":
            sid = json.loads(complete[0]).get("sessionId", "x") if complete else "x"
            rows = claude_rows(sid, 1, rng, start=100 + step, prefix=None)
        elif agent == "pi":
            rows = pi_rows("x", 1, rng, start=100 + step)[1:]
        else:
            last = json.loads(complete[-1]) if complete else {"seq": 0}
            rows = [
                {
                    "type": "turn/start",
                    "seq": last.get("seq", 0) + 1,
                    "time": 1790000009000 + step,
                    "data": {"turn": 900 + step},
                },
            ]
        with target.open("a") as handle:
            if lines and not lines[-1].endswith("\n"):
                handle.write("}\n")  # Complete a pending tail before appending.
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    elif action == "rewrite" and len(complete) > 2:
        index = rng.randrange(1, len(complete))
        row = json.loads(complete[index])
        if isinstance(row.get("message"), dict) and isinstance(row["message"].get("content"), str):
            row["message"]["content"] += " 已修改"
        else:
            row["fixture_edit"] = step
        complete[index] = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        target.write_text("".join(complete))
    elif action == "delete":
        target.unlink()
    elif action == "rename":
        target.rename(target.with_name("renamed-" + target.name) if agent != "dsh" else target)
    else:
        source = rng.choice(files)
        if agent == "dsh":
            new = source.parent.parent / f"new{step}" / "session.v4.jsonl"
            new.parent.mkdir(parents=True, exist_ok=True)
            new.write_text(json.dumps(dsh_rows(f"new{step}", 1, rng)[0]) + "\n")
        elif agent == "pi":
            new = source.with_name(f"new{step}.jsonl")
            _dump(new, pi_rows(f"new{step}", 1, rng))
        else:
            new = source.with_name(f"new{step}.jsonl")
            _dump(new, claude_rows(f"new{step}", 1, rng))
    return f"{action}:{agent}:{target.name}"
