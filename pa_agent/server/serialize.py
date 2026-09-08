"""JSON-safe serializers for domain objects sent to the WebUI."""
from __future__ import annotations

from typing import Any

from pa_agent.data.base import KlineBar, KlineFrame


def bar_to_dict(bar: KlineBar) -> dict[str, Any]:
    return {
        "seq": bar.seq,
        "ts_open": int(bar.ts_open),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "amount": bar.amount,
        "pct_chg": bar.pct_chg,
        "closed": bar.closed,
    }


def frame_to_dict(frame: KlineFrame) -> dict[str, Any]:
    """Serialize a KlineFrame oldest→newest for charting (lightweight-charts order)."""
    bars = [bar_to_dict(b) for b in frame.bars]
    bars.reverse()  # frame.bars is newest-first
    return {
        "symbol": frame.symbol,
        "timeframe": frame.timeframe,
        "snapshot_ts_local_ms": frame.snapshot_ts_local_ms,
        "bars": bars,
        # 指标与 bars 同为最新优先，一并反转保持下标对齐；否则前端画出的 EMA
        # 会时间镜像，且 EMA 预热期 NaN 落在最新一段，曲线末端缺一截
        "ema20": [v if v == v else None for v in reversed(frame.indicators.ema20)],
        "atr14": [v if v == v else None for v in reversed(frame.indicators.atr14)],
    }


def bars_to_payload(bars: list[Any]) -> dict[str, Any]:
    """Serialize a newest-first raw bar list (RefreshLoop payload)."""
    return {"bars": [bar_to_dict(b) for b in bars]}


def record_to_dict(record: Any) -> dict[str, Any]:
    """Full AnalysisRecord summary for the frontend."""
    meta = getattr(record, "meta", None)
    return {
        "meta": {
            "symbol": getattr(meta, "symbol", ""),
            "timeframe": getattr(meta, "timeframe", ""),
            "timestamp_local_iso": getattr(meta, "timestamp_local_iso", ""),
            "decision_stance": getattr(meta, "decision_stance", None),
        }
        if meta is not None
        else None,
        "stage1_diagnosis": getattr(record, "stage1_diagnosis", None),
        "stage2_decision": getattr(record, "stage2_decision", None),
        "stage1_messages": getattr(record, "stage1_messages", None),
        "stage2_messages": getattr(record, "stage2_messages", None),
        "stage1_response": getattr(record, "stage1_response", None),
        "stage2_response": getattr(record, "stage2_response", None),
        "exception": getattr(record, "exception", None),
        "strategy_files_used": getattr(record, "strategy_files_used", None),
        "experience_loaded": getattr(record, "experience_loaded", None),
        "usage_total": getattr(record, "usage_total", None),
    }


def ledger_to_dict(ledger: Any) -> dict[str, Any] | None:
    if ledger is None:
        return None
    try:
        return ledger.breakdown()
    except Exception:  # noqa: BLE001
        return None
