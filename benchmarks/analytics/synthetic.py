"""Deterministic, fully fictional analysis inputs for benchmarks and equivalence regression.

Nothing here reads local agent history. Every name, path, prompt and command is invented.

Two outputs share one seeded plan:

* ``generate_bundle(sessions, seed)`` returns an ``analysis-input-v1`` dict shaped like the
  canonical reader (``tandem_data.analysis_input.read_analysis``) output, including
  ``statistical_members`` so ``analyze_bundle`` takes the canonical selection path.
* ``build_canonical_home(home, sessions, seed)`` writes fictional Codex-format JSONL under
  three source roots and imports them through the public ingest path into ``tandem.db``,
  so ``read_analysis`` can be measured on a real canonical database.
"""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from pathlib import Path

PROJECTS = 12
SOURCES = 3
BASE_TS = 1_790_000_000_000  # fixed epoch milliseconds; never wall-clock
TIMEZONE = "Asia/Shanghai"

REQUESTS = (
    "请修复登录模块的测试失败，并解释修改原因。",
    "帮我把报表导出改成分页读取，先做最小可运行版本。",
    "请给这个函数补充单元测试，覆盖空输入。",
    "Please refactor the parser into smaller functions and keep behaviour identical.",
    "Add a CLI flag that prints the summary as JSON.",
    "Investigate why the build is slow and propose two options.",
)
CORRECTIONS = (
    "不对，应该改配置文件，不要动接口。",
    "没看懂，换个直观的例子。",
    "No, revert that change and keep the original signature.",
    "这个方向错了，先回滚再说。",
)
PREFERENCES = (
    "以后这个项目都用中文回复。",
    "Always run the linter before committing.",
    "回答尽量简短，先给结论。",
)
FEEDBACK = (
    "这一版比上一版更清楚，谢谢。",
    "Great, that works now.",
    "还是不行，测试依然失败。",
    "很好，就按这个来。",
)
ASSISTANT = (
    "已定位到问题，修改如下并已运行测试。",
    "I updated the function and added the missing test case.",
    "以下是两个方案的对比与建议。",
)
TOOLS = {
    "shell": ("exec_command", ("pnpm test", "uv run pytest -q", "git status", "make build")),
    "edit": ("apply_patch", ("src/app.py", "src/report.ts", "README.md")),
    "read": ("read_file", ("src/app.py", "docs/guide.md", "package.json")),
    "web": ("web_search", ("python dataclass replace", "sqlite json_each limits")),
}
MODELS = (
    ("synthetic-model-large", "high"),
    ("synthetic-model-large", "medium"),
    ("synthetic-model-small", "low"),
)


def _uid(prefix: str, *parts) -> str:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _time(ts: int) -> dict:
    return {
        "source_field": "timestamp",
        "semantics": "created",
        "quality": "reported",
        "reported": {"timestamp_ms": ts},
    }


class _Session:
    """Accumulates one session's rows with monotonically increasing seq and timestamps."""

    def __init__(self, bundle, uid, ts):
        self.bundle, self.uid, self.ts, self.seq, self.turn = bundle, uid, ts, 0, None

    def event(self, kind, actor, /, *, text=None, call_id=None, **attrs):
        self.ts += 1_000 + self.seq % 7 * 250
        uid = _uid("event", self.uid, self.seq)
        attrs.setdefault("time", _time(self.ts))
        self.bundle["events"].append(
            {
                "event_uid": uid,
                "session_uid": self.uid,
                "record_uid": _uid("record", uid),
                "native_id": None,
                "event_path": kind,
                "kind": kind,
                "actor": actor,
                "seq": self.seq,
                "ts": self.ts,
                "parent_uid": None,
                "turn_uid": self.turn,
                "call_id": call_id,
                "text": text,
                "text_truncated": 0,
                "attrs": attrs,
                "ext": {},
            }
        )
        self.seq += 1
        return uid


