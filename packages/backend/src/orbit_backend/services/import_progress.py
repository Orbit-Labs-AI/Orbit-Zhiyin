"""One readable line per import progress frame (docs/development/import-pipeline.md §3).

The ingest worker adds where the job is (source, batch) to the data layer's progress and
``detail`` turns the frame into the line the UI shows under 导入历史会话.
"""

from __future__ import annotations

AGENT_NAMES = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "dsh": "DSH",
    "pi": "pi",
    "opencode": "OpenCode",
    "hermes": "Hermes",
    "kimi": "Kimi",
}
PHASE_NAMES = {
    "head": "最近的会话",
    "window": "近 30 天",
    "rest": "更早的会话",
    "full": "全部会话",
    "selection": "所选文件",
    "rebuild": "重建",
}
SCOPE_NAMES = {"closure": "只重建受影响的会话", "source": "重建整个来源"}


def detail(frame: dict) -> str:
    """One readable line for a progress frame: which source and batch, what the step rebuilds
    and why it reruns. ``completed``/``total`` stay numbers with their ``unit`` (the UI shows
    「419 / 975 个文件」); only the map stage's record count is spelled out here."""
    parts = []
    agent = frame.get("source_agent")
    if agent:
        where = AGENT_NAMES.get(agent, agent)
        if (frame.get("steps") or 0) > 1:
            where += f" · 第 {frame['step']}/{frame['steps']} 个来源"
        parts.append(where)
    if (frame.get("batches") or 0) > 1:
        parts.append(
            f"第 {frame['batch']}/{frame['batches']} 批（{PHASE_NAMES.get(frame.get('batch_phase'), frame.get('batch_phase'))}）"
        )
    projecting = frame.get("projecting")
    if projecting and projecting != agent:
        parts.append(f"发布 {AGENT_NAMES.get(projecting, projecting)} 尚未发布的文件")
    if frame.get("scope") in SCOPE_NAMES and frame.get("stage") in (
        "reset_projection",
        "prepare",
        "map",
    ):
        parts.append(SCOPE_NAMES[frame["scope"]])
    if frame.get("stage") == "capture_retry":
        reason = ("源文件在读取时变化" if frame.get("source_status") == "changed"
                  else "来源数据库暂时被锁定" if frame.get("sqlite_errorname")
                  else "来源暂时出现 I/O 错误")
        parts.append(f"第 {frame.get('attempt', 2)} 次尝试：{reason}，重新读取；持续失败则保留上次事实")
    elif (frame.get("attempt") or 1) > 1:
        parts.append(f"第 {frame['attempt']} 次尝试：源文件在导入途中变化，保留其上次的事实")
    if frame.get("stage") == "map" and frame.get("records"):
        parts.append(f"已解析 {frame['records']:,} 条记录")
    return " · ".join(parts)
