"""A RunContext (contract C2) stand-in so analysis tasks are testable before the runtime lands."""

from __future__ import annotations

import jsonschema

from orbit_backend.ai.tasks_analysis import CallFailed

DAY = 86_400_000
NOW = 1_790_000_000_000  # fixed "now" (ms) so windows are deterministic


class FakeCtx:
    """`responses`: list consumed in order, each a dict, an Exception, or callable(call_kwargs) -> dict."""

    def __init__(self, task, pack, responses=(), *, reads=None, params=None, cancel_after=None,
                 grants=("summary", "snippets")):
        self.job_id, self.task, self.pack = "job-test", task, pack
        self.grants = set(grants)
        self.template, self.engine, self.params = "v1", "fake", params or {}
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.stages: list[tuple] = []
        self.logs: list[str] = []
        self.progresses: list[tuple] = []
        self._reads = reads
        self.cancel_after = cancel_after

    def _next(self, kwargs):
        if not self.responses:
            raise CallFailed("no response")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r(kwargs) if callable(r) else r

    def call(self, *, system=None, prompt=None, schema=None, slot=None, validate=None, task_id=None):
        prompt = prompt if prompt is not None else self.task["build_prompt"](self.pack)
        schema = schema or self.task["schema"]
        validate = validate if validate is not None else self.task.get("validate")
        kwargs = {"system": system or self.task["system"], "prompt": prompt, "schema": schema,
                  "slot": slot or self.task["slot"], "task_id": task_id or self.task["task_id"]}
        errors: list[str] = []
        for attempt in range(2):
            self.calls.append({**kwargs, "attempt": attempt, "errors": errors})
            output = self._next(kwargs)
            errors = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(output)]
            if not errors and validate:
                errors = validate(output, self.pack) or []
            if not errors:
                return output
        raise CallFailed("; ".join(errors))

    def granted(self, data_class):
        return data_class in self.grants

    def stage(self, stage_id, status, message=None):
        self.stages.append((stage_id, status, message))

    def log(self, line):
        self.logs.append(line)

    def progress(self, n, total):
        self.progresses.append((n, total))

    def cancelled(self):
        return self.cancel_after is not None and len(self.calls) >= self.cancel_after

    def reads(self):
        return self._reads()


def run_task(task, ctx):
    """The runtime's default orchestration: run() or call → fallback → finalize."""
    if task.get("run"):
        return task["run"](ctx, ctx.pack)
    try:
        output, source = ctx.call(), "ai"
    except CallFailed as error:
        output, source = task["fallback"](ctx.pack, str(error)), "fallback"
    return task["finalize"](output, ctx.pack, source)
