"""Settings persistence + derived display helpers (Qt-free)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def persist_settings(settings: Any, path: Any = None) -> None:
    """Save settings to disk (best-effort; failures are logged, not raised)."""
    try:
        from pa_agent.config.settings import save_settings

        if path is None:
            save_settings(settings)
        else:
            save_settings(settings, path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to persist settings: %s", exc)


def has_api_key(settings: Any) -> bool:
    from pa_agent.config.settings import provider_api_key_configured

    return provider_api_key_configured(settings)


def ai_mode_label(settings: Any) -> str:
    """Toolbar text describing current thinking / effort / model."""
    if settings is None:
        return ""
    p = settings.provider
    thinking = "开" if p.thinking else "关"
    return f"模型: {p.model} · 思考={thinking} · effort={p.reasoning_effort}"


def rebuild_ai_client(ctx: Any) -> None:
    """Re-create the AI client after provider settings changed."""
    from pa_agent.ai.client_factory import create_ai_client

    ctx.client = create_ai_client(ctx.settings.provider, logger_=logger)
    key = getattr(ctx.settings.provider, "api_key", "") or ""
    try:
        from pa_agent.util.logging import update_api_key

        update_api_key(key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("update_api_key failed: %s", exc)


def rebuild_data_source_if_kind_changed(ctx: Any) -> None:
    """Re-create the data source when the persisted kind no longer matches ctx."""
    from pa_agent.data.factory import (
        create_data_source,
        normalize_data_source_kind,
    )

    settings = getattr(ctx, "settings", None)
    kind = normalize_data_source_kind(
        getattr(getattr(settings, "general", None), "last_data_source", "easytdx") or "easytdx"
    )
    current = getattr(ctx, "data_source", None)
    current_kind = getattr(current, "kind", None)
    if current is not None and current_kind == kind:
        return
    try:
        ctx.data_source = create_data_source(kind)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rebuild_data_source failed: %s", exc)
