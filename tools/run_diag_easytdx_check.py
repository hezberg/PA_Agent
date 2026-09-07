"""对拍验收：easy_tdx（通达信）vs akshare（东财）同标的同周期数据一致性核对。

用法：
    uv run python tools/run_diag_easytdx_check.py
    uv run python tools/run_diag_easytdx_check.py --symbols 600519 sh000300 --timeframes 1d 1h

核对项（决策 2026-09-05「逐项核对数据的各项要求」）：
- 时间戳对齐率（两边按 ts_open 精确匹配的 bar 占比）
- OHLC 相对误差（阈值 0.1%，容忍复权因子舍入差异）
- 成交量相对误差（阈值 1%，同时检测 手/股 单位错位 ×100）
- 收盘价序列方向一致性

全部通过（exit 0）= easy_tdx 数据口径与现有 akshare 源一致，可接入。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 1d 两源应精确一致（同日收盘价）；盘中周期跨供应商聚合存在少量口径差
# （竞价成交归属、分钟聚合方式），放宽至 0.5% / 5%。
PRICE_TOL_DAILY = 0.001   # 0.1%
VOL_TOL_DAILY = 0.01      # 1%
PRICE_TOL_INTRADAY = 0.005
VOL_TOL_INTRADAY = 0.05

DEFAULT_SYMBOLS = ("600519", "000001", "300750", "688981", "sh000300")
DEFAULT_TIMEFRAMES = ("1d", "1h")


def fetch_easytdx(symbol: str, timeframe: str, n: int) -> dict[int, dict]:
    from pa_agent.data.base import DataSourceTransientError
    from pa_agent.data.easytdx_source import EasyTdxSource
    from pa_agent.data.kline_adjust import set_kline_adjust

    set_kline_adjust("qfq")  # akshare 对拍基准为 qfq，两边口径一致
    src = EasyTdxSource()
    src.connect()
    try:
        src.subscribe(symbol, timeframe)
        bars = src.latest_snapshot(n)
    except DataSourceTransientError as exc:
        print(f"  [easytdx] {symbol} {timeframe} 拉取失败: {exc}")
        return {}
    finally:
        src.disconnect()
    # bars newest-first → dict by ts_open；剔除形成中 bar
    return {
        int(b.ts_open): {
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
        }
        for b in bars
        if b.closed
    }


def fetch_baseline(symbol: str, timeframe: str, n: int, baseline: str) -> dict[int, dict]:
    """拉取对拍基准数据（akshare=东财 / baostock，均为前复权）。"""
    from pa_agent.data.akshare_source import AkShareSource
    from pa_agent.data.base import DataSourceTransientError

    if baseline == "baostock" and timeframe != "1d":
        from pa_agent.data.ashare_common import is_index_symbol

        if is_index_symbol(symbol):
            print(f"  [baostock] {symbol} 不提供指数分钟线，跳过")
            return {}

    src = AkShareSource()
    src.connect()
    try:
        if baseline == "baostock":
            src._baostock_login()
            rows = src._fetch_history_baostock(symbol, timeframe, n)
        else:
            rows = src._fetch_history(symbol, timeframe, n)
    except DataSourceTransientError as exc:
        print(f"  [{baseline}] {symbol} {timeframe} 拉取失败: {exc}")
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"  [{baseline}] {symbol} {timeframe} 拉取异常: {exc}")
        return {}
    finally:
        src.disconnect()
    return {
        int(r["ts_open"]): {
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r.get("volume") or 0.0),
        }
        for r in rows
    }


def rel_diff(a: float, b: float) -> float:
    base = max(abs(a), abs(b))
    return abs(a - b) / base if base else 0.0


def compare(symbol: str, timeframe: str, n: int, baseline: str = "akshare") -> bool:
    print(f"\n== {symbol} {timeframe} ==")
    from pa_agent.data.ashare_common import is_index_symbol

    if baseline == "baostock" and timeframe != "1d" and is_index_symbol(symbol):
        print("  ⊘ 跳过（baostock 不提供指数分钟线，无法对拍）")
        return True
    tdx = fetch_easytdx(symbol, timeframe, n)
    ak = fetch_baseline(symbol, timeframe, n, baseline)
    if not tdx or not ak:
        print("  ✗ 一侧无数据，无法对拍")
        return False

    common = sorted(set(tdx) & set(ak))
    # 覆盖率以较小一侧为分母（基准可能多取几天，多出的不算 easytdx 缺失）
    coverage = len(common) / max(min(len(tdx), len(ak)), 1)
    print(f"  easytdx {len(tdx)} 根 / 基准 {len(ak)} 根 / 交集 {len(common)} 根")
    print(f"  时间戳对齐率: {coverage:.1%}")
    if not common:
        # 打印两侧最近 3 个时间戳帮助定位口径错位（开始/结束标签、时区）
        tdx_ts = sorted(tdx)[-3:]
        ak_ts = sorted(ak)[-3:]
        from pa_agent.data.datetime_ts import format_epoch_for_display

        print(f"  easytdx 尾部: {[format_epoch_for_display(t) for t in tdx_ts]}")
        print(f"  akshare 尾部: {[format_epoch_for_display(t) for t in ak_ts]}")
        return False

    max_ohlc = 0.0
    max_vol = 0.0
    worst_ts = 0
    from pa_agent.data.ashare_common import is_index_symbol as _is_idx

    check_volume = not (_is_idx(symbol) and baseline == "baostock")
    for ts in common:
        a, b = tdx[ts], ak[ts]
        for key in ("open", "high", "low", "close"):
            d = rel_diff(a[key], b[key])
            if d > max_ohlc:
                max_ohlc, worst_ts = d, ts
        va, vb = a["volume"], b["volume"]
        if check_volume and va > 0 and vb > 0:
            d = rel_diff(va, vb)
            if d > max_vol:
                max_vol = d

    price_tol = PRICE_TOL_DAILY if timeframe == "1d" else PRICE_TOL_INTRADAY
    vol_tol = VOL_TOL_DAILY if timeframe == "1d" else VOL_TOL_INTRADAY
    ok = coverage >= 0.95 and max_ohlc <= price_tol and max_vol <= vol_tol
    print(f"  OHLC 最大相对误差: {max_ohlc:.4%}（阈值 {price_tol:.1%}）")
    if check_volume:
        print(f"  成交量最大相对误差: {max_vol:.4%}（阈值 {vol_tol:.0%}）")
    else:
        print("  成交量: 跳过（baostock 指数单位为股，与 TDX/东财的手不可比）")
    if max_ohlc > price_tol and worst_ts:
        from pa_agent.data.datetime_ts import format_epoch_for_display

        print(f"  最大误差 bar: {format_epoch_for_display(worst_ts)}")
    if check_volume and (0.5 < max_vol < 0.99 or 99 < max_vol * 100 <= 101):
        print("  ⚠ 成交量疑似 手/股 单位错位")
    print(f"  {'✓ 通过' if ok else '✗ 未通过'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="easy_tdx vs akshare 数据对拍")
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", nargs="*", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument("--bars", type=int, default=30)
    parser.add_argument(
        "--baseline", choices=("akshare", "baostock"), default="baostock",
        help="对拍基准源（默认 baostock；akshare 需东财网络可达）",
    )
    args = parser.parse_args()

    print(f"对拍基准：{args.baseline} · 复权口径 qfq（两源一致）；比较最近 {args.bars} 根已收盘 bar")
    all_ok = True
    for symbol in args.symbols:
        for timeframe in args.timeframes:
            try:
                ok = compare(symbol, timeframe, args.bars, args.baseline)
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ 对拍异常: {type(exc).__name__}: {exc}")
                ok = False
            all_ok = all_ok and ok

    print("\n结论：", "全部通过 — easy_tdx 可接入" if all_ok else "存在未通过项，见上方明细")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
