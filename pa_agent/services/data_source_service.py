"""Data-source lifecycle service — switching, subscription, frame building.

Extracted from the historical MainWindow so the WebUI server can drive the
same behaviour without Qt widgets.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def chart_bar_count(settings: Any) -> int:
    """K 线图显示根数（分析仍用 analysis_bar_count，互不影响）。"""
    try:
        return int(getattr(settings.general, "chart_bar_count", 300))
    except Exception:  # noqa: BLE001
        return 300


def analysis_bar_count(settings: Any) -> int:
    """Closed-bar count for AI analysis and chart fetch (from settings)."""
    if settings is None:
        return 100
    return int(getattr(settings.general, "analysis_bar_count", 100))


def refresh_interval_ms(settings: Any, kind: str) -> int:
    """Refresh-loop polling interval; A-share HTTP sources are throttled."""
    interval_ms = 1000
    if settings is not None:
        interval_ms = int(getattr(settings.general, "refresh_interval_ms", 1000))
    if kind in ("akshare", "eastmoney", "tushare") and interval_ms < 2500:
        interval_ms = 2500
    if kind == "easytdx" and interval_ms < 10_000:
        # 通达信免费公共服务器：轮询下限 10 秒（决策 2026-09-05）。
        interval_ms = 10_000
    return interval_ms


def build_frame_from_bars(
    bars_raw: Any,
    *,
    bar_count: int | None,
    symbol: str,
    timeframe: str,
    now_ms: int,
    include_forming: bool = False,
    settings: Any = None,
) -> Any:
    """Build a chart/analysis KlineFrame.

    - include_forming=True: forming + N closed (live chart view)
    - include_forming=False: N closed only (chart + AI; K1 = newest closed bar)
    """
    from pa_agent.data.snapshot import build_display_frame, build_live_frame

    n = bar_count if bar_count is not None else analysis_bar_count(settings)
    if not bars_raw:
        return None
    if include_forming:
        return build_live_frame(bars_raw, n, symbol, timeframe, now_ms=now_ms)
    return build_display_frame(bars_raw, n, symbol, timeframe, now_ms=now_ms)


def symbol_placeholder(kind: str) -> str:
    """Input placeholder text per data source (mirrors the old combo tooltip)."""
    if kind == "tradingview":
        return "A股 6 位 / 港股 1810 / 名称 小米集团；交易所可自动；或 XAUUSD+OANDA"
    if kind == "easytdx":
        return "A股/ETF 代码（600519、510300）或名称（贵州茅台）；港股 00700（恒指 HSI）；指数 000300（无 4h 周期）"
    if kind == "eastmoney_futures":
        return "选择左侧品种后在此选合约, 或直接输入如 AO2509"
    if kind in ("akshare", "eastmoney", "tushare"):
        return "A股 6 位代码，如 600519；指数 000300 或 sh000300"
    return "输入 MT5 品种名，如 XAUUSDm…"


def symbol_alert_message(kind: str, symbol: str, data_source: Any) -> str | None:
    """Hint text when the symbol is unavailable (MT5) or looks wrong (TV)."""
    if not symbol:
        return None
    if kind == "tradingview":
        if symbol.lower().endswith("m") and len(symbol) > 2:
            return (
                "TradingView 提示：品种名勿用 MT5 的 m 后缀；"
                "请用交易所 OANDA + 品种 XAUUSD"
            )
        return None
    if kind != "mt5":
        return None
    checker = getattr(data_source, "is_symbol_available", None)
    if not callable(checker):
        return None
    if checker(symbol):
        return None
    return (
        "未在 MT5 获取到该品种，请检查当前输入是否与 MT5「市场报价」中的名称完全一致"
        "（含后缀，如 XAUUSDm）。"
    )


def normalize_symbol_for_kind(kind: str, symbol: str) -> str:
    """Reset symbol to the kind's gold default when switching data source."""
    from pa_agent.data.market_defaults import normalize_gold_symbol_for_kind

    return normalize_gold_symbol_for_kind(kind, symbol)


def apply_tv_exchange(data_source: Any, exchange: str) -> None:
    from pa_agent.data.tradingview import TradingViewSource

    if isinstance(data_source, TradingViewSource):
        data_source.set_exchange(exchange)


def normalize_tv_exchange(raw: Any) -> str:
    """Normalize a TV exchange value (combo data or display text) to upper code."""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text or text in ("（自动）", "(auto)"):
        return ""
    return text.upper()


def coerce_timeframe_for_kind(kind: str, timeframe: str) -> str:
    """Fall back to a supported timeframe when switching sources (e.g. 4h → easytdx)."""
    if kind == "easytdx":
        supported = ("1m", "5m", "15m", "30m", "1h", "1d", "1w")
        if timeframe not in supported:
            from pa_agent.data.market_defaults import A_SHARE_DEFAULT_TIMEFRAME

            return A_SHARE_DEFAULT_TIMEFRAME
    return timeframe


def status_message_after_symbol_switch(kind: str, symbol: str, timeframe: str, exchange: str = "") -> str:
    """Status bar text after symbol/tf change (TV shows resolved feed)."""
    if kind == "tradingview":
        ex_show = exchange or "自动"
        return f"TradingView 正在拉取 {ex_show}:{symbol.strip()} {timeframe}…"
    return f"已切换至 {symbol} {timeframe}"


def switch_data_source(ctx: Any, kind: str, *, symbol: str, timeframe: str, exchange: str = "") -> Any:
    """Replace ``ctx.data_source`` with a freshly connected source for *kind*.

    The caller is responsible for stopping/starting its refresh loop around
    this call.  Returns the new source.
    """
    from pa_agent.data.factory import create_data_source

    new_source = create_data_source(kind)
    apply_tv_exchange(new_source, exchange)
    new_source.connect()
    new_source.subscribe(symbol, timeframe)
    ctx.data_source = new_source

    settings = getattr(ctx, "settings", None)
    if settings is not None:
        settings.general.last_data_source = kind  # type: ignore[assignment]
        settings.general.last_symbol = symbol
        settings.general.last_timeframe = timeframe
        try:
            from pa_agent.config.settings import save_settings

            save_settings(settings)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to persist data source: %s", exc)
    return new_source


def disconnect_data_source(data_source: Any) -> None:
    if data_source is None:
        return
    try:
        data_source.unsubscribe()
    except Exception as exc:  # noqa: BLE001
        logger.debug("unsubscribe failed: %s", exc)
    try:
        data_source.disconnect()
    except Exception as exc:  # noqa: BLE001
        logger.debug("disconnect failed: %s", exc)


def close_live_socket(data_source: Any) -> None:
    """Actively close a live WebSocket so a blocked refresh fetch exits early."""
    if data_source is None:
        return
    close_ws = getattr(data_source, "_close_tv_socket", None)
    if callable(close_ws):
        try:
            close_ws()
        except Exception:  # noqa: BLE001
            pass


def ensure_tradingview_connectivity() -> tuple[bool, str]:
    """On-demand TV connectivity probe (called before fetching data)."""
    from pa_agent.data.tradingview_connectivity import check_tradingview_connectivity

    ok, detail = check_tradingview_connectivity()
    if ok:
        # Brief pause to let the probe's WebSocket fully disconnect before
        # the refresh loop opens its own connection (avoids TV rate-limiting).
        time.sleep(1.5)
    return ok, detail
