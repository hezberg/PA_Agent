"""A-share + HK K-line data source via the easy_tdx library (通达信 MAC protocol).

Scope (agreed 2026-09-05, HK added 2026-09-06): A股 + ETF + 指数 (MacClient,
port 7709) and 港股主板/恒指 (MacExClient 扩展行情, port 7727).  Timeframes
1m/5m/15m/30m/1h/1d/1w — the TDX protocol has no native 4h period, so ``4h``
is deliberately unsupported for this source.  Refresh polling is throttled to
≥10 s (see ``services/data_source_service.refresh_interval_ms``).

Verified live against easy-tdx 1.32.4 (MAC servers):

- ``MacClient.get_stock_kline(market, code, period, start, count, adjust)``
  returns columns ``datetime, open, high, low, close, vol, amount, float_shares``.
- ``MacExClient.goods_kline(ExMarket.HK_MAIN_BOARD=31 / HK_INDEX=27, ...)``
  returns the same columns (00700 腾讯控股 15m; HSI 恒生指数 daily).
- Intraday ``datetime`` labels are bar **END** times on both channels (A股
  morning 09:45→11:30, afternoon 13:15→15:00; HK afternoon …→16:00); daily/
  weekly/monthly labels are period-END dates (Friday for weeks, month-end for
  months).  PA_Agent's convention is bar **START** time, so intraday labels are
  shifted back by one period while daily/weekly/monthly labels already match
  akshare.
- HK time is UTC+8 like CN — timestamps need no cross-timezone handling.
- Invalid codes return an empty DataFrame → index fallback routing works.
- Index codes (000300 on SH, 399xxx on SZ) work through the same endpoint.
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pa_agent.data.base import (
    DataSource,
    DataSourceTransientError,
    KlineBar,
    normalize_kline_bar,
)
from pa_agent.data.datetime_ts import datetime_to_ts_ms
from pa_agent.data.kline_adjust import get_kline_adjust

logger = logging.getLogger(__name__)

_CN_TZ = ZoneInfo("Asia/Shanghai")

_SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "1d", "1w")

_PERIOD_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

_STOCK_CODE_RE = re.compile(r"^\d{6}$")
_PREFIX_RE = re.compile(r"^(sh|sz|bj)[(\d]{6}$", re.IGNORECASE)
_HK_CODE_RE = re.compile(r"^\d{1,5}$")
_HK_PREFIX_RE = re.compile(r"^hk[.\s]?", re.IGNORECASE)

_HK_MAIN_BOARD = 31  # easy_tdx ExMarket.HK_MAIN_BOARD（港股主板，实测可用）
_HK_INDEX = 27  # easy_tdx ExMarket.HK_INDEX（恒生指数 HSI，实测可用）
_HK_INDEX_CODES = {"hsi": "HSI"}  # 恒指；HSTECH 等扩展指数实测返回空，先不放开

_PRESET_SYMBOLS: tuple[str, ...] = (
    "000001",  # 平安银行
    "600519",  # 贵州茅台
    "000300",  # 沪深300（指数）
    "399006",  # 创业板指
    "00700",  # 腾讯控股（港股）
)


def resolve_market(symbol: str) -> tuple[int, str, bool]:
    """Resolve a user-entered symbol to ``(market, code, is_index)``.

    Market encoding follows easy_tdx ``Market``: SZ=0, SH=1, BJ=2.

    Rules (mirrors the akshare source conventions):
    - explicit ``sh``/``sz``/``bj`` prefix wins;
    - 60xxxx/68xxxx → SH stock, 00xxxx/30xxxx → SZ stock,
      43xxxx/83xxxx/87xxxx/92xxxx → BJ stock;
    - 000xxx/880xxx → SH index, 399xxx → SZ index;
    - a bare 6-digit code that matches no rule raises ValueError.
    """
    text = str(symbol or "").strip().lower()
    if _PREFIX_RE.match(text):
        prefix, code = text[:2], text[2:]
        market = {"sh": 1, "sz": 0, "bj": 2}[prefix]
        is_index = code.startswith("000") or code.startswith("399") or code.startswith("880")
        return market, code, is_index
    if not _STOCK_CODE_RE.match(text):
        raise ValueError("A股代码无效，请输入 6 位数字（如 600519）或指数 000300 / sh000300")
    if text.startswith(("60", "68")):
        return 1, text, False
    if text.startswith(("00", "30")):
        return 0, text, False
    if text.startswith(("43", "83", "87", "92")):
        return 2, text, False
    # ETF / LOF / 封基：沪 50/51/52/56/58，深 15/16/18（与个股同一行情接口）
    if text.startswith(("50", "51", "52", "56", "58")):
        return 1, text, False
    if text.startswith(("15", "16", "18")):
        return 0, text, False
    if text.startswith("399"):
        return 0, text, True
    if text.startswith(("000", "880")):
        return 1, text, True
    raise ValueError(f"无法识别的 A 股代码：{text}")


def resolve_hk(symbol: str) -> tuple[int, str, bool] | None:
    """Resolve a symbol to ``(ex_market, code, is_index)`` when it is HK, else None.

    HK codes are ≤5 digits (TDX pads to 5, e.g. 700/0700/00700 → 00700);
    ``hk``-prefixed forms (hk00700 / hk.00700) are accepted.  ``hsi`` routes to
    the 恒生指数 on ExMarket.HK_INDEX.  6-digit codes never match (A股 wins).
    """
    text = str(symbol or "").strip().lower()
    if not text:
        return None
    index_code = _HK_INDEX_CODES.get(text)
    if index_code:
        return _HK_INDEX, index_code, True
    text = _HK_PREFIX_RE.sub("", text)
    if not _HK_CODE_RE.match(text):
        return None
    return _HK_MAIN_BOARD, text.zfill(5), False


def resolve_route(symbol: str) -> tuple[str, int, str, bool]:
    """Route a symbol to ``(kind, market, code, is_index)``; kind is ``ashare``/``hk``."""
    hk = resolve_hk(symbol)
    if hk is not None:
        return "hk", hk[0], hk[1], hk[2]
    market, code, is_index = resolve_market(symbol)
    return "ashare", market, code, is_index


def _row_time_to_ts_ms(value: Any) -> int:
    """Parse an easy_tdx ``datetime`` cell (pd.Timestamp or str) to epoch ms (CN tz)."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_CN_TZ)
        return int(dt.timestamp() * 1000)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=_CN_TZ)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return datetime_to_ts_ms(text)


