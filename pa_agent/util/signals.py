"""Minimal Qt-free signal primitive (connect/emit/disconnect).

Drop-in surface replacement for the Qt signal attributes on classes that
were decoupled from the desktop GUI framework.  Callbacks run synchronously
on the emitting thread — cross-thread marshalling is the consumer's job
(the WebUI server funnels callbacks through its asyncio event bridge).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class Signal:
    """A tiny observable slot list mimicking the Qt signal API we use."""

    def __init__(self, *_types: Any) -> None:
        self._slots: list[Callable[..., None]] = []
        self._lock = threading.Lock()

    def connect(self, fn: Callable[..., None]) -> None:
        with self._lock:
            if fn not in self._slots:
                self._slots.append(fn)

    def disconnect(self, fn: Callable[..., None] | None = None) -> None:
        with self._lock:
            if fn is None:
                self._slots.clear()
                return
            try:
                self._slots.remove(fn)
            except ValueError:
                pass

    def emit(self, *args: Any) -> None:
        with self._lock:
            slots = list(self._slots)
        for fn in slots:
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                logger.exception("signal slot %r raised", getattr(fn, "__name__", fn))
