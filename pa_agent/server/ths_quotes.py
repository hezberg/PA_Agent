"""同花顺自选行情快照：批量拉自选股现价/当日涨跌（A 股 + 港股）。

- 单条长连接复用（A 股走 UnifiedTdxClient，港股走 MacExClient），失败重建并指数退避；
- 仅在交易时段拉取（A 股 9:15–11:30 / 13:00–15:15；港股 09:30–16:00；周一至周五，
  不含节假日表），收盘后自动停——数据不会变，拉了也白拉；
- 后台线程按 settings.ths.quotes_interval（默认 5s）刷新快照；仅当前端在消费
  （60 秒内有 GET /api/ths/quotes 请求）时才真正发请求，无人观看时零流量。
"""
from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime as _dt
from datetime import time as _dtime
from zoneinfo import ZoneInfo

from pa_agent.config.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

_CN_TZ = ZoneInfo("Asia/Shanghai")
_COOKIE_CACHE = PROJECT_ROOT / "data_cache" / "ths_cookie.json"
_CONSUMER_TTL_S = 60.0  # 前端超过这个时间没来取，就停止后台拉取
_FAIL_BACKOFF = [5.0, 10.0, 20.0, 30.0, 60.0]

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STARTED = False

# ── 运行态 ──
_SNAPSHOT: dict[str, dict[str, float]] = {}  # sub_code -> {price, change_pct}
_SNAPSHOT_TS: float = 0.0
_LAST_CONSUMER_TS: float = 0.0
_LAST_FAIL_TS: float = 0.0
_FAIL_COUNT: int = 0
_CODES: list[tuple[str, str]] = []  # [(sub_code, market)]，随自选清单更新


def note_consumer_activity() -> None:
    """前端来取快照时记录，用于判断是否有人在看（决定后台是否拉取）。"""
    global _LAST_CONSUMER_TS
    with _LOCK:
        _LAST_CONSUMER_TS = _time.monotonic()


def set_codes(codes: list[tuple[str, str]]) -> None:
    """自选清单更新后同步代码表 [(sub_code, market)]。"""
    global _CODES
    with _LOCK:
        _CODES = list(codes)


def get_snapshot() -> dict[str, Any]:
    """最新行情快照（即刻返回，不等待网络）。"""
    with _LOCK:
        return {
            "ok": True,
            "quotes": {k: dict(v) for k, v in _SNAPSHOT.items()},
            "fetched_at": _SNAPSHOT_TS,
            "interval": _interval_s(),
            "in_session": in_session(),
        }


def _interval_s(settings: Any = None) -> int:
    if settings is not None:
        ths = getattr(settings, "ths", None)
        if ths is not None:
            return int(max(1, min(120, getattr(ths, "quotes_interval", 5) or 5)))
    return 5


def in_session(now: _dt | None = None) -> bool:
    """A 股 9:15–11:30 / 13:00–15:15；港股 09:30–16:00（周一至五，忽略节假日）。"""
    now = now or _dt.now(tz=_CN_TZ)
    if now.weekday() >= 5:
        return False
    t = now.time()
    a_share = _dtime(9, 15) <= t <= _dtime(11, 30) or _dtime(13, 0) <= t <= _dtime(15, 15)
    hk = _dtime(9, 30) <= t <= _dtime(16, 0)
    return a_share or hk


def _split_codes() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """(sub_code, market) → (A 股 [(市场int, 代码)], 港股 [(市场int, 代码)])。

    market 标签含同花顺全家族：SH/SZ/BJ + SHETF/SZETF（ETF）+ ST（沪市ST）+
    ZS（指数）+ KC/CY/CYB（科创/创业）+ 数字市场号（177/169/185/120/217 等，
    为港股各板块变体）。未知标签一律按港股处理（拉不到也不会影响其他）。
    """
    a: list[tuple[int, str]] = []
    hk: list[tuple[int, str]] = []
    seen: set[str] = set()
    with _LOCK:
        codes = list(_CODES)
    for sub_code, market in codes:
        code = str(sub_code)
        if code in seen:  # 同一股票可出现在多个分组
            continue
        seen.add(code)
        m = str(market or "").upper()
        if m in ("SH", "KC", "SHETF", "ST"):
            a.append((1, code))  # 上交所（含科创板/ETF/ST）
        elif m in ("SZ", "CY", "CYB", "SZETF"):
            a.append((0, code))  # 深交所（含创业板/ETF）
        elif m in ("BJ", "151"):
            a.append((2, code))  # 北交所（151 为备用码）
        elif m == "ZS":
            a.append((0 if code.startswith("39") else 1, code))  # 指数按前缀分沪深
        else:
            # 港股（含 177/169/185/120/217 等数字市场号变体，代码形如 HK2162）
            raw = code
            if raw.upper().startswith("HK") and raw[2:].isdigit():
                c = raw[2:].zfill(5)
            elif code.isdigit() and len(code) <= 5:
                c = code.zfill(5)
            else:
                c = code
            hk.append((48 if len(c) == 5 and c[1] == "8" else 31, c))  # 创业板 / 主板
    return a, hk


