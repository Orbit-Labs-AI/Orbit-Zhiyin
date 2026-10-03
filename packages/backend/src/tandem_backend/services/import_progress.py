"""One readable line per import progress frame (docs/development/import-pipeline.md §3).

The ingest worker adds where the job is (source, batch) to the data layer's progress and
``detail`` turns the frame into the line the UI shows under 导入历史会话.
"""

from __future__ import annotations

from tandem_data.progress import UNITS

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
    """One readable line for a progress frame: where the job is and what the numbers mean."""
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
    if (frame.get("attempt") or 1) > 1:
        parts.append(f"第 {frame['attempt']} 次尝试：源文件在导入途中变化，保留其上次的事实")
    unit = frame.get("unit")
    if unit and frame.get("total") is not None and frame.get("completed") is not None:
        count = f"{frame['completed']} / {frame['total']} {UNITS.get(unit, unit)}"
        if frame.get("records"):
            count += f"，已解析 {frame['records']} 条记录"
        parts.append(count)
    return " · ".join(parts)
