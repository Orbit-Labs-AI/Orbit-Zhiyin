"""Static 16-type copy for the share card and persona reveal, kept verbatim as data.

Source: prototypes/advance/src/js/05-data.js (``TYPES``: code -> [中文名, English, 描述]) and
prototypes/advance/src/js/55-exports.js (``SHAREQ``: share-card two-line quote and its
default). Codes outside this table get no name or copy; nothing here is generated.
"""

from __future__ import annotations

TYPES: dict[str, tuple[str, str, str]] = {
    "DPMV": ("总设计师", "The Architect", "先写清规格，再分派给多个 Agent，并逐一验收。"),
    "DPMT": ("调度官", "The Dispatcher", "规格清楚、并行分派，信任结果、追求吞吐。"),
    "DPFV": ("监制", "The Producer", "一次只盯一件事：交代清楚、放手执行、严格验收。"),
    "DPFT": ("委托人", "The Commissioner", "写好需求就交出去，看结果不看过程。"),
    "DIMV": ("指挥家", "The Conductor", "整段目标交给 Agent，多线并进，坚持亲自验收。"),
    "DIMT": ("冲浪者", "The Surfer", "同时开很多条线，顺着结果走，很少回头检查。"),
    "DIFV": ("探路者", "The Pathfinder", "让 Agent 带路探索，一条线走深，再自己核实。"),
    "DIFT": ("漫游者", "The Wanderer", "随兴而起，放手让 Agent 发挥，享受意外收获。"),
    "SPMV": ("塔台", "The Controller", "多线并行，但每一步都由你下指令、逐个核对。"),
    "SPMT": ("杂技师", "The Juggler", "计划周全、亲自操盘多件事，节奏快、少回看。"),
    "SPFV": ("工匠", "The Artisan", "先规划、亲自掌舵、单线深耕、反复打磨。"),
    "SPFT": ("执笔人", "The Scribe", "你把步骤说清楚，Agent 逐条照做。"),
    "SIMV": ("实验家", "The Experimenter", "同时试几种做法，边做边改，用结果说话。"),
    "SIMT": ("即兴乐手", "The Jammer", "和多个 Agent 快速来回，灵感驱动，少收尾。"),
    "SIFV": ("雕刻师", "The Sculptor", "小步试、即时看、反复改，一点点削出想要的形状。"),
    "SIFT": ("搭档", "The Partner", "像结对编程一样边聊边推进，彼此信任。"),
}

SHARE_QUOTES: dict[str, tuple[str, str]] = {
    "DIMV": ("把目标交出去，", "把验收留给自己。"),
    "DIFV": ("让 Agent 带路，", "方向由我来核实。"),
    "DIMT": ("同时开很多条线，", "顺着结果往前走。"),
    "DIFT": ("放手让它发挥，", "享受意外的收获。"),
    "DPMV": ("先把规格写清楚，", "再让每个 Agent 各司其职。"),
    "SIFV": ("一次只做一件事，", "每一步都亲自确认。"),
    "SPFV": ("先规划，再打磨，", "每一处都亲手确认。"),
}
DEFAULT_QUOTE = ("和 AI 一起，", "找到自己的节奏。")


def copy_for(code: str | None) -> tuple[str | None, dict | None]:
    """(type_name, {headline, lines}) for a code in the table, else (None, None)."""
    entry = TYPES.get(code or "")
    if entry is None:
        return None, None
    zh, en, line = entry
    quote = SHARE_QUOTES.get(code, DEFAULT_QUOTE)
    return zh, {"headline": "".join(quote), "lines": [f"{zh} · {en}", line]}
