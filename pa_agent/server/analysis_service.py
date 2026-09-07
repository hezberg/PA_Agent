"""Analysis task service — submit / cancel / event streaming.

Ports MainWindow's analysis submission state machine to server-side threads:
cached-bars check → background prep (frame + incremental lookup) → orchestrator
runner thread with event-bridge callbacks → record/finished broadcast →
FreeChatSession creation.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pa_agent.data.bar_close_wait import current_forming_ts
from pa_agent.services import analysis_flow as flow
from pa_agent.services import data_source_service as dss
from pa_agent.services.settings_service import persist_settings

logger = logging.getLogger(__name__)


@dataclass
class AnalysisTask:
    """One submitted analysis run."""

    id: str
    symbol: str
    timeframe: str
    bar_count: int
    force_incremental: bool
    channel: str
    cancel_token: Any = None
    thread: Any = None
    status: str = "preparing"        # preparing | running | finished | cancelled
    started_ts: float = field(default_factory=time.monotonic)


# ── Submission entry ──────────────────────────────────────────────────────────

def submit(
    state: Any,
    *,
    force_incremental: bool | None = None,
    wait_close: bool = False,
) -> dict[str, Any]:
    """Handle a UI submit request. Returns ``{"ok": bool, "task_id"/"error"}``."""
    from pa_agent.config.settings import provider_api_key_configured
    from pa_agent.server import market_service as market

    settings = state.settings()
    wait = state.bar_close_wait
    reason = flow.submit_block_reason(
        api_key_configured=provider_api_key_configured(settings),
        demo_mode=state.demo_mode,
        analysis_in_progress=state.analysis_in_progress,
        pending_submit_after_close=bool(wait is not None and wait.armed),
        switching=state.switching,
    )
    if reason:
        return {"ok": False, "error": reason}

    incremental_flag = state.incremental_available if force_incremental is None else force_incremental
    state.auto_incremental_pending = False

    # If the UI entered a symbol/tf that differs from the subscription, apply it first.
    data_source = state.data_source()
    if data_source is not None:
        wanted_symbol = market.current_symbol(state)
        wanted_tf = market.current_timeframe(state)
        if state.active_data_source_kind == "eastmoney_futures":
            from pa_agent.data.eastmoney_futures_source import normalize_futures_symbol

            wanted_norm = normalize_futures_symbol(wanted_symbol)
        else:
            wanted_norm = wanted_symbol
        cur_symbol = str(getattr(data_source, "_symbol", "") or "").strip()
        cur_tf = str(getattr(data_source, "_timeframe", "") or "").strip()
        if wanted_norm and (wanted_norm != cur_symbol or wanted_tf != cur_tf):
            from pa_agent.server.routes.market import change_symbol_timeframe

            change_symbol_timeframe(state, wanted_symbol, wanted_tf)
            return {"ok": False, "error": "已切换品种，数据到位后请再次提交"}

    bar_count = dss.analysis_bar_count(settings)
    symbol = market.current_symbol(state)
    timeframe = market.current_timeframe(state)

    if wait_close:
        armed = _arm_wait_for_bar_close(
            state, symbol, timeframe, bar_count, force_incremental=incremental_flag
        )
        if not armed:
            return {"ok": False, "error": "数据不足，请等待图表刷新后再提交"}
        return {"ok": True, "armed": True}

    task = start_analysis(
        state,
        symbol=symbol,
        timeframe=timeframe,
        bar_count=bar_count,
        force_incremental=incremental_flag,
    )
    if task is None:
        return {"ok": False, "error": "数据不足，请等待图表刷新后再提交"}
    return {"ok": True, "task_id": task.id, "channel": task.channel, "armed": False}


def _arm_wait_for_bar_close(
    state: Any,
    symbol: str,
    timeframe: str,
    bar_count: int,
    *,
    force_incremental: bool,
) -> bool:
    from pa_agent.server import market_service as market

    data_source = state.data_source()
    if data_source is None or not getattr(data_source, "_connected", False):
        state.status("数据源未连接")
        return False

    bars_raw = market.cached_bars_for_analysis(state, bar_count)
    if not bars_raw:
        state.status("数据不足，请等待图表刷新后再提交")
        return False

    now = market.now_ms(state)
    forming_ts = current_forming_ts(bars_raw, timeframe, symbol=symbol, now_ms=now)
    if forming_ts is None:
        state.status("最新K线已收盘，正在提交分析…")
        start_analysis(
            state,
            symbol=symbol,
            timeframe=timeframe,
            bar_count=bar_count,
            force_incremental=force_incremental,
            snapshot_bars=bars_raw,
        )
        return True

    state.bar_close_wait = flow.BarCloseWait(
        armed=True,
        forming_ts=forming_ts,
        force_incremental=force_incremental,
        symbol=symbol.strip(),
        timeframe=timeframe,
        bar_count=bar_count,
    )
    try:
        ts_hint = time.strftime("%H:%M:%S", time.localtime(forming_ts / 1000))
    except (OSError, OverflowError, ValueError):
        ts_hint = f"ts={forming_ts}"
    action = "提交增量分析" if force_incremental else "提交分析"
    state.status(f"等待当前K线收盘…（开盘 {ts_hint}，收盘后将自动{action}）")
    _publish_state(state)
    return True


# ── Analysis execution ────────────────────────────────────────────────────────

def start_analysis(
    state: Any,
    *,
    symbol: str,
    timeframe: str,
    bar_count: int,
    force_incremental: bool,
    snapshot_bars: Any = None,
) -> AnalysisTask | None:
    """Start the full analysis pipeline on background threads. Returns the task."""
    from pa_agent.server import market_service as market

    if snapshot_bars is None:
        snapshot_bars = market.cached_bars_for_analysis(state, bar_count)
    if snapshot_bars is None or not market.bars_sufficient(state, snapshot_bars, bar_count):
        _start_analysis_async_fetch(
            state,
            symbol=symbol,
            timeframe=timeframe,
            bar_count=bar_count,
            force_incremental=force_incremental,
        )
        return None

    task = AnalysisTask(
        id=uuid.uuid4().hex,
        symbol=symbol,
        timeframe=timeframe,
        bar_count=bar_count,
        force_incremental=force_incremental,
        channel=f"analysis:{uuid.uuid4().hex}",
    )
    state.current_task = task
    state.analysis_in_progress = True
    state.last_analysis_had_error = False
    state.status("准备分析…（构建快照）")
    state.publish("ui", "analysis_started", task_id=task.id, channel=task.channel)
    _publish_state(state)

    settings = state.settings()
    threshold = int(
        getattr(getattr(settings, "general", None), "incremental_max_new_bars", 10)
    )
    bars_snapshot = list(snapshot_bars)

    def _prep() -> None:
        try:
            prep = flow.prepare_analysis_sync(
                bars_raw=bars_snapshot,
                symbol=symbol,
                timeframe=timeframe,
                bar_count=bar_count,
                now_ms=market.now_ms(state),
                force_incremental=force_incremental,
                incremental_threshold=threshold,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analysis prep failed: %s", exc)
            state.analysis_in_progress = False
            state.current_task = None
            state.status(str(exc) or "准备分析失败")
            _publish_state(state)
            return
        try:
            _launch_after_prep(
                state,
                task,
                prep,
                snapshot_bars=bars_snapshot,
                force_incremental=force_incremental,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Analysis launch failed — unsticking state")
            state.analysis_in_progress = False
            state.current_task = None
            state.status("分析启动异常，请重试（详情见日志）")
            state.publish("ui", "alert", level="error", title="分析启动异常",
                          message="详见服务日志")
            _publish_state(state)

    threading.Thread(target=_prep, name="analysis-prep", daemon=True).start()
    return task


def _start_analysis_async_fetch(
    state: Any,
    *,
    symbol: str,
    timeframe: str,
    bar_count: int,
    force_incremental: bool,
) -> None:
    """Fetch K-lines on a thread when no refresh snapshot is cached yet."""
    from pa_agent.data.snapshot import INDICATOR_WARMUP_BARS
    from pa_agent.server import market_service as market

    data_source = state.data_source()
    if data_source is None or not getattr(data_source, "_connected", False):
        state.status("数据源未连接")
        return

    state.status("正在后台获取K线…")

    def _fetch() -> None:
        try:
            bars = data_source.latest_snapshot(bar_count + INDICATOR_WARMUP_BARS + 5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Snapshot fetch failed: %s", exc)
            state.status(str(exc) or "获取K线失败")
            return
        if not market.bars_sufficient(state, bars, bar_count):
            state.status("数据不足，请等待图表刷新后再提交")
            return
        state.last_frame_bars = list(bars)
        task = start_analysis(
            state,
            symbol=symbol,
            timeframe=timeframe,
            bar_count=bar_count,
            force_incremental=force_incremental,
            snapshot_bars=bars,
        )
        if task is None:
            state.status("数据不足，请等待图表刷新后再提交")

    threading.Thread(target=_fetch, name="snapshot-fetch", daemon=True).start()


def _launch_after_prep(
    state: Any,
    task: AnalysisTask,
    prep: Any,
    *,
    snapshot_bars: list,
    force_incremental: bool,
) -> None:
    """Runner launch after background prep (mirrors _launch_analysis_worker)."""
    frame = getattr(prep, "frame", None)
    symbol = task.symbol
    timeframe = task.timeframe

    if frame is None:
        state.analysis_in_progress = False
        state.current_task = None
        state.status("数据不足，请等待图表刷新后再提交")
        _publish_state(state)
        return

    previous_record = getattr(prep, "previous_record", None)
    state.last_analysis_frame = frame
    state.analysis_previous_record = previous_record
    incremental_new_bar_count = getattr(prep, "incremental_new_bar_count", None)
    incremental_detail = getattr(prep, "incremental_detail", None)

    if force_incremental and previous_record is None:
        reason = flow.incremental_unavailable_reason(frame, symbol, timeframe)
        state.analysis_in_progress = False
        state.current_task = None
        state.status(reason)
        state.publish("ui", "alert", level="warning", title="无法增量分析", message=reason)
        _publish_state(state)
        return

    orchestrator = _build_orchestrator(state)
    if orchestrator is None:
        state.analysis_in_progress = False
        state.current_task = None
        state.status("编排器未就绪，请检查设置")
        _publish_state(state)
        return

    # Snapshot the closed bar ts at submit time for the keep-analysis sentinel.
    try:
        from pa_agent.server import market_service as market

        forming = current_forming_ts(
            snapshot_bars, timeframe, symbol=symbol, now_ms=market.now_ms(state)
        )
        submit_closed_ts = None
        if forming is not None:
            for b in snapshot_bars:
                ts = getattr(b, "ts_open", None)
                if ts is not None and int(ts) != int(forming):
                    submit_closed_ts = int(ts)
                    break
        elif snapshot_bars:
            ts = getattr(snapshot_bars[0], "ts_open", None)
            if ts is not None:
                submit_closed_ts = int(ts)
        tracker = state.keep_analysis_tracker
        if tracker is not None:
            tracker.submit_closed_ts = submit_closed_ts
    except Exception:  # noqa: BLE001
        pass

    task.cancel_token = _new_cancel_token()
    task.status = "running"
    channel = task.channel

    state.chart_refresh_paused = True
    state.status(
        _analysis_start_status(
            state, incremental_new_bar_count, incremental_detail, force_incremental
        )
    )
    state.publish("ui", "flow_reset")
    _publish_state(state)

    callbacks = {
        "on_status": lambda text: (
            state.status(text),
            _drive_flow_bar(state, channel, text),
        ),
        "on_retry": lambda stage: (
            state.publish(channel, "retry_occurred", stage=stage),
            state.publish("ui", "retry_occurred", stage=stage),
            _maybe_cancel_keep_analysis_on_retry(state, stage),
        ),
        "on_reasoning": lambda stage, chunk: state.publish(
            channel, "reasoning_token", stage=stage, chunk=chunk
        ),
        "on_content": lambda stage, chunk: state.publish(
            channel, "content_token", stage=stage, chunk=chunk
        ),
        "on_stage_prompt": lambda stage, system, user: state.publish(
            channel, "stage_prompt", stage=stage, system=system, user=user
        ),
        "on_stage2_files": lambda files: state.publish(
            channel, "stage2_files", files=list(files)
        ),
    }

    def _run() -> None:
        try:
            _run_inner()
        except CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Analysis runner crashed — unsticking state")
            state.analysis_in_progress = False
            state.current_task = None
            state.status("分析线程异常，请重试（详情见日志）")
            state.publish("ui", "alert", level="error", title="分析线程异常",
                          message="详见服务日志")
            _publish_state(state)
            state.hub.close_channel(task.channel)

    def _run_inner() -> None:
        decision, record = flow.run_two_stage_analysis(
            orchestrator,
            frame,
            task.cancel_token,
            callbacks,
            previous_record=previous_record,
            incremental_new_bar_count=incremental_new_bar_count,
        )
        if record is not None:
            from pa_agent.server.serialize import record_to_dict

            state.publish(channel, "record", record=record_to_dict(record))
            _on_record_ready(state, record)
        cancelled = record is None and not decision
        state.publish(
            channel, "finished", decision=decision or {}, cancelled=cancelled
        )
        state.hub.close_channel(channel)
        task.status = "cancelled" if cancelled else "finished"
        state.analysis_in_progress = False
        state.current_task = None
        _finish_round(state, decision)
        _publish_state(state)

    thread = threading.Thread(target=_run, name=f"analysis-{task.id[:8]}", daemon=True)
    task.thread = thread
    thread.start()


def cancel(state: Any, task_id: str | None = None) -> dict[str, Any]:
    task = state.current_task
    if task is None:
        return {"ok": False, "error": "没有进行中的分析"}
    if task_id and task.id != task_id:
        return {"ok": False, "error": "任务不匹配"}
    if task.cancel_token is not None:
        task.cancel_token.set()
    state.status("正在取消分析…")
    return {"ok": True}


# ── Record handling / follow-ups ──────────────────────────────────────────────

def _on_record_ready(state: Any, record: Any) -> None:
    """Update state + broadcast the derived panel payload when a record lands."""
    state.last_analysis_record = record
    s1_diag = getattr(record, "stage1_diagnosis", None) or {}
    state.last_stage1_diagnosis = s1_diag if isinstance(s1_diag, dict) else None

    from pa_agent.server.record_payload import build_record_payload

    payload = build_record_payload(state, record)
    state.publish("ui", "record_payload", **payload)

    # Order opportunity alert → frontend toast (sound played client-side).
    decision_inner = payload.get("decision_inner") or {}
    if decision_inner and not state.demo_mode:
        settings = state.settings()
        threshold = int(
            getattr(getattr(settings, "general", None), "decision_confidence_threshold", 0)
        )
        alert_enabled = bool(
            getattr(getattr(settings, "general", None), "alert_on_order_opportunity", True)
        )
        if alert_enabled:
            from pa_agent.services.order_opportunity import (
                format_order_alert_message,
                has_order_opportunity,
            )

            if has_order_opportunity(decision_inner, confidence_threshold=threshold):
                state.publish(
                    "ui",
                    "order_opportunity",
                    message=format_order_alert_message(decision_inner),
                )
                flow.spawn_post_order_followup(
                    decision_inner,
                    payload.get("stage2_full") or {},
                    settings=settings,
                    stage1_diagnosis=state.last_stage1_diagnosis,
                    frame=state.last_analysis_frame,
                )

    # Free-chat session for the finished record (demo mode creates none).
    if not state.demo_mode:
        try:
            from pa_agent.orchestrator.free_chat import FreeChatSession
            from pa_agent.util.threading import CancelToken

            client = getattr(state.ctx, "client", None)
            assembler = getattr(state.ctx, "assembler", None)
            pending_writer = getattr(state.ctx, "pending_writer", None)
            ledger = getattr(state.ctx, "ledger", None)
            if all(x is not None for x in (client, assembler, pending_writer, ledger)):
                session = FreeChatSession(
                    base_record=record,
                    client=client,
                    assembler=assembler,
                    pending_writer=pending_writer,
                    ledger=ledger,
                    settings=state.settings(),
                    kline_snapshot_fn=_make_kline_snapshot_fn(state),
                )
                state.chat_session = session
                state.chat_cancel_token = CancelToken()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to create FreeChatSession: %s", exc)


def _finish_round(state: Any, decision: dict) -> None:
    """End-of-round housekeeping: sentinel + chart resume + status text."""
    from pa_agent.server import market_service as market

    market.refresh_keep_analysis_sentinel(state)
    if state.keep_analysis_enabled and state.chart_refresh_paused:
        state.chart_refresh_paused = False

    auto_resume_enabled = bool(
        getattr(
            getattr(state.settings(), "general", None),
            "auto_resume_chart_after_analysis",
            False,
        )
    )
    auto_resumed = False
    if (
        not state.demo_mode
        and auto_resume_enabled
        and state.chart_refresh_paused
    ):
        state.chart_refresh_paused = False
        auto_resumed = True

    if state.last_analysis_had_error:
        msg = "分析结束（存在错误，请查看「原始」页调试信息）"
    elif decision:
        msg = "分析完成，图表已恢复实时更新" if auto_resumed else "分析完成"
    else:
        msg = "分析已取消"
    if auto_resumed and state.last_analysis_had_error:
        msg += "；图表已恢复实时更新"
    state.status(msg)


def _make_kline_snapshot_fn(state: Any) -> Any:
    from pa_agent.ai.prompt_assembler import PromptAssembler
    from pa_agent.server import market_service as market

    def _snapshot() -> str:
        bar_count = dss.analysis_bar_count(state.settings())
        bars = market.cached_bars_for_analysis(state, bar_count)
        if not bars:
            return ""
        frame = dss.build_frame_from_bars(
            bars,
            bar_count=bar_count,
            symbol=market.current_symbol(state),
            timeframe=market.current_timeframe(state),
            now_ms=market.now_ms(state),
            include_forming=False,
            settings=state.settings(),
        )
        if frame is None:
            return ""
        return PromptAssembler._render_kline_table(frame)

    return _snapshot


def _build_orchestrator(state: Any) -> Any:
    try:
        from pa_agent.orchestrator.two_stage import TwoStageOrchestrator

        ctx = state.ctx
        parts = (
            getattr(ctx, "client", None),
            getattr(ctx, "assembler", None),
            getattr(ctx, "router", None),
            getattr(ctx, "validator", None),
            getattr(ctx, "pending_writer", None),
            getattr(ctx, "exp_reader", None),
        )
        if any(p is None for p in parts):
            return None
        return TwoStageOrchestrator(
            client=parts[0],
            assembler=parts[1],
            router=parts[2],
            validator=parts[3],
            pending_writer=parts[4],
            exp_reader=parts[5],
            settings=state.settings(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not build orchestrator: %s", exc)
        return None


def _new_cancel_token() -> Any:
    from pa_agent.util.threading import CancelToken

    return CancelToken()


# ── Status/flow-bar derivation (ported from _on_status_update) ────────────────

def _drive_flow_bar(state: Any, channel: str, text: str) -> None:
    step: dict[str, Any] | None = None
    if text == "阶段一分析中…":
        step = {"index": 2, "status": "active", "caption": "分析中…"}
    elif text == "阶段一完成":
        step = {"index": 2, "status": "done", "caption": "已完成"}
    elif text == "阶段一失败":
        step = {"index": 2, "status": "error", "caption": "失败"}
    elif text == "阶段二分析中…":
        step = {"index": 3, "status": "active", "caption": "决策中…"}
    elif text == "阶段二完成":
        step = {"index": 3, "status": "done", "caption": "已完成"}
    elif text == "阶段二失败":
        step = {"index": 3, "status": "error", "caption": "失败"}
    elif text == "已取消":
        step = {"reset": True}
    if step:
        state.publish(channel, "flow_step", **step)
        state.publish("ui", "flow_step", **step)


def _maybe_cancel_keep_analysis_on_retry(state: Any, stage: str) -> None:
    settings = state.settings()
    if settings is None:
        return
    if not bool(getattr(settings.general, "cancel_keep_analysis_on_retry", False)):
        return
    if state.keep_analysis_enabled:
        state.keep_analysis_enabled = False
        settings.general.keep_analysis = False
        persist_settings(settings)
        logger.info("持续跟踪分析已因 %s 重试自动关闭", stage)
        _publish_state(state)


def _analysis_start_status(
    state: Any,
    incremental_new_bar_count: int | None,
    incremental_detail: str | None,
    force_incremental: bool,
) -> str:
    from pa_agent.ai.decision_stance import stance_label_zh

    stance_raw = "balanced"
    settings = state.settings()
    if settings is not None:
        stance_raw = getattr(settings.general, "decision_stance", "balanced")
    stance_label = stance_label_zh(stance_raw)
    if incremental_new_bar_count is not None:
        prefix = "强制增量分析中" if force_incremental else "增量分析中"
        if incremental_new_bar_count > 0:
            detail = incremental_detail or f"新增{incremental_new_bar_count}根已收盘K线"
        else:
            detail = "无新增K线，基于上一轮结论复核"
        return f"{prefix}…（倾向:{stance_label}，{detail}，图表已冻结）"
    return f"分析中…（倾向:{stance_label}，图表已冻结，K1=最新已收盘K线）"


def _publish_state(state: Any) -> None:
    from pa_agent.server import market_service as market

    state.publish("ui", "state", **market.publish_ui_state(state))
