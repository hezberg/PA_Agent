"""Thread-safe event hub bridging worker-thread callbacks to SSE subscribers.

Worker threads (refresh loop, analysis runner, demo replayer) publish events;
each SSE endpoint holds an :class:`asyncio.Queue` fed via
``loop.call_soon_threadsafe`` so no lock is ever held across the boundary.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_ALL = "*"


@dataclass
class Event:
    """One SSE payload: ``{"type": ..., **data}``."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_sse(self) -> str:
        import json

        payload = {"type": self.type, **self.data}
        return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


class EventHub:
    """Fan-out pub/sub keyed by channel name (``analysis:<id>``, ``frames``, ...)."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[int, tuple[set[str], asyncio.Queue[Event | None]]] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the asyncio loop that drains subscriber queues (called at startup)."""
        self._loop = loop

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, channels: set[str]) -> tuple[int, asyncio.Queue[Event | None]]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=4096)
        sub_id = next(self._ids)
        with self._lock:
            self._subs[sub_id] = (set(channels), queue)
        return sub_id, queue

    def unsubscribe(self, sub_id: int) -> None:
        with self._lock:
            self._subs.pop(sub_id, None)

    def close_channel(self, channel: str) -> None:
        """Push a sentinel None to every subscriber of *channel* (ends their SSE stream)."""
        with self._lock:
            targets = [q for chans, q in self._subs.values() if channel in chans]
        for queue in targets:
            self._offer(queue, None)

    # ── Publishing ────────────────────────────────────────────────────────────

    def publish(self, channel: str, event: Event) -> None:
        with self._lock:
            targets = [
                q
                for chans, q in self._subs.values()
                if channel in chans or _ALL in chans
            ]
        for queue in targets:
            self._offer(queue, event)

    def _offer(self, queue: asyncio.Queue[Event | None], item: Event | None) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._put_nowait, queue, item)
        except RuntimeError:
            # Loop shutting down while a worker thread still publishes.
            pass

    @staticmethod
    def _put_nowait(queue: asyncio.Queue[Event | None], item: Event | None) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("event queue overflow — dropping %s", getattr(item, "type", item))


def bar_close_wait_state_payload(
    armed: bool, seconds_remaining: int | None, force_incremental: bool
) -> dict[str, Any]:
    return {
        "armed": armed,
        "seconds_remaining": seconds_remaining,
        "force_incremental": force_incremental,
    }
