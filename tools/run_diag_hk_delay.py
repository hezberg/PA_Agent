"""实测 easy_tdx 扩展行情的港股报价延迟（仅交易时段内有意义）。

用法（港股交易时段 9:30-16:00 运行，午休 12:00-13:00 除外）：
    uv run --no-sync python tools/run_diag_hk_delay.py

判定：盘中 1 分钟 K 最新 bar 的结束时间落后墙上时钟 ≥14 分钟 → 延迟行情
（典型 15 分钟）；落后 <2 分钟 → 实时。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CN = ZoneInfo("Asia/Shanghai")


def _minute_bar_check(ex, now: datetime) -> None:
    """盘中拉 1 分钟 K：最新 bar 时间戳落后墙上时钟多久 = 实际延迟。"""
    from easy_tdx import ExMarket, Period

    df = ex.goods_kline(
        market=ExMarket.HK_MAIN_BOARD,
        code="00700",
        period=Period.MIN_1,
        start=0,
        count=3,
    )
    if df is None or df.empty:
        print("\n✗ 未取到 1 分钟 K")
        return
    print("\n== 00700 最新 1 分钟 K（判定延迟的核心依据）==")
    print(df[["datetime", "close", "vol"]].to_string())
    last = str(df.iloc[-1]["datetime"])
    try:
        bar_end = pd.Timestamp(last).tz_localize(CN)
        lag_min = (now.astimezone(CN) - bar_end).total_seconds() / 60
        print(f"\n最新 bar 结束于 {last}，落后墙上时钟 {lag_min:.1f} 分钟")
        print("判定：≥14 分钟 → 延迟行情（典型 15 分钟）；<2 分钟 → 实时")
        print("（仅交易时段内有效；午休/盘后请看该 bar 是否为时段最后一根）")
    except Exception as exc:  # noqa: BLE001
        print(f"\n时间戳解析失败（{exc}）——请人工对照富途 1 分线最新 bar 时间")


def main() -> int:
    from easy_tdx import ExMarket, MacExClient

    now = datetime.now(CN)
    print(f"本机时间: {now:%Y-%m-%d %H:%M:%S}")
    if now.weekday() >= 5:
        print("⚠ 今天是周末，港股休市——延迟实测需在交易日盘中运行")
    hhmm = now.hour * 100 + now.minute
    if not (930 <= hhmm <= 1200 or 1300 <= hhmm <= 1600):
        print("⚠ 当前不在港股交易时段（9:30-12:00 / 13:00-16:00），数据为最后成交快照")

    ex = MacExClient.from_best_host()
    ex.connect()
    try:
        df = ex.goods_quotes(
            [(ExMarket.HK_MAIN_BOARD, code) for code in ("00700", "09988", "03690")]
        )
        if df is None or df.empty:
            print("✗ 未取到报价")
            return 1
        cols = ["code", "name", "close", "pre_close", "vol"]
        print("\n== 港股报价（扩展行情）==")
        print(df[cols].to_string())
        _minute_bar_check(ex, now)
        return 0
    finally:
        try:
            ex.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
