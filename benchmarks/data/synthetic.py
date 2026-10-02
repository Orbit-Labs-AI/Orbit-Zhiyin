"""Deterministic synthetic native session trees for import benchmarks and integrity tests.

Only fictional data is produced. The same preset and seed always produce byte-identical
files, including the SQLite source database and ``manifest.json``.

Layout under ``out``::

    sources/claude_code   projects/**.jsonl, subagents + meta sidecars, resumed copies
    sources/pi            sessions/**.jsonl, forks with ``parentSession`` copied prefixes
    sources/dsh           sessions/**/session.v4.jsonl plus older ``session.v3`` generations
    sources/opencode      opencode.db (SQLite source)
    inventory/claude_code skills, MCP servers, hooks, plugins and rules
    manifest.json         expected sessions/events/inventory and large-output digests

Usage: ``uv run python -m benchmarks.data.synthetic --preset small --out DIR``.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

GENERATOR_VERSION = "1"
BASE_MS = 1_780_000_000_000
BIG_EVERY = 20  # 1 in 20 tool outputs (5%) is a large output.
BIG_LINES = 700  # 700 * 61 bytes + header > 40 KiB.
BIG_MIN_BYTES = 40 * 1024


@dataclass(frozen=True)
class Preset:
    sessions: int  # per JSONL agent (claude_code, pi, dsh)
    turns: int
    opencode_sessions: int


PRESETS = {
    "small": Preset(sessions=10, turns=4, opencode_sessions=4),
    "med": Preset(sessions=300, turns=15, opencode_sessions=30),
    "full": Preset(sessions=2000, turns=15, opencode_sessions=100),
}

# Expected L2 events per native record shape, pinned against the current mappers.
# A mapper change that alters these counts must update the table deliberately.
EVENTS = {
    "claude_code": {"session": 1, "user": 1, "assistant": 3, "tool_result": 1, "subagent_meta": 1},
    "pi": {"session": 1, "user": 1, "assistant": 3, "tool_result": 1},
    "dsh": {
        "session": 1,
        "turn/start": 1,
        "user/message": 1,
        "assistant/message": 2,
        "tool/call": 1,
        "tool/result": 1,
        "turn/end": 1,
    },
    "opencode": {"session": 1, "user": 1, "assistant": 3},
}


def _line(row) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_line(row) for row in rows), encoding="utf-8")


def iso(ms: int) -> str:
    moment = datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Generator:
    def __init__(self, out: Path, preset: Preset, seed: int):
        self.out, self.preset = out, preset
        self.rng = random.Random(seed)
        self.outputs = 0
        self.large: list[dict] = []
        self.counts: dict[str, dict[str, int]] = {}

    # Shared helpers -------------------------------------------------------------------
    def tally(self, agent: str, *, sessions=0, events=0, records=0, files=0) -> None:
        bucket = self.counts.setdefault(
            agent, {"sessions": 0, "events": 0, "records": 0, "files": 0}
        )
        bucket["sessions"] += sessions
        bucket["events"] += events
        bucket["records"] += records
        bucket["files"] += files

    def output(self, agent: str, session: str) -> str:
        index = self.outputs
        self.outputs += 1
        if index % BIG_EVERY:
            return "ok " * self.rng.randrange(5, 80)
        text = (
            f"{agent} output {index}: line {self.rng.randrange(10**6)}\n"
            + ("x" * 60 + "\n") * BIG_LINES
        )
        data = text.encode()
        assert len(data) >= BIG_MIN_BYTES
        self.large.append(
            {
                "agent": agent,
                "session": session,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        return text

    def words(self, word: str, high: int) -> str:
        return (word + " ") * self.rng.randrange(1, high)

    # claude_code ---------------------------------------------------------------------
    def claude_turn(self, sid, native, prefix, k, t, cwd, extra=None):
        common = {"sessionId": sid, "cwd": cwd, "version": "2.1.0", **(extra or {})}
        out = self.output("claude_code", native)
        user, assistant, result = f"{prefix}-u{k}", f"{prefix}-a{k}", f"{prefix}-o{k}"
        return [
            {
                **common,
                "type": "user",
                "uuid": user,
                "timestamp": iso(t),
                "message": {
                    "role": "user",
                    "content": f"请修复第 {k} 个问题 " + self.words("需求描述", 30),
                },
            },
            {
                **common,
                "type": "assistant",
                "uuid": assistant,
                "parentUuid": user,
                "timestamp": iso(t + 1000),
                "message": {
                    "id": f"{prefix}-r{k}",
                    "model": "fixture-model",
                    "stop_reason": "tool_use",
                    "content": [
                        {"type": "text", "text": self.words("我来检查。", 20)},
                        {
                            "type": "tool_use",
                            "id": f"{prefix}-c{k}",
                            "name": "Bash",
                            "input": {"command": f"git status && pytest -q tests/test_{k}.py"},
                        },
                    ],
                    "usage": {
                        "input_tokens": 1000 + k,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 10,
                    },
                },
            },
            {
                **common,
                "type": "user",
                "uuid": result,
                "parentUuid": assistant,
                "timestamp": iso(t + 3000),
                "toolUseResult": {
                    "durationMs": 800,
                    "stdout": out,
                    "stderr": "",
                    "interrupted": False,
                },
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"{prefix}-c{k}",
                            "content": out,
                            "is_error": False,
                        }
                    ],
                },
            },
        ]

    def claude_events(self, turns: int) -> int:
        per = EVENTS["claude_code"]
        return per["session"] + turns * (per["user"] + per["assistant"] + per["tool_result"])

    def claude(self, s: int, t0: int) -> None:
        root = self.out / "sources/claude_code/projects" / f"-work-proj{s % 17}"
        sid, cwd, turns = f"cc-{s:05d}", f"/work/proj{s % 17}", self.preset.turns
        rows = []
        for k in range(turns):
            rows += self.claude_turn(sid, sid, sid, k, t0 + k * 6000, cwd)
        _write_jsonl(root / f"{sid}.jsonl", rows)
        self.tally(
            "claude_code", sessions=1, events=self.claude_events(turns), records=len(rows), files=1
        )
        if s % 10 == 3:
            # Subagent transcript beside its parent plus the metadata sidecar.
            agent = f"agent-a{s:05d}"
            native = f"{sid}:{agent}"
            extra = {"isSidechain": True, "agentId": f"a{s:05d}"}
            sub = []
            for k in range(2):
                sub += self.claude_turn(
                    sid, native, f"{sid}-sa", k, t0 + 500 + k * 6000, cwd, extra
                )
            folder = root / sid / "subagents"
            _write_jsonl(folder / f"{agent}.jsonl", sub)
            meta = {"agentType": "general-purpose", "spawnDepth": 1, "toolUseId": f"{sid}-c0"}
            (folder / f"{agent}.meta.json").write_text(
                json.dumps(meta, sort_keys=True) + "\n", encoding="utf-8"
            )
            self.tally(
                "claude_code",
                sessions=1,
                events=self.claude_events(2) + EVENTS["claude_code"]["subagent_meta"],
                records=len(sub) + 1,
                files=2,
            )
        if s % 10 == 7:
            # `--resume` writes a new session file that copies the earlier prefix verbatim
            # except for the new sessionId; copied rows are replayed, not new events.
            new = f"cc-r-{s:05d}"
            copied = [{**row, "sessionId": new} for row in rows[:6]]
            own = []
            for k in range(2):
                own += self.claude_turn(new, new, new, k, t0 + (turns + k) * 6000, cwd)
            _write_jsonl(root / f"{new}.jsonl", copied + own)
            self.tally(
                "claude_code",
                sessions=1,
                events=self.claude_events(2),
                records=len(copied) + len(own),
                files=1,
            )

    # pi --------------------------------------------------------------------------------
    def pi_turn(self, sid, ids, k, t, previous):
        user, assistant, result = (f"{ids}u{k}", f"{ids}a{k}", f"{ids}o{k}")
        return [
            {
                "type": "message",
                "id": user,
                "parentId": previous,
                "timestamp": iso(t),
                "message": {"role": "user", "content": f"任务 {k} " + self.words("细节", 30)},
            },
            {
                "type": "message",
                "id": assistant,
                "parentId": user,
                "timestamp": iso(t + 1000),
                "message": {
                    "role": "assistant",
                    "provider": "fixture",
                    "model": "fixture-model",
                    "content": [
                        {"type": "text", "text": "好的" * self.rng.randrange(1, 30)},
                        {
                            "type": "toolCall",
                            "id": f"{ids}c{k}",
                            "name": "bash",
                            "arguments": {"command": f"ls -la src/{k}"},
                        },
                    ],
                    "usage": {
                        "input": 900,
                        "output": 40,
                        "cacheRead": 800,
                        "cacheWrite": 0,
                        "cost": {"total": 0.01},
                    },
                },
            },
            {
                "type": "message",
                "id": result,
                "parentId": assistant,
                "timestamp": iso(t + 3000),
                "message": {
                    "role": "toolResult",
                    "toolCallId": f"{ids}c{k}",
                    "toolName": "bash",
                    "isError": False,
                    "content": [{"type": "text", "text": self.output("pi", sid)}],
                },
            },
        ]

    def pi(self, s: int, t0: int, previous_file: str | None, previous_rows: list) -> tuple:
        sid, turns = f"pi-{s:05d}", self.preset.turns
        relative = f"sessions/proj{s % 13}/{sid}.jsonl"
        header = {
            "type": "session",
            "id": sid,
            "version": 3,
            "timestamp": iso(t0),
            "cwd": f"/work/proj{s % 13}",
        }
        rows, copied, ids = [header], [], ""
        fork = s % 10 == 5 and previous_file is not None
        if fork:
            # A fork copies the parent's first turn verbatim and records the parent file.
            header["parentSession"] = previous_file
            copied = previous_rows[1:4]
            rows += copied
            ids = "f"
        last = copied[-1]["id"] if copied else None
        own = []
        for k in range(turns):
            own += self.pi_turn(sid, ids, k, t0 + k * 6000, last)
            last = own[-1]["id"]
        rows += own
        _write_jsonl(self.out / "sources/pi" / relative, rows)
        per = EVENTS["pi"]
        self.tally(
            "pi",
            sessions=1,
            events=per["session"] + turns * (per["user"] + per["assistant"] + per["tool_result"]),
            records=len(rows),
            files=1,
        )
        return relative, rows

    # dsh -------------------------------------------------------------------------------
    def dsh(self, s: int, t0: int) -> None:
        sid, turns = f"dsh-{s:05d}", self.preset.turns
        folder = self.out / "sources/dsh/sessions" / f"proj{s % 11}" / sid
        rows = [
            {
                "type": "session",
                "id": sid,
                "version": 4,
                "createdAt": t0,
                "cwd": f"/work/proj{s % 11}",
            }
        ]
        clock = [t0]

        def add(kind, data):
            rows.append({"type": kind, "seq": len(rows) - 1, "time": clock[0], "data": data})
            clock[0] += 500

        for k in range(1, turns + 1):
            add("turn/start", {"turn": k})
            add(
                "user/message",
                {
                    "role": "user",
                    "source": {"kind": "user"},
                    "content": [{"type": "text", "text": f"第 {k} 步 " + self.words("说明", 30)}],
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
                        "content": [{"type": "text", "text": "执行" * self.rng.randrange(1, 20)}],
                    },
                    "usage": {
                        "inputTokens": 900,
                        "outputTokens": 30,
                        "cacheReadTokens": 700,
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
                    "arguments": json.dumps({"command": f"make test-{k}"}),
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
                        "content": [{"type": "text", "text": self.output("dsh", sid)}],
                    },
                },
            )
            add("turn/end", {"turn": k, "reason": {"kind": "completed"}})
        _write_jsonl(folder / "session.v4.jsonl", rows)
        per = EVENTS["dsh"]
        events = per["session"] + turns * sum(
            per[kind]
            for kind in (
                "turn/start",
                "user/message",
                "assistant/message",
                "tool/call",
                "tool/result",
                "turn/end",
            )
        )
        self.tally("dsh", sessions=1, events=events, records=len(rows), files=1)
        if s % 10 == 1:
            # An older on-disk generation: indexed for lossless L1, ignored for L2.
            legacy = [{**rows[0], "version": 3}, *rows[1:4]]
            _write_jsonl(folder / "session.v3.jsonl", legacy)
            self.tally("dsh", records=len(legacy), files=1)

    # opencode (SQLite source) ----------------------------------------------------------
    def opencode(self) -> None:
        folder = self.out / "sources/opencode"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "opencode.db"
        sessions, messages = [], []
        for s in range(self.preset.opencode_sessions):
            sid, t0 = f"oc-{s:05d}", BASE_MS + s * 3_600_000
            sessions.append((sid, f"/work/proj{s % 7}", f"OpenCode 会话 {s}"))
            for k in range(self.preset.turns):
                t = t0 + k * 6000
                user = {"text": f"请处理 {k} " + self.words("内容", 20), "time": {"created": t}}
                messages.append((f"{sid}-u{k}", sid, 2 * k, "user", _line(user).strip()))
                assistant = {
                    "model": {"id": "fixture-model", "providerID": "fixture"},
                    "time": {"created": t + 1000},
                    "content": [
                        {
                            "type": "tool",
                            "id": f"{sid}-c{k}",
                            "name": "bash",
                            "time": {"created": t + 1000, "ran": t + 1500, "completed": t + 3000},
                            "state": {
                                "status": "completed",
                                "input": {"command": f"npm test -- {k}"},
                                "content": [{"type": "text", "text": self.output("opencode", sid)}],
                                "structured": {},
                            },
                        }
                    ],
                    "tokens": {
                        "input": 900,
                        "output": 30,
                        "reasoning": 5,
                        "cache": {"read": 700, "write": 0},
                    },
                    "cost": 0.01,
                }
                messages.append(
                    (f"{sid}-a{k}", sid, 2 * k + 1, "assistant", _line(assistant).strip())
                )
            per = EVENTS["opencode"]
            self.tally(
                "opencode",
                sessions=1,
                events=per["session"] + self.preset.turns * (per["user"] + per["assistant"]),
            )
        if path.exists():
            path.unlink()
        db = sqlite3.connect(path)
        try:
            db.executescript(
                "PRAGMA journal_mode=DELETE;"
                "CREATE TABLE session(id TEXT PRIMARY KEY,directory TEXT,title TEXT);"
                "CREATE TABLE session_message(id TEXT PRIMARY KEY,session_id TEXT,seq INTEGER,"
                "type TEXT,data TEXT);"
            )
            db.executemany("INSERT INTO session VALUES(?,?,?)", sessions)
            db.executemany("INSERT INTO session_message VALUES(?,?,?,?,?)", messages)
            db.commit()
        finally:
            db.close()
        self.tally("opencode", records=len(sessions) + len(messages), files=1)

    # Inventory -------------------------------------------------------------------------
    def inventory(self) -> dict:
        root = self.out / "inventory/claude_code"
        items = []

        def put(relative: str, data: bytes) -> None:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        def source_hash(value) -> str:
            # Same normalization as tandem_data.inventory.adapters._source_bytes.
            raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
            return hashlib.sha256(raw).hexdigest()

        servers = {
            "search": {"command": "npx", "args": ["fixture-search"]},
            "docs": {"url": "https://mcp.example.test/docs", "disabled": True},
        }
        hooks = {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}
            ],
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": "echo stop"},
                        {"type": "prompt", "prompt": "summarize"},
                    ]
                }
            ],
        }
        plugins = {"formatter@fixture-market": True, "linter@fixture-market": False}
        settings = {"mcpServers": servers, "hooks": hooks, "enabledPlugins": plugins}
        put("settings.json", (json.dumps(settings, indent=2, sort_keys=True) + "\n").encode())
        for name, value in sorted(servers.items()):
            items.append(("mcp", name, f"mcpServers/{name}", source_hash(value)))
        for event, groups in sorted(hooks.items()):
            for i, group in enumerate(groups):
                for j, hook in enumerate(group["hooks"]):
                    items.append(("hook", event, f"hooks/{event}/{i}/{j}", source_hash(hook)))
        for name, enabled in sorted(plugins.items()):
            items.append(("plugin", name, f"enabledPlugins/{name}", source_hash(enabled)))
        for name in ("review", "release-notes", "sql-tuning"):
            body = f"---\nname: {name}\ndescription: fixture skill {name}\n---\n合成技能 {name}\n"
            put(f"skills/{name}/SKILL.md", body.encode())
            items.append(("skill", name, "", hashlib.sha256(body.encode()).hexdigest()))
        rules = {
            "CLAUDE.md": "# 合成规则\n只使用构造数据。\n",
            "rules/style.md": "保持小步提交。\n",
            "rules/testing.md": "提交前运行检查。\n",
        }
        for relative, body in sorted(rules.items()):
            put(relative, body.encode())
            items.append(("rule", relative, "", hashlib.sha256(body.encode()).hexdigest()))
        return {
            "agent": "claude_code",
            "root": "inventory/claude_code",
            "items": [
                {"type": t, "name": n, "locator": loc, "content_hash": h}
                for t, n, loc, h in sorted(items)
            ],
        }

    def run(self) -> dict:
        previous_file, previous_rows = None, []
        for s in range(self.preset.sessions):
            t0 = BASE_MS + s * 3_600_000
            self.claude(s, t0)
            previous_file, previous_rows = self.pi(s, t0, previous_file, previous_rows)
            self.dsh(s, t0)
        self.opencode()
        inventory = self.inventory()
        return {"agents": self.counts, "large_outputs": self.large, "inventory": inventory}


def generate(out: str | Path, preset: str | Preset = "small", seed: int = 7) -> dict:
    """Write the synthetic tree and ``manifest.json``; return the manifest."""
    out = Path(out)
    spec = PRESETS[preset] if isinstance(preset, str) else preset
    if (out / "manifest.json").exists() or (out / "sources").exists():
        raise FileExistsError(f"{out} already contains generated data")
    out.mkdir(parents=True, exist_ok=True)
    body = Generator(out, spec, seed).run()
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "preset": preset if isinstance(preset, str) else "custom",
        "parameters": asdict(spec),
        "seed": seed,
        "sources": {agent: f"sources/{agent}" for agent in sorted(body["agents"])},
        "large_output_min_bytes": BIG_MIN_BYTES,
        **body,
    }
    totals = {
        key: sum(agent[key] for agent in body["agents"].values())
        for key in ("sessions", "events", "records", "files")
    }
    manifest["totals"] = totals
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preset", choices=sorted(PRESETS), default="small")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = generate(args.out, args.preset, args.seed)
    print(json.dumps({"out": str(args.out), "totals": manifest["totals"]}))


if __name__ == "__main__":
    main()
