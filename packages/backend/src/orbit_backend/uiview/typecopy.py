"""16-type copy and the four axes, verbatim from ``prototypes/advance/src/js/05-data.js``.

Round 3 ships the same table as ``exporting.type_copy.TYPES``; when that module exists it
is the source of truth, otherwise the built-in copy below (kept character-identical) is used.
"""

from __future__ import annotations

BUILTIN: dict[str, tuple[str, str, str]] = {
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
UNDETERMINED = ("暂无画像", "No persona yet", "所选范围还没有会话。")
# k = value key; high value → L letter (prototype ``pairs``), low value → R letter.
AXES = (
    {"k": "D", "hi": "D", "hi_n": "委托", "lo": "S", "lo_n": "掌舵", "dim": "自主度",
     "q": "你把多大块的事交出去？", "sig": "每会话消息数 · 单轮自主步数 · 打断与中止率"},
    {"k": "I", "hi": "I", "hi_n": "即兴", "lo": "P", "lo_n": "规划", "dim": "结构度",
     "q": "先想清楚再动手，还是边做边想？", "sig": "首条消息长度与验收标准 · 规格文件引用 · 中途改向"},
    {"k": "M", "hi": "M", "hi_n": "多线", "lo": "F", "lo_n": "专注", "dim": "并发度",
     "q": "你同时推进几件事？", "sig": "每日会话数 · 同日使用的 Agent 数 · 子代理并行度"},
    {"k": "V", "hi": "V", "hi_n": "求证", "lo": "T", "lo_n": "信任", "dim": "求证度",
     "q": "你怎么确认它做对了？", "sig": "要求测试 / 编译 / 线上验证的比例 · 回滚与重做率"},
)


def _types() -> tuple[dict[str, tuple[str, str, str]], str]:
    try:
        from ..exporting.type_copy import TYPES as shared  # round 3
    except ImportError:
        return BUILTIN, "builtin"
    if isinstance(shared, dict) and len(shared) == 16:
        return {k: tuple(v) for k, v in shared.items()}, "exporting.type_copy"
    return BUILTIN, "builtin"


TYPES, SOURCE = _types()


def copy(code: str | None) -> tuple[str, str, str]:
    return TYPES.get(code or "", UNDETERMINED)
