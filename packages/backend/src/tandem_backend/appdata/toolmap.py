"""``GET /v1/app/tool_map`` (SET-11): how raw tool names map to Tandem's tool kinds.

The static table is ``tandem_data.tool_kinds.AGENT_TOOL_KINDS``, listed per agent because
classification is per agent (``tool_kind(name, agent)``): the same name can mean different
things to different harnesses, and the union table ``reduce.TOOL_KINDS`` hides which agent
registers which name. Names an agent registers without an analytic category are listed under
``other``. MCP names follow ``mcp__<server>__<tool>``. Observed names come from ``tool_call``
grouped by agent; with no database only the static table is returned. Editing the map is
planned for v2.
"""

from __future__ import annotations

import logging
import sqlite3

from ..services.auth import ApiError

log = logging.getLogger(__name__)

OBSERVED_LIMIT = 200
LABELS = {"shell": "终端命令", "file.read": "读文件", "file.edit": "改文件", "file.write": "写文件",
          "search": "搜索代码", "web.search": "网页搜索", "web.fetch": "抓取网页",
          "subagent": "子代理", "skill": "技能", "plan": "计划/待办", "ask_user": "向你提问",
          "mcp": "MCP 工具", "other": "其他"}


def _observed(reads) -> list[tuple]:
    if reads is None:
        return []
    try:
        with reads.read(check=False) as db:
            return db.execute(
                "SELECT COALESCE(src.agent, ''), tc.name, COALESCE(tc.kind, 'other'), COUNT(*) n "
                "FROM tool_call tc LEFT JOIN session s ON s.session_uid = tc.session_uid "
                "LEFT JOIN source src ON src.source_id = s.source_id "
                "GROUP BY 1, 2, 3 ORDER BY n DESC, 2 LIMIT ?", (OBSERVED_LIMIT,)).fetchall()
    except (sqlite3.Error, OSError, ValueError, RuntimeError, ApiError):
        log.debug("tool_call unavailable", exc_info=True)
        return []


def tool_map(reads=None) -> dict:
    from tandem_data import REDUCER_VERSION
    from tandem_data.tool_kinds import AGENT_TOOL_KINDS, KINDS

    kinds = {kind: {"kind": kind, "label": LABELS.get(kind, kind), "names": []}
             for kind in KINDS}
    kinds.setdefault("mcp", {"kind": "mcp", "label": LABELS["mcp"], "names": []})
    static: dict[tuple[str, str], dict] = {}
    for agent in sorted(AGENT_TOOL_KINDS):
        for name, kind in sorted(AGENT_TOOL_KINDS[agent].items()):
            entry = {"agent": agent, "name": name, "calls": None}
            kinds.setdefault(kind, {"kind": kind, "label": LABELS.get(kind, kind), "names": []})
            kinds[kind]["names"].append(entry)
            static[(agent, name)] = entry
    observed = 0
    for agent, name, kind, calls in _observed(reads):
        entry = kinds.setdefault(kind, {"kind": kind, "label": LABELS.get(kind, kind),
                                        "names": []})
        known = static.pop((agent or "", str(name).lower()), None)
        if known is not None and known in entry["names"]:
            entry["names"].remove(known)  # Observed under its raw spelling instead.
        entry["names"].append({"agent": agent or None, "name": name, "calls": calls})
        observed += 1
    return {"version": REDUCER_VERSION, "kinds": list(kinds.values()), "observed": observed,
            "agents": sorted(AGENT_TOOL_KINDS), "mcp": {"pattern": "mcp__<server>__<tool>"},
            "editable": False}
