"""Synthetic Codex home with common friction (parity audit row format). Never reads real data.

Six session kinds repeat: read-only approvals, failing tests plus a missing CLI, long unverified
edits, corrections, compactions and mixed tasks; plus unused skills/MCP and a 261-line AGENTS.md.
"""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path


def iso(ts):
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


class S:
    def __init__(self, root, idx, started, cwd):
        self.root = root
        self.idx, self.t, self.rows, self.n = idx, started, [], 0
        sid = f"00000000-0000-4000-9000-{idx:012d}"
        self.sid = sid
        self.add(
            {
                "type": "session_meta",
                "payload": {
                    "id": sid,
                    "session_id": sid,
                    "timestamp": iso(started),
                    "cwd": cwd,
                    "model_provider": "openai",
                    "cli_version": "synthetic",
                    "source": "cli",
                },
            }
        )
        self.turn = None

    def add(self, row):
        self.t += 7
        row["timestamp"] = iso(self.t)
        self.rows.append(row)

    def item(self, item):
        self.add(
            {
                "type": "event_msg",
                "payload": {"type": "item_completed", "turn_id": self.turn, "item": item},
            }
        )

    def user(self, text):
        self.n += 1
        self.turn = f"t{self.idx}-{self.n}"
        self.add({"type": "event_msg", "payload": {"type": "task_started", "turn_id": self.turn}})
        self.add(
            {
                "type": "turn_context",
                "payload": {"turn_id": self.turn, "model": "gpt-5-codex", "cwd": "x"},
            }
        )
        self.item(
            {
                "id": f"u{self.idx}-{self.n}",
                "type": "UserMessage",
                "content": [{"type": "text", "text": text}],
            }
        )

    def say(self, text):
        self.n += 1
        self.item(
            {
                "id": f"a{self.idx}-{self.n}",
                "type": "AgentMessage",
                "content": [{"type": "text", "text": text}],
            }
        )

    def cmd(self, argv, ok=True, out="", approve=False):
        self.n += 1
        cid = f"c{self.idx}-{self.n}"
        if approve:
            self.add(
                {
                    "type": "event_msg",
                    "payload": {"type": "exec_approval_request", "call_id": cid, "command": argv},
                }
            )
            self.add(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "exec_approval_response",
                        "call_id": cid,
                        "decision": "approved",
                    },
                }
            )
        self.item(
            {
                "id": cid,
                "type": "CommandExecution",
                "command": argv,
                "status": "completed" if ok else "failed",
                "exit_code": 0 if ok else (127 if "not found" in out else 1),
                "duration_ms": 900,
                "aggregated_output": out or "ok",
            }
        )

    def patch(self, path):
        self.n += 1
        self.item(
            {
                "id": f"p{self.idx}-{self.n}",
                "type": "FileChange",
                "status": "completed",
                "changes": {path: {"type": "update", "unified_diff": "@@ -1 +1 @@\n-a\n+b\n"}},
            }
        )

    def compact(self):
        self.add({"type": "event_msg", "payload": {"type": "context_compacted"}})

    def usage(self, inp=60000):
        self.add(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": inp,
                            "cached_input_tokens": 1000,
                            "output_tokens": 2000,
                            "total_tokens": inp + 2000,
                        },
                        "model_context_window": 200000,
                    },
                },
            }
        )

    def done(self):
        self.add({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": self.turn}})

    def write(self):
        d = datetime.fromtimestamp(
            float(
                datetime.fromisoformat(self.rows[0]["timestamp"].replace("Z", "+00:00")).timestamp()
            ),
            UTC,
        )
        p = (
            self.root
            / "sessions"
            / f"{d:%Y}"
            / f"{d:%m}"
            / f"{d:%d}"
            / f"rollout-{d:%Y-%m-%dT%H-%M-%S}-{self.idx:06d}.jsonl"
        )
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows))
        st = datetime.fromisoformat(self.rows[0]["timestamp"].replace("Z", "+00:00")).timestamp()
        os.utime(p, (st, st))


