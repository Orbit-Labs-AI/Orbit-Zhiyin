"""16-type copy and the four axes, verbatim from ``prototypes/advance/src/js/05-data.js``.

Round 3 ships the same table as ``exporting.type_copy.TYPES``; when that module exists it
is the source of truth, otherwise the built-in copy below (kept character-identical) is used.
"""

from __future__ import annotations

BUILTIN: dict[str, tuple[str, str, str]] = {
    "DPMV": ("总设计师", "The Master Planner", "胸有蓝图的统筹者，规格先行、多线分派、件件验收，再大的项目也井井有条。"),
    "DPMT": ("调度官", "The Dispatcher", "果断高效的组织者，把需求讲清就放手并行，善于授权，让产出源源不断。"),
    "DPFV": ("监制", "The Producer", "专注严谨的把关人，一次只推一件事，交代清楚、严格验收，出品稳定可靠。"),
    "DPFT": ("策划人", "The Strategist", "思路清晰的出题人，擅长把想法写成好任务书，放心交付，把精力留给关键判断。"),
    "DIMV": ("指挥家", "The Conductor", "统揽全局的领军人，多个 Agent 齐头并进，亲自守住验收，速度与质量兼得。"),
    "DIMT": ("冲浪者", "The Surfer", "敏锐灵活的弄潮儿，同时驾驭多条线、顺势快速迭代，总能在变化中抓住机会。"),
    "DIFV": ("探路者", "The Pathfinder", "敢闯又踏实的开拓者，让 Agent 先行探索、一路走深，再亲自核实每一步。"),
    "DIFT": ("远航者", "The Voyager", "好奇开放的旅人，给 Agent 充分的发挥空间，享受一路上的意外之喜。"),
    "SPMV": ("飞控官", "The Mission Controller", "冷静缜密的全局掌控者，多条线同时推进也步步有令、逐项核对，让每条线都稳稳落地。"),
    "SPMT": ("杂技师", "The Juggler", "精力充沛的多面手，计划周全、亲自操盘多件事，节奏明快，推进效率惊人。"),
    "SPFV": ("分析学家", "The Analyst", "冷静理性的思考者，先想清楚再动手，亲自掌舵、单线深挖、步步求证，结论经得起推敲。"),
    "SPFT": ("领航员", "The Navigator", "条理分明的引路人，把步骤一条条讲清楚，Agent 照着执行就能精准抵达。"),
    "SIMV": ("实验家", "The Experimenter", "不拘一格的尝鲜派，同时尝试几种做法、边做边改，用结果找到更优解。"),
    "SIMT": ("即兴乐手", "The Jammer", "灵感充沛的创作者，和多个 Agent 快速往来、彼此激发，擅长打开新思路。"),
    "SIFV": ("雕刻师", "The Sculptor", "耐心细致的打磨者，小步尝试、即时查看、反复修改，一点点刻出理想的形状。"),
    "SIFT": ("同行者", "The Companion", "默契十足的协作伙伴，像结对编程一样边聊边推进，彼此信任、配合流畅。"),
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
