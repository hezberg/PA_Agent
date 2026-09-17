"""Market data service — refresh loop, frame broadcast, bar-close wait, keep-analysis.

Server-side port of the flow control that used to live in MainWindow's
refresh/frame handlers, driven by services/analysis_flow helpers.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pa_agent.data.bar_close_wait import current_forming_ts, reference_now_ms
from pa_agent.server.event_hub import Event
from pa_agent.data.snapshot import INDICATOR_WARMUP_BARS
from pa_agent.services import analysis_flow as flow
from pa_agent.services import data_source_service as dss

logger = logging.getLogger(__name__)


def now_ms(state: Any) -> int:
    """Broker/server time when available (MT5), else local."""
    return reference_now_ms(data_source=state.data_source())


def current_symbol(state: Any) -> str:
    settings = state.settings()
    return str(getattr(getattr(settings, "general", None), "last_symbol", "") or "").strip()


def current_timeframe(state: Any) -> str:
    settings = state.settings()
    return str(getattr(getattr(settings, "general", None), "last_timeframe", "1d") or "1d")


def bars_sufficient(state: Any, bars: list[Any], bar_count: int) -> bool:
    return flow.bars_sufficient_for_analysis(
        bars,
        bar_count,
        timeframe=current_timeframe(state),
        symbol=current_symbol(state),
        now_ms=now_ms(state),
    )


def cached_bars_for_analysis(state: Any, bar_count: int) -> list[Any] | None:
    """Newest-first bars from the latest refresh tick (same source as the chart)."""
    fresh = state.last_frame_bars
    if not fresh or not bars_sufficient(state, fresh, bar_count):
        return None
    need = bar_count + INDICATOR_WARMUP_BARS + 5
    return list(fresh[:need]) if len(fresh) >= need else list(fresh)


# ── Refresh loop lifecycle ────────────────────────────────────────────────────

def publish_fetch_progress(state: Any, stage: str, text: str) -> None:
    """获取数据进度文案：状态栏 + SSE ``fetch_progress`` 事件。

    stage: probing（连通性检测）/ fetching（拉取中）/ retrying（重试）/
           done（首帧已到）/ error（失败，刷新未启动）。
    """
    state.status(text)
    state.publish("ui", "fetch_progress", stage=stage, text=text)


def on_loop_status(state: Any, text: str) -> None:
    """RefreshLoop 状态文案：进状态栏；首帧未到时同步为进度文案。"""
    if not text:
        return
    state.status(text)
    if state.fetch_pending:
        state.publish("ui", "fetch_progress", stage="retrying", text=text)


def start_refresh_loop(state: Any) -> bool:
    """Start the RefreshLoop when the data source is connected. Returns success."""
    from pa_agent.data.refresh_loop import RefreshLoop
    from pa_agent.util.threading import CancelToken

    data_source = state.data_source()
    if data_source is None:
        logger.debug("RefreshLoop not started: data_source not available")
        return False
    if not getattr(data_source, "_connected", False):
        publish_fetch_progress(state, "error", "数据源未连接，请检查网络后重启程序")
        return False

    settings = state.settings()
    interval_ms = dss.refresh_interval_ms(settings, state.active_data_source_kind)
    n_bars = dss.analysis_bar_count(settings)

    state.refresh_cancel_token = CancelToken()
    loop = RefreshLoop(
        data_source=data_source,
        n_bars=n_bars,
        interval_ms=interval_ms,
        cancel_token=state.refresh_cancel_token,
    )
    loop.frame_ready.connect(lambda bars: on_frame_ready(state, bars))
    loop.status_changed.connect(lambda text: on_loop_status(state, text))
    state.refresh_loop = loop

    state.fetch_pending = True
    publish_fetch_progress(
        state,
        "fetching",
        f"正在获取 {current_symbol(state)} {current_timeframe(state)} K线数据…",
    )
    loop.start()
    logger.info(
        "RefreshLoop started for %s %s",
        getattr(data_source, "_symbol", "?"),
        getattr(data_source, "_timeframe", "?"),
    )
    return True


def stop_refresh_loop(state: Any, join_ms: int = 250) -> None:
    loop = state.refresh_loop
    state.fetch_pending = False
    if loop is None:
        return
    token = state.refresh_cancel_token
    if token is not None:
        token.set()
    dss.close_live_socket(state.data_source())
    if loop.is_alive():
        loop.join(max(0.0, join_ms / 1000.0))
        if loop.is_alive():
            logger.warning("RefreshLoop did not stop within %d ms", join_ms)
    state.refresh_loop = None
    state.refresh_cancel_token = None


def restart_refresh_loop(state: Any) -> None:
    stop_refresh_loop(state)
    state.last_frame_bars = None
    state.chart_refresh_paused = False
    start_refresh_loop(state)


# ── Frame handling ────────────────────────────────────────────────────────────

def on_frame_ready(state: Any, bars: Any) -> None:
    """RefreshLoop tick: cache bars, broadcast chart frame, run wait/keep checks."""
    if not bars:
        return
    state.last_frame_bars = list(bars)
    state.last_refresh_ts = time.monotonic()

    # 获取数据首帧到达 → 进度收口（K线数量 + 刷新间隔）。
    if state.fetch_pending:
        state.fetch_pending = False
        closed = sum(1 for b in bars if getattr(b, "closed", True))
        interval_s = dss.refresh_interval_ms(
            state.settings(), state.active_data_source_kind
        ) / 1000
        publish_fetch_progress(
            state,
            "done",
            f"已获取 {closed} 根K线 · {current_symbol(state)} "
            f"{current_timeframe(state)}，持续刷新中（每 {interval_s:g} 秒）",
        )

    from pa_agent.server.serialize import bars_to_payload, frame_to_dict
    from pa_agent.services.data_source_service import build_frame_from_bars

    payload = bars_to_payload(bars)
    state.hub.publish("frames", Event(type="bars", data=payload))

    price = flow.live_price_info(bars)
    if price:
        state.hub.publish("frames", Event(type="price", data=price))

    if not state.chart_refresh_paused:
        settings = state.settings()
        frame = build_frame_from_bars(
            bars,
            bar_count=None,
            symbol=current_symbol(state),
            timeframe=current_timeframe(state),
            now_ms=now_ms(state),
            include_forming=True,
            settings=settings,
        )
        if frame is not None:
            state.hub.publish(
                "frames", Event(type="frame", data=frame_to_dict(frame))
            )

    # Deferred analysis armed on bar close
    wait = state.bar_close_wait
    if wait is not None and wait.armed:
        fired = wait.pop_if_closed(bars, now_ms=now_ms(state))
        if fired is not None:
            symbol, timeframe, bar_count, force_incremental = fired
            submit_hint = "提交增量分析" if force_incremental else "提交分析"
            state.status(f"最新K线已收盘，正在{submit_hint}…")
            from pa_agent.server.analysis_service import start_analysis

            start_analysis(
                state,
                symbol=symbol,
                timeframe=timeframe,
                bar_count=bar_count,
                force_incremental=force_incremental,
                snapshot_bars=bars,
            )

    # Keep-analysis: auto-submit on new bar close
    if state.keep_analysis_enabled:
        _check_keep_analysis(state, bars)

    # Auto incremental armed by symbol switch
    if state.auto_incremental_pending:
        bar_count = dss.analysis_bar_count(state.settings())
        if bars_sufficient(state, bars, bar_count):
            state.auto_incremental_pending = False
            from pa_agent.server.analysis_service import start_analysis

            start_analysis(
                state,
                symbol=current_symbol(state),
                timeframe=current_timeframe(state),
                bar_count=bar_count,
                force_incremental=False,
                snapshot_bars=bars,
            )


def _check_keep_analysis(state: Any, bars: Any) -> None:
    if state.analysis_in_progress or (
        state.bar_close_wait is not None and state.bar_close_wait.armed
    ):
        logger.debug("持续跟踪分析：跳过（分析进行中/等待收盘）")
        return
    if state.demo_mode:
        return
    tracker = state.keep_analysis_tracker
    if tracker is None:
        return
    result = tracker.check(
        bars,
        timeframe=current_timeframe(state),
        symbol=current_symbol(state),
        now_ms=now_ms(state),
    )
    if result == "armed_first":
        # 只初始化哨兵：下一根K线收盘时走 new_bar 分支自动分析。
        # 不武装 bar_close_wait——那是「手动提交等待收盘」的门禁，复用它会把
        # 手动「开始分析」按钮扣住直到收盘（非交易时段长达数小时）。
        state.status("持续跟踪分析已开启：下一根K线收盘后自动分析，手动分析不受影响")
    elif result == "new_bar":
        bar_count = dss.analysis_bar_count(state.settings())
        if bars_sufficient(state, bars, bar_count):
            from pa_agent.server.analysis_service import start_analysis

            start_analysis(
                state,
                symbol=current_symbol(state),
                timeframe=current_timeframe(state),
                bar_count=bar_count,
                force_incremental=False,
                snapshot_bars=bars,
            )


def refresh_keep_analysis_sentinel(state: Any) -> None:
    """Sync sentinel after analysis completes (submit-time snapshot wins)."""
    tracker = state.keep_analysis_tracker
    if tracker is None:
        return
    tracker.refresh_sentinel(
        state.last_frame_bars or [],
        timeframe=current_timeframe(state),
        symbol=current_symbol(state),
        now_ms=now_ms(state),
    )


def publish_ui_state(state: Any) -> dict[str, Any]:
    """Current submission-state snapshot for the control bar."""
    from pa_agent.config.settings import provider_api_key_configured

    settings = state.settings()
    wait = state.bar_close_wait
    seconds = wait.seconds_remaining(now_ms=now_ms(state)) if wait else None
    reason = flow.submit_block_reason(
        api_key_configured=provider_api_key_configured(settings),
        demo_mode=state.demo_mode,
        analysis_in_progress=state.analysis_in_progress,
        pending_submit_after_close=bool(wait is not None and wait.armed),
        switching=state.switching,
    )
    return {
        "analysis_in_progress": state.analysis_in_progress,
        "demo_mode": state.demo_mode,
        "submit_block_reason": reason,
        "incremental_available": state.incremental_available,
        "chart_refresh_paused": state.chart_refresh_paused,
        "wait_close": {
            "armed": bool(wait is not None and wait.armed),
            "seconds_remaining": seconds,
            "force_incremental": bool(getattr(wait, "force_incremental", False)) if wait else False,
        },
        "keep_analysis": state.keep_analysis_enabled,
        "last_refresh_ts": state.last_refresh_ts,
    }
