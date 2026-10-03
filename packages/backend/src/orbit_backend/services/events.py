"""SSE event bus: monotonic ids, a 1000-frame ring buffer and Last-Event-ID resume.

Publishers are worker reader threads; subscribers are asyncio stream generators. Frames
carry ids, stages, counts and revisions only. A client whose Last-Event-ID has already
left the buffer receives ``resync`` first and must refetch ``/v1/status``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

from ..platform.telemetry import gauge

TOPICS = frozenset({"job", "data", "analysis", "service", "notify"})


@dataclass(frozen=True)
class Frame:
    id: int
    topic: str
    event: str
    data: dict

    def encode(self) -> bytes:
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"), default=str)
        prefix = f"id: {self.id}\n" if self.id else ""  # Control frames keep the cursor.
        return f"{prefix}event: {self.event}\ndata: {payload}\n\n".encode()


class EventBus:
    def __init__(self, capacity: int = 1000, heartbeat_s: float = 15.0):
        self.frames: deque[Frame] = deque(maxlen=capacity)
        self.next_id = 1
        self.lock = threading.Lock()
        self.heartbeat_s = heartbeat_s
        self.waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        self.closed = False

    def publish(self, topic: str, event: str, data: dict) -> int:
        if topic not in TOPICS:
            raise ValueError(f"Unknown event topic {topic}")
        with self.lock:
            frame = Frame(self.next_id, topic, event, data)
            self.next_id += 1
            self.frames.append(frame)
            waiters = list(self.waiters)
        self._wake(waiters)
        return frame.id

    def _wake(self, waiters):
        for loop, flag in waiters:
            try:
                loop.call_soon_threadsafe(flag.set)
            except RuntimeError:
                pass  # Loop already closed; its stream is gone.

    @property
    def last_id(self) -> int:
        with self.lock:
            return self.next_id - 1

    def since(self, last_id: int, topics: Iterable[str] = TOPICS) -> tuple[list[Frame], bool]:
        """Frames after ``last_id``; ``gap`` is true when some were already evicted."""
        wanted = set(topics)
        with self.lock:
            oldest = self.frames[0].id if self.frames else self.next_id
            restarted = last_id >= self.next_id
            gap = restarted or last_id < oldest - 1
            if restarted:
                last_id = oldest - 1
            frames = [f for f in self.frames if f.id > last_id and f.topic in wanted]
        return frames, gap

    def close(self) -> None:
        with self.lock:
            self.closed = True
            waiters = list(self.waiters)
        self._wake(waiters)

    async def stream(self, last_id: int | None, topics: Iterable[str]) -> AsyncIterator[bytes]:
        topics = set(topics)
        flag = asyncio.Event()
        waiter = (asyncio.get_running_loop(), flag)
        with self.lock:
            self.waiters.add(waiter)
            cursor = self.next_id - 1 if last_id is None else last_id
            clients = len(self.waiters)
        gauge("sse.clients", clients)
        try:
            yield b"retry: 2000\n\n"
            while not self.closed:
                flag.clear()
                latest = self.last_id
                frames, gap = self.since(cursor, topics)
                if gap:
                    reason = "server_restart" if cursor > latest else "buffer_overflow"
                    cursor = frames[0].id - 1 if frames else latest
                    yield Frame(0, "service", "resync", {"reason": reason}).encode()
                for frame in frames:
                    cursor = frame.id
                    yield frame.encode()
                if frames:
                    continue
                try:
                    await asyncio.wait_for(flag.wait(), self.heartbeat_s)
                except TimeoutError:
                    yield b": hb\n\n"
        finally:
            with self.lock:
                self.waiters.discard(waiter)
                clients = len(self.waiters)
            gauge("sse.clients", clients)
