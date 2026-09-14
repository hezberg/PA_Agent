"""Market data routes: meta, klines, data-source switch, frame stream."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pa_agent.server.routes.common import get_state, sse_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["market"])


class DataSourceSwitch(BaseModel):
    kind: str
    symbol: str | None = None
    timeframe: str | None = None
    exchange: str | None = None


class SubscribeBody(BaseModel):
    symbol: str
    timeframe: str
    #: False = 仅订阅，不武装「自动增量分析」（自选清单浏览场景）
    arm_auto_incremental: bool = True


@router.get("/meta")
def get_meta(request: Request) -> dict[str, Any]:
    """Static + dynamic metadata for the control bar."""
    from pa_agent.config.settings import provider_api_key_configured
    from pa_agent.data.factory import (
        DATA_SOURCE_CHOICES,
        data_source_label,
        default_symbol_for_kind,
    )
    from pa_agent.data.tradingview import TV_EXCHANGE_PRESETS
    from pa_agent.server import market_service as market
    from pa_agent.services import data_source_service as dss

    state = get_state(request)
    settings = state.settings()
    general = getattr(settings, "general", None)
    kind = state.active_data_source_kind
    symbol = str(getattr(general, "last_symbol", "") or "")
    timeframe = str(getattr(general, "last_timeframe", "1d") or "1d")

    data_source = state.data_source()
    symbols: list[str] = []
    timeframes: list[str] = []
    if data_source is not None and getattr(data_source, "_connected", False):
        try:
            symbols = list(data_source.list_symbols())
        except Exception:  # noqa: BLE001
            symbols = []
        try:
            supported = list(data_source.supported_timeframes())
        except Exception:  # noqa: BLE001
            supported = []
        preferred = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
        timeframes = [tf for tf in preferred if tf in supported] or supported[:12]

    futures_varieties: list[str] = []
    if kind == "eastmoney_futures" and data_source is not None:
        try:
            futures_varieties = list(data_source.list_symbols())
        except Exception:  # noqa: BLE001
            futures_varieties = []

    return {
        "data_sources": [
            {"kind": k, "label": label} for k, label in DATA_SOURCE_CHOICES
        ],
        "active_kind": kind,
        "active_label": data_source_label(kind),
        "symbol": symbol,
        "timeframe": timeframe,
        "exchange": str(getattr(general, "last_tradingview_exchange", "") or ""),
        "tv_exchanges": list(TV_EXCHANGE_PRESETS),
        "default_symbol": default_symbol_for_kind(kind),
        "symbol_placeholder": dss.symbol_placeholder(kind),
        "symbol_alert": dss.symbol_alert_message(kind, symbol.strip(), data_source),
        "symbols": symbols[:120],
        "timeframes": timeframes,
        "futures_varieties": futures_varieties,
        "source_connected": bool(
            data_source is not None and getattr(data_source, "_connected", False)
        ),
        "refresh_running": state.refresh_loop is not None,
        "analysis_bar_count": int(getattr(general, "analysis_bar_count", 100)),
        "ths_enabled": bool(getattr(settings, "ths", None) is not None and settings.ths.enabled),
        "ai_mode_label": _ai_mode_label(settings),
        "api_key_configured": provider_api_key_configured(settings),
    }


def _ai_mode_label(settings: Any) -> str:
    from pa_agent.services.settings_service import ai_mode_label

    return ai_mode_label(settings)


@router.get("/stream/frames")
def stream_frames(request: Request) -> StreamingResponse:
    """SSE: K-line bars / chart frames / live price / status."""
    state = get_state(request)
    sub_id, queue = state.hub.subscribe({"frames", "ui"})
    return StreamingResponse(
        sse_stream(queue, sub_id, state), media_type="text/event-stream"
    )


@router.post("/fetch")
def fetch_data(request: Request) -> dict[str, Any]:
    """Start (or restart) continuous refresh; probes TV connectivity on demand."""
    from pa_agent.server import market_service as market
    from pa_agent.services import data_source_service as dss

    state = get_state(request)
    data_source = state.data_source()
    if data_source is None or not getattr(data_source, "_connected", False):
        market.publish_fetch_progress(state, "error", "数据源未连接，请先切换数据来源")
        return {"ok": False, "error": "数据源未连接"}

    if state.active_data_source_kind == "tradingview":
        market.publish_fetch_progress(state, "probing", "正在检测 TradingView 连通性…")
        ok, detail = dss.ensure_tradingview_connectivity()
        if not ok:
            state.publish(
                "ui",
                "tv_blocked",
                detail=detail or "",
            )
            market.publish_fetch_progress(
                state, "error", f"获取数据失败：{detail or 'TradingView 连接失败'}"
            )
            return {"ok": False, "error": detail or "TradingView 连接失败"}

    market.stop_refresh_loop(state)
    tracker = state.keep_analysis_tracker
    if tracker is not None:
        tracker.last_closed_ts = None
    state.chart_refresh_paused = False
    ok = market.start_refresh_loop(state)
    return {"ok": ok}


@router.post("/refresh/stop")
def stop_refresh(request: Request) -> dict[str, Any]:
    from pa_agent.server import market_service as market

    market.stop_refresh_loop(get_state(request))
    return {"ok": True}


@router.post("/chart/pause")
def pause_chart(request: Request) -> dict[str, Any]:
    state = get_state(request)
    state.chart_refresh_paused = True
    state.status("图表已冻结")
    return {"ok": True, "paused": True}


@router.post("/chart/resume")
def resume_chart(request: Request) -> dict[str, Any]:
    from pa_agent.server import market_service as market

    state = get_state(request)
    if not state.chart_refresh_paused:
        return {"ok": True, "paused": False}
    tracker = state.keep_analysis_tracker
    if tracker is not None:
        tracker.last_closed_ts = None
    state.chart_refresh_paused = False
    state.status("图表已恢复实时更新")
    market.publish_ui_state(state)
    return {"ok": True, "paused": False}


@router.post("/data-source")
def switch_data_source(request: Request, body: DataSourceSwitch) -> dict[str, Any]:
    from pa_agent.config.settings import save_settings
    from pa_agent.data.factory import normalize_data_source_kind
    from pa_agent.server import market_service as market
    from pa_agent.services import data_source_service as dss

    state = get_state(request)
    kind = normalize_data_source_kind(body.kind)
    if state.switching:
        return {"ok": False, "error": "正在切换中"}
    if state.demo_mode:
        return {"ok": False, "error": "演示模式中不可切换数据源"}

    state.switching = True
    try:
        _cancel_running_analysis(state)
        market.stop_refresh_loop(state)
        dss.disconnect_data_source(state.data_source())
        state.last_frame_bars = None
        state.active_data_source_kind = kind

        settings = state.settings()
        general = getattr(settings, "general", None)
        symbol = (body.symbol or getattr(general, "last_symbol", "") or "").strip()
        timeframe = body.timeframe or getattr(general, "last_timeframe", "1d")
        timeframe = dss.coerce_timeframe_for_kind(kind, timeframe)
        exchange = (body.exchange or getattr(general, "last_tradingview_exchange", "") or "")
        if kind == "tradingview":
            symbol = dss.normalize_symbol_for_kind(kind, symbol)
        try:
            dss.switch_data_source(
                state.ctx, kind, symbol=symbol, timeframe=timeframe, exchange=exchange
            )
        except Exception as exc:  # noqa: BLE001
            market.publish_fetch_progress(state, "error", f"切换数据来源失败：{exc}")
            return {"ok": False, "error": str(exc)}

        state.chart_refresh_paused = False
        state.chat_session = None
        state.chat_cancel_token = None
        if general is not None:
            general.last_data_source = kind  # type: ignore[assignment]
            general.last_symbol = symbol
            general.last_timeframe = timeframe
        try:
            save_settings(settings)
        except Exception:  # noqa: BLE001
            pass

        label = _label_for(kind)
        state.status(
            f"已切换至 {label} · {symbol} {timeframe}"
            if kind != "tradingview"
            else f"已切换至 {label} {exchange or '自动'} · {symbol} {timeframe}"
        )
        market.start_refresh_loop(state)
        return {"ok": True, "kind": kind, "symbol": symbol, "timeframe": timeframe}
    finally:
        state.switching = False


def _cancel_running_analysis(state: Any) -> None:
    task = state.current_task
    if task is not None and task.cancel_token is not None:
        task.cancel_token.set()
    state.analysis_in_progress = False
    state.current_task = None


def _label_for(kind: str) -> str:
    from pa_agent.data.factory import data_source_label

    return data_source_label(kind)


@router.post("/subscribe")
def subscribe(request: Request, body: SubscribeBody) -> dict[str, Any]:
    """Change symbol/timeframe (mirrors _on_symbol_or_tf_changed)."""
    return change_symbol_timeframe(
        get_state(request), body.symbol, body.timeframe,
        arm_auto_incremental=body.arm_auto_incremental,
    )


def change_symbol_timeframe(
    state: Any, new_symbol: str, new_tf: str, *, arm_auto_incremental: bool = True
) -> dict[str, Any]:
    from pa_agent.data.market_defaults import is_partial_tv_symbol_input
    from pa_agent.server import market_service as market
    from pa_agent.services import data_source_service as dss
    from pa_agent.services.settings_service import persist_settings

    if state.switching:
        return {"ok": False, "error": "正在切换中"}
    if state.demo_mode:
        return {"ok": False, "error": "演示模式中不可切换品种"}

    state.bar_close_wait = None
    state.switching = True
    state.auto_incremental_pending = False
    tracker = state.keep_analysis_tracker
    if tracker is not None:
        tracker.last_closed_ts = None
    try:
        had_analysis = state.analysis_in_progress
        task = state.current_task
        if task is not None and task.cancel_token is not None:
            task.cancel_token.set()
        if had_analysis:
            pending_writer = getattr(state.ctx, "pending_writer", None)
            if pending_writer is not None:
                try:
                    pending_writer.save_partial(None, reason="user_switched")
                except Exception:  # noqa: BLE001
                    pass
            state.analysis_in_progress = False
            state.current_task = None

        market.stop_refresh_loop(state)

        kind = state.active_data_source_kind
        if kind == "tradingview" and is_partial_tv_symbol_input(new_symbol.strip()):
            hint = (
                "请输入至少 2 个字的股票名称"
                if _is_tv_name_input(new_symbol)
                else "请输入完整代码（A 股 6 位如 600519，港股如 1810）"
            )
            market.publish_fetch_progress(
                state, "error", f"{hint} — 当前：{new_symbol.strip()}"
            )
            return {"ok": False, "error": hint}

        if kind == "easytdx":
            resolved = _resolve_easytdx_symbol(new_symbol)
            if resolved.get("candidates") is not None:
                # 多候选/无候选：不动当前订阅，把候选交回前端展示。
                market.publish_fetch_progress(
                    state, "error", str(resolved.get("error", ""))
                )
                return {"ok": False, **resolved}
            new_symbol = resolved["symbol"]

        data_source = state.data_source()
        state.last_frame_bars = None
        state.incremental_available = False
        if data_source is not None:
            dss.apply_tv_exchange(data_source, _current_exchange(state))
            try:
                data_source.unsubscribe()
            except Exception as exc:  # noqa: BLE001
                logger.warning("unsubscribe failed: %s", exc)
            try:
                data_source.subscribe(new_symbol, new_tf)
            except Exception as exc:  # noqa: BLE001
                market.publish_fetch_progress(state, "error", f"订阅失败：{exc}")
                return {"ok": False, "error": str(exc)}

        state.chat_session = None
        state.chat_cancel_token = None
        ledger = getattr(state.ctx, "ledger", None)
        if ledger is not None:
            try:
                ledger.reset()
            except Exception:  # noqa: BLE001
                pass

        state.chart_refresh_paused = False
        msg = dss.status_message_after_symbol_switch(
            kind, new_symbol, new_tf, _current_exchange(state)
        )
        if had_analysis:
            msg = f"已切换至 {new_symbol} {new_tf}，进行中的分析已取消 — {msg}"
        state.status(msg)

        settings = state.settings()
        general = getattr(settings, "general", None)
        if general is not None:
            general.last_symbol = new_symbol
            general.last_timeframe = new_tf
            persist_settings(settings)

        # Auto-incremental: check for a prior record, flag the button label.
        if arm_auto_incremental:
            _check_auto_incremental(state, new_symbol.strip(), new_tf)

        data_source = state.data_source()
        if data_source is not None and getattr(data_source, "_connected", False):
            market.start_refresh_loop(state)
        return {"ok": True}
    finally:
        state.switching = False


def _is_tv_name_input(symbol: str) -> bool:
    from pa_agent.data.tv_symbol_lookup import is_tv_name_input

    return is_tv_name_input(symbol)


def _resolve_easytdx_symbol(symbol: str) -> dict[str, Any]:
    """easytdx 名称反查：唯一候选 → 直接替换为代码；多候选/无候选 → 交回前端。

    Returns ``{"symbol": code}`` or ``{"error": msg, "candidates": [...]}``
    （``candidates`` 键存在表示未消解，调用方应中断切换）。
    """
    from pa_agent.data.easytdx_source import resolve_route

    try:
        resolve_route(symbol)
        return {"symbol": symbol}
    except ValueError:
        pass
    from pa_agent.data.symbol_search import search_symbols

    try:
        candidates = search_symbols(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("symbol name lookup failed: %s", exc)
        return {
            "error": f"名称反查失败（{exc}），请直接输入代码",
            "candidates": [],
        }
    if len(candidates) == 1:
        return {"symbol": candidates[0]["code"]}
    if len(candidates) > 1:
        return {
            "error": f"「{symbol.strip()}」匹配到 {len(candidates)} 个候选，请选择",
            "candidates": candidates,
        }
    return {
        "error": f"未找到「{symbol.strip()}」对应的证券，请输入 6 位代码 / 港股 5 位代码 / 名称关键字",
        "candidates": [],
    }


@router.get("/symbol/search")
def search_symbol(request: Request, q: str = "", limit: int = 12) -> dict[str, Any]:
    """Name/code fuzzy search for the easytdx source (returns candidates)."""
    from pa_agent.data.symbol_search import search_symbols

    try:
        candidates = search_symbols(q, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "candidates": []}
    return {"ok": True, "candidates": candidates}


def _current_exchange(state: Any) -> str:
    settings = state.settings()
    return str(
        getattr(getattr(settings, "general", None), "last_tradingview_exchange", "") or ""
    )


def _check_auto_incremental(state: Any, symbol: str, timeframe: str) -> None:
    from pa_agent.records.analysis_history import find_latest_successful_record

    state.auto_incremental_pending = False
    settings = state.settings()
    threshold = int(
        getattr(getattr(settings, "general", None), "incremental_max_new_bars", 10)
    )
    if threshold <= 0:
        return
    try:
        previous = find_latest_successful_record(symbol=symbol, timeframe=timeframe)
        if previous is None:
            return
        state.auto_incremental_pending = True
        state.incremental_available = True
        state.status(f"找到历史记录，下次分析将自动增量（{symbol} {timeframe}）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto-incremental check failed: %s", exc)


@router.post("/exchange")
def set_exchange(request: Request, body: dict) -> dict[str, Any]:
    """TradingView exchange change (re-subscribes immediately)."""
    from pa_agent.services import data_source_service as dss
    from pa_agent.services.settings_service import persist_settings

    state = get_state(request)
    if state.switching or state.demo_mode:
        return {"ok": False, "error": "状态不允许"}
    if state.active_data_source_kind != "tradingview":
        return {"ok": False, "error": "仅 TradingView 支持交易所"}
    exchange = dss.normalize_tv_exchange(body.get("exchange", ""))
    settings = state.settings()
    general = getattr(settings, "general", None)
    if general is not None:
        general.last_tradingview_exchange = exchange
        persist_settings(settings)
    data_source = state.data_source()
    dss.apply_tv_exchange(data_source, exchange)
    symbol = str(getattr(getattr(settings, "general", None), "last_symbol", "") or "").strip()
    timeframe = str(getattr(getattr(settings, "general", None), "last_timeframe", "1d"))
    if data_source is not None and getattr(data_source, "_connected", False):
        from pa_agent.server import market_service as market

        try:
            data_source.unsubscribe()
            data_source.subscribe(symbol, timeframe)
            state.status(f"TradingView 正在拉取 {exchange or '自动'}:{symbol} {timeframe}…")
            market.stop_refresh_loop(state)
            market.start_refresh_loop(state)
        except Exception as exc:  # noqa: BLE001
            market.publish_fetch_progress(state, "error", f"订阅失败：{exc}")
            return {"ok": False, "error": str(exc)}
    return {"ok": True}


@router.get("/klines")
def get_klines(request: Request, bars: int = 0) -> dict[str, Any]:
    """One-shot snapshot fetch for the current subscription (chart bootstrap)."""
    from pa_agent.data.snapshot import INDICATOR_WARMUP_BARS
    from pa_agent.server import market_service as market
    from pa_agent.server.serialize import bars_to_payload, frame_to_dict
    from pa_agent.services import data_source_service as dss

    state = get_state(request)
    data_source = state.data_source()
    if data_source is None or not getattr(data_source, "_connected", False):
        return {"ok": False, "error": "数据源未连接"}
    bar_count = bars or dss.analysis_bar_count(state.settings())
    try:
        raw = data_source.latest_snapshot(bar_count + INDICATOR_WARMUP_BARS + 5)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not raw:
        return {"ok": False, "error": "未获取到数据"}
    state.last_frame_bars = list(raw)
    import time as _time

    state.last_refresh_ts = _time.monotonic()
    frame = dss.build_frame_from_bars(
        raw,
        bar_count=None,
        symbol=market.current_symbol(state),
        timeframe=market.current_timeframe(state),
        now_ms=market.now_ms(state),
        include_forming=True,
        settings=state.settings(),
    )
    return {
        "ok": True,
        "bars": bars_to_payload(raw)["bars"],
        "frame": frame_to_dict(frame) if frame is not None else None,
    }
