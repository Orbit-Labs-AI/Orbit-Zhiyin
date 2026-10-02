"""Session handoff prompt (RC-15.1, L0): task, recent files and pending verification.

Template-only, no model call. Reads ``tandem.db`` through the gateway read pool.
"""

from __future__ import annotations

import json

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "apply_patch")
VERIFY_HEADS = ("pytest", "npm test", "pnpm check", "pnpm test", "cargo test", "go test", "make",
                "uv run pytest", "npm run test", "npm run lint", "ruff", "tsc")
MAX_FILES = 10


def _is_verify(command_head: str | None) -> bool:
    head = " ".join((command_head or "").split())
    return any(head == h or head.startswith(h + " ") for h in VERIFY_HEADS)


def build(conn, session_uid: str) -> dict | None:
    session = conn.execute("SELECT title FROM session WHERE session_uid=?",
                           (session_uid,)).fetchone()
    if session is None:
        return None
    files: list[str] = []
    last_edit = last_verify = None
    last_test = None
    rows = conn.execute("SELECT name, command_head, files, started_at FROM tool_call WHERE "
                        "session_uid=? ORDER BY started_at DESC, rowid DESC",
                        (session_uid,)).fetchall()
    for index, (name, command_head, raw_files, _) in enumerate(rows):
        if name in EDIT_TOOLS:
            last_edit = index if last_edit is None else last_edit
            try:
                paths = json.loads(raw_files or "[]")
            except ValueError:
                paths = []
            for path in paths if isinstance(paths, list) else []:
                path = path.get("path") if isinstance(path, dict) else path
                if isinstance(path, str) and path not in files and len(files) < MAX_FILES:
                    files.append(path)
        elif _is_verify(command_head):
            if last_verify is None:
                last_verify, last_test = index, " ".join(command_head.split())
    # Rows are newest first: a verify run after the last edit has a smaller index.
    verify_pending = last_edit is not None and (last_verify is None or last_verify > last_edit)
    task = session[0] or "（未命名会话）"
    lines = [f"继续上一个任务：{task}",
             f"最近改动：{'、'.join(files) if files else '（无文件改动记录）'}"]
    lines.append("注意：最后一次改动之后还没有运行测试或检查。" if verify_pending
                 else "最后一次改动之后已经运行过验证。" if last_edit is not None else "")
    lines.append("请先阅读以上文件再继续，完成后运行验证。")
    return {"session_uid": session_uid, "text": "\n".join(line for line in lines if line),
            "parts": {"task": task, "recent_files": files, "verify_pending": verify_pending,
                      "last_test_command": last_test}}
