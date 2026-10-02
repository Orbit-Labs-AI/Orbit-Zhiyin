"""Second redaction pass for anything sent to a model (EV-14), plus token estimates.

`privacy.redact` guards persistence (keys, auth); this pass also hides identity:
emails, home-directory user names, the local user name, private hosts, phone numbers and
user-defined patterns. The rule table and toggles live in ``privacy_rules``.
"""

from __future__ import annotations

import json
import math
import re

from tandem_backend import privacy, privacy_rules

_CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")


def redact2(text: str, *, human: bool = False, rules: dict | None = None) -> tuple[str, int]:
    """Return (redacted text, hit count). Idempotent on already-redacted text.

    ``rules`` is a ``privacy_rules`` config ({"enabled": {...}, "custom": [...]}); the
    default is the user's current rule set (all built-in rules when nothing is stored).
    """
    if not text:
        return text or "", 0
    if human:
        text = privacy.direct_user_text(text)
    text, hits = privacy_rules.apply(text, rules)
    return text, len(hits)


def _is_id_key(key) -> bool:
    return isinstance(key, str) and (key in ("id", "ref_id") or key.endswith(("_uid", "_id", "_hash")))


def redact_value(value, key=None):
    """Redact every string inside a JSON-like value; identifiers are left alone."""
    if isinstance(value, str):
        return (value, 0) if _is_id_key(key) else redact2(value)
    if isinstance(value, dict):
        out, hits = {}, 0
        for k, v in value.items():
            out[k], n = redact_value(v, k)
            hits += n
        return out, hits
    if isinstance(value, (list, tuple)):
        out, hits = [], 0
        for v in value:
            r, n = redact_value(v, key if _is_id_key(key) else None)
            out.append(r)
            hits += n
        return out, hits
    return value, 0


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def est_tokens(value) -> int:
    """CJK chars count one token each; everything else ~4 chars per token."""
    s = value if isinstance(value, str) else compact(value)
    cjk = len(_CJK.findall(s))
    return cjk + math.ceil((len(s) - cjk) / 4)
