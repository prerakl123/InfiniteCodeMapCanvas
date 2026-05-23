from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

RING_BUFFER_SIZE = 1000


@dataclass
class Subscriber:
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    project_id: str


@dataclass
class ProjectChannel:
    seq: int = 0
    ring: deque = field(default_factory=lambda: deque(maxlen=RING_BUFFER_SIZE))
    subscribers: list[Subscriber] = field(default_factory=list)


class EventBus:
    def __init__(self) -> None:
        self._channels: dict[str, ProjectChannel] = {}
        self._lock = threading.Lock()

    def _channel(self, project_id: str) -> ProjectChannel:
        with self._lock:
            ch = self._channels.get(project_id)
            if ch is None:
                ch = ProjectChannel()
                self._channels[project_id] = ch
            return ch

    def publish(self, project_id: str, event: dict[str, Any]) -> int:
        """Thread-safe. Returns the sequence number assigned."""
        ch = self._channel(project_id)
        with self._lock:
            ch.seq += 1
            seq = ch.seq
            wrapped = {"seq": seq, **event}
            ch.ring.append(wrapped)
            subs = list(ch.subscribers)
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(_safe_put_nowait, sub.queue, wrapped)
            except RuntimeError:
                # subscriber's loop is closed
                continue
        return seq

    def subscribe(
        self, project_id: str, since_seq: int | None = None
    ) -> tuple[Subscriber, list[dict]]:
        """Register a subscriber and return (sub, replay_events).

        Caller MUST await the subscriber's queue, then unsubscribe() in finally.
        """
        loop = asyncio.get_running_loop()
        sub = Subscriber(queue=asyncio.Queue(), loop=loop, project_id=project_id)
        ch = self._channel(project_id)
        with self._lock:
            replay: list[dict] = []
            if since_seq is not None and ch.ring:
                oldest = ch.ring[0]["seq"]
                if since_seq + 1 < oldest:
                    # We have missed events beyond the ring; signal client to resync.
                    replay = [{"seq": ch.seq, "type": "resync_required"}]
                else:
                    for evt in ch.ring:
                        if evt["seq"] > since_seq:
                            replay.append(evt)
            ch.subscribers.append(sub)
        return sub, replay

    def unsubscribe(self, sub: Subscriber) -> None:
        ch = self._channel(sub.project_id)
        with self._lock:
            try:
                ch.subscribers.remove(sub)
            except ValueError:
                pass

    def last_seq(self, project_id: str) -> int:
        return self._channel(project_id).seq


def _safe_put_nowait(queue: asyncio.Queue, item: dict) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        pass


event_bus = EventBus()