def _hk_session_open(now: datetime | None = None) -> bool:
    """True during the HK cash session (Mon–Fri, 09:30–12:00 & 13:00–16:00 HK).

    HK shares the UTC+8 wall clock with CN, so CN tz arithmetic applies directly.
    Half-day holidays are ignored (only affects the forming-bar flag).
    """
    now = now or datetime.now(tz=_CN_TZ)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    morning = 9 * 60 + 30 <= t < 12 * 60
    afternoon = 13 * 60 <= t < 16 * 60
    return morning or afternoon


class EasyTdxSource(DataSource):
    """A-share/HK quotes via easy_tdx MAC servers; polls on each snapshot."""

    def __init__(
        self,
        *,
        client: Any = None,
        client_factory: Callable[[], Any] | None = None,
        ex_client: Any = None,
        ex_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory or self._default_client_factory
        self._ex_client = ex_client
        self._ex_client_factory = ex_client_factory or self._default_ex_client_factory
        self._symbol: str = ""
        self._timeframe: str = ""
        self._kind: str = "ashare"
        self._market: int | None = None
        self._code: str = ""
        self._is_index: bool = False
        self._connected: bool = False
        self._ex_connected: bool = False
        # RefreshLoop thread and UI-triggered snapshot calls share one socket
        # per channel: A股 (7709) and 港股扩展行情 (7727) each get their own lock.
        self._lock = threading.Lock()
        self._ex_lock = threading.Lock()

    @staticmethod
    def _default_client_factory() -> Any:
        from easy_tdx import MacClient

        # 显式超时：防止服务器半开连接让 latest_snapshot 无限阻塞刷新线程。
        return MacClient.from_best_host(timeout=15.0)

    @staticmethod
    def _default_ex_client_factory() -> Any:
        from easy_tdx import MacExClient

        return MacExClient.from_best_host(timeout=15.0)

    # ── DataSource ABC ────────────────────────────────────────────────────────

    def connect(self) -> None:
        try:
            import easy_tdx  # noqa: F401
        except ImportError as exc:
            raise DataSourceTransientError(
                "未安装 easy_tdx，请执行: pip install easy-tdx"
            ) from exc
        with self._lock:
            if self._client is None:
                try:
                    self._client = self._client_factory()
                except Exception as exc:
                    raise DataSourceTransientError(
                        f"通达信服务器连接失败: {exc}"
                    ) from exc
            try:
                self._client.connect()
            except Exception as exc:
                self._client = None
                raise DataSourceTransientError(f"通达信服务器连接失败: {exc}") from exc
            self._connected = True
        logger.info("EasyTdxSource connected")

    def disconnect(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self._connected = False
        with self._ex_lock:
            ex_client = self._ex_client
            self._ex_client = None
            self._ex_connected = False
        for cl in (client, ex_client):
            if cl is not None:
                try:
                    cl.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("easy_tdx close failed: %s", exc)
        logger.info("EasyTdxSource disconnected")

    def list_symbols(self) -> list[str]:
        return list(_PRESET_SYMBOLS)

    def supported_timeframes(self) -> list[str]:
        # 通达信协议无原生 4h 周期 — 本源不支持 4h（决策 2026-09-05）。
        return list(_SUPPORTED_TIMEFRAMES)

    def subscribe(self, symbol: str, timeframe: str) -> None:
        if timeframe not in _SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"easytdx 源不支持周期 {timeframe!r}（通达信协议无 4h）。"
                f"可用周期: {list(_SUPPORTED_TIMEFRAMES)}"
            )
        kind, market, code, is_index = resolve_route(symbol)
        # Probe fetches share the socket with the refresh loop and the
        # startup background subscribe — serialize through the channel lock.
        if kind == "hk":
            self._ensure_ex_client()
            with self._ex_lock:
                try:
                    probe = self._fetch_hk_df(market, code, timeframe, count=2, is_index=is_index)
                except DataSourceTransientError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise DataSourceTransientError(f"港股订阅探测失败: {exc}") from exc
            if probe is None or len(probe) == 0:
                raise DataSourceTransientError(
                    f"通达信扩展行情未返回 {symbol} 数据（代码不存在或非港股主板/恒指）"
                )
            display = code
            route = "恒指" if is_index else "港股"
        else:
            # Probe-resolve the route: a bare 000xxx code probes as a SZ stock first
            # and falls back to the SH index only when the stock lookup is empty
            # (000300 etc.).  resolve_market maps 399xxx/880xxx to index directly.
            with self._lock:
                try:
                    probe = self._fetch_df(market, code, timeframe, count=2, is_index=False)
                except DataSourceTransientError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise DataSourceTransientError(f"订阅探测失败: {exc}") from exc
                if probe is None or len(probe) == 0 and code.startswith("000"):
                    alt = self._fetch_df(1, code, timeframe, count=2, is_index=True)
                else:
                    alt = None
            if probe is None or len(probe) == 0:
                if alt is not None and len(alt) > 0:
                    market, is_index = 1, True
                else:
                    raise DataSourceTransientError(
                        f"通达信未返回 {symbol} 数据（代码不存在或已退市）"
                    )
            display = str(symbol).strip()
            route = "指数" if is_index else "个股"
        self._kind = kind
        self._market, self._code, self._is_index = market, code, is_index
        self._symbol = display
        self._timeframe = timeframe
        logger.info("EasyTdxSource subscribed: %s %s (%s)", self._symbol, timeframe, route)

    def unsubscribe(self) -> None:
        self._symbol = ""
        self._timeframe = ""
        self._kind = "ashare"
        self._market = None
        self._code = ""
        self._is_index = False
        logger.info("EasyTdxSource unsubscribed")

    def latest_snapshot(self, n: int) -> list[KlineBar]:
        if not self._connected or self._client is None:
            raise DataSourceTransientError("easytdx 未连接")
        if not self._timeframe or self._market is None:
            raise DataSourceTransientError("easytdx 未订阅品种/周期")

        fetch_n = max(int(n) + 5, 30)
        if self._kind == "hk":
            with self._ex_lock:
                try:
                    df = self._fetch_hk_df(
                        self._market,
                        self._code,
                        self._timeframe,
                        count=fetch_n,
                        is_index=self._is_index,
                    )
                except DataSourceTransientError:
                    raise
                except Exception as exc:
                    logger.warning("easy_tdx HK fetch failed: %s", exc)
                    raise DataSourceTransientError(f"港股行情拉取失败: {exc}") from exc
        else:
            with self._lock:
                try:
                    df = self._fetch_df(
                        self._market,
                        self._code,
                        self._timeframe,
                        count=fetch_n,
                        is_index=self._is_index,
                    )
                except DataSourceTransientError:
                    raise
                except Exception as exc:
                    logger.warning("easy_tdx fetch failed: %s", exc)
                    raise DataSourceTransientError(f"通达信拉取失败: {exc}") from exc

        if df is None or len(df) == 0:
            raise DataSourceTransientError(
                f"通达信未返回数据: {self._symbol} {self._timeframe}"
            )

        rows_asc = df.to_dict("records")
        rows_newest = list(reversed(rows_asc))
        bars = self._rows_to_bars(rows_newest, n, self._timeframe, self._kind)
        if not bars:
            raise DataSourceTransientError(
                f"通达信返回数据为空: {self._symbol} {self._timeframe}"
            )
        return bars

    def server_time_ms(self) -> int | None:
        """TDX MAC servers expose no wall-clock endpoint we use — local time applies."""
        return None

    # ── Internals ─────────────────────────────────────────────────────────────

    def _ensure_ex_client(self) -> Any:
        """Lazily create + connect the 扩展行情 client (first HK use pays the cost)."""
        with self._ex_lock:
            if self._ex_client is None:
                try:
                    self._ex_client = self._ex_client_factory()
                except Exception as exc:
                    raise DataSourceTransientError(
                        f"通达信扩展行情服务器连接失败: {exc}"
                    ) from exc
            try:
                self._ex_client.connect()
            except Exception as exc:
                self._ex_client = None
                raise DataSourceTransientError(
                    f"通达信扩展行情服务器连接失败: {exc}"
                ) from exc
            self._ex_connected = True
            return self._ex_client

    def _fetch_df(
        self, market: int, code: str, timeframe: str, *, count: int, is_index: bool
    ) -> Any:
        """Fetch an A-share kline DataFrame; single call for typical sizes, paged beyond."""
        client = self._client
        if client is None:
            raise DataSourceTransientError("easytdx 未连接")
        period, _period_ms = self._period_for(timeframe)
        adjust = self._adjust_for(is_index)
        count = int(count)

        def fetch_one(start: int, n: int) -> Any:
            return client.get_stock_kline(
                market, code, period, start=start, count=n, adjust=adjust
            )

        return self._paged_klines(fetch_one, count, code)

    def _fetch_hk_df(
        self, market: int, code: str, timeframe: str, *, count: int, is_index: bool
    ) -> Any:
        """Fetch an HK kline DataFrame via the 扩展行情 channel (ex_client under its lock)."""
        ex_client = self._ex_client
        if ex_client is None:
            raise DataSourceTransientError("easytdx 扩展行情未连接")
        period, _period_ms = self._period_for(timeframe)
        adjust = self._adjust_for(is_index)
        count = int(count)

        def fetch_one(start: int, n: int) -> Any:
            return ex_client.goods_kline(
                market, code, period, start=start, count=n, adjust=adjust
            )

        return self._paged_klines(fetch_one, count, code)

    def _paged_klines(self, fetch_one: Callable[[int, int], Any], count: int, code: str) -> Any:
        """Single call for typical sizes; page backwards when history continues."""
        df = fetch_one(0, count)
        # Page backwards when the server returns fewer bars than asked for and
        # history may continue (macOS MAC hosts have served 1500 in one call).
        pages = 1
        got = 0 if df is None else len(df)
        while 0 < got < count and pages < 8:
            more = fetch_one(got, count - got)
            if more is None or len(more) == 0:
                break
            # Guard against servers that repeat data when start is past history:
            # the page must continue strictly backwards in time.
            try:
                if str(more["datetime"].iloc[-1]) >= str(df["datetime"].iloc[0]):
                    logger.debug("easy_tdx paging stopped: no older rows returned")
                    break
            except Exception:  # noqa: BLE001
                pass
            df = concat_frames(more, df)
            got += len(more)
            pages += 1
        return df

    @staticmethod
    def _period_for(timeframe: str) -> tuple[Any, int]:
        from easy_tdx import Period

        mapping = {
            "1m": Period.MIN_1,
            "5m": Period.MIN_5,
            "15m": Period.MIN_15,
            "30m": Period.MIN_30,
            "1h": Period.MIN_60,
            "1d": Period.DAILY,
            "1w": Period.WEEKLY,
        }
        period = mapping[timeframe]
        minutes = _PERIOD_MINUTES.get(timeframe, 0)
        return period, minutes * 60_000

    @staticmethod
    def _adjust_for(is_index: bool) -> Any:
        from easy_tdx import Adjust

        if is_index:
            return Adjust.NONE  # 指数无复权概念，固定不复权
        key = get_kline_adjust()
        return {"qfq": Adjust.QFQ, "hfq": Adjust.HFQ, "none": Adjust.NONE}.get(
            key, Adjust.QFQ
        )

    def _rows_to_bars(
        self,
        rows_newest_first: list[dict[str, Any]],
        n: int,
        timeframe: str,
        kind: str = "ashare",
    ) -> list[KlineBar]:
        period_ms = _PERIOD_MINUTES.get(timeframe, 0) * 60_000
        session_open = _hk_session_open() if kind == "hk" else _ashare_session_open()
        bars: list[KlineBar] = []
        for i, row in enumerate(rows_newest_first[: max(int(n), 0)]):
            ts_open = _row_time_to_ts_ms(row.get("datetime"))
            if period_ms:
                # MAC 协议分钟线 datetime 为 bar 结束时刻 → 归一为开始时刻。
                ts_open -= period_ms
            bars.append(
                normalize_kline_bar(
                    KlineBar(
                        seq=i + 1,
                        ts_open=float(ts_open),
                        open=float(row.get("open") or 0.0),
                        high=float(row.get("high") or 0.0),
                        low=float(row.get("low") or 0.0),
                        close=float(row.get("close") or 0.0),
                        volume=float(row.get("vol") or 0.0),
                        amount=float(row.get("amount") or 0.0),
                        closed=not (i == 0 and session_open),
                    )
                )
            )
        return bars


def concat_frames(older: Any, newer: Any) -> Any:
    """Concat ``older`` rows above ``newer`` rows (both oldest→newest)."""
    import pandas as pd

    return pd.concat([older, newer], ignore_index=True)


def _ashare_session_open() -> bool:
    """True when the A-share market is in a trading session right now."""
    try:
        from pa_agent.data.akshare_source import _ashare_session_open

        return _ashare_session_open()
    except ImportError:  # pragma: no cover - akshare missing
        return False
