"""同花顺自选服务：登录态管理 + 自选清单拉取（只读）。

- PortfolioManager 进程级单例，按 (username, password) 失效重建；
- cookie 缓存于 data_cache/ths_cookie.json（库自身 24h TTL），过期自动用密码重登；
- 拉取失败进入冷却（默认 120s），防止前端 30 分钟轮询 + 手动刷新打爆接口；
- 「我的自选」虚拟分组（group_id=__selfstock__）排在首位；
- 市场码映射：SH/SZ/BJ/KC/CY → 6 位裸代码，HK → 5 位（zfill），即可直接订阅通达信源。
"""
from __future__ import annotations

import logging
import threading
import time as _time
from pathlib import Path
from typing import Any

from pa_agent.config.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

_COOKIE_CACHE = PROJECT_ROOT / "data_cache" / "ths_cookie.json"
_FAIL_COOLDOWN_S = 120.0

_LOCK = threading.Lock()
_MANAGER: Any = None
_MANAGER_KEY: tuple[str, str] | None = None
_LAST_FAIL_TS: float = 0.0
#: 最近一次成功拉取的自选清单（失败时兜底返回）
_LAST_GOOD_WATCHLIST: dict[str, Any] | None = None


def _friendly_error(exc: Exception) -> str:
    """把库的异常翻译成给用户看的一句话。"""
    from pa_agent.vendor.ths_favorite.exceptions import THSAPIError, THSNetworkError

    if isinstance(exc, THSAPIError):
        return f"同花顺接口返回错误：{exc}"
    if isinstance(exc, THSNetworkError):
        return f"网络请求失败：{exc}（检查服务器网络）"
    return f"登录/请求失败：{exc}"


def _build_manager(username: str, password: str) -> Any:
    from pa_agent.vendor.ths_favorite import PortfolioManager

    _COOKIE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    # enable_cache=False：禁用库往 CWD 写 ths_favorite_cache.json；兜底缓存由本模块负责。
    return PortfolioManager(
        username=username,
        password=password,
        cookie_cache_path=str(_COOKIE_CACHE),
        enable_cache=False,
    )


def _creds(settings: Any) -> tuple[str, str]:
    ths = getattr(settings, "ths", None)
    return (
        str(getattr(ths, "username", "") or "").strip(),
        str(getattr(ths, "password", "") or ""),
    )


def _get_manager(settings: Any) -> Any:
    """凭据未变时复用单例；变化（重登/退出再登录）则重建（构造即登录）。"""
    global _MANAGER, _MANAGER_KEY
    username, password = _creds(settings)
    if not username or not password:
        return None
    key = (username, password)
    if _MANAGER is not None and _MANAGER_KEY == key:
        return _MANAGER
    _MANAGER = _build_manager(username, password)
    _MANAGER_KEY = key
    return _MANAGER


def _drop_manager() -> None:
    global _MANAGER, _MANAGER_KEY, _LAST_GOOD_WATCHLIST
    _MANAGER = None
    _MANAGER_KEY = None
    _LAST_GOOD_WATCHLIST = None


def _subscribable_code(code: str, market: str | None) -> str:
    """同花顺 市场码+代码 → 本系统可直接订阅的代码。"""
    m = (market or "").upper()
    c = str(code or "").strip()
    if m == "HK":
        return c.zfill(5)
    return c  # SH/SZ/BJ/KC/CY：6 位裸代码本身可路由


def _zh_name(code: str, market: str | None) -> str | None:
    """本地名称表回填中文名；上证 000xxx 系指数优先按 sh 前缀查，避免命中深市同名代码。"""
    from pa_agent.data.symbol_search import symbol_name

    m = (market or "").upper()
    if m == "SH" and str(code).startswith("000"):
        name = symbol_name(f"sh{code}")
        if name:
            return name
    return symbol_name(code)


def login(settings: Any, username: str, password: str) -> dict[str, Any]:
    """验证账号密码并持久化（设置页「登录」按钮）。"""
    global _MANAGER, _MANAGER_KEY
    username = (username or "").strip()
    if not username or not password:
        return {"ok": False, "error": "请输入同花顺账号和密码"}
    try:
        manager = _build_manager(username, password)
        manager.get_all_groups(include_self_stocks=True)  # 登录成功性校验
    except Exception as exc:  # noqa: BLE001
        logger.warning("THS login failed for %s: %s", username[:3] + "***", exc)
        return {"ok": False, "error": _friendly_error(exc)}
    with _LOCK:
        _MANAGER = manager
        _MANAGER_KEY = (username, password)
    ths = getattr(settings, "ths", None)
    if ths is not None:
        ths.username = username
        ths.password = password
        ths.enabled = True
    return {"ok": True, "username": username}


def logout(settings: Any) -> dict[str, Any]:
    """退出：清凭据与登录态，删除本地 cookie 缓存。"""
    with _LOCK:
        _drop_manager()
    try:
        _COOKIE_CACHE.unlink(missing_ok=True)
    except OSError:
        pass
    ths = getattr(settings, "ths", None)
    if ths is not None:
        ths.enabled = False
        ths.username = ""
        ths.password = ""
    return {"ok": True}


def fetch_watchlist(settings: Any, *, force: bool = False) -> dict[str, Any]:
    """拉取全部分组 + 股票（含中文名）。cookie 失效时静默重登一次。

    force=True（手动刷新）绕过失败冷却。
    """
    global _LAST_FAIL_TS, _LAST_GOOD_WATCHLIST
    username, password = _creds(settings)
    if not username or not password:
        return {"ok": False, "error": "未登录", "logged_in": False}

    with _LOCK:
        if not force and (_time.monotonic() - _LAST_FAIL_TS) < _FAIL_COOLDOWN_S:
            if _LAST_GOOD_WATCHLIST is not None:
                return {**_LAST_GOOD_WATCHLIST, "stale": True}
            return {"ok": False, "error": "稍前一次拉取失败，冷却中（约 2 分钟后再试）"}

    def _fetch_once() -> dict[str, Any]:
        manager = _get_manager(settings)
        groups: dict[str, Any] = manager.get_all_groups(include_self_stocks=True)
        out_groups: list[dict[str, Any]] = []
        for name, group in groups.items():
            items = [
                {
                    "code": it.code,
                    "market": it.market or "",
                    "sub_code": _subscribable_code(it.code, it.market),
                    "name": _zh_name(it.code, it.market) or "",
                }
                for it in group.items
            ]
            out_groups.append(
                {
                    "id": group.group_id,
                    "name": group.name or name,
                    "readonly": bool(group.readonly),
                    "items": items,
                }
            )
        return {"ok": True, "groups": out_groups, "fetched_at": _time.time()}

    try:
        result = _fetch_once()
    except Exception as exc:  # noqa: BLE001
        logger.info("THS watchlist fetch failed (%s); 静默重登后重试一次", exc)
        try:
            with _LOCK:
                _drop_manager_keep_cookie()
            result = _fetch_once()
        except Exception as exc2:  # noqa: BLE001
            with _LOCK:
                _LAST_FAIL_TS = _time.monotonic()
                stale = _LAST_GOOD_WATCHLIST
            if stale is not None:
                return {**stale, "stale": True}
            return {"ok": False, "error": _friendly_error(exc2)}

    with _LOCK:
        _LAST_GOOD_WATCHLIST = result
    return result


def _drop_manager_keep_cookie() -> None:
    """丢弃单例（下次访问用密码重登），保留 last-good 清单兜底。"""
    global _MANAGER, _MANAGER_KEY
    _MANAGER = None
    _MANAGER_KEY = None
