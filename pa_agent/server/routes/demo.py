"""Demo replay routes (manual / auto record playback)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pa_agent.server.routes.common import get_state, sse_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["demo"])


class DemoStartBody(BaseModel):
    mode: str = "auto"                    # manual | auto
    path: str | None = None               # required for manual


@router.post("/start")
def start_demo(request: Request, body: DemoStartBody) -> dict[str, Any]:
    state = get_state(request)
    if state.analysis_in_progress:
        return {"ok": False, "error": "分析进行中，无法进入演示模式"}
    if body.mode == "manual":
        if not body.path:
            return {"ok": False, "error": "缺少记录文件路径"}
        loaded = _load_manual(state, Path(body.path))
    else:
        loaded = _load_random(state)
    if loaded is None:
        return {"ok": False, "error": "所选记录无法读取或缺少阶段结果。"}
    path, record, skipped = loaded
    _enter_demo(state, path, record)
    if skipped:
        state.publish(
            "ui", "alert", level="info", title="演示模式",
            message=f"已跳过无法使用的记录「{skipped}」，改用：{Path(path).name}",
        )
    return {"ok": True, "name": Path(path).name, "record_path": str(path)}


@router.post("/stop")
def stop_demo(request: Request) -> dict[str, Any]:
    state = get_state(request)
    _exit_demo(state)
    return {"ok": True}


@router.get("/stream")
def stream_demo(request: Request) -> StreamingResponse:
    state = get_state(request)
    sub_id, queue = state.hub.subscribe({"demo", "ui"})
    return StreamingResponse(
        sse_stream(queue, sub_id, state), media_type="text/event-stream"
    )


def _load_manual(state: Any, path: Path) -> tuple[Any, Any, str] | None:
    from pa_agent.services import demo_service

    loaded = demo_service.load_demo_record(path)
    if loaded is None:
        return None
    new_path, record = loaded
    skipped = "" if str(new_path) == str(path) else Path(path).name
    return new_path, record, skipped


def _load_random(state: Any) -> tuple[Any, Any, str] | None:
    from pa_agent.services import demo_service

    loaded = demo_service.pick_random_demo_record(exclude=state.demo_record_path)
    if loaded is None:
        return None
    path, record = loaded
    return path, record, ""


def _enter_demo(state: Any, path: Path, record: Any) -> None:
    from pa_agent.demo.replayer import DemoReplayer
    from pa_agent.server import analysis_service
    from pa_agent.server.serialize import frame_to_dict
    from pa_agent.services import demo_service

    if state.demo_replayer is not None:
        state.demo_replayer.stop()
        state.demo_replayer = None

    prev_kind = state.demo_kind or "auto"
    if state.demo_mode:
        _exit_demo(state, silent=True)
    state.demo_mode = True
    state.demo_kind = prev_kind
    state.demo_record_path = str(Path(path))

    try:
        frame = demo_service.build_demo_frame(path, record)
    except Exception as exc:  # noqa: BLE001
        logger.warning("demo frame build failed: %s", exc)
        _exit_demo(state, silent=True)
        state.publish(
            "ui", "alert", level="warning", title="演示模式",
            message=f"无法构建 K 线快照，已跳过该记录：\n{Path(path).name}\n{exc}",
        )
        return

    state.chart_refresh_paused = True
    state.analysis_in_progress = True
    meta = record.meta
    state.publish(
        "demo",
        "demo_started",
        name=Path(path).name,
        symbol=meta.symbol,
        timeframe=meta.timeframe,
        frame=frame_to_dict(frame) if frame is not None else None,
    )
    state.status(f"演示回放中… ({Path(path).name})")

    replayer = DemoReplayer(record)
    state.demo_replayer = replayer

    channel = "demo"
    replayer.status_update.connect(lambda text: state.status(text))
    replayer.stage_prompt_ready.connect(
        lambda stage, system, user: state.publish(
            channel, "stage_prompt", stage=stage, system=system, user=user
        )
    )
    replayer.reasoning_token.connect(
        lambda stage, chunk: state.publish(
            channel, "reasoning_token", stage=stage, chunk=chunk
        )
    )
    replayer.content_token.connect(
        lambda stage, chunk: state.publish(
            channel, "content_token", stage=stage, chunk=chunk
        )
    )
    replayer.stage2_files_ready.connect(
        lambda files: state.publish(channel, "stage2_files", files=list(files))
    )
    replayer.record_ready.connect(
        lambda rec: (
            state.publish(
                channel, "record", record=_record_dict(rec)
            ),
            analysis_service._on_record_ready(state, rec),
        )
    )
    replayer.finished.connect(
        lambda decision: (
            state.publish(channel, "finished", decision=decision or {}),
            state.hub.close_channel(channel),
        )
    )
    replayer.replay_finished.connect(lambda: _on_replay_done(state))
    replayer.start()


def _record_dict(record: Any) -> dict:
    from pa_agent.server.serialize import record_to_dict

    return record_to_dict(record)


def _on_replay_done(state: Any) -> None:
    state.analysis_in_progress = False
    if state.demo_mode:
        name = Path(state.demo_record_path).name if state.demo_record_path else ""
        state.status(f"演示回放完成 · {name}")
    if state.demo_mode and state.demo_kind == "auto":
        state.demo_auto_next_armed = True
        timer = threading.Timer(0.65, lambda: _next_auto(state))
        timer.daemon = True
        timer.start()


def _next_auto(state: Any) -> None:
    if not state.demo_mode or state.demo_kind != "auto":
        return
    state.demo_auto_next_armed = False
    loaded = _load_random(state)
    if loaded is None:
        state.status("自动演示：未找到可用记录，已停止")
        _exit_demo(state)
        return
    path, record, _skipped = loaded
    _enter_demo(state, path, record)


def _exit_demo(state: Any, *, silent: bool = False) -> None:
    if state.demo_replayer is not None:
        state.demo_replayer.stop()
        state.demo_replayer = None
    was_demo = state.demo_mode
    state.demo_mode = False
    state.demo_kind = None
    state.demo_record_path = None
    state.analysis_in_progress = False
    state.chart_refresh_paused = False
    if was_demo and not silent:
        state.status("已退出演示模式")
