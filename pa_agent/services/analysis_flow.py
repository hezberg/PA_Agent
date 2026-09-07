"""Analysis submission flow — business logic extracted from the old MainWindow.

Everything here is Qt-free and callback-driven so it can back the WebUI
(or any other frontend).  Signal payloads mirror the historical Qt signals:

``reasoning_token(stage, chunk)``, ``content_token(stage, chunk)``,
``stage_prompt_ready(stage, system, user)``, ``stage2_files_ready(files)``,
``retry_occurred(stage)``, ``status_update(text)``, ``record_ready(record)``,
``finished(decision)``.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pa_agent.data.bar_close_wait import (
    current_forming_ts,
    forming_bar_has_closed,
    has_forming_bar_at_head,
    reference_now_ms,
    seconds_until_bar_closes,
)

logger = logging.getLogger(__name__)

WORKER_JOIN_TIMEOUT_S = 5.0


def format_price(price: float) -> str:
    """格式化价格：大数加千分位、小币自适应小数位。"""
    if price >= 1:
        return f"{price:,.2f}"        # BTC → 78,840.52
    if price >= 0.01:
        return f"{price:.4f}"         # 中等价 → 0.1234
    # 极小价币（如 PEPE）：最多 8 位小数，去掉尾部 0，避免科学计数法
    s = f"{price:.8f}".rstrip("0").rstrip(".")
    return s if s else "0"


def parse_sr_price(raw: object) -> float | None:
    """Parse a support/resistance price string from the AI output.

    Accepts single values (``"5402"``, ``5402``) and range strings
    (``"5380-5400"``).  Returns the midpoint for ranges, or the value
    itself for single prices.  Returns None on parse failure.
    """
    import re as _re
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        return v if v > 0 else None
    text = str(raw).strip()
    # Range: e.g. "5380-5400" or "5380~5400"
    m = _re.search(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)", text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (lo + hi) / 2.0
    # Single number
    m2 = _re.search(r"\d+(?:\.\d+)?", text)
    if m2:
        return float(m2.group(0))
    return None


def best_probability_key(probs: dict) -> str | None:
    """Return the key with highest numeric probability; tolerate bad values."""
    best_key: str | None = None
    best_val = -1
    for key, raw in probs.items():
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val > best_val:
            best_val = val
            best_key = str(key)
    return best_key


def live_price_info(bars: Any) -> dict | None:
    """Latest price + direction colour hint from a newest-first bar list."""
    if not bars:
        return None
    latest = bars[0]
    price = float(getattr(latest, "close", 0.0))
    if price <= 0:
        return None
    color = "#8b949e"
    if len(bars) >= 2:
        prev_close = float(getattr(bars[1], "close", 0.0))
        if prev_close > 0:
            if price > prev_close:
                color = "#ef4444"
            elif price < prev_close:
                color = "#3fb950"
    return {"price": format_price(price), "color": color}


# ── Submission gating ─────────────────────────────────────────────────────────

def submit_block_reason(
    *,
    api_key_configured: bool,
    demo_mode: bool,
    analysis_in_progress: bool,
    pending_submit_after_close: bool,
    switching: bool,
) -> str | None:
    """Human-readable reason when submit must stay disabled, or None."""
    if not api_key_configured:
        return "未配置 API Key，请点击左上角「AI 模型」填写后才能分析"
    if demo_mode:
        return "演示模式中，请退出演示后再提交真实分析"
    if analysis_in_progress:
        return "分析进行中"
    if pending_submit_after_close:
        return "等待最新K线收盘"
    if switching:
        return "正在切换品种/周期"
    return None


# ── Analysis preparation (frame + incremental base lookup) ────────────────────

@dataclass(frozen=True)
class AnalysisPrepResult:
    frame: Any
    previous_record: Any | None
    incremental_new_bar_count: int | None
    incremental_detail: str | None


def prepare_analysis_sync(
    *,
    bars_raw: list[Any],
    symbol: str,
    timeframe: str,
    bar_count: int,
    now_ms: int,
    force_incremental: bool,
    incremental_threshold: int,
) -> AnalysisPrepResult:
    """Build the KlineFrame and resolve the incremental base record.

    Synchronous extract of the historical ``AnalysisPrepWorker.run`` —
    callers run it on their own worker thread.
    """
    from pa_agent.data.snapshot import build_display_frame
    from pa_agent.records.analysis_history import (
        compute_incremental_bar_delta,
        find_latest_successful_record,
        format_bar_ts,
    )

    frame = build_display_frame(
        bars_raw,
        bar_count,
        symbol,
        timeframe,
        now_ms=now_ms,
    )
    if frame is None:
        raise ValueError("数据不足，无法构建分析快照")

    previous = None
    incremental_new_bar_count: int | None = None
    incremental_detail: str | None = None

    if force_incremental or incremental_threshold > 0:
        previous = find_latest_successful_record(
            symbol=symbol,
            timeframe=timeframe,
        )
        if previous is not None:
            delta = compute_incremental_bar_delta(frame, previous)
            if delta is not None:
                new_count = delta.new_count
                if force_incremental or new_count <= incremental_threshold:
                    incremental_new_bar_count = new_count
                    anchor_label = format_bar_ts(delta.anchor_ts_open)
                    if new_count == 0:
                        incremental_detail = (
                            f"锚定K线 {anchor_label}，无新增已收盘K线"
                        )
                    elif new_count == 1:
                        incremental_detail = (
                            f"锚定K线 {anchor_label}，新增1根 "
                            f"{format_bar_ts(delta.new_bar_ts_opens[0])}"
                        )
                    else:
                        newest = format_bar_ts(delta.new_bar_ts_opens[0])
                        oldest_new = format_bar_ts(delta.new_bar_ts_opens[-1])
                        incremental_detail = (
                            f"锚定K线 {anchor_label}，新增{new_count}根"
                            f"（{oldest_new} → {newest}）"
                        )
                elif not force_incremental:
                    previous = None

    return AnalysisPrepResult(
        frame=frame,
        previous_record=previous,
        incremental_new_bar_count=incremental_new_bar_count,
        incremental_detail=incremental_detail,
    )


def incremental_unavailable_reason(
    frame: Any,
    symbol: str,
    timeframe: str,
) -> str:
    """Explain why forced incremental analysis cannot start."""
    try:
        from pa_agent.records.analysis_history import (
            compute_incremental_bar_delta,
            find_latest_successful_record,
        )

        previous = find_latest_successful_record(symbol=symbol, timeframe=timeframe)
        if previous is None:
            return (
                f"无法强制增量分析：未找到 {symbol} {timeframe} 的成功分析记录。"
                "请先完成一次完整分析。"
            )
        if compute_incremental_bar_delta(frame, previous) is None:
            return (
                "无法强制增量分析：当前 K 线与上一轮记录无法对齐。"
                "可能缺口过大或 K 线数量/范围变化过大，请改用「提交分析」。"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Incremental unavailable reason lookup failed: %s", exc)
    return "无法强制增量分析：未找到可用的上一轮记录。"


# ── Two-stage analysis runner (replaces the Qt _AnalysisWorker) ───────────────

class AnalysisCancelled(Exception):
    """Raised internally when the orchestrator reports a user cancellation."""


def run_two_stage_analysis(
    orchestrator: Any,
    frame: Any,
    cancel_token: Any,
    callbacks: dict[str, Callable],
    *,
    previous_record: Any = None,
    incremental_new_bar_count: int | None = None,
) -> tuple[dict, Any | None]:
    """Run ``orchestrator.submit`` driving plain callbacks instead of Qt signals.

    *callbacks* keys (all optional):
    ``on_status(text)``, ``on_retry(stage)``, ``on_reasoning(stage, chunk)``,
    ``on_content(stage, chunk)``, ``on_stage_prompt(stage, system, user)``,
    ``on_stage2_files(files)``.

    Returns ``(decision, record)``.  On cancellation ``decision`` is ``{}`` and
    ``record`` is None; on program errors a minimal failed record is persisted
    and returned.
    """
    from pa_agent.util.threading import OrchestratorEvent

    _EVENT_LABELS = {
        OrchestratorEvent.Stage1Started: "阶段一分析中…",
        OrchestratorEvent.Stage1Retry: "阶段一重试",
        OrchestratorEvent.Stage1Done: "阶段一完成",
        OrchestratorEvent.Stage2Started: "阶段二分析中…",
        OrchestratorEvent.Stage2Retry: "阶段二重试",
        OrchestratorEvent.Stage2Done: "阶段二完成",
        OrchestratorEvent.RecordSaved: "记录已保存",
        OrchestratorEvent.Cancelled: "已取消",
        OrchestratorEvent.Stage1Failed: "阶段一失败",
        OrchestratorEvent.Stage2Failed: "阶段二失败",
    }

    on_status = callbacks.get("on_status", lambda text: None)
    on_retry = callbacks.get("on_retry", lambda stage: None)
    on_reasoning = callbacks.get("on_reasoning", lambda stage, chunk: None)
    on_content = callbacks.get("on_content", lambda stage, chunk: None)
    on_stage_prompt = callbacks.get("on_stage_prompt", lambda stage, system, user: None)
    on_stage2_files = callbacks.get("on_stage2_files", lambda files: None)

    def on_event(event: OrchestratorEvent) -> None:
        on_status(_EVENT_LABELS.get(event, str(event)))
        if event == OrchestratorEvent.Stage1Retry:
            on_retry("stage1")
        elif event == OrchestratorEvent.Stage2Retry:
            on_retry("stage2")

    record: Any = None
    try:
        record = orchestrator.submit(
            frame,
            cancel_token,
            on_event,
            on_stage1_reasoning=lambda chunk: on_reasoning("stage1", chunk),
            on_stage1_content=lambda chunk: on_content("stage1", chunk),
            on_stage2_reasoning=lambda chunk: on_reasoning("stage2", chunk),
            on_stage2_content=lambda chunk: on_content("stage2", chunk),
            on_stage_prompt=on_stage_prompt,
            on_stage2_files=on_stage2_files,
            previous_record=previous_record,
            incremental_new_bar_count=incremental_new_bar_count,
        )
        decision = record.stage2_decision or {}
    except Exception as exc:  # noqa: BLE001
        from pa_agent.ai.deepseek_client import CancelledError as _CancelledError
        if isinstance(exc, _CancelledError):
            logger.info("Analysis cancelled: %s", exc)
            return {}, None
        logger.error("Analysis error: %s", exc, exc_info=True)
        record = persist_program_error_record(orchestrator, frame, exc)
        on_status(f"程序异常：{exc}")
        return {}, record
    return decision, record


def persist_program_error_record(
    orchestrator: Any, frame: Any, exc: Exception
) -> Any:
    """Write a minimal failed record to pending when submit() raises unexpectedly."""
    try:
        from pa_agent.orchestrator.two_stage import _build_empty_record

        settings = getattr(orchestrator, "_settings", None)
        pending_writer = getattr(orchestrator, "_pending_writer", None)
        if pending_writer is None:
            return None
        record = _build_empty_record(frame, settings)
        record = record.model_copy(
            update={
                "exception": {
                    "type": "program_error",
                    "stage": "unknown",
                    "message": str(exc),
                }
            }
        )
        pending_writer.save_partial(record, "program_error")
        return record
    except Exception as save_exc:  # noqa: BLE001
        logger.warning("Failed to persist program_error record: %s", save_exc)
        return None


# ── Post-order follow-up (trade CSV + notifications) ──────────────────────────

def spawn_post_order_followup(
    inner: dict,
    decision: dict,
    *,
    settings: Any,
    stage1_diagnosis: dict | None,
    frame: Any,
) -> None:
    """Run trade CSV/chart + notifications off the caller thread (can take seconds)."""
    model_name = ""
    meta_symbol = ""
    meta_timeframe = ""
    decision_stance = ""
    if settings is not None:
        model_name = getattr(settings.provider, "model", "") or ""
        meta_symbol = getattr(settings.general, "last_symbol", "") or ""
        meta_timeframe = getattr(settings.general, "last_timeframe", "") or ""
        decision_stance = getattr(settings.general, "decision_stance", "") or ""

    def _run() -> None:
        try:
            from pa_agent.records.trade_logger import save_trade_record

            save_trade_record(
                decision_inner=inner,
                stage2_full=decision,
                stage1_diagnosis=stage1_diagnosis,
                frame=frame,
                meta_symbol=meta_symbol,
                meta_timeframe=meta_timeframe,
                decision_stance=decision_stance,
                model_name=model_name,
                structure_flip_cooldown_bars=int(
                    getattr(settings.general, "structure_flip_cooldown_bars", 3) or 3
                )
                if settings is not None
                else 3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Trade record logging failed: %s", exc)

        try:
            from pa_agent.notify.feishu_notifier import send_order_signal as send_feishu_order
            from pa_agent.notify.pushplus_notifier import (
                pushplus_is_active,
                send_order_signal as send_pushplus_order,
            )
            from pa_agent.records.trade_logger import _TRADE_RECORDS_DIR

            safe_sym = meta_symbol.replace("/", "-").replace("\\", "-")
            safe_tf = meta_timeframe.replace("/", "-")
            img_glob = f"{safe_sym}_{safe_tf}_*.png"
            candidates = sorted(
                _TRADE_RECORDS_DIR.glob(img_glob),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            latest_img = candidates[0] if candidates else None

            send_feishu_order(
                decision_inner=inner,
                stage2_full=decision,
                symbol=meta_symbol,
                timeframe=meta_timeframe,
                chart_image_path=latest_img,
                settings=settings,
            )
            if pushplus_is_active(settings):
                send_pushplus_order(
                    decision_inner=inner,
                    stage2_full=decision,
                    symbol=meta_symbol,
                    timeframe=meta_timeframe,
                    settings=settings,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("下单信号通知失败（不影响主流程）: %s", exc)

    threading.Thread(
        target=_run,
        name="post-order-followup",
        daemon=True,
    ).start()


# ── Bar-close wait state ──────────────────────────────────────────────────────

@dataclass
class BarCloseWait:
    """Armed "wait for the current forming bar to close, then submit" state."""

    armed: bool = False
    forming_ts: int | None = None
    force_incremental: bool = False
    symbol: str = ""
    timeframe: str = ""
    bar_count: int = 0

    def clear(self) -> None:
        self.armed = False
        self.forming_ts = None
        self.force_incremental = False
        self.symbol = ""
        self.timeframe = ""
        self.bar_count = 0

    def seconds_remaining(self, *, now_ms: int) -> int | None:
        if not self.armed or self.forming_ts is None or not self.timeframe:
            return None
        return seconds_until_bar_closes(
            int(self.forming_ts), self.timeframe, now_ms=now_ms
        )

    def pop_if_closed(self, bars: Any, *, now_ms: int) -> tuple[str, str, int, bool] | None:
        """Return ``(symbol, timeframe, bar_count, force_incremental)`` when the
        forming bar has rolled over (and disarm), else None."""
        if not self.armed or self.forming_ts is None:
            return None
        if not forming_bar_has_closed(
            self.forming_ts,
            bars,
            self.timeframe,
            symbol=self.symbol,
            now_ms=now_ms,
        ):
            return None
        result = (self.symbol, self.timeframe, self.bar_count, self.force_incremental)
        self.clear()
        return result


def latest_closed_bar_ts(bars: Any, timeframe: str, *, symbol: str, now_ms: int) -> int | None:
    """``ts_open`` of the most recently closed bar (forming bar excluded)."""
    forming_ts = current_forming_ts(bars, timeframe, symbol=symbol, now_ms=now_ms)
    if forming_ts is not None:
        for bar in bars:
            ts_open = getattr(bar, "ts_open", None) or (
                bar[0] if hasattr(bar, "__getitem__") else None
            )
            if ts_open is not None and int(ts_open) != int(forming_ts):
                return int(ts_open)
        return None
    bar = bars[0] if bars else None
    if bar is None:
        return None
    ts_open = getattr(bar, "ts_open", None) or (
        bar[0] if hasattr(bar, "__getitem__") else None
    )
    return int(ts_open) if ts_open is not None else None


def bars_sufficient_for_analysis(
    bars: list[Any],
    bar_count: int,
    *,
    timeframe: str,
    symbol: str,
    now_ms: int,
) -> bool:
    """True when *bars* can build an analysis frame of *bar_count* closed bars."""
    if not bars or len(bars) < bar_count:
        return False
    if has_forming_bar_at_head(bars, timeframe, symbol=symbol, now_ms=now_ms):
        return len(bars) >= bar_count + 1
    return True


# ── Keep-analysis (持续跟踪分析) sentinel ──────────────────────────────────────

class KeepAnalysisTracker:
    """Detects new bar closes and requests a fresh analysis round.

    Mirrors the historical MainWindow keep-analysis behaviour: the sentinel is
    the ``ts_open`` of the most recently closed bar; a change between ticks
    means a new bar closed.  The submit-time snapshot
    (``keep_analysis_submit_closed_ts``) is restored after each round so bars
    that closed *during* an analysis still trigger the next round.
    """

    def __init__(self) -> None:
        self.last_closed_ts: int | None = None
        self.submit_closed_ts: int | None = None

    def reset(self) -> None:
        self.last_closed_ts = None
        self.submit_closed_ts = None

    def refresh_sentinel(
        self, bars: Any, *, timeframe: str, symbol: str, now_ms: int
    ) -> None:
        """Sync the sentinel after analysis completes (submit-time snapshot first)."""
        if self.submit_closed_ts is not None:
            self.last_closed_ts = self.submit_closed_ts
            self.submit_closed_ts = None
            return
        if not bars or len(bars) < 2:
            return
        try:
            ts = latest_closed_bar_ts(bars, timeframe, symbol=symbol, now_ms=now_ms)
            if ts is not None:
                self.last_closed_ts = ts
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh_sentinel error: %s", exc)

    def check(
        self,
        bars: Any,
        *,
        timeframe: str,
        symbol: str,
        now_ms: int,
    ) -> str:
        """Feed the latest RefreshLoop bars; return one of:

        - ``"armed_first"``   — first tick; sentinel initialised
        - ``"new_bar"``       — a new bar closed since the last tick
        - ``"no_new_bar"``    — nothing to do
        """
        if not bars or len(bars) < 2:
            logger.warning(
                "持续跟踪分析：跳过（bars 数量不足，len=%d）", len(bars) if bars else 0
            )
            return "no_new_bar"
        try:
            closed_ts = latest_closed_bar_ts(
                bars, timeframe, symbol=symbol, now_ms=now_ms
            )
            if closed_ts is None:
                return "no_new_bar"
            if self.last_closed_ts is None:
                self.last_closed_ts = closed_ts
                logger.info(
                    "持续跟踪分析：哨兵初始化 closed_ts=%s，等待当前K线收盘", closed_ts
                )
                return "armed_first"
            if closed_ts == self.last_closed_ts:
                return "no_new_bar"
            self.last_closed_ts = closed_ts
            logger.info("保持分析：检测到新K线收盘（ts_open=%s）", closed_ts)
            return "new_bar"
        except Exception as exc:  # noqa: BLE001
            logger.warning("check_keep_analysis error: %s", exc, exc_info=True)
            return "no_new_bar"


def monotonic_ts() -> float:
    """Small indirection so tests can patch the clock."""
    return time.monotonic()
