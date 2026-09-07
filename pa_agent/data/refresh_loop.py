"""1 Hz data refresh loop running on a dedicated thread (Qt-free)."""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from pa_agent.data.base import DataSource, DataSourceTransientError
from pa_agent.data.snapshot import INDICATOR_WARMUP_BARS
from pa_agent.util.signals import Signal

if TYPE_CHECKING:
    from pa_agent.util.threading import CancelToken

logger = logging.getLogger(__name__)


class RefreshLoop(threading.Thread):
    """Fetches the latest K-line snapshot every *interval_ms* milliseconds.

    Signals (Qt-free; use ``.connect(fn)``)
    -------
    frame_ready(list[KlineBar])
        Emitted after each successful fetch with the raw bar list (newest-first).
    status_changed(str)
        Emitted with a human-readable status string (e.g. "数据延迟").
    """

    def __init__(
        self,
        data_source: DataSource,
        n_bars: int,
        interval_ms: int = 1000,
        cancel_token: "CancelToken | None" = None,
        parent: object | None = None,
    ) -> None:
        super().__init__(name="RefreshLoop", daemon=True)
        self.frame_ready = Signal(list)
        self.status_changed = Signal(str)
        self._source = data_source
        self._n_bars = n_bars
        self._interval_ms = interval_ms
        self._cancel_token = cancel_token
        self._consecutive_failures = 0
        self._failure_threshold_s = 5.0
        self._in_flight = False  # guard against overlapping fetches
        self._first_fetch_pending = True  # 首帧未到（重试文案带次数）

    # Compatibility shims for historical QThread call sites (isRunning/wait).
    def isRunning(self) -> bool:  # noqa: N802
        return self.is_alive()

    def wait(self, timeout_ms: int | None = None) -> bool:
        self.join(max(0.0, (timeout_ms or 0) / 1000.0))
        return not self.is_alive()

    def run(self) -> None:  # noqa: C901
        """Main loop — runs on the worker thread."""
        failure_start: float | None = None

        while True:
            if self._cancel_token is not None and self._cancel_token.is_set():
                logger.debug("RefreshLoop cancelled")
                break

            # Skip this tick if a previous fetch is still in flight.
            # This prevents overlapping WebSocket connections that trigger
            # TradingView rate-limiting (especially in nologin mode).
            if self._in_flight:
                time.sleep(0.5)
                continue

            t0 = time.monotonic()
            self._in_flight = True
            try:
                try:
                    bars = self._source.latest_snapshot(
                        self._n_bars + INDICATOR_WARMUP_BARS + 5
                    )
                    if self._consecutive_failures > 0:
                        # Clear any previous error message from the status bar.
                        self.status_changed.emit("")
                    self._consecutive_failures = 0
                    failure_start = None
                    if bars:
                        self._first_fetch_pending = False
                        self.frame_ready.emit(bars)

                except DataSourceTransientError as exc:
                    logger.debug("RefreshLoop transient error: %s", exc)
                    self._consecutive_failures += 1
                    if failure_start is None:
                        failure_start = time.monotonic()
                    user_msg = str(exc).strip()
                    elapsed = time.monotonic() - failure_start
                    if self._first_fetch_pending:
                        # 首帧未到：进度文案带重试次数，让用户知道仍在获取。
                        retry_note = f"正在重试（第 {self._consecutive_failures} 次）…"
                        self.status_changed.emit(
                            f"{user_msg}，{retry_note}"
                            if user_msg
                            else f"尚未获取到数据，{retry_note}"
                        )
                    elif user_msg:
                        self.status_changed.emit(user_msg)
                    elif elapsed >= self._failure_threshold_s:
                        self.status_changed.emit("数据延迟")
                except Exception as exc:  # noqa: BLE001
                    logger.error("RefreshLoop unexpected error: %s", exc, exc_info=True)
            finally:
                self._in_flight = False

            # Exponential backoff on repeated failures to avoid hammering
            # TradingView's WebSocket endpoint
            if self._consecutive_failures > 0:
                backoff_s = min(
                    0.5 * (2 ** (self._consecutive_failures - 1)),
                    10.0,
                )
                logger.debug(
                    "RefreshLoop backoff %.1fs after %d consecutive failure(s)",
                    backoff_s,
                    self._consecutive_failures,
                )
                time.sleep(backoff_s)
                continue

            elapsed_ms = (time.monotonic() - t0) * 1000
            sleep_ms = max(0.0, self._interval_ms - elapsed_ms)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