def generate_bundle(sessions: int = 200, seed: int = 7) -> dict:
    """Return a canonical-shaped analysis-input-v1 dict; identical for equal arguments."""
    rng = random.Random(seed)
    bundle = {
        "input_contract": "analysis-input-v1",
        "db_schema_version": 0,
        "parser_version": "synthetic",
        "derivation_version": "synthetic",
        "redaction_version": "synthetic",
        "projection_run_id": seed,
        "scope": {"display_timezone": TIMEZONE},
        "projects": [
            {
                "project_id": f"project-{p:02d}",
                "key_type": "path",
                "key": f"/synthetic/project-{p:02d}",
                "name": f"project-{p:02d}",
                "git_remote": None,
                "paths": [f"/synthetic/project-{p:02d}"],
            }
            for p in range(PROJECTS)
        ],
        "sessions": [],
        "turns": [],
        "events": [],
        "tool_calls": [],
        "model_calls": [],
    }
    for index in range(sessions):
        _main_session(bundle, rng, index)
    bundle["sample_boundary"] = {
        "sources": [
            {
                "source_id": f"source-{s}",
                "agent": "synthetic",
                "root_path": f"/synthetic/source-{s}",
            }
            for s in range(SOURCES)
        ]
    }
    rows = {
        name: len(bundle[name])
        for name in ("sessions", "projects", "turns", "events", "tool_calls", "model_calls")
    }
    bundle["coverage"] = {
        name: {"status": "available", "rows": count} for name, count in rows.items()
    }
    bundle["statistical_members"] = {"event_uids": [e["event_uid"] for e in bundle["events"]]}
    return bundle


def _session_row(uid, index, project, source, ts, kind="main", parent=None):
    return {
        "session_uid": uid,
        "source_id": f"source-{source}",
        "native_id": f"native-{index}",
        "kind": kind,
        "parent_uid": parent,
        "root_uid": parent or uid,
        "forked_from": None,
        "depth": 1 if parent else 0,
        "project_id": f"project-{project:02d}",
        "cwd": f"/synthetic/project-{project:02d}",
        "title": f"Synthetic session {index}",
        "started_at": ts,
        "ended_at": None,
        "timezone": TIMEZONE,
        "timezone_source": "reported",
        "status": "unknown",
    }


def _main_session(bundle, rng, index):
    project, source = rng.randrange(PROJECTS), index % SOURCES
    uid = _uid("session", "main", index)
    start = BASE_TS + index * 3_600_000 + rng.randrange(600_000)
    row = _session_row(uid, index, project, source, start)
    bundle["sessions"].append(row)
    session = _Session(bundle, uid, start)
    model, effort = MODELS[rng.randrange(len(MODELS))]
    session.event("session.meta", "harness", kind="main", cwd=row["cwd"])
    for turn_index in range(rng.randint(2, 5)):
        _turn(bundle, rng, session, row, turn_index, model, effort)
    if index % 5 == 0:
        _subagent(bundle, rng, session, row, index, model, effort)
    row["ended_at"] = session.ts


