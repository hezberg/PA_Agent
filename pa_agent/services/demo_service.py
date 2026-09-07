"""Demo-replay orchestration — record selection and frame reconstruction."""
from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_demo_record(path: Path) -> tuple[Path, Any] | None:
    """Load a record file, falling back to any other playable record."""
    from pa_agent.demo.record_loader import (
        is_demo_playable,
        pick_playable_demo_record,
        try_load_analysis_record,
    )

    record = try_load_analysis_record(path)
    if record is not None and is_demo_playable(record):
        return path, record
    alt = pick_playable_demo_record(exclude=path)
    if alt is None:
        return None
    return alt


def pick_random_demo_record(exclude: str | None = None) -> tuple[Path, Any] | None:
    """Return (path, record) for a random playable pending record, or None."""
    from pa_agent.demo.record_loader import pick_playable_demo_record

    picked = pick_playable_demo_record(exclude=exclude or None)
    if picked is not None:
        return picked
    if exclude:
        return pick_playable_demo_record(exclude=None)
    return None


def build_demo_frame(path: Path, record: Any) -> Any:
    """Reconstruct the KlineFrame snapshot from a saved record's klines."""
    from pa_agent.demo.record_loader import frame_from_record_klines

    meta = record.meta
    return frame_from_record_klines(
        record.kline_data,
        symbol=meta.symbol,
        timeframe=meta.timeframe,
        snapshot_ts_local_ms=meta.timestamp_local_ms,
    )


def enter_demo(ctx: Any, path: Path, record: Any) -> dict:
    """Prepare demo state; returns a payload describing the replay session."""
    meta = record.meta
    return {
        "path": str(Path(path)),
        "name": Path(path).name,
        "symbol": meta.symbol,
        "timeframe": meta.timeframe,
    }


def shuffled_queue(paths: list[Path]) -> list[Path]:
    """Randomised replay order for auto demo."""
    out = list(paths)
    random.shuffle(out)
    return out
