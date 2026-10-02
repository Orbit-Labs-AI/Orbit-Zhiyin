"""Engines: the user's logged-in ``claude`` / ``codex`` CLIs run headless, an optional
Anthropic API key, and a fake for tests.

CLI runs share one recipe: isolated cwd and env, a new process group, the prompt on
stdin (never argv), stdout capped at 4 MB, and SIGTERM → 1.5 s → SIGKILL on cancel or
timeout. Tandem never stores credentials; optional flags are passed only when the
installed CLI's ``--help`` lists them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import isolation, prices

STDOUT_LIMIT = 4 * 1024 * 1024
KILL_GRACE_S = 1.5
FALLBACK_DIRS: tuple[str, ...] = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin",
                                  "~/.claude/local", "~/.npm-global/bin")
API_URL = "https://api.anthropic.com/v1/messages"
API_MODELS = {"cheap": "claude-haiku-4-5", "main": "claude-sonnet-5-5"}


@dataclass
class EngineRequest:
    system: str
    prompt: str
    schema: dict
    model: str | None = None
    max_budget_usd: float | None = None
    timeout_s: float = 120.0
    cwd: Path | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    task_id: str = ""
    job_id: str = ""
    slot: str = "cheap"
    max_tokens: int = 4096


@dataclass
class EngineResult:
    output: dict | None = None
    model_id: str | None = None
    usage: dict = field(default_factory=lambda: {"input": 0, "cache_read": 0,
                                                 "cache_write": 0, "output": 0})
    cost_usd: float | None = None
    cost_source: str = "unknown"  # reported | price_table | unknown
    latency_ms: int = 0
    error: str | None = None  # timeout|cancelled|budget_exceeded|not_logged_in|schema_invalid|engine_error
    detail: str | None = None


def find_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for directory in FALLBACK_DIRS:
        path = Path(directory).expanduser() / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


_help_cache: dict[tuple[str, tuple[str, ...], float], str] = {}


def help_text(path: str, args: tuple[str, ...], home: Path) -> str:
    """``<cli> <args>`` output, cached by (path, args, mtime); never runs a model."""
    try:
        key = (path, args, os.stat(path).st_mtime)
    except OSError:
        return ""
    if key not in _help_cache:
        try:
            done = subprocess.run([path, *args], capture_output=True, text=True, timeout=3,
                                  cwd=isolation.cwd(home), env=isolation.env())
            _help_cache[key] = done.stdout + done.stderr
        except (OSError, subprocess.SubprocessError):
            return ""
    return _help_cache[key]


def has_flag(text: str, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text) is not None


@dataclass
class Completed:
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None  # timeout | cancelled | None
    latency_ms: int


def run_process(argv: list[str], stdin_text: str, *, home: Path, timeout_s: float,
                cancel: threading.Event) -> Completed:
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=isolation.cwd(home), env=isolation.env(),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    chunks: dict[str, list[bytes]] = {"out": [], "err": []}

    def drain(stream, key: str, limit: int) -> None:
        size = 0
        for chunk in iter(lambda: stream.read(65536), b""):
            if size < limit:
                chunks[key].append(chunk[: limit - size])
                size += len(chunk)

    def feed() -> None:
        try:
            process.stdin.write(stdin_text.encode())
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    threads = [threading.Thread(target=drain, args=(process.stdout, "out", STDOUT_LIMIT),
                                daemon=True),
               threading.Thread(target=drain, args=(process.stderr, "err", 256 * 1024),
                                daemon=True),
               threading.Thread(target=feed, daemon=True)]
    for thread in threads:
        thread.start()
    error = None
    deadline = started + timeout_s
    while process.poll() is None:
        if cancel.is_set():
            error = "cancelled"
        elif time.monotonic() > deadline:
            error = "timeout"
        if error:
            _kill(process)
            break
        cancel.wait(0.05)
    for thread in threads[:2]:
        thread.join(2)
    return Completed(process.returncode, b"".join(chunks["out"]).decode(errors="replace"),
                     b"".join(chunks["err"]).decode(errors="replace"), error,
                     int((time.monotonic() - started) * 1000))


def _kill(process: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, KILL_GRACE_S), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(wait)
            return
        except subprocess.TimeoutExpired:
            continue


def _tail(text: str, n: int = 400) -> str:
    return text.strip()[-n:]


class ClaudeCodeEngine:
    id, name, binary = "claude_code", "Claude Code", "claude"
    OPTIONAL = ("--safe-mode", "--strict-mcp-config", "--max-budget-usd", "--model", "--effort",
                "--settings", "--max-turns")

    def __init__(self, home: Path):
        self.home = Path(home)

    def path(self) -> str | None:
        return find_binary(self.binary)

    def flags(self, path: str) -> list[str]:
        text = help_text(path, ("--help",), self.home)
        return [flag for flag in self.OPTIONAL if has_flag(text, flag)]

    def argv(self, path: str, req: EngineRequest) -> list[str]:
        flags = set(self.flags(path))
        argv = [path, "-p", "--output-format", "json", "--json-schema",
                json.dumps(req.schema, ensure_ascii=False), "--system-prompt", req.system,
                "--tools", "", "--no-session-persistence"]
        for flag in ("--safe-mode", "--strict-mcp-config"):
            if flag in flags:
                argv.append(flag)
        if req.max_budget_usd is not None and "--max-budget-usd" in flags:
            argv += ["--max-budget-usd", f"{req.max_budget_usd:g}"]
        if req.model and "--model" in flags:
            argv += ["--model", req.model]
        if "--effort" in flags:
            argv += ["--effort", "low"]
        if "--settings" in flags:
            argv += ["--settings", '{"alwaysThinkingEnabled":false}']
        if "--max-turns" in flags:
            argv += ["--max-turns", "3"]
        return argv

    def call(self, req: EngineRequest) -> EngineResult:
        path = self.path()
        if path is None:
            return EngineResult(error="engine_error", detail="not_installed")
        stdin = isolation.marker_line(req.task_id, req.job_id) + "\n" + req.prompt
        done = run_process(self.argv(path, req), stdin, home=self.home,
                           timeout_s=req.timeout_s, cancel=req.cancel)
        result = EngineResult(latency_ms=done.latency_ms)
        if done.error:
            result.error = done.error
            return result
        return self.parse(done, result)

    @staticmethod
    def parse(done: Completed, result: EngineResult) -> EngineResult:
        try:
            data = json.loads(done.stdout)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):  # Some versions print the whole event list.
            data = next((d for d in reversed(data) if d.get("type") == "result"), None)
        if not isinstance(data, dict):
            text = done.stderr + done.stdout
            result.error = "not_logged_in" if "login" in text.lower() else "engine_error"
            result.detail = _tail(text)
            return result
        usage = data.get("usage") or {}
        result.usage = {"input": usage.get("input_tokens") or 0,
                        "cache_read": usage.get("cache_read_input_tokens") or 0,
                        "cache_write": usage.get("cache_creation_input_tokens") or 0,
                        "output": usage.get("output_tokens") or 0}
        if data.get("total_cost_usd") is not None:
            result.cost_usd, result.cost_source = float(data["total_cost_usd"]), "reported"
        result.model_id = next(iter(data.get("modelUsage") or {}), None)
        text = str(data.get("result") or "")
        if data.get("subtype") == "error_max_budget_usd":
            result.error = "budget_exceeded"
            return result
        if data.get("is_error"):
            lowered = text.lower()
            result.error = "not_logged_in" if "login" in lowered else "engine_error"
            result.detail = _tail(text)
            return result
        output = data.get("structured_output")
        if output is None:
            try:
                output = json.loads(text)
            except json.JSONDecodeError:
                output = None
        if not isinstance(output, dict):
            result.error, result.detail = "schema_invalid", _tail(text)
            return result
        result.output = output
        return result


class CodexEngine:
    id, name, binary = "codex", "Codex", "codex"

    def __init__(self, home: Path):
        self.home = Path(home)

    def path(self) -> str | None:
        return find_binary(self.binary)

    def flags(self, path: str) -> list[str]:
        text = help_text(path, ("exec", "--help"), self.home)
        wanted = ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--output-schema")
        return [flag for flag in wanted if has_flag(text, flag)]

    def call(self, req: EngineRequest) -> EngineResult:
        path = self.path()
        if path is None:
            return EngineResult(error="engine_error", detail="not_installed")
        work = self.home / "tmp" / "ai" / (req.job_id or uuid.uuid4().hex)
        work.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            schema, out = work / "schema.json", work / "out.json"
            schema.write_text(json.dumps(req.schema, ensure_ascii=False), encoding="utf-8")
            cwd = isolation.cwd(self.home)
            argv = [path, "exec", "--ephemeral", "--json", "--skip-git-repo-check", "-s",
                    "read-only", "--ignore-user-config", "--ignore-rules", "--output-schema",
                    str(schema), "-o", str(out), "-C", str(cwd)]
            if req.model:
                argv += ["-m", req.model]
            argv.append("-")
            stdin = (isolation.marker_line(req.task_id, req.job_id) + "\n" + req.system
                     + "\n\n" + req.prompt)
            done = run_process(argv, stdin, home=self.home, timeout_s=req.timeout_s,
                               cancel=req.cancel)
            result = EngineResult(latency_ms=done.latency_ms, model_id=req.model)
            if done.error:
                result.error = done.error
                return result
            return self.parse(done, out, result)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def parse(done: Completed, out: Path, result: EngineResult) -> EngineResult:
        usage = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
        errors = []
        for line in done.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "turn.completed":
                u = event.get("usage") or {}
                usage["input"] += u.get("input_tokens") or 0
                usage["cache_read"] += u.get("cached_input_tokens") or 0
                usage["cache_write"] += u.get("cache_write_input_tokens") or 0
                usage["output"] += u.get("output_tokens") or 0
            elif kind in ("error", "turn.failed"):
                message = event.get("message") or (event.get("error") or {}).get("message")
                errors.append(str(message or kind))
        result.usage = usage
        cost = prices.estimate(usage["input"], usage["output"], result.model_id)
        if cost is not None:
            result.cost_usd, result.cost_source = cost, "price_table"
        try:
            output = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            output = None
        if isinstance(output, dict) and not errors:
            result.output = output
            return result
        text = " ".join(errors) + " " + done.stderr
        if "login" in text.lower():
            result.error = "not_logged_in"
        else:
            result.error = "engine_error" if errors or done.returncode else "schema_invalid"
        result.detail = _tail(text)
        return result


class ApiKeyEngine:
    """Direct Messages API with a forced ``emit`` tool; registered only when
    ``ANTHROPIC_API_KEY`` is set. The key is read per call and never stored or logged."""

    id, name = "api_key", "Anthropic API"

    def __init__(self, home: Path):
        self.home = Path(home)

    def call(self, req: EngineRequest) -> EngineResult:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return EngineResult(error="not_logged_in")
        model = req.model or API_MODELS.get(req.slot, API_MODELS["cheap"])
        body = {"model": model, "max_tokens": req.max_tokens, "system": req.system,
                "messages": [{"role": "user", "content": req.prompt}],
                "tools": [{"name": "emit", "description": "Return the result.",
                           "input_schema": req.schema}],
                "tool_choice": {"type": "tool", "name": "emit"}}
        request = urllib.request.Request(
            API_URL, data=json.dumps(body).encode(), method="POST",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        started = time.monotonic()
        result = EngineResult(model_id=model)
        if req.cancel.is_set():
            result.error = "cancelled"
            return result
        try:
            with urllib.request.urlopen(request, timeout=req.timeout_s) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            result.error = "not_logged_in" if error.code in (401, 403) else "engine_error"
            result.detail = f"http {error.code}"
            return result
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            result.error = "timeout" if isinstance(error, TimeoutError) else "engine_error"
            result.detail = type(error).__name__
            return result
        finally:
            result.latency_ms = int((time.monotonic() - started) * 1000)
        if req.cancel.is_set():
            result.error = "cancelled"
            return result
        usage = data.get("usage") or {}
        result.model_id = data.get("model") or model
        result.usage = {"input": usage.get("input_tokens") or 0,
                        "cache_read": usage.get("cache_read_input_tokens") or 0,
                        "cache_write": usage.get("cache_creation_input_tokens") or 0,
                        "output": usage.get("output_tokens") or 0}
        cost = prices.estimate(result.usage["input"] + result.usage["cache_write"],
                               result.usage["output"], result.model_id)
        if cost is not None:
            result.cost_usd, result.cost_source = cost, "price_table"
        block = next((b for b in data.get("content") or [] if b.get("type") == "tool_use"), None)
        if block is None or not isinstance(block.get("input"), dict):
            result.error = "schema_invalid"
            return result
        result.output = block["input"]
        return result


Response = dict | EngineResult | Callable[[EngineRequest], "dict | EngineResult"]


class FakeEngine:
    """Test double: ``responses[task_id or "*"]`` is an output dict, an EngineResult or a
    callable taking the request. Injected only via ``service.register_engine``."""

    id, name = "fake", "Fake"
    info = {"available": True, "logged_in": True, "version": "fake", "path": None,
            "flags": [], "slots": {"cheap": "fake-cheap", "main": "fake-main"}}

    def __init__(self, responses: dict[str, Response] | None = None):
        self.responses = responses or {}
        self.requests: list[EngineRequest] = []

    def call(self, req: EngineRequest) -> EngineResult:
        self.requests.append(req)
        response = self.responses.get(req.task_id, self.responses.get("*"))
        if callable(response):
            response = response(req)
        if req.cancel.is_set():
            return EngineResult(error="cancelled")
        if isinstance(response, EngineResult):
            return response
        if response is None:
            return EngineResult(error="engine_error", detail="no fake response")
        tokens = (len(req.system) + len(req.prompt)) // 4
        return EngineResult(output=response, model_id=req.model or "fake",
                            usage={"input": tokens, "cache_read": 0, "cache_write": 0,
                                   "output": len(json.dumps(response)) // 4},
                            cost_usd=0.0, cost_source="reported", latency_ms=1)


def default_engines(home: Path) -> dict:
    engines: dict = {"claude_code": ClaudeCodeEngine(home), "codex": CodexEngine(home)}
    if os.environ.get("ANTHROPIC_API_KEY"):
        engines["api_key"] = ApiKeyEngine(home)
    return engines
