#!/usr/bin/env python3
"""在本机共享闸门后运行重负载命令，避免多个任务同时抢 CPU。

用法：python3 scripts/heavy.py <命令> [参数...]
  HEAVY_SLOTS  同名闸门允许同时运行的命令数，默认 2
  HEAVY_NAME   闸门名，默认 heavy；合并用 HEAVY_NAME=merge HEAVY_SLOTS=1
锁文件位于主 checkout 的 .local/locks/，所有 worktree 共用。
"""
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)
slots = int(os.environ.get("HEAVY_SLOTS", "2"))
name = os.environ.get("HEAVY_NAME", "heavy")
common = subprocess.run(
    ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
    capture_output=True, text=True, check=True,
).stdout.strip()
locks = Path(common).parent / ".local" / "locks"
locks.mkdir(parents=True, exist_ok=True)
started = time.time()
while True:
    for i in range(slots):
        fd = os.open(locks / f"{name}-{i}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        waited = time.time() - started
        if waited > 1:
            print(f"[heavy] {name}: waited {waited:.0f}s for slot {i}", file=sys.stderr, flush=True)
        sys.exit(subprocess.call(sys.argv[1:]))
    time.sleep(2)
