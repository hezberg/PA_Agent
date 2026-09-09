"""FastAPI application factory: lifespan wiring, routers, static SPA hosting."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from pa_agent.server.state import AppState

logger = logging.getLogger(__name__)

_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def create_app(*, bootstrap: bool = True) -> FastAPI:
    app = FastAPI(title="PA Agent WebUI", docs_url="/api/docs", redoc_url=None)
    state = AppState()
    app.state.pa = state

    from pa_agent.server.routes import (
        analysis,
        chat,
        demo,
        market,
        records,
        settings,
        ths,
    )

    app.include_router(market.router)
    app.include_router(analysis.router)
    app.include_router(chat.router)
    app.include_router(settings.router)
    app.include_router(records.router)
    app.include_router(demo.router)
    app.include_router(ths.router)

    @app.on_event("startup")
    async def _startup() -> None:
        state.hub.attach_loop(asyncio.get_running_loop())
        if bootstrap:
            _bootstrap_ctx(state)
        else:
            logger.info("Skipping AppContext bootstrap (bootstrap=False)")

    @app.get("/api/health")
    def _health() -> dict[str, Any]:
        return {"ok": True, "app": "pa-agent-web"}

    # SPA hosting: serve web/dist assets with an index.html fallback.
    # dist 可能正被 vite 重建（目录短暂缺失），故逐项检查而非假设其完整。
    if (_WEB_DIST / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=_WEB_DIST / "assets"),
            name="assets",
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        def _spa(full_path: str) -> Response:
            candidate = (_WEB_DIST / full_path).resolve()
            if (
                full_path
                and candidate.is_file()
                and str(candidate).startswith(str(_WEB_DIST))
            ):
                return FileResponse(candidate)
            index = _WEB_DIST / "index.html"
            if not index.is_file():
                return Response("frontend is rebuilding, try again shortly", status_code=503)
            return FileResponse(index)

    return app


def _bootstrap_ctx(state: AppState) -> None:
    """Build the AppContext and initialise server-side trackers."""
    from pa_agent.app_context import AppContext
    from pa_agent.services.analysis_flow import BarCloseWait, KeepAnalysisTracker
    from pa_agent.services.data_source_service import normalize_symbol_for_kind

    try:
        state.ctx = AppContext.bootstrap()
    except Exception as exc:  # noqa: BLE001
        logger.error("AppContext bootstrap failed: %s", exc, exc_info=True)
        state.status(f"启动失败：{exc}")
        return

    settings = state.settings()
    general = getattr(settings, "general", None)
    from pa_agent.data.factory import normalize_data_source_kind

    kind = normalize_data_source_kind(
        getattr(general, "last_data_source", "easytdx") or "easytdx"
    )
    state.active_data_source_kind = kind

    state.bar_close_wait = BarCloseWait()
    state.keep_analysis_tracker = KeepAnalysisTracker()
    # 持续跟踪分析每次启动强制关闭（与 Qt 版一致，避免启动即自动分析）
    if general is not None and getattr(general, "keep_analysis", False):
        general.keep_analysis = False

    symbol = str(getattr(general, "last_symbol", "") or "").strip()
    if kind == "eastmoney_futures":
        symbol = normalize_symbol_for_kind(kind, symbol)

    from pa_agent.util.logging import update_api_key

    update_api_key(getattr(settings.provider, "api_key", "") or "")

    from pa_agent.server import market_service

    market_service.publish_ui_state(state)
    state.status("就绪")
    logger.info("WebUI context bootstrapped for %s", kind)
