"""Engines and capability probes against fake CLIs (no real model, no network)."""

from __future__ import annotations

import io
import json
import statistics
import threading
import time
from pathlib import Path

import pytest
from ai_support import ANSWER

from tandem_backend.ai import capabilities, engines, isolation, prices
from tandem_backend.ai.capabilities import Capabilities
from tandem_backend.ai.engines import (
    ApiKeyEngine,
    ClaudeCodeEngine,
    CodexEngine,
    EngineRequest,
    FakeEngine,
)
from tandem_backend.appdb import AppDB


def request(**overrides) -> EngineRequest:
    values = {"system": "SYSTEM-TEXT", "prompt": "SECRET-PROMPT-TEXT", "schema": ANSWER,
              "task_id": "test.echo", "job_id": "aj_1", "timeout_s": 20}
    values.update(overrides)
    return EngineRequest(**values)


def test_claude_argv_env_cwd_and_marker(fake_cli, ai_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("CLAUDE_CODE_SOMETHING", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    home = ai_env.tmp / "tandem"
    result = ClaudeCodeEngine(home).call(request(model="sonnet", max_budget_usd=0.1))
    assert result.error is None and result.output == {"answer": "ok"}
    assert result.usage == {"input": 120, "cache_read": 30, "cache_write": 10, "output": 40}
    assert (result.cost_usd, result.cost_source) == (0.0123, "reported")
    assert result.model_id == "claude-sonnet-5-5"
    call = fake_cli.calls()[-1]
    argv = call["argv"][1:]
    assert argv[:2] == ["-p", "--output-format"] and "--no-session-persistence" in argv
    assert argv[argv.index("--tools") + 1] == ""
    for flag in ("--safe-mode", "--strict-mcp-config", "--max-budget-usd", "--model",
                 "--effort", "--settings"):
        assert flag in argv
    assert "--max-turns" not in argv  # Not listed by this CLI's --help.
    assert not any("SECRET-PROMPT-TEXT" in part for part in call["argv"])
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_SOMETHING", "OPENAI_API_KEY"):
        assert key not in call["env"]
    assert call["env"]["NO_COLOR"] == "1"
    cwd = Path(call["cwd"]).resolve()
    assert cwd == (home / "agent-cwd").resolve() and (cwd / ".tandem-ai").is_file()
    first, rest = call["stdin"].split("\n", 1)
    assert first == isolation.marker_line("test.echo", "aj_1") and rest == "SECRET-PROMPT-TEXT"


def test_claude_error_modes(fake_cli, ai_env):
    engine = ClaudeCodeEngine(ai_env.tmp / "tandem")
    fake_cli.mode = "budget"
    assert engine.call(request()).error == "budget_exceeded"
    fake_cli.mode = "notlogged"
    assert engine.call(request()).error == "not_logged_in"


def test_claude_not_installed(ai_env):
    assert ClaudeCodeEngine(ai_env.tmp / "t").call(request()).detail == "not_installed"


def test_codex_argv_usage_and_cleanup(fake_cli, ai_env):
    home = ai_env.tmp / "tandem"
    result = CodexEngine(home).call(request())
    assert result.error is None and result.output == {"answer": "ok"}
    assert result.usage == {"input": 1000, "cache_read": 200, "cache_write": 0, "output": 50}
    assert result.cost_source == "unknown" and result.cost_usd is None
    call = fake_cli.calls()[-1]
    argv = call["argv"][1:]
    assert argv[:5] == ["exec", "--ephemeral", "--json", "--skip-git-repo-check", "-s"]
    assert {"--ignore-user-config", "--ignore-rules", "--output-schema", "-o"} <= set(argv)
    assert argv[-1] == "-" and argv[argv.index("-C") + 1] == str(home / "agent-cwd")
    assert call["stdin"].startswith(isolation.marker_line("test.echo", "aj_1") + "\nSYSTEM-TEXT")
    assert not (home / "tmp" / "ai" / "aj_1").exists()
    fake_cli.mode = "notlogged"
    assert CodexEngine(home).call(request(job_id="aj_2")).error == "not_logged_in"


def test_codex_price_table_when_model_known(fake_cli, ai_env):
    result = CodexEngine(ai_env.tmp / "t").call(request(model="claude-haiku-4-5"))
    assert result.cost_source == "price_table"
    assert result.cost_usd == prices.estimate(1000, 50, "claude-haiku-4-5")


def test_cancel_and_timeout_kill_process_group(fake_cli, ai_env):
    fake_cli.mode = "sleep"
    engine = ClaudeCodeEngine(ai_env.tmp / "tandem")
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    assert engine.call(request(cancel=cancel)).error == "cancelled"
    assert time.monotonic() - started < 2.5
    started = time.monotonic()
    assert engine.call(request(timeout_s=0.5)).error == "timeout"
    assert time.monotonic() - started < 3


def test_api_key_engine_forced_tool(monkeypatch, ai_env):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    seen = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(req, timeout):
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data)
        return Response(json.dumps({
            "model": "claude-haiku-4-5", "content": [
                {"type": "tool_use", "name": "emit", "input": {"answer": "hi"}}],
            "usage": {"input_tokens": 100, "output_tokens": 10}}).encode())

    monkeypatch.setattr(engines.urllib.request, "urlopen", urlopen)
    result = ApiKeyEngine(ai_env.tmp).call(request(slot="cheap"))
    assert result.output == {"answer": "hi"} and result.cost_source == "price_table"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "emit"}
    assert seen["body"]["model"] == "claude-haiku-4-5"
    assert seen["headers"]["Anthropic-version"] == "2023-06-01"
    assert "sk-test" not in repr(result)


