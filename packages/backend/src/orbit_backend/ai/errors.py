"""Exceptions shared by the AI runtime and the task modules (contract C2)."""

from __future__ import annotations


class AIError(Exception):
    """A request-level refusal; routes turn it into ``{"error": {code, message, ...extra}}``."""

    def __init__(self, status: int, code: str, message: str = "", **extra):
        super().__init__(message or code)
        self.status, self.code, self.message, self.extra = status, code, message or code, extra


class CallFailed(Exception):
    """``ctx.call()`` gave up (engine error or output still invalid after one retry)."""

    def __init__(self, reason: str, detail: str | None = None):
        super().__init__(reason if detail is None else f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


class Cancelled(Exception):
    """The job was cancelled while a call was pending."""


class AIUnavailable(Exception):
    """``AIService.run`` cannot run the task (AI off, no consent, no engine, …)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
