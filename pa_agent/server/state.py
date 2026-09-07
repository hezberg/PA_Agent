"""Process-wide WebUI session state (single user, local app).

Replaces the historical MainWindow's role as the state machine owner:
analysis task registry, refresh loop, cached bars, bar-close wait,
keep-analysis tracker, free-chat session and demo replay state.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pa_agent.server.event_hub import Event, EventHub


@dataclass
class AnalysisTask:
    """One submitted analysis run."""

    id: str
    symbol: str
    timeframe: str
    bar_count: int
    force_incremental: bool
    cancel_token: Any = None
    thread: Any = None
    status: str = "running"          # running | finished | cancelled | error
    started_ts: float = field(default_factory=time.monotonic)


class AppState:
    """All mutable WebUI session state plus the shared EventHub."""

    def __init__(self) -> None:
        self.ctx: Any = None                  # AppContext (set during startup)
        self.hub = EventHub()

        self._lock = threading.RLock()

        # Market / refresh loop
        self.refresh_loop: Any = None
        self.refresh_cancel_token: Any = None
        self.last_frame_bars: list[Any] | None = None   # newest-first raw bars
        self.last_refresh_ts: float = 0.0
        self.fetch_pending: bool = False          # 获取数据等待首帧（驱动进度文案）
        self.chart_refresh_paused: bool = False
        self.active_data_source_kind: str = "mt5"

        # Submission state machine
        self.analysis_in_progress: bool = False
        self.switching: bool = False
        self.demo_mode: bool = False
        self.last_analysis_had_error: bool = False
        self.incremental_available: bool = False
        self.auto_incremental_pending: bool = False
        self.last_analysis_record: Any = None
        self.last_analysis_frame: Any = None
        self.analysis_previous_record: Any = None
        self.last_stage1_diagnosis: dict | None = None

        # Bar-close wait
        self.bar_close_wait: Any = None       # services BarCloseWait

        # Keep-analysis
        self.keep_analysis_enabled: bool = False
        self.keep_analysis_tracker: Any = None

        # Tasks
        self.current_task: AnalysisTask | None = None

        # Free chat
        self.chat_session: Any = None
        self.chat_cancel_token: Any = None

        # Demo
        self.demo_kind: str | None = None            # manual | auto
        self.demo_record_path: str | None = None
        self.demo_replayer: Any = None
        self.demo_auto_next_armed: bool = False

    # ── Small helpers ─────────────────────────────────────────────────────────

    def settings(self) -> Any:
        return getattr(self.ctx, "settings", None)

    def data_source(self) -> Any:
        return getattr(self.ctx, "data_source", None)

    def publish(self, channel: str, event_type: str, /, **data: Any) -> None:
        """位置参数仅限 channel/event_type；其余关键字全部进事件 data
        （数据键允许叫 channel，见 analysis_started 事件）。"""
        self.hub.publish(channel, Event(type=event_type, data=data))

    def status(self, text: str) -> None:
        """Broadcast a status-bar message to every UI."""
        self.publish("ui", "status", text=text)
