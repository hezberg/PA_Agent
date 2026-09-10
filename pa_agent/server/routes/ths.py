"""同花顺自选股路由：登录 / 退出 / 自选清单（只读）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from pa_agent.server.routes.common import get_state

router = APIRouter(prefix="/api/ths", tags=["ths"])


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""


@router.post("/login")
def ths_login(request: Request, body: LoginBody) -> dict[str, Any]:
    from pa_agent.server import ths_service

    state = get_state(request)
    settings = state.settings()
    result = ths_service.login(settings, body.username, body.password)
    if result.get("ok"):
        from pa_agent.config.settings import save_settings

        try:
            save_settings(settings)
        except Exception:  # noqa: BLE001 — 持久化失败不影响本次登录
            pass
    return result


@router.post("/logout")
def ths_logout(request: Request) -> dict[str, Any]:
    from pa_agent.server import ths_service

    state = get_state(request)
    settings = state.settings()
    result = ths_service.logout(settings)
    from pa_agent.config.settings import save_settings

    try:
        save_settings(settings)
    except Exception:  # noqa: BLE001
        pass
    return result


@router.get("/watchlist")
def ths_watchlist(request: Request, force: bool = False) -> dict[str, Any]:
    from pa_agent.server import ths_service

    return ths_service.fetch_watchlist(get_state(request).settings(), force=force)


@router.get("/quotes")
def ths_quotes_snapshot(request: Request) -> dict[str, Any]:
    """最新自选行情快照（后台线程按交易时段+间隔刷新；本接口即刻返回）。"""
    from pa_agent.server import ths_quotes

    state = get_state(request)
    ths_quotes.note_consumer_activity()
    return ths_quotes.get_snapshot()
