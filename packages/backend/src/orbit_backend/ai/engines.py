"""Engines: the user's logged-in ``claude`` / ``codex`` CLIs run headless, an optional
Anthropic API key, and a fake for tests.

CLI runs share one recipe: isolated cwd and env, a new process group, the prompt on
stdin (never argv), stdout capped at 4 MB, and SIGTERM → 1.5 s → SIGKILL on cancel or
timeout. Orbit never stores credentials; optional flags are passed only when the
installed CLI's ``--help`` lists them.
"""

from __future__ import annotations

import glob
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
                                  "~/.claude/local", "~/.npm-global/bin",
                                  "/Applications/*.app/Contents/Resources/codex-cli/bin",
                                  "~/Applications/*.app/Contents/Resources/codex-cli/bin")
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
    error: str | None = None  # timeout|cancelled|budget_exceeded|not_logged_in|schema_invalid|engine_error|truncated|refused
    detail: str | None = None


def find_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for pattern in FALLBACK_DIRS:
        directory = os.path.expanduser(pattern)
        candidates = sorted(glob.glob(directory)) if glob.has_magic(directory) else [directory]
        for candidate in candidates:
            path = Path(candidate) / name
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
                # OpenAI-style usage: input_tokens *includes* cached_input_tokens; store the
                # uncached remainder so input/cache_read are disjoint like the Anthropic fields.
                cached = u.get("cached_input_tokens") or 0
                usage["input"] += max(0, (u.get("input_tokens") or 0) - cached)
                usage["cache_read"] += cached
                usage["cache_write"] += u.get("cache_write_input_tokens") or 0
                usage["output"] += u.get("output_tokens") or 0
            elif kind in ("error", "turn.failed"):
                message = event.get("message") or (event.get("error") or {}).get("message")
                errors.append(str(message or kind))
        result.usage = usage
        cost = prices.cost(usage, result.model_id)
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


# -- Anthropic Messages API ---------------------------------------------------------------
# Request shape follows the Claude API reference (claude-api skill, cached 2026-09-25):
# * Forced ``tool_choice`` (``any``/``tool``) returns HTTP 400 on claude-sonnet-5-5,
#   claude-opus-5-5 and claude-fable-5-1, so JSON is requested through structured outputs
#   (``output_config.format`` = json_schema). Schemas that structured outputs cannot express
#   (``additionalProperties`` other than false) fall back to an ``emit`` tool with
#   ``tool_choice: auto`` and a prompt line naming the tool; the runner validates either way.
# * Those models always think (adaptive) and thinking tokens count against ``max_tokens``, so
#   the visible-output budget gets THINKING_HEADROOM on top. Non-streaming requests should stay
#   around 16k max_tokens (SDK guidance); out budgets here are <= 2k, so 2k + 8k stays under it.
# * Effort is explicit (Opus 5.5 defaults to medium, Sonnet 5.5 to high): cheap slot -> low
#   (classification/short answers), main slot -> medium (the documented cost-saving step-down).
#   Haiku 4.5 / Sonnet 4.5 reject ``effort`` and get none.
# * ``stop_reason`` max_tokens / refusal are explicit errors (``truncated`` / ``refused``), never
#   a half-parsed payload. 429 / 529 / 5xx are retried a bounded number of times.
THINKING_HEADROOM = 8000
EFFORT = {"cheap": "low", "main": "medium"}
RETRY_STATUS = (429, 500, 502, 503, 504, 529)
API_RETRIES = 2  # SDK default max_retries
RETRY_BASE_S, RETRY_MAX_S = 1.0, 8.0
_UNSUPPORTED_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                     "minLength", "maxLength", "maxItems", "uniqueItems", "$schema")
_sleep = time.sleep  # patched in tests


def _always_thinks(model: str) -> bool:
    return any(model.startswith(p) for p in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5",
                                              "claude-mythos-5"))


