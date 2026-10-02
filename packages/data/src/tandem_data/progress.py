"""Optional terminal progress on stderr; library callers remain silent."""

import sys
import time


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
