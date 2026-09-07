"""Event bus for inter-component communication (Qt-free signal hub)."""
from __future__ import annotations

from pa_agent.data.base import KlineFrame
from pa_agent.records.schema import AlarmPayload
from pa_agent.util.signals import Signal


class EventBus:
    """Central signal hub shared across frontends and orchestrators.

    Signals (Qt-free; use ``.connect(fn)``)
    -------
    data_frame  : emitted by RefreshLoop with the latest KlineFrame
    status      : emitted with a human-readable status string for the status bar
    exception   : emitted when a JSON-validation alarm fires (AlarmPayload)
    token_update: emitted with a dict of token/cost update data for Tab2
    """

    def __init__(self) -> None:
        self.data_frame = Signal(object)    # KlineFrame
        self.status = Signal(str)           # status text
        self.exception = Signal(object)     # AlarmPayload
        self.token_update = Signal(dict)    # token/cost update dict

    def emit_status(self, text: str) -> None:
        """Convenience wrapper — emit a status string."""
        self.status.emit(text)

    def emit_exception(self, payload: AlarmPayload) -> None:
        """Convenience wrapper — emit an AlarmPayload."""
        self.exception.emit(payload)

    def emit_data_frame(self, frame: KlineFrame) -> None:
        """Convenience wrapper — emit a KlineFrame."""
        self.data_frame.emit(frame)

    def emit_token_update(self, data: dict) -> None:
        """Convenience wrapper — emit a token/cost update dict."""
        self.token_update.emit(data)
