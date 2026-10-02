"""Second redaction pass for anything sent to a model (EV-14), plus token estimates.

`privacy.redact` guards persistence (keys, auth); this pass also hides identity:
emails, home-directory user names, the local user name and private hosts.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from tandem_backend import privacy

_MARKERS = ("[密钥已隐藏]", "[认证已隐藏]")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")
_PRIVATE_IP = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168|127\.\d{1,3})\.\d{1,3}\.\d{1,3}(?![\d.])")
_LOCAL_HOST = re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:local|internal)(?![A-Za-z0-9_-])")
_GENERIC_NAMES = {"root", "user", "users", "admin", "home", "runner", "shared", "guest"}
_CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")


def _user_names() -> list[str]:
    names = {Path.home().name, os.environ.get("USER", ""), os.environ.get("LOGNAME", "")}
    return sorted(n for n in names if len(n) >= 3 and n.lower() not in _GENERIC_NAMES)


def redact2(text: str, *, human: bool = False) -> tuple[str, int]:
    """Return (redacted text, hit count). Idempotent on already-redacted text."""
    if not text:
        return text or "", 0
    if human:
        text = privacy.direct_user_text(text)
    before = sum(text.count(m) for m in _MARKERS)
    text = privacy.redact(text)
    hits = sum(text.count(m) for m in _MARKERS) - before
    text, n = _EMAIL.subn("[email]", text)
    hits += n
    text, n = _HOME_PATH.subn("~", text)
    hits += n
    text, n = _PRIVATE_IP.subn("[host]", text)
    hits += n
    text, n = _LOCAL_HOST.subn("[host]", text)
    hits += n
    for name in _user_names():
        text, n = re.subn(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", "[user]", text,
                          flags=re.I)
        hits += n
    return text, hits


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