def write_friction_codex(ROOT: Path, N: int = 36, NOW: float | None = None) -> Path:
    NOW = time.time() if NOW is None else NOW
    PROJ = ["/synthetic/webapp", "/synthetic/paper", "/synthetic/infra"]
    N = 36
    for i in range(N):
        s = S(ROOT, i, NOW - (N - i) * 20 * 3600, PROJ[i % 3])
        kind = i % 6
        if kind == 0:  # read-only approvals
            s.user("看一下当前分支状态和 PR 情况")
            for argv in (
                ["git", "status"],
                ["git", "diff", "--stat"],
                ["ls", "-la"],
                ["gh", "pr", "view", "12"],
                ["git", "log", "-5"],
                ["git", "status"],
            ):
                s.cmd(argv, approve=True)
            s.say("分支干净，PR #12 等待 review。")
            s.done()
        elif kind == 1:  # recurring test failures + identical retries + missing tool
            s.user("修复登录接口的测试失败，用 pnpm 跑测试")
            for _ in range(4):
                s.cmd(
                    ["pytest", "tests/test_login.py"],
                    ok=False,
                    out="FAILED tests/test_login.py::test_token - AssertionError",
                )
            s.cmd(["wrangler", "deploy"], ok=False, out="zsh: command not found: wrangler")
            s.cmd(["wrangler", "deploy"], ok=False, out="zsh: command not found: wrangler")
            s.patch("src/auth/login.py")
            s.cmd(
                ["pytest", "tests/test_login.py"],
                ok=False,
                out="FAILED tests/test_login.py::test_token - AssertionError",
            )
            s.user("还是失败，不对，先看清楚报错再改，不要乱改")
            s.patch("src/auth/login.py")
            s.cmd(["pytest", "tests/test_login.py"], ok=True, out="1 passed")
            s.say("已修复，测试通过。")
            s.done()
        elif kind == 2:  # long editing session, no verification, claims done
            s.user("重构 webapp 的路由模块，把 handlers 拆成多个文件")
            for k in range(12):
                s.patch(f"src/routes/handler_{k}.py")
            s.usage(150000)
            s.say("已完成重构，所有路由都已拆分，功能应该没问题。")
            s.done()
        elif kind == 3:  # corrections / wrong approach + repeated instruction
            s.user("把站点部署上线，请用 pnpm 而不是 npm")
            s.cmd(["npx", "vercel", "--prod"], ok=False, out="Error: not logged in")
            s.user("不对，我们不用 Vercel，部署目标是 Cloudflare Pages")
            s.cmd(["npx", "vercel", "deploy"], ok=False, out="Error: not logged in")
            s.user("还是不对！我说了不要用 Vercel，用 wrangler 部署到 Cloudflare")
            s.cmd(
                ["wrangler", "pages", "deploy", "dist"],
                ok=False,
                out="zsh: command not found: wrangler",
            )
            s.user("请用 pnpm 而不是 npm，记住这一点")
            s.say("好的，已改用 pnpm。")
            s.done()
        elif kind == 4:  # context compaction then repeated explanation
            s.user("继续写论文第三节的实验部分，正文不要超过 9 页，回答用中文")
            for k in range(6):
                s.patch(f"paper/sec3_{k}.tex")
                s.usage(120000 + k * 10000)
            s.compact()
            s.user("压缩之后你忘了：正文不要超过 9 页，回答用中文，我再说一遍")
            s.patch("paper/sec3.tex")
            s.compact()
            s.user("又忘了约定，正文不超过 9 页")
            s.say("已更新第三节。")
            s.done()
        else:  # mixed tasks in one session
            s.user("修一下登录页的样式问题")
            s.patch("src/ui/login.css")
            s.user("另外帮我写论文摘要的英文版")
            s.patch("paper/abstract.tex")
            s.user("顺便把 infra 的 cron 任务改成每 30 分钟一次")
            s.patch("infra/cron.yaml")
            s.user("再查一下为什么 CI 慢")
            s.cmd(["gh", "run", "list"], approve=True)
            s.say("几件事都处理好了。")
            s.done()
        s.write()

    # inventory: MCP never used, skills never used, long AGENTS.md
    (ROOT / "config.toml").write_text(
        'model = "gpt-5-codex"\n\n[mcp_servers.figma]\ncommand = "figma-mcp"\nargs = []\n\n[mcp_servers.browser]\ncommand = "browser-mcp"\nargs = []\n'
    )
    for name in ("pdf-tools", "old-helper"):
        d = ROOT / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: synthetic skill {name} that is never used\n---\n"
            + "Use this skill carefully.\n" * 400
        )
    (ROOT / "AGENTS.md").write_text(
        "# Rules\n"
        + "".join(f"- 规则 {k}：保持代码风格一致，提交前运行测试。\n" for k in range(260))
    )
    return ROOT
