"""Small helpers shared by the generate tasks (no imports from other ai/ files)."""

from __future__ import annotations

import hashlib
import json
import re

try:  # P1 owns the real classes; fall back to same-named placeholders until it lands.
    from tandem_backend.ai.errors import Cancelled, CallFailed  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only before the runtime package exists
    class CallFailed(Exception):  # noqa: N818 - name fixed by contract C2
        """A controlled engine call failed after its single retry."""

    class Cancelled(Exception):  # noqa: N818 - name fixed by contract C2
        """The job was cancelled while a call was in flight."""


def is_call_failed(error: BaseException) -> bool:
    return type(error).__name__ == "CallFailed"


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content(pack: dict) -> dict:
    return pack.get("content") or {}


def refs(pack: dict, key: str) -> list:
    return list((pack.get("refs") or {}).get(key) or [])


def goal_text(pack: dict) -> str:
    goal = content(pack).get("goal")
    if isinstance(goal, dict) and goal.get("text"):
        return str(goal["text"])
    return str(pack.get("goal") or "")


_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(\s*%)?")
TOLERANCE = 0.051


def bad_numbers(text: str, numbers) -> list[str]:
    """Numbers in `text` that are not backed by the pack's whitelist (±0.051, % ↔ fraction)."""
    allowed = [float(n) for n in numbers or [] if isinstance(n, int | float)]
    bad = []
    for match in _NUMBER.finditer(text or ""):
        raw, percent = match.group(1).replace(",", ""), bool(match.group(2))
        value = float(raw)
        if not percent and "." not in raw and value <= 10:
            continue
        options = [value, value / 100] if percent else [value, value * 100]
        if not any(abs(option - n) <= TOLERANCE for option in options for n in allowed):
            bad.append(match.group(0).strip())
    return bad


def numbers_ok(text: str, numbers) -> bool:
    return not bad_numbers(text, numbers)


def slug(text: str, fallback_seed: str = "") -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]
    return ascii_slug or "r" + sha256_text(fallback_seed or text or "rule")[:8]