def _turn(bundle, rng, session, row, turn_index, model, effort):
    turn_uid = _uid("turn", session.uid, turn_index)
    session.turn = turn_uid
    first_seq = session.seq
    if turn_index == 0:
        pool = REQUESTS
    else:
        pool = (REQUESTS, CORRECTIONS, PREFERENCES, FEEDBACK)[rng.randrange(4)]
    trigger = session.event(
        "message.user", "human", text=pool[rng.randrange(len(pool))], origin="human"
    )
    status = "completed"
    previous_args = None
    for call_index in range(rng.randint(1, 4)):
        kind = ("shell", "edit", "read", "web")[rng.randrange(4)]
        # Repeat the previous arguments sometimes to exercise retry/duplicate detection.
        args = (
            previous_args
            if previous_args and rng.random() < 0.25
            else TOOLS[kind][1][rng.randrange(len(TOOLS[kind][1]))]
        )
        previous_args = args
        if kind == "shell" and rng.random() < 0.3:
            session.event("permission.request", "harness", tool=TOOLS[kind][0])
            session.event("permission.response", "human", decision="approved")
        failed = rng.random() < 0.2
        _tool_pair(bundle, session, row, kind, args, failed, call_index)
    if rng.random() < 0.15:
        session.event("context.compaction", "harness", trigger="auto")
    if rng.random() < 0.1:
        session.event("turn.interrupted", "human", reason="user_cancel")
        status = "interrupted"
    else:
        session.event(
            "message.assistant", "assistant", text=ASSISTANT[rng.randrange(len(ASSISTANT))]
        )
    usage = session.event("model.usage", "harness", model=model, effort=effort)
    tokens = rng.randint(2_000, 40_000)
    bundle["model_calls"].append(
        {
            "call_uid": _uid("model_call", usage),
            "session_uid": session.uid,
            "turn_uid": turn_uid,
            "project_id": row["project_id"],
            "usage_event_uid": usage,
            "request_id": None,
            "provider": "synthetic",
            "model_raw": model,
            "model_id": model,
            "model_resolution": "exact",
            "effort_raw": effort,
            "effort_rank": None,
            "purpose": "main",
            "coverage": "self",
            "usage_scope": "call",
            "measurement": "delta",
            "boundary_reliable": True,
            "input_tokens": tokens,
            "cache_read_tokens": tokens // 4,
            "cache_write_tokens": 0,
            "output_tokens": tokens // 10,
            "reasoning_tokens": tokens // 20,
            "cost_usd": None,
            "cost_source": None,
            "latency_ms": rng.randint(800, 9_000),
            "ttft_ms": None,
            "stop_reason": None,
            "ts": session.ts,
        }
    )
    bundle["turns"].append(
        {
            "turn_uid": turn_uid,
            "session_uid": session.uid,
            "idx": turn_index,
            "native_id": f"turn-{turn_index}",
            "trigger": "human",
            "boundary_source": "reported",
            "project_id": row["project_id"],
            "status": status,
            "started_at": None,
            "ended_at": session.ts,
            "trigger_event_uid": trigger,
            "first_event_uid": _uid("event", session.uid, first_seq),
            "last_event_uid": _uid("event", session.uid, session.seq - 1),
        }
    )


def _tool_pair(bundle, session, row, kind, args, failed, call_index):
    name = TOOLS[kind][0]
    call_id = f"call-{session.seq}-{call_index}"
    head = args if kind == "shell" else None
    files = [args] if kind in ("edit", "read") else []
    call = session.event(
        "tool.call", "assistant", call_id=call_id, name=name, category=kind, command_head=head
    )
    started = session.ts
    result = session.event(
        "tool.result",
        "tool",
        call_id=call_id,
        text="error: synthetic failure" if failed else "ok",
        status="failed" if failed else "success",
    )
    bundle["tool_calls"].append(
        {
            "call_uid": _uid("tool_call", call),
            "session_uid": session.uid,
            "turn_uid": session.turn,
            "project_id": row["project_id"],
            "native_call_id": call_id,
            "call_event_uid": call,
            "result_event_uid": result,
            "name_raw": name,
            "name": name,
            "kind": kind,
            "mcp_server": None,
            "mcp_tool": None,
            "skill": None,
            "subagent_session_uid": None,
            "command_head": head,
            "files": files,
            "status": "failed" if failed else "success",
            "pairing_quality": "native_id",
            "exit_code": (1 if failed else 0) if kind == "shell" else None,
            "error_class": "synthetic" if failed else None,
            "is_wrapper": 0,
            "argument_digest": _uid("arguments", name, args),
            "status_scope": "tool",
            "started_at": started,
            "ended_at": session.ts,
            "duration_ms": session.ts - started,
            "duration_source": "reported",
            "duration_quality": "reported",
            "approval": None,
            "approval_wait_ms": None,
        }
    )


