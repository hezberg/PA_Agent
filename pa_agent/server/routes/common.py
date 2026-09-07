"""Shared helpers for route modules."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

from pa_agent.server.event_hub import Event
from pa_agent.server.state import AppState

PING_INTERVAL_S = 15.0


def get_state(request: Request) -> AppState:
    return request.app.state.pa


def sse_stream(queue: asyncio.Queue, sub_id: int, state: AppState) -> Any:
    """Wrap an event-hub queue as a StreamingResponse body with keep-alive pings."""

    async def _gen() -> AsyncIterator[str]:
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    yield "event: done\ndata: {}\n\n"
                    return
                assert isinstance(item, Event)
                yield item.as_sse()
        except asyncio.CancelledError:  # pragma: no cover - client disconnect
            raise
        finally:
            state.hub.unsubscribe(sub_id)

    return _gen()


def json_safe(payload: Any) -> Any:
    """Best-effort conversion of arbitrary domain objects to JSON."""
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))
