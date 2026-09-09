"""Settings routes: read/update config, feishu test send."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from pa_agent.server.routes.common import get_state, json_safe

router = APIRouter(prefix="/api/settings", tags=["settings"])

_MASK = "••••••••"


class SettingsUpdate(BaseModel):
    provider: dict[str, Any] | None = None
    general: dict[str, Any] | None = None
    prompt: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    feishu: dict[str, Any] | None = None
    pushplus: dict[str, Any] | None = None
    tushare: dict[str, Any] | None = None
    ths: dict[str, Any] | None = None


class FeishuTestBody(BaseModel):
    webhook_url: str
    secret: str = ""


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return _MASK
    return f"{key[:4]}{_MASK}{key[-4:]}"


@router.get("")
def get_settings(request: Request) -> dict[str, Any]:
    state = get_state(request)
    settings = state.settings()
    if settings is None:
        return {"ok": False, "error": "设置未加载"}
    payload = json_safe(settings.model_dump())
    provider = payload.get("provider") or {}
    if provider.get("api_key"):
        provider["api_key_masked"] = _mask_key(provider["api_key"])
        provider["api_key"] = ""  # never echo the real key
    provider["api_key_configured"] = bool(
        getattr(settings.provider, "api_key", "")
        or getattr(settings.provider, "api_key_encrypted", "")
    )
    ths = payload.get("ths") or {}
    if ths.get("password"):
        ths["password"] = _MASK  # never echo the real password
    ths["password_configured"] = bool(getattr(settings.ths, "password", ""))
    return {"ok": True, "settings": payload}


@router.put("")
def put_settings(request: Request, body: SettingsUpdate) -> dict[str, Any]:
    state = get_state(request)
    settings = state.settings()
    if settings is None:
        return {"ok": False, "error": "设置未加载"}

    updates = body.model_dump(exclude_none=True)
    for section, values in updates.items():
        if not isinstance(values, dict):
            continue
        current = getattr(settings, section, None)
        if current is None:
            continue
        # Empty api_key means "keep existing" (frontend sends masked placeholder).
        if section == "provider":
            values.pop("api_key_configured", None)
            values.pop("api_key_masked", None)
            if not str(values.get("api_key") or "").strip():
                values.pop("api_key", None)
        if section == "ths":
            values.pop("password_configured", None)
            # 掩码/空密码表示「保留原值」，避免回显值覆盖真实密码
            if str(values.get("password") or "").strip() in ("", _MASK):
                values.pop("password", None)
        cleaned = {k: v for k, v in values.items() if k in current.model_fields}
        if cleaned:
            setattr(settings, section, current.model_copy(update=cleaned))

    from pa_agent.config.paths import SETTINGS_JSON_PATH
    from pa_agent.services.settings_service import (
        persist_settings,
        rebuild_ai_client,
    )

    persist_settings(settings, SETTINGS_JSON_PATH)
    rebuild_ai_client(state.ctx)

    from pa_agent.ai.client_factory import create_ai_client  # noqa: F401

    state.publish("ui", "settings_updated")
    return {"ok": True}


@router.post("/feishu/test")
def feishu_test(request: Request, body: FeishuTestBody) -> dict[str, Any]:
    """Send a test text message to a Feishu webhook (runs in the threadpool)."""
    webhook_url = body.webhook_url.strip()
    if not webhook_url:
        return {"ok": False, "error": "请先填写 Webhook URL 再测试。"}
    payload: dict = {
        "msg_type": "text",
        "content": {"text": "✅ PA Agent 飞书通知测试消息，配置正常！"},
    }
    secret = body.secret.strip()
    if secret:
        ts = int(time.time())
        string_to_sign = f"{ts}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        payload["timestamp"] = str(ts)
        payload["sign"] = base64.b64encode(hmac_code).decode("utf-8")
    try:
        import requests

        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        result = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"HTTP 请求失败：\n{exc}"}
    if result.get("code") == 0 or result.get("StatusCode") == 0:
        return {"ok": True, "message": "测试消息已成功发送到飞书群，请查收！"}
    code = result.get("code", result.get("StatusCode", "?"))
    msg = result.get("msg", "")
    return {"ok": False, "error": f"发送失败（code={code}）：{msg}"}
