"""Synthetic Codex + Claude Code trees for uiview tests (fixed seeds, fixed clock).

Frozen copies of the a1a3 parity audit generators (``gen_rich`` Codex 90 / ``gen_cc`` Claude
Code 60): five projects, ~60 days, corrections, tool failures and token usage. Never reads
real agent directories; everything is written under the caller's tmp path.
"""

from __future__ import annotations

import json
import os
import random
import uuid
from datetime import UTC, datetime
from pathlib import Path

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC).timestamp()
PROJECTS = ["/synthetic/confluo", "/synthetic/latentskill", "/synthetic/team-hub",
            "/synthetic/hackathon", "/synthetic/quant"]
OK_MSG = ["继续", "好的，下一步", "先看看现在的进度", "可以，请运行测试并验证结果"]
BAD_MSG = ["不要用 Vercel，用 Cloudflare", "别重复试了，先检查认证", "不对，这不是我要的，重新来",
           "错了，你改多了，只改这一处"]
CMDS = [["git", "status"], ["npm", "run", "build"], ["pytest", "-q"], ["wrangler", "deploy"],
        ["ls", "-la"], ["curl", "-I", "https://x"], ["sed", "-n", "1,20p", "a.py"]]
CC_TOOLS = [("Bash", {"command": "npm run build"}), ("Read", {"file_path": "/synthetic/a.ts"}),
            ("Edit", {"file_path": "/synthetic/a.ts", "old_string": "a", "new_string": "b"}),
            ("Grep", {"pattern": "deploy"}), ("WebFetch", {"url": "https://x"})]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _codex_rollout(idx, started, rnd, project):
    sid = f"00000000-0000-4000-8000-{idx:012d}"
    rows = [{"timestamp": iso(started), "type": "session_meta",
             "payload": {"id": sid, "session_id": sid, "timestamp": iso(started), "cwd": project,
                         "model_provider": "openai", "cli_version": "synthetic"}}]
    t = started
    for k in range(rnd.randint(2, 9)):
        t += rnd.randint(40, 600)
        turn = f"turn-{idx}-{k}"
        corr = k > 0 and rnd.random() < 0.3
        if k == 0:
            text = f"synthetic task {idx}: 部署并验证 {project}"
        else:
            text = rnd.choice(BAD_MSG) if corr else rnd.choice(OK_MSG)
        rows += [
            {"timestamp": iso(t), "type": "event_msg",
             "payload": {"type": "task_started", "turn_id": turn, "started_at": int(t)}},
            {"timestamp": iso(t), "type": "turn_context",
             "payload": {"turn_id": turn, "model": rnd.choice(["gpt-x-high", "gpt-x-low"]),
                         "cwd": project}},
            {"timestamp": iso(t + 1), "type": "event_msg",
             "payload": {"type": "item_completed", "turn_id": turn, "item": {
                 "type": "UserMessage", "id": f"human-{idx}-{k}",
                 "content": [{"type": "text", "text": text}]}}},
        ]
        for j in range(rnd.randint(1, 8)):
            call = f"call-{idx}-{k}-{j}"
            cmd = rnd.choice(CMDS)
            fail = rnd.random() < 0.15
            rows += [
                {"timestamp": iso(t + 2 + j * 3), "type": "response_item",
                 "payload": {"type": "function_call", "name": "shell", "call_id": call,
                             "arguments": json.dumps({"command": cmd})}},
                {"timestamp": iso(t + 3 + j * 3), "type": "response_item",
                 "payload": {"type": "function_call_output", "call_id": call,
                             "output": json.dumps({"output": "err" if fail else "ok",
                                                   "metadata": {"exit_code": 1 if fail else 0}})}},
            ]
        rows += [
            {"timestamp": iso(t + 40), "type": "token_usage_record",
             "payload": {"response_id": f"resp-{idx}-{k}", "turn_id": turn,
                         "usage": {"input_tokens": rnd.randint(2000, 90000),
                                   "cached_input_tokens": 500,
                                   "output_tokens": rnd.randint(100, 4000)}}},
            {"timestamp": iso(t + 45), "type": "event_msg",
             "payload": {"type": "task_complete", "turn_id": turn, "completed_at": int(t + 45)}},
        ]
        t += 45
    return rows


def _start(rnd, now, hours):
    day = rnd.randint(0, 59)
    hour = rnd.choice(hours)
    return (now - day * 86400 - ((datetime.fromtimestamp(now, UTC).hour - hour) % 24) * 3600
            - rnd.randint(0, 3000))


def build_codex(root: Path, n: int = 90, now: float = NOW, seed: int = 7) -> None:
    rnd = random.Random(seed)
    for i in range(n):
        started = _start(rnd, now, [1, 2, 9, 10, 11, 14, 15, 16, 20, 21, 22])
        d = datetime.fromtimestamp(started, UTC)
        path = (root / "sessions" / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}"
                / f"rollout-{d:%Y-%m-%dT%H-%M-%S}-{i:06d}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = _codex_rollout(i, started, rnd, rnd.choice(PROJECTS))
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        os.utime(path, (started, started))


