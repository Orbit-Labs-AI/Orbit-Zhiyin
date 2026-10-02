"""Per-component disk usage of the Tandem home (Settings → storage, SET-15)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

SCAN_LIMIT = 200_000
KEEP_REPORTS = 30
# id, label, paths (files or directories, glob allowed), rebuildable, hint
COMPONENTS = (
    ("tandem_db", "规范数据库", ("tandem.db", "tandem.db-wal", "tandem.db-shm"), True,
     "从 Agent 日志重新导入可重建"),
    ("raw", "原始归档", ("archive", "raw"), False, "无损原始记录，删除后无法从已轮转日志恢复"),
    ("app_db", "应用数据库", ("app.db", "app.db-wal", "app.db-shm"), False,
     "推荐记录、安装台账、AI 产物与遥测"),
    ("catalog_db", "组件目录", ("catalog.db", "catalog.db-wal", "catalog.db-shm"), True,
     "可重新同步目录"),
    ("analysis", "分析库", ("analysis.sqlite*",), True, "可重新计算"),
    ("snapshot_cache", "界面快照缓存", ("cache",), True, "可随时清除，只影响首屏速度"),
    ("backups", "备份", ("backups",), False, "数据库备份"),
    ("logs", "日志", ("logs",), True, "本机日志，2 MB × 5 轮转"),
    ("exports", "导出", ("exports",), True, "诊断包与导出文件，保留最近 5 个"),
)


def dir_size(path: Path, limit: int = SCAN_LIMIT) -> tuple[int, bool]:
    """Total bytes under ``path`` (no symlink following); ``approx`` when truncated."""
    total, seen, stack = 0, 0, [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    seen += 1
                    if seen > limit:
                        return total, True
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, False


def _tilde(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home) else text


def path_bytes(path: Path) -> tuple[int, bool]:
    try:
        if path.is_dir():
            return dir_size(path)
        return (path.stat().st_size, False) if path.exists() else (0, False)
    except OSError:
        return 0, False


def storage_report(home: Path) -> dict:
    items, total = [], 0
    for key, label, patterns, rebuildable, hint in COMPONENTS:
        size, approx = 0, False
        for pattern in patterns:
            paths = home.glob(pattern) if "*" in pattern else [home / pattern]
            for path in paths:
                part, rough = path_bytes(path)
                size += part
                approx = approx or rough
        item = {"id": key, "label": label, "bytes": size, "rebuildable": rebuildable,
                "hint": hint, "path": _tilde(home / patterns[0].rstrip("*"))}
        if approx:
            item["approx"] = True
        items.append(item)
        total += size
    return {"generated_at": int(time.time() * 1000), "home": _tilde(home), "total_bytes": total,
            "components": items}


def save_report(appdb, report: dict) -> None:
    with appdb.write() as db:
        db.execute("INSERT OR REPLACE INTO storage_report VALUES (?, ?)",
                   (report["generated_at"], json.dumps(report, ensure_ascii=False)))
        db.execute("DELETE FROM storage_report WHERE ts NOT IN (SELECT ts FROM storage_report"
                   " ORDER BY ts DESC LIMIT ?)", (KEEP_REPORTS,))


def latest_report(appdb) -> dict | None:
    with appdb.read() as db:
        row = db.execute("SELECT body FROM storage_report ORDER BY ts DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None
