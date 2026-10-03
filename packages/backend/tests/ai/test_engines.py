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

from orbit_backend.ai import capabilities, engines, isolation, prices
from orbit_backend.ai.capabilities import Capabilities
from orbit_backend.ai.engines import (
    ApiKeyEngine,
    ClaudeCodeEngine,
    CodexEngine,
    EngineRequest,
    FakeEngine,
)
from orbit_backend.appdb import AppDB


def request(**overrides) -> EngineRequest:
    values = {"system": "SYSTEM-TEXT", "prompt": "SECRET-PROMPT-TEXT", "schema": ANSWER,
              "task_id": "test.echo", "job_id": "aj_1", "timeout_s": 20}
    values.update(overrides)
    return EngineRequest(**values)


def test_claude_argv_env_cwd_and_marker(fake_cli, ai_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("CLAUDE_CODE_SOMETHING", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    home = ai_env.tmp / "orbit"
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
    assert cwd == (home / "agent-cwd").resolve() and (cwd / ".orbit-ai").is_file()
    first, rest = call["stdin"].split("\n", 1)
    assert first == isolation.marker_line("test.echo", "aj_1") and rest == "SECRET-PROMPT-TEXT"


def test_claude_error_modes(fake_cli, ai_env):
    engine = ClaudeCodeEngine(ai_env.tmp / "orbit")
    fake_cli.mode = "budget"
    assert engine.call(request()).error == "budget_exceeded"
    fake_cli.mode = "notlogged"
    assert engine.call(request()).error == "not_logged_in"


def test_claude_not_installed(ai_env):
    assert ClaudeCodeEngine(ai_env.tmp / "t").call(request()).detail == "not_installed"


def test_codex_argv_usage_and_cleanup(fake_cli, ai_env):
    home = ai_env.tmp / "orbit"
    result = CodexEngine(home).call(request())
    assert result.error is None and result.output == {"answer": "ok"}
    assert result.usage == {"input": 800, "cache_read": 200, "cache_write": 0, "output": 50}
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
    # fake codex: 2 turns x (500 input incl. 100 cached, 25 output) -> 800 uncached, 200 cached, 50 out
    assert result.usage == {"input": 800, "cache_read": 200, "cache_write": 0, "output": 50}
    assert result.cost_usd == pytest.approx((800 * 1 + 200 * 0.1 + 50 * 5) / 1e6)


def test_cancel_and_timeout_kill_process_group(fake_cli, ai_env):
    fake_cli.mode = "sleep"
    engine = ClaudeCodeEngine(ai_env.tmp / "orbit")
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    assert engine.call(request(cancel=cancel)).error == "cancelled"
    assert time.monotonic() - started < 2.5
    started = time.monotonic()
    assert engine.call(request(timeout_s=0.5)).error == "timeout"
    assert time.monotonic() - started < 3


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _api(monkeypatch, *replies):
    """Patch urlopen with a queue of replies: dict -> 200 JSON body, int -> HTTPError status."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(engines, "_sleep", lambda s: seen["sleeps"].append(s))
    queue = list(replies)
    seen = {"bodies": [], "sleeps": []}

    def urlopen(req, timeout):
        seen["headers"] = dict(req.header_items())
        seen["bodies"].append(json.loads(req.data))
        reply = queue.pop(0)
        if isinstance(reply, int):
            raise engines.urllib.error.HTTPError(req.full_url, reply, "err", {}, None)
        return _Response(json.dumps(reply).encode())

    monkeypatch.setattr(engines.urllib.request, "urlopen", urlopen)
    return seen


def _text_reply(model, payload, stop="end_turn", **usage):
    return {"model": model, "stop_reason": stop,
            "content": [{"type": "thinking", "thinking": ""},
                        {"type": "text", "text": json.dumps(payload)}],
            "usage": {"input_tokens": 100, "output_tokens": 10, **usage}}


def test_api_key_engine_haiku_structured_output(monkeypatch, ai_env):
    seen = _api(monkeypatch, _text_reply("claude-haiku-4-5", {"answer": "hi"}))
    result = ApiKeyEngine(ai_env.tmp).call(request(slot="cheap", max_tokens=600))
    assert result.output == {"answer": "hi"} and result.cost_source == "price_table"
    body = seen["bodies"][0]
    assert body["model"] == "claude-haiku-4-5" and "tool_choice" not in body and "tools" not in body
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": ANSWER}}  # no effort on haiku
    assert body["max_tokens"] == 600  # haiku does not think unless asked: no headroom
    assert seen["headers"]["Anthropic-version"] == "2023-06-01"
    assert "sk-test" not in repr(result)
    # 100 in x $1 + 10 out x $5 per MTok
    assert result.cost_usd == pytest.approx((100 * 1 + 10 * 5) / 1e6)


@pytest.mark.parametrize("model,slot,effort", [("claude-sonnet-5-5", "main", "medium"),
                                               ("claude-opus-5-5", "main", "medium"),
                                               ("claude-fable-5-1", "cheap", "low")])
def test_api_key_engine_new_models_never_force_tool_choice(monkeypatch, ai_env, model, slot, effort):
    seen = _api(monkeypatch, _text_reply(model, {"answer": "ok"}))
    result = ApiKeyEngine(ai_env.tmp).call(request(slot=slot, model=model, max_tokens=1500))
    assert result.error is None and result.output == {"answer": "ok"}
    body = seen["bodies"][0]
    assert body.get("tool_choice", {}).get("type") not in ("any", "tool")
    assert body["output_config"]["effort"] == effort
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["max_tokens"] == 1500 + engines.THINKING_HEADROOM
    assert "thinking" not in body  # always-on adaptive; "disabled" would 400


def test_api_key_engine_open_schema_falls_back_to_auto_tool(monkeypatch, ai_env):
    schema = {"type": "object", "properties": {"m": {"type": "object", "additionalProperties": {"type": "integer"}}}}
    reply = {"model": "claude-sonnet-5-5", "stop_reason": "tool_use",
             "content": [{"type": "tool_use", "name": "emit", "input": {"m": {"a": 1}}}],
             "usage": {"input_tokens": 1, "output_tokens": 1}}
    seen = _api(monkeypatch, reply)
    result = ApiKeyEngine(ai_env.tmp).call(request(schema=schema, slot="main", model="claude-sonnet-5-5"))
    body = seen["bodies"][0]
    assert body["tool_choice"] == {"type": "auto"} and "emit" in body["messages"][0]["content"]
    assert "format" not in body["output_config"] and result.output == {"m": {"a": 1}}


def test_strict_schema_strips_unsupported_constraints():
    schema = {"type": "object", "required": ["n"], "properties": {
        "n": {"type": "integer", "minimum": 0, "maximum": 5},
        "s": {"type": "string", "maxLength": 9},
        "xs": {"type": "array", "maxItems": 3, "minItems": 2, "items": {"type": "object", "properties": {}}}}}
    assert engines.strict_schema(schema) == {
        "type": "object", "required": ["n"], "additionalProperties": False, "properties": {
            "n": {"type": "integer"}, "s": {"type": "string"},
            "xs": {"type": "array", "items": {"type": "object", "properties": {}, "additionalProperties": False}}}}


@pytest.mark.parametrize("stop,error", [("max_tokens", "truncated"), ("refusal", "refused")])
def test_api_key_engine_stop_reason_is_an_explicit_error(monkeypatch, ai_env, stop, error):
    reply = {"model": "claude-sonnet-5-5", "stop_reason": stop,
             "content": [{"type": "text", "text": '{"answer": "half'}],
             "usage": {"input_tokens": 5, "output_tokens": 9508}}
    if stop == "refusal":
        reply["stop_details"] = {"type": "refusal", "category": "cyber"}
    _api(monkeypatch, reply)
    result = ApiKeyEngine(ai_env.tmp).call(request(slot="main", model="claude-sonnet-5-5"))
    assert result.error == error and result.output is None
    assert f"stop_reason={stop}" in result.detail
    assert result.cost_usd is not None  # tokens were billed even though the output is unusable


def test_api_key_engine_http_400_is_not_retried(monkeypatch, ai_env):
    seen = _api(monkeypatch, 400)
    result = ApiKeyEngine(ai_env.tmp).call(request())
    assert (result.error, result.detail) == ("engine_error", "http 400")
    assert len(seen["bodies"]) == 1 and seen["sleeps"] == []


@pytest.mark.parametrize("status", [429, 529])
def test_api_key_engine_retries_overload_then_succeeds(monkeypatch, ai_env, status):
    seen = _api(monkeypatch, status, status, _text_reply("claude-haiku-4-5", {"answer": "ok"}))
    result = ApiKeyEngine(ai_env.tmp).call(request())
    assert result.output == {"answer": "ok"} and len(seen["bodies"]) == 3
    assert seen["sleeps"] == [1.0, 2.0]  # exponential backoff from RETRY_BASE_S


def test_api_key_engine_gives_up_after_bounded_retries(monkeypatch, ai_env):
    seen = _api(monkeypatch, 529, 529, 529)
    result = ApiKeyEngine(ai_env.tmp).call(request())
    assert (result.error, result.detail) == ("engine_error", "http 529")
    assert len(seen["bodies"]) == engines.API_RETRIES + 1


def test_api_cancel_during_retry_never_sends_again(monkeypatch, ai_env):
    seen = _api(monkeypatch, 503, _text_reply("claude-haiku-4-5", {"answer": "late"}))
    req = request()
    monkeypatch.setattr(engines, "_sleep", lambda _: req.cancel.set())
    result = ApiKeyEngine(ai_env.tmp).call(req)
    assert result.error == "cancelled" and len(seen["bodies"]) == 1


def test_api_retries_share_one_deadline(monkeypatch, ai_env):
    seen = _api(monkeypatch, 503, 503, 503)
    clock = [0.0]
    monkeypatch.setattr(engines.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engines, "_sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    result = ApiKeyEngine(ai_env.tmp).call(request(timeout_s=1.5))
    assert result.error == "timeout" and len(seen["bodies"]) == 2
    assert clock[0] == 1.5


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


def test_is_orbit_ai_session(ai_env):
    home = ai_env.tmp / "orbit"
    cwd = isolation.cwd(home)
    assert isolation.is_orbit_ai_session(cwd, None, home)
    assert isolation.is_orbit_ai_session(cwd / "sub", None, home)
    assert isolation.is_orbit_ai_session(cwd, None)  # Marker file, no home given.
    assert isolation.is_orbit_ai_session("/x", "[orbit-analysis v1 task=a job=b]\nhi")
    assert not isolation.is_orbit_ai_session("/x", "hello", home)
    assert oct(cwd.stat().st_mode & 0o777) == "0o700"
    assert set(isolation.env()) <= {*isolation.ENV_KEEP, *isolation.ENV_OPTIONAL, *isolation.ENV_NETWORK, "NO_COLOR"}


def test_isolation_env_keeps_network_drops_credentials(monkeypatch):
    keep = {"HTTPS_PROXY": "http://p:1", "http_proxy": "http://p:2", "ALL_PROXY": "socks5://p:3",
            "no_proxy": "localhost", "SSL_CERT_FILE": "/ca.pem", "NODE_EXTRA_CA_CERTS": "/ca2.pem"}
    drop = {"ANTHROPIC_API_KEY": "sk-x", "OPENAI_API_KEY": "sk-y", "GITHUB_TOKEN": "t",
            "ANTHROPIC_BASE_URL": "http://x", "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_SECRET_ACCESS_KEY": "s"}
    for k, v in {**keep, **drop}.items():
        monkeypatch.setenv(k, v)
    env = isolation.env()
    assert {k: env.get(k) for k in keep} == keep
    assert not set(drop) & set(env)


@pytest.mark.parametrize("model,price_in,price_out", [
    ("claude-fable-5-1", 10, 50), ("claude-opus-5-5", 4, 20), ("claude-opus-5", 5, 25),
    ("claude-opus-4-8", 5, 25), ("claude-sonnet-5-5", 2, 10), ("claude-sonnet-4-6", 3, 15),
    ("claude-haiku-4-5", 1, 5), ("claude-opus-4-8-20260101", 5, 25), ("claude-sonnet-5-5[1m]", 2, 10),
    ("anthropic.claude-opus-5-5", 4, 20)])
def test_prices_by_full_model_id(model, price_in, price_out):
    # List prices per MTok (Anthropic API price table, 2026-09-25); versions must not collapse.
    assert prices.estimate(1_000_000, 0, model) == price_in
    assert prices.estimate(0, 1_000_000, model) == price_out


@pytest.mark.parametrize("model", ["opus", "sonnet", "gpt-5", "claude-opus-6", None, ""])
def test_prices_unknown_model_is_none(model):
    assert prices.estimate(10, 10, model) is None
    assert prices.cost({"input": 10}, model) is None


def test_cache_pricing():
    million = 1_000_000
    # sonnet-4-6: write 1.25 x $3 = $3.75, read 0.1 x $3 = $0.30
    assert prices.cost({"cache_write": million}, "claude-sonnet-4-6") == 3.75
    assert prices.cost({"cache_read": million}, "claude-sonnet-4-6") == 0.3
    # models with a published cache-read price: opus-5-5 $0.20, fable-5-1 $0.25
    assert prices.cost({"cache_read": million}, "claude-opus-5-5") == 0.2
    assert prices.cost({"cache_read": million}, "claude-fable-5-1") == 0.25
    assert prices.cost({"input": 1000, "cache_write": 1000, "cache_read": 1000, "output": 1000},
                       "claude-haiku-4-5") == round((1000 * 1 + 1000 * 1.25 + 1000 * 0.1 + 1000 * 5) / 1e6, 6)
    # unknown model: conservative = most expensive table rate ($10 / $50)
    assert prices.conservative(million, million) == 60.0
