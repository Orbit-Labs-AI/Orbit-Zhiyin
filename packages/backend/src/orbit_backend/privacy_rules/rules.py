"""Redaction rules (SET-10): built-in table, user toggles, custom patterns and a preview.

Stages: ``ingest`` rules run before persistence (``privacy.redact``) and are fixed;
``outbound`` rules run on what leaves Orbit (AI context packs and exports Orbit renders).
Toggles never re-wash stored data (that is a rebuild, planned for v1).

Config lives in ``platform_kv['privacy.rules']`` as ``{"enabled": {id: bool}, "custom":
[{id, pattern, replacement, enabled}]}``; ``bind()`` points the module at the gateway's
platform settings so ``ai.redact.redact2`` picks up the current rules without a gateway.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from orbit_data.privacy import REDACTION_VERSION

from .. import privacy

KV_KEY = "privacy.rules"
VERSION = REDACTION_VERSION
MAX_CUSTOM = 5
MAX_PATTERN = 200
MAX_REPLACEMENT = 100
MAX_PREVIEW = 20_000
REGEX_BUDGET_MS = 50.0
REGEX_TIMEOUT_S = 1.5
SCOPE_NOTE = ("outbound 规则作用于 AI 上下文包与 Orbit 渲染的导出；ingest 规则固定，"
              "修改规则不回洗已入库数据（回洗即重建，留到 v1）。")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")
_PRIVATE_IP = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168|127\.\d{1,3})\.\d{1,3}\.\d{1,3}(?![\d.])")
_LOCAL_HOST = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:local|internal)(?![A-Za-z0-9_-])")
_PHONE = re.compile(r"(?<![\d.+-])1[3-9]\d{9}(?![\d.])")
_GENERIC_NAMES = {"root", "user", "users", "admin", "home", "runner", "shared", "guest"}

# Probe text for custom patterns: ordinary log-like content plus classic backtracking bait.
_SAMPLE = ("user alice ran pnpm test in /Users/alice/work/app, mail alice@example.com, "
           "host 10.0.0.8 build.internal, phone 13800138000, token sk-" + "a" * 24 + "\n") * 20 + (
    "a" * 40 + "!" + "\n" + "x" * 40 + "@" + "\n" + "1" * 40 + "z\n" + " " * 40 + "-\n")


@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    placeholder: str | None
    stage: str
    example: str
    locked: bool = False


BUILTIN = (
    Rule("credentials", "密钥、令牌与带认证的地址", "[密钥已隐藏]", "ingest",
         "api_key=sk-ant-… → api_key=[密钥已隐藏]", locked=True),
    Rule("home_user", "主目录中的用户名", "~", "outbound", "/Users/alice/x → ~/x"),
    Rule("email", "邮箱地址", "[email]", "outbound", "alice@example.com → [email]"),
    Rule("private_host", "内网地址与本地主机名", "[host]", "outbound",
         "10.0.0.8 / build.internal → [host]"),
    Rule("local_user", "本机用户名", "[user]", "outbound", "alice → [user]"),
    Rule("phone", "手机号", "[phone]", "outbound", "13800138000 → [phone]"),
    Rule("custom", "自定义规则", None, "outbound", "按你写的正则替换"),
)
RULE_IDS = tuple(r.id for r in BUILTIN)
_settings = None  # PlatformSettings (or any object with get/put) bound by the gateway.


class RuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def bind(settings) -> None:
    global _settings
    _settings = settings


def default_config() -> dict:
    return {"enabled": {r.id: True for r in BUILTIN}, "custom": []}


def current() -> dict:
    """Stored config merged over defaults; unbound or unreadable storage yields defaults."""
    config = default_config()
    stored = None
    if _settings is not None:
        try:
            stored = _settings.get(KV_KEY)
        except Exception:  # noqa: BLE001 - a closed app.db must not break redaction.
            stored = None
    if isinstance(stored, dict):
        enabled = stored.get("enabled") or {}
        config["enabled"].update({k: bool(v) for k, v in enabled.items() if k in RULE_IDS})
        config["custom"] = [c for c in stored.get("custom") or [] if isinstance(c, dict)]
    for rule in BUILTIN:
        if rule.locked:
            config["enabled"][rule.id] = True
    return config


# -- validation -----------------------------------------------------------------------------

def _probe_ms(pattern: str) -> float | None:
    """Time the pattern over the fixed sample in a child process (killable); None = too slow."""
    code = ("import re,sys,time\np=re.compile(sys.argv[1])\nt=time.perf_counter()\n"
            "p.findall(sys.argv[2])\nprint((time.perf_counter()-t)*1000)")
    try:
        done = subprocess.run([sys.executable, "-c", code, pattern, _SAMPLE], capture_output=True,
                              text=True, timeout=REGEX_TIMEOUT_S,
                              env={"PATH": os.environ.get("PATH", "")}, check=False)
        return float(done.stdout.strip()) if done.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def validate_custom(items, *, probe: bool = True) -> list[dict]:
    if not isinstance(items, list):
        raise RuleError("bad_regex", "custom must be a list")
    if len(items) > MAX_CUSTOM:
        raise RuleError("bad_regex", f"最多 {MAX_CUSTOM} 条自定义规则")
    out = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("pattern"), str):
            raise RuleError("bad_regex", f"custom[{index}].pattern is required")
        pattern = item["pattern"]
        replacement = item.get("replacement", "[custom]")
        enabled = item.get("enabled", True)
        if not pattern or len(pattern) > MAX_PATTERN:
            raise RuleError("bad_regex", f"custom[{index}]: 正则长度须为 1..{MAX_PATTERN}")
        if not isinstance(replacement, str) or len(replacement) > MAX_REPLACEMENT:
            raise RuleError("bad_regex", f"custom[{index}]: replacement 最长 {MAX_REPLACEMENT}")
        if not isinstance(enabled, bool):
            raise RuleError("bad_regex", f"custom[{index}]: enabled must be a boolean")
        try:
            compiled = re.compile(pattern)
        except re.error as error:
            raise RuleError("bad_regex", f"custom[{index}]: {error}") from None
        if compiled.search("") is not None:
            raise RuleError("bad_regex", f"custom[{index}]: 正则不能匹配空字符串")
        if probe:
            elapsed = _probe_ms(pattern)
            if elapsed is None or elapsed > REGEX_BUDGET_MS:
                raise RuleError("bad_regex", f"custom[{index}]: 正则在样本上超过 "
                                             f"{REGEX_BUDGET_MS:g} ms，可能存在回溯爆炸")
        out.append({"id": f"custom-{index + 1}", "pattern": pattern,
                    "replacement": replacement, "enabled": enabled})
    return out


def merge(base: dict, enabled: dict | None = None, custom=None, *, probe: bool = True) -> dict:
    """Apply a PUT/preview body over ``base``; locked rules cannot be switched off."""
    config = json.loads(json.dumps(base))
    for key, value in (enabled or {}).items():
        rule = next((r for r in BUILTIN if r.id == key), None)
        if rule is None:
            raise RuleError("invalid_request", f"unknown rule: {key}")
        if not isinstance(value, bool):
            raise RuleError("invalid_request", f"{key} must be a boolean")
        if rule.locked and not value:
            raise RuleError("locked_rule", f"{key} 是固定规则，不能关闭")
        config["enabled"][key] = value
    if custom is not None:
        config["custom"] = validate_custom(custom, probe=probe)
    return config


def save(config: dict) -> None:
    if _settings is None:
        raise RuntimeError("privacy rules are not bound to storage")
    _settings.put(KV_KEY, {"enabled": config["enabled"], "custom": config["custom"]})


def describe(config: dict | None = None) -> dict:
    config = config or current()
    rules = [{"id": r.id, "label": r.label, "placeholder": r.placeholder, "stage": r.stage,
              "enabled": bool(config["enabled"].get(r.id, True)), "locked": r.locked,
              "example": r.example} for r in BUILTIN]
    custom_on = config["enabled"].get("custom", True)
    active = sum(1 for r in rules if r["enabled"] and r["id"] != "custom") + (
        sum(1 for c in config["custom"] if c.get("enabled", True)) if custom_on else 0)
    return {"version": VERSION, "active_count": active, "rules": rules,
            "custom": [dict(c) for c in config["custom"]], "scope_note": SCOPE_NOTE}


def active_count() -> int:
    return describe()["active_count"]


# -- application ----------------------------------------------------------------------------

def user_names() -> list[str]:
    names = {Path.home().name, os.environ.get("USER", ""), os.environ.get("LOGNAME", "")}
    return sorted(n for n in names if len(n) >= 3 and n.lower() not in _GENERIC_NAMES)


class _Tracker:
    """Sequential substitutions with hit spans kept in the coordinates of the output text."""

    def __init__(self, text: str):
        self.text = text
        self.hits: list[dict] = []

    def sub(self, rule: str, pattern: re.Pattern, replace) -> None:
        pieces, spans, last, shift = [], [], 0, 0
        for match in pattern.finditer(self.text):
            new = replace(match)
            start, end = match.span()
            pieces.append(self.text[last:start])
            pieces.append(new)
            spans.append((start, end, start + shift, len(new), new))
            shift += len(new) - (end - start)
            last = end
        if not spans:
            return
        pieces.append(self.text[last:])
        self.text = "".join(pieces)
        moved = []
        for hit in self.hits:  # Earlier hits shift by the length change before them.
            delta = sum(n - (e - s) for s, e, _, n, _ in spans if e <= hit["start"])
            moved.append({**hit, "start": hit["start"] + delta, "end": hit["end"] + delta})
        new_hits = [{"rule": rule, "start": at, "end": at + n, "replacement": text}
                    for _, _, at, n, text in spans]
        self.hits = sorted(moved + new_hits, key=lambda h: (h["start"], h["end"]))


def _expand(template: str):
    return lambda match: match.expand(template)


def apply(text: str, config: dict | None = None, *, stages=("ingest", "outbound")) -> tuple[str, list[dict]]:
    """Run the enabled rules of ``stages`` in table order; returns (text, hits)."""
    config = config or current()
    on = config["enabled"]
    tracker = _Tracker(text or "")
    if "ingest" in stages:
        for pattern, replacement in privacy._PATTERNS:
            tracker.sub("credentials", re.compile(pattern), _expand(replacement))
    if "outbound" not in stages:
        return tracker.text, tracker.hits
    if on.get("email", True):
        tracker.sub("email", _EMAIL, lambda _m: "[email]")
    if on.get("home_user", True):
        tracker.sub("home_user", _HOME_PATH, lambda _m: "~")
    if on.get("private_host", True):
        tracker.sub("private_host", _PRIVATE_IP, lambda _m: "[host]")
        tracker.sub("private_host", _LOCAL_HOST, lambda _m: "[host]")
    if on.get("phone", True):
        tracker.sub("phone", _PHONE, lambda _m: "[phone]")
    if on.get("local_user", True):
        for name in user_names():
            pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", re.I)
            tracker.sub("local_user", pattern, lambda _m: "[user]")
    if on.get("custom", True):
        for item in config.get("custom") or []:
            if not item.get("enabled", True):
                continue
            try:
                pattern = re.compile(item["pattern"])
            except (re.error, KeyError, TypeError):
                continue  # Stored config was validated; a broken entry is skipped, not fatal.
            replacement = item.get("replacement", "[custom]")
            tracker.sub(item.get("id") or "custom", pattern, lambda _m, r=replacement: r)
    return tracker.text, tracker.hits


def preview(text: str, config: dict) -> dict:
    out, hits = apply(text, config)
    return {"text": out, "n": len(hits), "hits": hits, "scope_note": SCOPE_NOTE}
