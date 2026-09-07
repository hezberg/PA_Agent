"""Unit tests for the easy_tdx (通达信) data source.

The mock client mirrors the verified live behaviour of easy-tdx 1.32.4:
intraday datetime labels are bar-END times; daily/weekly labels are period-END
dates; invalid codes return an empty DataFrame.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from pa_agent.data.base import DataSourceTransientError
from pa_agent.data.easytdx_source import (
    EasyTdxSource,
    _hk_session_open,
    _row_time_to_ts_ms,
    resolve_hk,
    resolve_market,
    resolve_route,
)
from pa_agent.data.kline_adjust import set_kline_adjust

_CN = ZoneInfo("Asia/Shanghai")


def _cn_ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_CN).timestamp() * 1000)


class MockTdxClient:
    """Scripted stand-in for easy_tdx.MacClient."""

    def __init__(self, frames: dict | None = None, error: Exception | None = None):
        # key: (market, code, start) → DataFrame
        self.frames = frames or {}
        self.error = error
        self.calls: list[tuple] = []

    def connect(self) -> None:
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        pass

    def get_stock_kline(self, market, code, period, start=0, count=800, adjust=None):
        self.calls.append((market, code, period, start, count, adjust))
        return self.frames.get((market, code, start))


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["datetime", "open", "high", "low", "close", "vol", "amount", "float_shares"],
    )


def _bar_row(ts: str, close: float = 10.0) -> dict:
    return {
        "datetime": ts,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "vol": 1234.0,
        "amount": 5678.0,
        "float_shares": 1.0,
    }


# ── Market resolution ─────────────────────────────────────────────────────────

def test_resolve_market_stock_rules() -> None:
    assert resolve_market("600519") == (1, "600519", False)   # 沪主板
    assert resolve_market("688981") == (1, "688981", False)   # 科创板
    assert resolve_market("000001") == (0, "000001", False)   # 深主板（平安银行）
    assert resolve_market("300750") == (0, "300750", False)   # 创业板
    assert resolve_market("830799") == (2, "830799", False)   # 北交所
    assert resolve_market("920002") == (2, "920002", False)   # 北交所


def test_resolve_market_index_rules() -> None:
    assert resolve_market("sh000300") == (1, "000300", True)
    assert resolve_market("399006") == (0, "399006", True)
    assert resolve_market("880001") == (1, "880001", True)


def test_resolve_market_etf_and_fund_rules() -> None:
    assert resolve_market("510300") == (1, "510300", False)   # 沪 ETF
    assert resolve_market("588000") == (1, "588000", False)   # 科创 ETF
    assert resolve_market("561980") == (1, "561980", False)   # 沪 ETF
    assert resolve_market("501000") == (1, "501000", False)   # 沪 LOF
    assert resolve_market("159915") == (0, "159915", False)   # 深 ETF
    assert resolve_market("160119") == (0, "160119", False)   # 深 LOF


def test_resolve_market_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        resolve_market("XAUUSDm")
    with pytest.raises(ValueError):
        resolve_market("123456")  # 无规则匹配的 6 位数字


# ── Label convention (END → START) ────────────────────────────────────────────

def test_intraday_end_label_shifted_to_start(monkeypatch) -> None:
    monkeypatch.setattr("pa_agent.data.easytdx_source._ashare_session_open", lambda: False)
    src = EasyTdxSource(
        client=MockTdxClient(
            {
                (0, "000001", 0): _frame(
                    [
                        _bar_row("2026-09-04 14:45:00", 11.0),
                        _bar_row("2026-09-04 15:00:00", 11.9),
                    ]
                )
            }
        )
    )
    src._connected = True
    src._market, src._code, src._is_index = 0, "000001", False
    src._timeframe = "15m"
    bars = src.latest_snapshot(5)
    assert len(bars) == 2
    # 结束标签 14:45/15:00 → 开始时刻 14:30/14:45
    assert bars[0].ts_open == _cn_ms("2026-09-04 14:45:00")
    assert bars[1].ts_open == _cn_ms("2026-09-04 14:30:00")
    assert bars[0].close == 11.9
    assert bars[0].volume == 1234.0
    assert bars[0].amount == 5678.0


def test_daily_label_kept_as_is(monkeypatch) -> None:
    monkeypatch.setattr("pa_agent.data.easytdx_source._ashare_session_open", lambda: False)
    src = EasyTdxSource(
        client=MockTdxClient(
            {(1, "600519", 0): _frame([_bar_row("2026-09-04 00:00:00", 1330.0)])}
        )
    )
    src._connected = True
    src._market, src._code, src._is_index = 1, "600519", False
    src._timeframe = "1d"
    bars = src.latest_snapshot(5)
    assert bars[0].ts_open == _cn_ms("2026-09-04 00:00:00")


def test_newest_first_order_and_seq(monkeypatch) -> None:
    monkeypatch.setattr("pa_agent.data.easytdx_source._ashare_session_open", lambda: False)
    rows = [_bar_row(f"2026-09-0{d} 00:00:00", 10.0 + d) for d in (1, 2, 3)]
    src = EasyTdxSource(client=MockTdxClient({(1, "600519", 0): _frame(rows)}))
    src._connected = True
    src._market, src._code, src._is_index = 1, "600519", False
    src._timeframe = "1d"
    bars = src.latest_snapshot(5)
    assert [b.seq for b in bars] == [1, 2, 3]
    assert bars[0].close == 13.0  # 最新在前
    assert bars[-1].close == 11.0


# ── Closed / forming semantics ────────────────────────────────────────────────

def test_head_bar_forming_only_when_session_open(monkeypatch) -> None:
    rows = [_bar_row("2026-09-04 14:45:00"), _bar_row("2026-09-04 15:00:00")]
    src = EasyTdxSource(client=MockTdxClient({(1, "600519", 0): _frame(rows)}))
    src._connected = True
    src._market, src._code, src._is_index = 1, "600519", False
    src._timeframe = "15m"

    monkeypatch.setattr("pa_agent.data.easytdx_source._ashare_session_open", lambda: True)
    bars = src.latest_snapshot(5)
    assert bars[0].closed is False   # 盘中 → 最新 bar 形成中
    assert bars[1].closed is True

    monkeypatch.setattr("pa_agent.data.easytdx_source._ashare_session_open", lambda: False)
    bars = src.latest_snapshot(5)
    assert all(b.closed for b in bars)  # 盘外/午休 → 全部已收盘


# ── Adjust mapping ────────────────────────────────────────────────────────────

def test_adjust_follows_global_setting_for_stocks(monkeypatch) -> None:
    from easy_tdx import Adjust

    seen: dict = {}

    class RecordingClient(MockTdxClient):
        def get_stock_kline(self, market, code, period, start=0, count=800, adjust=None):
            seen["adjust"] = adjust
            return _frame([_bar_row("2026-09-04 00:00:00")])

    set_kline_adjust("hfq")
    src = EasyTdxSource(client=RecordingClient())
    src._connected = True
    src._market, src._code, src._is_index = 1, "600519", False
    src._timeframe = "1d"
    src.latest_snapshot(5)
    assert seen["adjust"] == Adjust.HFQ
    set_kline_adjust("qfq")


def test_index_always_unadjusted(monkeypatch) -> None:
    from easy_tdx import Adjust

    seen: dict = {}

    class RecordingClient(MockTdxClient):
        def get_stock_kline(self, market, code, period, start=0, count=800, adjust=None):
            seen["adjust"] = adjust
            return _frame([_bar_row("2026-09-04 00:00:00")])

    set_kline_adjust("qfq")
    src = EasyTdxSource(client=RecordingClient())
    src._connected = True
    src._market, src._code, src._is_index = 1, "000300", True
    src._timeframe = "1d"
    src.latest_snapshot(5)
    assert seen["adjust"] == Adjust.NONE


# ── HK routing ───────────────────────────────────────────────────────────────

def test_resolve_hk_codes() -> None:
    assert resolve_hk("00700") == (31, "00700", False)
    assert resolve_hk("700") == (31, "00700", False)      # 短代码补齐 5 位
    assert resolve_hk("0700") == (31, "00700", False)
    assert resolve_hk("hk00700") == (31, "00700", False)  # hk 前缀
    assert resolve_hk("HK.09988") == (31, "09988", False)
    assert resolve_hk("hsi") == (27, "HSI", True)         # 恒指
    assert resolve_hk("HSI") == (27, "HSI", True)


def test_resolve_hk_rejects_ashare_and_garbage() -> None:
    assert resolve_hk("600519") is None                   # 6 位仍走 A 股
    assert resolve_hk("000300") is None
    assert resolve_hk("sh000300") is None
    assert resolve_hk("") is None
    assert resolve_hk("XAUUSDm") is None


def test_resolve_route_dispatch() -> None:
    assert resolve_route("600519") == ("ashare", 1, "600519", False)
    assert resolve_route("399006") == ("ashare", 0, "399006", True)
    assert resolve_route("00700") == ("hk", 31, "00700", False)
    assert resolve_route("hsi") == ("hk", 27, "HSI", True)


class MockExClient:
    """Scripted stand-in for easy_tdx.MacExClient (港股扩展行情)."""

    def __init__(self, frames: dict | None = None, error: Exception | None = None):
        # key: (market, code, start) → DataFrame
        self.frames = frames or {}
        self.error = error
        self.calls: list[tuple] = []
        self.closed = False

    def connect(self) -> None:
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.closed = True

    def goods_kline(self, market, code, period, start=0, count=800, adjust=None):
        self.calls.append((market, code, period, start, count, adjust))
        return self.frames.get((market, code, start))


def _hk_source(monkeypatch, ex_client: MockExClient, session_open: bool = False) -> EasyTdxSource:
    src = EasyTdxSource(client=MockTdxClient(), ex_client=ex_client)
    src._connected = True
    src._ex_connected = True
    src.subscribe("00700", "15m")
    monkeypatch.setattr("pa_agent.data.easytdx_source._hk_session_open", lambda: session_open)
    return src


def test_hk_subscribe_routes_to_ex_channel(monkeypatch) -> None:
    ex = MockExClient({(31, "00700", 0): _frame([_bar_row("2026-09-04 16:00:00", 442.8)])})
    src = EasyTdxSource(client=MockTdxClient(), ex_client=ex)
    src._connected = True
    src._ex_connected = True
    src.subscribe("hk00700", "15m")
    assert src._kind == "hk"
    assert (src._market, src._code, src._is_index) == (31, "00700", False)
    assert src._symbol == "00700"  # 归一化后的展示代码
    assert ex.calls, "subscribe 应探测扩展行情"


def test_hk_snapshot_end_label_shift_and_closed(monkeypatch) -> None:
    # 港股下午时段 15:45/16:00 结束标签（实测 00700 15m）
    rows = [_bar_row("2026-09-04 15:45:00", 444.2), _bar_row("2026-09-04 16:00:00", 442.8)]
    src = _hk_source(monkeypatch, MockExClient({(31, "00700", 0): _frame(rows)}), session_open=False)
    bars = src.latest_snapshot(5)
    assert len(bars) == 2
    # 结束标签 15:45/16:00 → 开始时刻 15:30/15:45
    assert bars[0].ts_open == _cn_ms("2026-09-04 15:45:00")
    assert bars[1].ts_open == _cn_ms("2026-09-04 15:30:00")
    assert bars[0].close == 442.8
    assert all(b.closed for b in bars)  # 盘外 → 全部已收盘


def test_hk_head_bar_forming_in_session(monkeypatch) -> None:
    rows = [_bar_row("2026-09-04 15:45:00"), _bar_row("2026-09-04 16:00:00")]
    src = _hk_source(monkeypatch, MockExClient({(31, "00700", 0): _frame(rows)}), session_open=True)
    bars = src.latest_snapshot(5)
    assert bars[0].closed is False
    assert bars[1].closed is True


def test_hk_daily_bar_not_shifted(monkeypatch) -> None:
    src = _hk_source(
        monkeypatch,
        MockExClient({(31, "00700", 0): _frame([_bar_row("2026-09-04 00:00:00", 442.8)])}),
    )
    src._timeframe = "1d"
    bars = src.latest_snapshot(5)
    assert bars[0].ts_open == _cn_ms("2026-09-04 00:00:00")


def test_hk_index_hsi_subscription(monkeypatch) -> None:
    ex = MockExClient({(27, "HSI", 0): _frame([_bar_row("2026-09-04 00:00:00", 25650.9)])})
    src = EasyTdxSource(client=MockTdxClient(), ex_client=ex)
    src._connected = True
    src._ex_connected = True
    src.subscribe("hsi", "1d")
    assert (src._kind, src._market, src._code, src._is_index) == ("hk", 27, "HSI", True)
    monkeypatch.setattr("pa_agent.data.easytdx_source._hk_session_open", lambda: False)
    bars = src.latest_snapshot(5)
    assert bars[0].close == 25650.9
    # 指数固定不复权
    from easy_tdx import Adjust

    assert ex.calls[-1][5] == Adjust.NONE


def test_hk_subscribe_empty_maps_to_transient() -> None:
    ex = MockExClient()  # 一切皆空（代码不存在）
    src = EasyTdxSource(client=MockTdxClient(), ex_client=ex)
    src._connected = True
    src._ex_connected = True
    with pytest.raises(DataSourceTransientError):
        src.subscribe("99999", "1d")


def test_hk_ex_connect_failure_maps_to_transient() -> None:
    src = EasyTdxSource(
        client=MockTdxClient(),
        ex_client_factory=lambda: MockExClient(error=ConnectionError("refused")),
    )
    src._connected = True
    with pytest.raises(DataSourceTransientError, match="扩展行情"):
        src.subscribe("00700", "15m")


def test_hk_lazy_ex_client_connects_on_first_hk_subscribe() -> None:
    ex = MockExClient({(31, "00700", 0): _frame([_bar_row("2026-09-04 16:00:00")])})
    created: list = []

    def factory() -> MockExClient:
        created.append(ex)
        return ex

    src = EasyTdxSource(client=MockTdxClient(), ex_client_factory=factory)
    src._connected = True
    src.subscribe("00700", "1d")
    assert created == [ex]  # 港股首次订阅才建扩展行情连接


def test_disconnect_closes_ex_client() -> None:
    ex = MockExClient()
    src = EasyTdxSource(client=MockTdxClient(), ex_client=ex)
    src._connected = True
    src._ex_connected = True
    src.disconnect()
    assert ex.closed is True
    assert src._ex_client is None and src._ex_connected is False


def test_hk_session_open_windows() -> None:
    def dt(text: str) -> datetime:
        return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=_CN)

    assert _hk_session_open(dt("2026-09-04 10:30")) is True   # 上午盘
    assert _hk_session_open(dt("2026-09-04 12:30")) is False  # 午休
    assert _hk_session_open(dt("2026-09-04 14:00")) is True   # 下午盘
    assert _hk_session_open(dt("2026-09-04 16:30")) is False  # 收盘后
    assert _hk_session_open(dt("2026-09-05 10:30")) is False  # 周六


# ── Subscribe routing (stock → index fallback) ────────────────────────────────

def test_subscribe_falls_back_to_index_for_bare_000300() -> None:
    # 000300 作为深市个股查不到（空 DataFrame），作为沪指数有数据。
    client = MockTdxClient(
        {(1, "000300", 0): _frame([_bar_row("2026-09-04 00:00:00")])}
    )
    src = EasyTdxSource(client=client)
    src._connected = True
    src._client = client
    src.subscribe("000300", "1d")
    assert src._market == 1 and src._is_index is True


def test_subscribe_prefers_stock_for_000001() -> None:
    client = MockTdxClient(
        {(0, "000001", 0): _frame([_bar_row("2026-09-04 00:00:00")])}
    )
    src = EasyTdxSource(client=client)
    src._connected = True
    src._client = client
    src.subscribe("000001", "15m")
    assert src._market == 0 and src._is_index is False


def test_subscribe_rejects_unknown_code() -> None:
    client = MockTdxClient()  # 一切皆空
    src = EasyTdxSource(client=client)
    src._connected = True
    src._client = client
    with pytest.raises(DataSourceTransientError):
        src.subscribe("000300", "1d")


def test_subscribe_rejects_4h() -> None:
    src = EasyTdxSource(client=MockTdxClient())
    with pytest.raises(ValueError, match="4h"):
        src.subscribe("600519", "4h")


def test_supported_timeframes_exclude_4h() -> None:
    src = EasyTdxSource()
    tfs = src.supported_timeframes()
    assert "4h" not in tfs
    assert set(tfs) == {"1m", "5m", "15m", "30m", "1h", "1d", "1w"}


# ── Error mapping ─────────────────────────────────────────────────────────────

def test_connect_failure_maps_to_transient() -> None:
    src = EasyTdxSource(
        client_factory=lambda: MockTdxClient(error=ConnectionError("refused"))
    )
    with pytest.raises(DataSourceTransientError):
        src.connect()


def test_snapshot_without_subscribe_maps_to_transient() -> None:
    src = EasyTdxSource(client=MockTdxClient())
    src._connected = True
    with pytest.raises(DataSourceTransientError):
        src.latest_snapshot(10)


# ── Paging guard ──────────────────────────────────────────────────────────────

def test_paging_stops_when_no_older_rows(monkeypatch) -> None:
    monkeypatch.setattr("pa_agent.data.easytdx_source._ashare_session_open", lambda: False)
    page0 = _frame([_bar_row("2026-09-04 00:00:00")])

    class RepeatClient(MockTdxClient):
        def get_stock_kline(self, market, code, period, start=0, count=800, adjust=None):
            self.calls.append(start)
            return _frame([_bar_row("2026-09-04 00:00:00")])  # 永远同一根

    src = EasyTdxSource(client=RepeatClient())
    src._connected = True
    src._market, src._code, src._is_index = 1, "600519", False
    src._timeframe = "1d"
    bars = src.latest_snapshot(50)  # 请求 50 根，历史只有 1 根
    assert len(bars) == 1           # 护栏生效：不重复拼接


# ── Timestamp parsing ─────────────────────────────────────────────────────────

def test_row_time_parses_common_formats() -> None:
    assert _row_time_to_ts_ms("2026-09-04 15:00:00") == _cn_ms("2026-09-04 15:00:00")
    assert _row_time_to_ts_ms("2026-09-04") == _cn_ms("2026-09-04 00:00:00")
    assert _row_time_to_ts_ms(datetime(2026, 9, 4, 15, 0, tzinfo=_CN)) == _cn_ms(
        "2026-09-04 15:00:00"
    )
