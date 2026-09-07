"""Records & prompt files routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from pa_agent.server.routes.common import get_state

router = APIRouter(prefix="/api", tags=["records"])


@router.get("/records")
def list_records(request: Request, limit: int = 50) -> dict[str, Any]:
    from pa_agent.config.paths import RECORDS_PENDING_DIR
    from pa_agent.records.analysis_history import list_record_paths, load_record

    paths = list_record_paths(RECORDS_PENDING_DIR)
    out: list[dict[str, Any]] = []
    for path in paths[:limit]:
        record = load_record(path)
        if record is None:
            continue
        meta = record.meta
        out.append(
            {
                "path": str(path),
                "name": path.name,
                "symbol": meta.symbol,
                "timeframe": meta.timeframe,
                "timestamp_local_iso": meta.timestamp_local_iso,
                "has_stage2": bool(record.stage2_decision),
                "exception": record.exception,
            }
        )
    return {"ok": True, "records": out, "directory": str(RECORDS_PENDING_DIR)}


@router.get("/records/latest")
def latest_record(request: Request, symbol: str = "", timeframe: str = "") -> dict[str, Any]:
    from pa_agent.records.analysis_history import find_latest_successful_record
    from pa_agent.server.serialize import record_to_dict

    record = find_latest_successful_record(symbol=symbol, timeframe=timeframe)
    if record is None:
        return {"ok": False, "error": "未找到成功记录"}
    return {"ok": True, "record": record_to_dict(record)}


@router.get("/prompts")
def prompt_files(request: Request) -> dict[str, Any]:
    from pa_agent.ai.prompt_assembler import stage1_prompt_txt_files

    state = get_state(request)
    assembler = getattr(state.ctx, "assembler", None)
    prompt_dir = getattr(assembler, "_prompt_dir", None)
    return {
        "ok": True,
        "stage1": stage1_prompt_txt_files(),
        "prompt_dir": str(prompt_dir) if prompt_dir is not None else "",
    }


@router.get("/ledger")
def token_ledger(request: Request) -> dict[str, Any]:
    from pa_agent.server.serialize import ledger_to_dict

    state = get_state(request)
    return {"ok": True, "ledger": ledger_to_dict(getattr(state.ctx, "ledger", None))}
