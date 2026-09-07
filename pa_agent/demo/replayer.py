"""Timed replay of a saved AnalysisRecord through the same event stream as live analysis (Qt-free)."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from pa_agent.ai.response_extract import content_from_response, reasoning_from_response
from pa_agent.records.schema import AnalysisRecord
from pa_agent.util.signals import Signal

# One Unicode codepoint per “token”, like real API streaming.
_CHAR_S = 0.016
_STAGE_GAP_S = 0.45


def _prompt_parts(messages: list[dict] | None, *, last_user: bool = False) -> tuple[str, str]:
    msgs = messages or []
    system = next((m.get("content", "") for m in msgs if m.get("role") == "system"), "")
    user_messages = reversed(msgs) if last_user else msgs
    user = next((m.get("content", "") for m in user_messages if m.get("role") == "user"), "")
    return str(system), str(user)


def _chars_for_stream(text: str) -> list[str]:
    """Single-character chunks (CJK and ASCII each one cell)."""
    if not text:
        return []
    return list(text)


class DemoReplayer:
    """Emit the same event sequence as a live analysis run on a timed schedule.

    Signals (Qt-free; use ``.connect(fn)``): finished, record_ready,
    status_update, reasoning_token, content_token, stage_prompt_ready,
    stage2_files_ready, replay_finished.
    Callbacks fire on the replayer's scheduler thread.
    """

    def __init__(self, record: AnalysisRecord, parent: object | None = None) -> None:
        self.finished = Signal(dict)
        self.record_ready = Signal(object)
        self.status_update = Signal(str)
        self.reasoning_token = Signal(str, str)
        self.content_token = Signal(str, str)
        self.stage_prompt_ready = Signal(str, str, str)
        self.stage2_files_ready = Signal(list)
        self.replay_finished = Signal()
        self._record = record
        self._steps: list[tuple[float, Callable[[], None]]] = []
        self._index = 0
        self._running = False
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()
        self._steps.clear()
        self._index = 0

    def start(self) -> None:
        self.stop()
        self._steps = self._build_steps()
        self._index = 0
        self._running = True
        self._run_next(0.0)

    def _schedule(self, delay_s: float) -> None:
        timer = threading.Timer(delay_s, self._run_next, args=(delay_s,))
        timer.daemon = True
        with self._lock:
            self._timer = timer
            if not self._running:
                timer.cancel()
                return
        timer.start()

    def _build_steps(self) -> list[tuple[float, Callable[[], None]]]:
        r = self._record
        steps: list[tuple[float, Callable[[], None]]] = []

        s1_sys, s1_user = _prompt_parts(r.stage1_messages)
        s2_sys, s2_user = _prompt_parts(r.stage2_messages, last_user=True)
        s1_reason = reasoning_from_response(r.stage1_response)
        s2_reason = reasoning_from_response(r.stage2_response)
        s2_content = content_from_response(r.stage2_response)
        strategy = list(r.strategy_files_used or [])

        def add(delay: float, fn: Callable[[], None]) -> None:
            steps.append((delay, fn))

        add(_STAGE_GAP_S, lambda: self.status_update.emit("阶段一分析中…"))
        add(0.08, lambda: self.stage_prompt_ready.emit("stage1", s1_sys, s1_user))
        for ch in _chars_for_stream(s1_reason):
            add(_CHAR_S, lambda c=ch: self.reasoning_token.emit("stage1", c))
        add(_STAGE_GAP_S, lambda: self.status_update.emit("阶段一完成"))

        if strategy or r.stage2_decision:
            add(0.2, lambda: self.stage2_files_ready.emit(strategy))
            add(_STAGE_GAP_S, lambda: self.status_update.emit("阶段二分析中…"))
            add(0.08, lambda: self.stage_prompt_ready.emit("stage2", s2_sys, s2_user))
            for ch in _chars_for_stream(s2_reason):
                add(_CHAR_S, lambda c=ch: self.reasoning_token.emit("stage2", c))
            if not s2_reason and s2_content:
                for ch in _chars_for_stream(s2_content):
                    add(_CHAR_S, lambda c=ch, s="stage2": self.content_token.emit(s, c))
            add(_STAGE_GAP_S, lambda: self.status_update.emit("阶段二完成"))

        # Match real worker: stream ends, then record persisted, then record_ready → finished.
        add(0.3, lambda: self.status_update.emit("记录已保存"))
        add(0.12, lambda: self.record_ready.emit(r))
        add(0.2, self._emit_finished)
        return steps

    def _emit_finished(self) -> None:
        decision = self._record.stage2_decision or {}
        self.finished.emit(decision if isinstance(decision, dict) else {})

    def _run_next(self, _delay: float = 0.0) -> None:
        if not self._running:
            return
        if self._index >= len(self._steps):
            self._running = False
            self.replay_finished.emit()
            return
        delay, action = self._steps[self._index]
        self._index += 1
        action()
        self._schedule(delay)