def _supports_effort(model: str) -> bool:
    return not any(model.startswith(p) for p in ("claude-haiku", "claude-sonnet-4-5", "claude-3"))


def strict_schema(schema) -> dict | None:
    """A copy of ``schema`` that structured outputs accepts, or ``None`` when it cannot be
    expressed (open objects). Dropped constraints are still enforced by the runner's validator."""
    def walk(node):
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        out = {k: walk(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
        if out.get("minItems", 0) > 1:
            out.pop("minItems")
        if out.get("type") == "object" or "properties" in out:
            extra = out.get("additionalProperties", False)
            if extra is not False:
                raise ValueError("open object")
            out["additionalProperties"] = False
        return out
    try:
        return walk(schema)
    except ValueError:
        return None


class ApiKeyEngine:
    """Direct Messages API with structured outputs; registered only when ``ANTHROPIC_API_KEY``
    is set. The key is read per call and never stored or logged."""

    id, name = "api_key", "Anthropic API"

    def __init__(self, home: Path):
        self.home = Path(home)

    @staticmethod
    def body(req: EngineRequest, model: str) -> dict:
        body = {"model": model, "system": req.system,
                "max_tokens": req.max_tokens + (THINKING_HEADROOM if _always_thinks(model) else 0),
                "messages": [{"role": "user", "content": req.prompt}]}
        config: dict = {}
        if _supports_effort(model):
            config["effort"] = EFFORT.get(req.slot, "low")
        schema = strict_schema(req.schema)
        if schema is not None:
            config["format"] = {"type": "json_schema", "schema": schema}
        else:
            body["tools"] = [{"name": "emit", "description": "Return the result.",
                              "input_schema": req.schema}]
            body["tool_choice"] = {"type": "auto"}
            body["messages"][0]["content"] = req.prompt + "\n\nReturn the result by calling the emit tool once."
        if config:
            body["output_config"] = config
        return body

    def _post(self, request: urllib.request.Request, req: EngineRequest) -> dict:
        for attempt in range(API_RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=req.timeout_s) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                if error.code not in RETRY_STATUS or attempt == API_RETRIES or req.cancel.is_set():
                    raise
                try:
                    wait = float(error.headers.get("retry-after") or 0) if error.headers else 0.0
                except ValueError:
                    wait = 0.0
                _sleep(min(RETRY_MAX_S, max(wait, RETRY_BASE_S * 2 ** attempt)))
        raise AssertionError("unreachable")

    def call(self, req: EngineRequest) -> EngineResult:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return EngineResult(error="not_logged_in")
        model = req.model or API_MODELS.get(req.slot, API_MODELS["cheap"])
        body = self.body(req, model)
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
            data = self._post(request, req)
        except urllib.error.HTTPError as error:
            result.error = "not_logged_in" if error.code in (401, 403) else "engine_error"
            result.detail = f"http {error.code}"
            return result
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            timed_out = isinstance(error, TimeoutError) or isinstance(
                getattr(error, "reason", None), TimeoutError)
            result.error = "timeout" if timed_out else "engine_error"
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
        cost = prices.cost(result.usage, result.model_id)
        if cost is not None:
            result.cost_usd, result.cost_source = cost, "price_table"
        stop = data.get("stop_reason")
        if stop in ("max_tokens", "refusal"):
            result.error = "truncated" if stop == "max_tokens" else "refused"
            details = data.get("stop_details") or {}
            result.detail = f"stop_reason={stop}" + (f" category={details.get('category')}"
                                                      if details.get("category") else "")
            return result
        blocks = data.get("content") or []
        if "tools" in body:
            block = next((b for b in blocks if b.get("type") == "tool_use"), None)
            output = block.get("input") if block else None
        else:
            text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
            try:
                output = json.loads(text)
            except ValueError:
                output = None
        if not isinstance(output, dict):
            result.error = "schema_invalid"
            return result
        result.output = output
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
