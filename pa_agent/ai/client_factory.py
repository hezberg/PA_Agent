"""Construct the AI client. Single route since the 2026-09 slim-down:
any OpenAI-compatible endpoint (base_url + api_key + model)."""

from __future__ import annotations

import logging
from typing import Any

from pa_agent.config.settings import AIProviderSettings


def create_ai_client(
    settings: AIProviderSettings,
    logger_: logging.Logger | None = None,
) -> Any:
    """Return the OpenAI-compatible client for *settings*."""
    log = logger_ or logging.getLogger(__name__)
    model = (settings.model or "").strip().lower()
    if model.startswith("openclaw"):
        log.warning(
            "模型 %s 属于 openclaw 工具链路由（已在精简中移除）。"
            "请在「AI 模型设置」改用任意 OpenAI 兼容端点（base_url + key + model）。",
            settings.model,
        )
    from pa_agent.ai.deepseek_client import DeepSeekClient

    log.info(
        "AI client route: OpenAI-compatible (model=%s base_url=%s)",
        settings.model,
        settings.base_url or "(empty)",
    )
    return DeepSeekClient(settings=settings, logger_=log)
