"""Second redaction pass for anything sent to a model (EV-14), plus token estimates.

`privacy.redact` guards persistence (keys, auth); this pass also hides identity:
emails, home-directory user names, the local user name, private hosts, phone numbers and
user-defined patterns. The rule table and toggles live in ``privacy_rules``.
"""

from __future__ import annotations

import json
import math
import re

from orbit_backend import privacy, privacy_rules

_CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")
# Any IPv4 literal (tailnet 100.64/10, link-local, public) that privacy_rules leaves: hosts are
# identity too. Version strings ("v1.2.3.4", "1.2.3.4.5") and out-of-range octets are kept.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?!\w|\.\d)")
# Home-relative paths keep only the last segment: "~/Projects/acme/src/a.md" → "~/…/a.md".
_HOME_REL = re.compile(r"(?<![\w/.])~/(?!…/)(?:[^\s/\"'`<>()\[\]]+/){2,}([^\s/\"'`<>()\[\]]*)")
# Folding the home directory to "~" is normalisation, not a hidden secret: not counted as a hit.
_UNCOUNTED = {"home_user"}


def redact2(text: str, *, human: bool = False, rules: dict | None = None) -> tuple[str, int]:
    """Return (redacted text, hit count). Idempotent on already-redacted text.

    ``rules`` is a ``privacy_rules`` config ({"enabled": {...}, "custom": [...]}); the
    default is the user's current rule set (all built-in rules when nothing is stored).
    The count covers hidden values (secrets, emails, hosts, users, …), not path folding.
    """
    if not text:
        return text or "", 0
    if human:
        text = privacy.direct_user_text(text)
    rules = rules or privacy_rules.current()
    text, hits = privacy_rules.apply(text, rules)
    count = sum(1 for h in hits if h.get("rule") not in _UNCOUNTED)
    enabled = rules.get("enabled") or {}
    if enabled.get("private_host", True):
        text, n = _IPV4.subn("[ip]", text)
        count += n
    if enabled.get("home_user", True):
        text = _HOME_REL.sub(lambda m: "~/…/" + m.group(1), text)
    return text, count


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
