"""Analysis routes: submit / cancel / SSE stream / UI state."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pa_agent.server.routes.common import get_state, sse_stream
from pa_agent.server.routes.market import change_symbol_timeframe  # re-export

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class SubmitBody(BaseModel):
    force_incremental: bool | None = None
    wait_close: bool = False


@router.post("")
def submit_analysis(request: Request, body: SubmitBody) -> dict[str, Any]:
    from pa_agent.server import analysis_service

    return analysis_service.submit(
        get_state(request),
        force_incremental=body.force_incremental,
        wait_close=body.wait_close,
    )


@router.post("/cancel")
def cancel_analysis(request: Request) -> dict[str, Any]:
    from pa_agent.server import analysis_service

    return analysis_service.cancel(get_state(request))


@router.get("/stream/{task_id}")
def stream_analysis(task_id: str, request: Request) -> StreamingResponse:
    state = get_state(request)
    sub_id, queue = state.hub.subscribe({f"analysis:{task_id}", "ui"})
    return StreamingResponse(
        sse_stream(queue, sub_id, state), media_type="text/event-stream"
    )


@router.get("/state")
def ui_state(request: Request) -> dict[str, Any]:
    from pa_agent.server import market_service as market

    return market.publish_ui_state(get_state(request))


@router.post("/keep-analysis")
def keep_analysis(request: Request, body: dict) -> dict[str, Any]:
    """Toggle 持续跟踪分析 (auto analysis on each new bar close)."""
    from pa_agent.services.analysis_flow import KeepAnalysisTracker
    from pa_agent.services.settings_service import persist_settings

    state = get_state(request)
    enabled = bool(body.get("enabled"))
    state.keep_analysis_enabled = enabled
    if enabled:
        if state.keep_analysis_tracker is None:
            state.keep_analysis_tracker = KeepAnalysisTracker()
        state.keep_analysis_tracker.last_closed_ts = None
        state.chart_refresh_paused = False
        # Auto-start the refresh loop so ticks arrive.
        if state.refresh_loop is None:
            from pa_agent.server import market_service as market

            market.start_refresh_loop(state)
        state.status("持续跟踪分析已开启：等待K线收盘后将自动开始分析")
    else:
        state.bar_close_wait = None
        state.status("持续跟踪分析已关闭")
    settings = state.settings()
    if settings is not None:
        settings.general.keep_analysis = enabled
        persist_settings(settings)
    market_service_publish(state)
    return {"ok": True, "enabled": enabled}


def market_service_publish(state: Any) -> None:
    from pa_agent.server import market_service as market

    market.publish_ui_state(state)