def test_default_engines_register_api_key_only_with_env(monkeypatch, ai_env):
    assert set(engines.default_engines(ai_env.tmp)) == {"claude_code", "codex"}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    assert "api_key" in engines.default_engines(ai_env.tmp)


@pytest.mark.serial
def test_detect_and_cache(fake_cli, ai_env, monkeypatch):
    info = capabilities.detect("claude_code", ai_env.tmp / "t")
    assert info["available"] and info["logged_in"] is True
    assert info["version"].startswith("2.1.287")
    assert "--safe-mode" in info["flags"] and "--max-turns" not in info["flags"]
    fake_cli.mode = "notlogged"
    codex = capabilities.detect("codex", ai_env.tmp / "t")
    assert codex["available"] and codex["logged_in"] is False
    assert capabilities.detect("api_key", ai_env.tmp)["available"] is False

    runs = []
    real = capabilities._run
    monkeypatch.setattr(capabilities, "_run", lambda argv, home: runs.append(argv) or real(
        argv, home))
    db = AppDB(ai_env.tmp / "app.db")
    caps = Capabilities(db, ai_env.tmp / "t")
    found = {"claude_code": ClaudeCodeEngine(ai_env.tmp), "codex": CodexEngine(ai_env.tmp),
             "fake": FakeEngine()}
    first = caps.get(found)
    assert first["fake"]["available"] and len(runs) == 6
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        assert caps.get(found) == first
        timings.append(time.perf_counter() - started)
    assert len(runs) == 6  # Served from ai_engine; no subprocess.
    assert statistics.median(timings) < 0.005
    caps.get(found, refresh=True)
    assert len(runs) == 12
    db.close()


def test_is_tandem_ai_session(ai_env):
    home = ai_env.tmp / "tandem"
    cwd = isolation.cwd(home)
    assert isolation.is_tandem_ai_session(cwd, None, home)
    assert isolation.is_tandem_ai_session(cwd / "sub", None, home)
    assert isolation.is_tandem_ai_session(cwd, None)  # Marker file, no home given.
    assert isolation.is_tandem_ai_session("/x", "[tandem-analysis v1 task=a job=b]\nhi")
    assert not isolation.is_tandem_ai_session("/x", "hello", home)
    assert oct(cwd.stat().st_mode & 0o777) == "0o700"
    assert set(isolation.env()) <= {*isolation.ENV_KEEP, *isolation.ENV_OPTIONAL, "NO_COLOR"}


def test_prices():
    assert prices.estimate(1_000_000, 0, "claude-sonnet-5-5") == 2.0
    assert prices.estimate(0, 1_000_000, "opus") == 20.0
    assert prices.estimate(10, 10, "gpt-5") is None