def _chg(close: float, pre_close: float) -> float | None:
    if not pre_close:
        return None
    return round((close - pre_close) / pre_close * 100, 2)


def _fetch_round(a_client: Any, hk_client: Any) -> dict[str, dict[str, Any]]:
    """一轮批量拉取，返回 sub_code -> {price, change_pct, name}。"""
    out: dict[str, dict[str, Any]] = {}
    a, hk = _split_codes()

    def _absorb(df: pd.DataFrame) -> None:  # noqa: ANN001
        for _, r in df.iterrows():
            chg = _chg(float(r["close"]), float(r["pre_close"]))
            out[str(r["code"])] = {
                "price": float(r["close"]),
                "change_pct": chg if chg is not None else 0.0,
                "name": str(r.get("name", "") or ""),
            }

    if a and a_client is not None:
        for chunk in (a[i : i + 80] for i in range(0, len(a), 80)):
            _absorb(a_client.get_stock_quotes(chunk))
    if hk and hk_client is not None:
        for chunk in (hk[i : i + 80] for i in range(0, len(hk), 80)):
            _absorb(hk_client.goods_quotes(chunk))
    return out


def _loop(settings_getter) -> None:  # noqa: ANN001
    global _SNAPSHOT, _SNAPSHOT_TS, _LAST_FAIL_TS, _FAIL_COUNT
    logger.info("THS 行情快照线程启动")
    while True:
        try:
            now = _time.monotonic()
            interval = _interval_s(settings_getter())
            with _LOCK:
                has_consumer = (now - _LAST_CONSUMER_TS) < _CONSUMER_TTL_S
                fail_wait = (
                    _FAIL_BACKOFF[min(_FAIL_COUNT, len(_FAIL_BACKOFF) - 1)]
                    if _FAIL_COUNT
                    else 0.0
                )
                due = (now - _SNAPSHOT_TS) >= max(interval, fail_wait)
                active = has_consumer and in_session()
            if not (active and due):
                _time.sleep(1.0)
                continue

            settings = settings_getter()
            try:
                a_client, hk_client = _clients(settings)
                snapshot = _fetch_round(a_client, hk_client)
                with _LOCK:
                    if snapshot:  # 拉到空数据（如收盘瞬间）不覆盖旧快照
                        _SNAPSHOT = snapshot
                        _SNAPSHOT_TS = _time.monotonic()
                    _FAIL_COUNT = 0
            except Exception as exc:  # noqa: BLE001
                _FAIL_COUNT += 1
                _LAST_FAIL_TS = now
                logger.warning(
                    "THS 行情拉取失败（第 %s 次，退避 %ss）: %s",
                    _FAIL_COUNT,
                    _FAIL_BACKOFF[min(_FAIL_COUNT, len(_FAIL_BACKOFF) - 1)],
                    exc,
                )
                _reset_clients()
            _time.sleep(0.5)
        except Exception:  # noqa: BLE001 — 线程永生
            logger.exception("THS quotes loop error")
            _time.sleep(5.0)


_A_CLIENT: Any = None
_HK_CLIENT: Any = None


def _clients(settings: Any) -> tuple[Any, Any]:
    """惰性建连：已连接直接复用；断线由调用方重置重建。"""
    global _A_CLIENT, _HK_CLIENT
    from easy_tdx.ex.mac_client import MacExClient
    from easy_tdx.unified import UnifiedTdxClient

    if _A_CLIENT is None:
        c = UnifiedTdxClient()
        c.connect()
        _A_CLIENT = c
    if _HK_CLIENT is None:
        _HK_CLIENT = MacExClient.from_best_host()
        _HK_CLIENT.connect()
    return _A_CLIENT, _HK_CLIENT


def _reset_clients() -> None:
    global _A_CLIENT, _HK_CLIENT
    for c in (_A_CLIENT, _HK_CLIENT):
        try:
            if c is not None and hasattr(c, "disconnect"):
                c.disconnect()
        except Exception:  # noqa: BLE001
            pass
    _A_CLIENT = None
    _HK_CLIENT = None


def start_loop(settings_getter) -> None:
    """启动后台快照线程（幂等）。settings_getter 用于运行中动态读取刷新间隔。"""
    global _THREAD, _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    _THREAD = threading.Thread(
        target=_loop, args=(settings_getter,), name="ths-quotes", daemon=True
    )
    _THREAD.start()
