"""Local rotating log (``home/logs/tandem.log``, 2 MB × 5) with JSON lines and redaction.

Logs never leave the machine; diagnostics exports re-redact them anyway.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from collections import deque
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = "tandem"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 4
_REDACTIONS = (
    (re.compile(r"Bearer\s+\S+", re.I), "Bearer <redacted>"),
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "<key>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"/Users/[^/\s\"']+"), "~"),
)
log = logging.getLogger(LOGGER)
_handler: logging.Handler | None = None


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        body = {"ts": ts, "lvl": record.levelname, "logger": record.name,
                "ev": getattr(record, "ev", None) or record.getMessage()}
        fields = getattr(record, "fields", None)
        if fields:
            body.update(fields)
        if record.exc_info:
            body["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(body, ensure_ascii=False, default=str))


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "fields", None) or {}
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"{self.formatTime(record)} {record.levelname} {record.name} {record.getMessage()}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return redact(f"{line} {extra}".rstrip())


def log_path(home: Path) -> Path:
    return home / "logs" / "tandem.log"


def setup_logging(home: Path, json_logs: bool = True, level: str = "INFO") -> logging.Handler:
    """Idempotent: replaces a previous Tandem handler; returns it for ``teardown``."""
    global _handler
    directory = home / "logs"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = log_path(home)
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    teardown()
    handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(JsonFormatter() if json_logs else TextFormatter())
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False
    logging.getLogger("uvicorn.error").addHandler(handler)
    _handler = handler
    _install_hooks()
    return handler


def teardown(handler: logging.Handler | None = None) -> None:
    """Remove the Tandem handler (only if it is still ``handler``, when given)."""
    global _handler
    if _handler is not None and (handler is None or handler is _handler):
        log.removeHandler(_handler)
        logging.getLogger("uvicorn.error").removeHandler(_handler)
        _handler.close()
        _handler = None


def log_event(ev: str, level: int = logging.INFO, **fields) -> None:
    try:
        log.log(level, ev, extra={"ev": ev, "fields": fields})
    except Exception:  # noqa: BLE001 - logging never breaks the caller.
        pass


_hooks_installed = False


def _install_hooks() -> None:
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    previous_sys, previous_thread = sys.excepthook, threading.excepthook

    def sys_hook(kind, value, tb):
        if _handler is not None:
            log.error("uncaught", exc_info=(kind, value, tb), extra={"ev": "uncaught"})
        previous_sys(kind, value, tb)

    def thread_hook(args):
        if _handler is not None and args.exc_type is not SystemExit:
            log.error("uncaught_thread", exc_info=(args.exc_type, args.exc_value,
                                                    args.exc_traceback),
                      extra={"ev": "uncaught_thread",
                             "fields": {"thread": getattr(args.thread, "name", None)}})
        previous_thread(args)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook


def tail(home: Path, n: int = 200, max_bytes: int = 1024 * 1024) -> list[str]:
    """Last ``n`` lines of the current log, reading at most ``max_bytes`` from the end."""
    path = log_path(home)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if size > max_bytes:
        lines = lines[1:]  # First line is partial.
    return list(deque(lines, maxlen=n))
