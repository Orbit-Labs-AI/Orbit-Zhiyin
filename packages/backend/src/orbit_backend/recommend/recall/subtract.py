"""Route ⑤ (RC-07): subtraction — trim resident context and disable unused components."""

import os
import re

from .kb_route import from_rule

DIM_BY_TYPE = {"rule": "rule", "skill": "skill", "mcp": "mcp", "plugin": "mcp", "hook": "hook"}
EVIDENCE_SESSIONS = 20
# Files under a plugin cache are rewritten on every plugin update: the action is disabling the
# plugin in the agent's settings, never editing the cached file.
_PLUGIN_CACHE = re.compile(r"/plugins/cache/(?P<vendor>[^/]+)/(?P<plugin>[^/]+)/")
PLUGIN_SETTINGS = {"claude_code": "~/.claude/settings.json · enabledPlugins", "codex": "~/.codex/config.toml"}


def plugin_of(path) -> str | None:
    """``<plugin>@<vendor>`` when ``path`` lies in an agent's plugin cache."""
    match = _PLUGIN_CACHE.search(str(path or ""))
    return f"{match['plugin']}@{match['vendor']}" if match else None


def tilde(path) -> str:
    """Home-relative display path (``~/…``); never expose the absolute home directory."""
    text = str(path or "")
    home = os.path.expanduser("~")
    if home and home != "~" and (text == home or text.startswith(home.rstrip("/") + "/")):
        return "~" + text[len(home.rstrip("/")):]
    return re.sub(r"^/(?:Users|home)/[^/]+(?=/|$)", "~", text)


def recent_sessions(inputs: dict, limit: int = EVIDENCE_SESSIONS) -> list[str]:
    """Newest root sessions: the ones that loaded (and never called) the component."""
    days = [d for d in (inputs.get("facts") or {}).get("session_days") or () if d.get("session_uid")]
    days.sort(key=lambda d: d.get("started_at") or 0, reverse=True)
    return [d["session_uid"] for d in days[:limit]]


def recall(problems: list[dict], rules, inputs: dict, memory: dict) -> tuple[list, dict]:
    by_id = {rule.id: rule for rule in rules}
    muted = set(memory.get("muted_kb_rules") or ())
    rows, payload = [], {}
    for problem in problems:
        if problem["type"] not in ("resident_cost", "installed_unused") or problem["status"] == "insufficient":
            continue
        v = problem["vars"]
        split = problem["key"].startswith("resident_cost:rules_file")
        rule_id = "split-rules-file" if split else "trim-resident" if problem["type"] == "resident_cost" else "disable-unused"
        rule = by_id.get(rule_id)
        if rule is None or rule_id in muted:
            continue
        key = f"removal:{v.get('inv_id') or problem['key']}"
        if key in payload:
            continue
        cand = from_rule(rule, problem, inputs, rec_key=key, match_basis="inventory_fact", origin="inventory")
        name = v.get("name") or v.get("inv_id")
        plugin = plugin_of(v.get("config_path"))
        if plugin:
            key = f"removal:plugin:{plugin}"
            if key in payload:
                continue
        if plugin:
            reason = "从未被调用" if problem["type"] == "installed_unused" else f"每个会话常驻约 {v.get('tokens', 0)} tokens"
            title = f"停用插件 {plugin.split('@')[0]}（其中的 {name} {reason}）"
        elif split:
            title = f"精简 {name}（{v.get('lines', 0)} 行，建议拆分到子目录）"
        elif problem["type"] == "installed_unused":
            title = f"停用 {v.get('days', 14)} 天未用的 {str(v.get('inv_type') or '组件').upper()} {name}"
        else:
            title = f"精简常驻内容 {name}（约 {v.get('tokens', 0)} tokens）"
        cand.update({"title": title, "dim": DIM_BY_TYPE.get(v.get("inv_type"), "rule"), "level": 3 if split else 2,
                     # per-session time of resident tokens is unmeasured: rank prices the tokens directly
                     "unit_minutes": None, "resident_tokens": int(v.get("tokens") or 0) or int(v.get("lines") or 0) * 15})
        path = PLUGIN_SETTINGS.get(v.get("agent") or "claude_code", PLUGIN_SETTINGS["claude_code"]) if plugin \
            else tilde(v.get("config_path"))
        cand["target"].update({"path_hint": path or None, "scope": "user", "project_id": None})
        if plugin:
            cand["target"]["plugin"] = plugin
            cand["file"] = [[f'"{plugin}": false', "+"]] if (v.get("agent") or "claude_code") == "claude_code" else None
        cand["source"]["item_id"] = v.get("inv_id") or rule.id
        if not cand["evidence"]["session_uids"]:
            cand["evidence"]["session_uids"] = recent_sessions(inputs)
        cand["rec_key"] = key
        payload[key] = cand
        rows.append((key, 1. if problem["status"] == "active" else .5))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows, payload