def _subagent(bundle, rng, parent, parent_row, index, model, effort):
    child_uid = _uid("session", "child", index)
    child_row = _session_row(
        child_uid,
        f"{index}-child",
        int(parent_row["project_id"][-2:]),
        int(parent_row["source_id"][-1]),
        parent.ts + 500,
        "subagent",
        parent.uid,
    )
    parent.event("subagent.spawn", "assistant", child_session_uid=child_uid)
    bundle["sessions"].append(child_row)
    child = _Session(bundle, child_uid, parent.ts)
    child.event("session.meta", "harness", kind="subagent", cwd=child_row["cwd"])
    _turn(bundle, rng, child, child_row, 0, model, effort)
    child_row["ended_at"] = child.ts
    parent.ts = max(parent.ts, child.ts)
    parent.event("subagent.result", "assistant", child_session_uid=child_uid)


def canonical_json(value) -> str:
    """Stable JSON used for determinism checks and golden digests."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


# --- Canonical database path ------------------------------------------------------------


def write_codex_sources(root: Path, sessions: int = 200, seed: int = 7) -> list[Path]:
    """Write fictional Codex JSONL into SOURCES roots; returns the root directories."""
    rng = random.Random(seed)
    roots = [root / f"source-{s}" for s in range(SOURCES)]
    for index in range(sessions):
        folder = roots[index % SOURCES] / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        project = rng.randrange(PROJECTS)
        model, effort = MODELS[rng.randrange(len(MODELS))]
        ts = BASE_TS + index * 3_600_000
        rows = [
            _codex(
                "session_meta",
                ts,
                {
                    "id": f"synthetic-{index}",
                    "cwd": f"/synthetic/project-{project:02d}",
                    "source": "cli",
                    "thread_source": "user",
                    "cli_version": "synthetic",
                },
            )
        ]
        for turn in range(rng.randint(2, 5)):
            turn_id = f"turn-{index}-{turn}"
            pool = REQUESTS if turn == 0 else (CORRECTIONS, PREFERENCES, FEEDBACK)[turn % 3]
            ts += 1_000
            rows += [
                _codex("event_msg", ts, {"type": "task_started", "turn_id": turn_id}),
                _codex("turn_context", ts, {"turn_id": turn_id, "model": model, "effort": effort}),
                _codex(
                    "response_item",
                    ts,
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": pool[rng.randrange(len(pool))]}],
                    },
                ),
            ]
            for call in range(rng.randint(1, 3)):
                kind = ("shell", "edit", "read")[rng.randrange(3)]
                args = TOOLS[kind][1][rng.randrange(len(TOOLS[kind][1]))]
                call_id = f"c-{index}-{turn}-{call}"
                ts += 500
                rows.append(
                    _codex(
                        "response_item",
                        ts,
                        {
                            "type": "function_call",
                            "name": TOOLS[kind][0],
                            "call_id": call_id,
                            "arguments": json.dumps(
                                {"cmd": args} if kind == "shell" else {"path": args}
                            ),
                        },
                    )
                )
                ts += 500
                rows.append(
                    _codex(
                        "response_item",
                        ts,
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps({"exit_code": int(rng.random() < 0.2)}),
                        },
                    )
                )
            ts += 1_000
            rows.append(
                _codex(
                    "response_item",
                    ts,
                    {
                        "type": "message",
                        "role": "assistant",
                        "channel": "final",
                        "content": [
                            {"type": "output_text", "text": ASSISTANT[turn % len(ASSISTANT)]}
                        ],
                    },
                )
            )
        (folder / f"synthetic-{index}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
    return roots


def _codex(kind, ts, payload):
    from datetime import UTC, datetime

    stamp = datetime.fromtimestamp(ts / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {"type": kind, "timestamp": stamp, "payload": payload}


def build_canonical_home(
    home: Path, sessions: int = 200, seed: int = 7, workdir: Path | None = None
) -> Path:
    """Import fictional sources through the public ingest path; returns the Tandem home."""
    from tandem_backend.data_access.ingest import ingest

    with tempfile.TemporaryDirectory(dir=workdir) as scratch:
        for source_root in write_codex_sources(Path(scratch), sessions, seed):
            ingest(home, "codex", source_root)
    return home
