"""Import progress: the stage catalog and optional terminal progress on stderr.

``STAGES`` is the single description of every ``progress["stage"]`` an import reports
(docs/development/import-pipeline.md §3): the user-facing label, the unit of
``completed`` / ``total`` and what the step does. ``describe`` adds ``label``, ``unit``
and ``weight`` to one update; library callers remain silent.
"""

import sys
import time

# stage -> (label, unit of completed/total or None, what the step does)
STAGES = {
    "capture": (
        "读取会话文件",
        "files",
        "按来源逐个读取允许导入的会话文件，记下每行的位置与摘要；没变的文件按 stat 跳过",
    ),
    "normalize": ("准备发布", None, "这批文件已读完，开始把它们投影成会话"),
    "reset_projection": (
        "开始重建",
        None,
        "清掉要重建范围（会话闭包或整个来源）的旧会话事实；attempt>1 表示源文件在"
        "导入途中变化，回滚后保留其上次事实重来",
    ),
    "prepare": (
        "预读会话文件",
        "files",
        "每个文件做一次映射前的预读（会话头、子代理关系、用量去重）",
    ),
    "map": ("解析会话记录", "files", "把原生记录映射成统一事件；records 是已映射的记录条数"),
    "derive": ("汇总会话", None, "从事件推导会话、轮次、工具调用、模型调用与项目"),
    "derive_metadata": ("汇总会话信息", "sessions", "读取每个会话的元数据（标题、目录、父会话）"),
    "derive_projects": ("归属项目", "sessions", "按工作目录与 Git 信息把会话归到项目"),
    "derive_sessions": ("统计轮次与工具", "sessions", "逐个会话统计轮次、工具调用、耗时与用量"),
    "validate_projection": ("校验", None, "检查外键与记录—事件对应关系"),
    "published": ("已发布", "files", "一次原子提交：新的数据版本（data_rev）对页面可见"),
    "progressive_batch": ("分批发布", "batches", "首次导入按批发布（CLI 渐进导入）"),
}
UNITS = {"files": "个文件", "sessions": "个会话", "batches": "批"}
# Share of one batch's work each stage roughly ends at (an estimate for one progress bar).
WEIGHTS = {
    "capture": 0.2,
    "normalize": 0.2,
    "reset_projection": 0.22,
    "prepare": 0.35,
    "map": 0.85,
    "derive": 0.86,
    "derive_metadata": 0.88,
    "derive_projects": 0.9,
    "derive_sessions": 0.97,
    "validate_projection": 0.99,
    "published": 1.0,
}
START = {
    "capture": 0.0,
    "prepare": 0.22,
    "map": 0.35,
    "derive_metadata": 0.86,
    "derive_projects": 0.88,
    "derive_sessions": 0.9,
}


def describe(update: dict) -> dict:
    """``label``/``unit`` for one update and ``fraction``: how far one batch is (0..1)."""
    stage = update.get("stage")
    label, unit, _ = STAGES.get(stage, (stage or "处理中", None, ""))
    end = WEIGHTS.get(stage)
    fraction = None
    if end is not None:
        start = START.get(stage, end)
        completed, total = update.get("completed"), update.get("total")
        share = completed / total if unit and total and completed is not None else 1.0
        fraction = start + (end - start) * max(0.0, min(1.0, share))
    return {"label": label, "unit": unit, "fraction": fraction}


class TerminalProgress:
    def __init__(self, *, enabled=True, interval=2.0):
        self.enabled = enabled
        self.interval = interval
        self.started = time.monotonic()
        self.last = 0.0
        self.stage = None

    def __call__(self, update):
        if not self.enabled:
            return
        now = time.monotonic()
        stage = update["stage"]
        completed, total = update.get("completed"), update.get("total")
        done = total is not None and completed == total
        if stage == self.stage and not done and now - self.last < self.interval:
            return
        self.stage, self.last = stage, now
        count = f" {completed}/{total}" if completed is not None and total is not None else ""
        records = f" · {update['records']} records" if "records" in update else ""
        print(
            f"[tandem] {stage}{count}{records} · {now - self.started:.1f}s",
            file=sys.stderr,
            flush=True,
        )