def _cc_session(idx, started, rnd, project):
    sid = str(uuid.UUID(int=idx + 1000))
    rows: list[dict] = []
    state = {"t": started, "parent": None}

    def add(typ, msg, ts, **kw):
        u = str(uuid.UUID(int=rnd.getrandbits(128)))
        rows.append({"type": typ, "uuid": u, "parentUuid": state["parent"], "sessionId": sid,
                     "cwd": project, "timestamp": iso(ts), "version": "2.1.0", "message": msg,
                     **kw})
        state["parent"] = u

    t = started
    for k in range(rnd.randint(2, 9)):
        t += rnd.randint(40, 500)
        if k == 0:
            text = f"synthetic cc task {idx}: 部署并验证"
        else:
            text = rnd.choice(BAD_MSG) if rnd.random() < 0.3 else rnd.choice(OK_MSG)
        prompt = f"p{idx}-{k}"
        add("user", {"role": "user", "content": text}, t, promptId=prompt)
        for j in range(rnd.randint(1, 7)):
            name, inp = rnd.choice(CC_TOOLS)
            tid = f"toolu_{idx}_{k}_{j}"
            fail = rnd.random() < 0.15
            t += 3
            add("assistant", {"id": f"msg_{idx}_{k}_{j}", "role": "assistant",
                              "model": "claude-opus-4-5", "stop_reason": "tool_use",
                              "content": [{"type": "tool_use", "id": tid, "name": name,
                                           "input": inp}],
                              "usage": {"input_tokens": rnd.randint(100, 3000),
                                        "cache_read_input_tokens": rnd.randint(1000, 60000),
                                        "cache_creation_input_tokens": rnd.randint(0, 2000),
                                        "output_tokens": rnd.randint(50, 1500)}},
                t, promptId=prompt)
            t += 2
            add("user", {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": "err" if fail else "ok",
                 "is_error": fail}]}, t, promptId=prompt,
                toolUseResult={"durationMs": rnd.randint(200, 9000)})
        t += 5
        add("assistant", {"id": f"msg_{idx}_{k}_end", "role": "assistant",
                          "model": "claude-opus-4-5", "stop_reason": "end_turn",
                          "content": [{"type": "text", "text": "done"}],
                          "usage": {"input_tokens": 200, "cache_read_input_tokens": 20000,
                                    "cache_creation_input_tokens": 0, "output_tokens": 300}},
            t, promptId=prompt)
    return sid, rows


def build_claude(root: Path, n: int = 60, now: float = NOW, seed: int = 11) -> None:
    rnd = random.Random(seed)
    for i in range(n):
        started = _start(rnd, now, [0, 1, 9, 10, 11, 14, 15, 16, 20, 21, 23])
        proj = rnd.choice(PROJECTS[:4])
        sid, rows = _cc_session(i, started, rnd, proj)
        path = root / "projects" / proj.replace("/", "-") / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        os.utime(path, (started, started))


def build_home(tmp: Path, codex: int = 90, claude: int = 60) -> Path:
    """Write both trees, capture them into a canonical store and return its home."""
    from orbit_data.store import Store as DataStore

    roots = {"codex": tmp / "agents" / "codex", "claude_code": tmp / "agents" / "claude"}
    build_codex(roots["codex"], codex)
    build_claude(roots["claude_code"], claude)
    home = tmp / "home"
    with DataStore(home) as store:
        for agent, root in roots.items():
            source = store.add_source(agent, root)
            for path in sorted(root.rglob("*.jsonl")):
                store.capture_stream(source, path.relative_to(root).as_posix(),
                                     [path.read_bytes()])
        store.rebuild()
    return home


TODAY = datetime.fromtimestamp(NOW, UTC).date()
_CACHE: dict = {}


def analysed(display_timezone: str = "UTC"):
    """(home, scope, analysis result, facts body), built once per test process."""
    if display_timezone in _CACHE:
        return _CACHE[display_timezone]
    import atexit
    import shutil
    import tempfile

    from orbit_backend.analytics.inputs import Scope
    from orbit_backend.analytics.service import analyze_store
    from orbit_backend.data_access.store import CanonicalStore
    from orbit_backend.uiview.facts import build_facts

    tmp = Path(tempfile.mkdtemp(prefix="uiview-synth-"))
    atexit.register(shutil.rmtree, tmp, True)
    home = build_home(tmp)
    store = CanonicalStore(home)
    scope = Scope(display_timezone=display_timezone)
    result = analyze_store(store, scope, False)
    with store.connect() as conn:
        body = build_facts(conn, result, scope)
    _CACHE[display_timezone] = (home, store, scope, result, body)
    return _CACHE[display_timezone]
