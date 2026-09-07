"""Free-chat routes (post-analysis follow-up)."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pa_agent.server.routes.common import get_state, sse_stream

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatBody(BaseModel):
    text: str


@router.post("")
def send_chat(request: Request, body: ChatBody) -> dict[str, Any]:
    """Start a free-chat turn on a worker thread; stream via /api/chat/{id}/stream."""
    state = get_state(request)
    session = state.chat_session
    if session is None:
        return {"ok": False, "error": "暂无可用追问会话，请先完成一次分析"}
    text = body.text.strip()
    if not text:
        return {"ok": False, "error": "消息为空"}
    if getattr(state, "chat_running", False):
        return {"ok": False, "error": "上一条追问仍在回复中"}

    chat_id = uuid.uuid4().hex
    channel = f"chat:{chat_id}"
    state.chat_running = True

    def _on_reasoning(chunk: str) -> None:
        state.publish(channel, "reasoning_token", chunk=chunk)

    def _on_content(chunk: str) -> None:
        state.publish(channel, "content_token", chunk=chunk)

    def _run() -> None:
        from pa_agent.ai.deepseek_client import CancelledError

        try:
            reply = session.send(
                text,
                state.chat_cancel_token,
                on_reasoning_token=_on_reasoning,
                on_content_token=_on_content,
            )
        except CancelledError:
            state.publish(channel, "finished", cancelled=True)
        except Exception as exc:  # noqa: BLE001
            state.publish(channel, "error", message=str(exc))
            state.publish(channel, "finished", cancelled=False, error=str(exc))
        else:
            state.publish(
                channel,
                "finished",
                cancelled=False,
                content=getattr(reply, "content", ""),
                reasoning=getattr(reply, "reasoning", None),
            )
            ledger = getattr(state.ctx, "ledger", None)
            if ledger is not None:
                state.publish("ui", "token_update", ledger=ledger.breakdown())
        state.hub.close_channel(channel)
        state.chat_running = False

    threading.Thread(target=_run, name=f"chat-{chat_id[:8]}", daemon=True).start()
    return {"ok": True, "chat_id": chat_id, "channel": channel}


@router.get("/stream/{chat_id}")
def stream_chat(chat_id: str, request: Request) -> StreamingResponse:
    state = get_state(request)
    sub_id, queue = state.hub.subscribe({f"chat:{chat_id}", "ui"})
    return StreamingResponse(
        sse_stream(queue, sub_id, state), media_type="text/event-stream"
    )


@router.post("/cancel")
def cancel_chat(request: Request) -> dict[str, Any]:
    state = get_state(request)
    token = state.chat_cancel_token
    if token is not None:
        token.set()
        state.chat_cancel_token = type(token)()
    return {"ok": True}


@router.get("/history")
def chat_history(request: Request) -> dict[str, Any]:
    state = get_state(request)
    session = state.chat_session
    if session is None:
        return {"ok": True, "history": []}
    return {"ok": True, "history": session.history_full}
