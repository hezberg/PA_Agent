"""冻结 LLM 优化对比测试的样本数据（ADR-001）。

分层抽样 20 支（沪主板6/深主板4/创业板3/科创板3/ETF2/港股2）× 30m × 100 根，
存 data/fixtures/llm_opt/<code>.json。K 线取自通达信（MacClient/MacExClient），
与 PA_Agent 分析管线的实际数据源一致。跑一次即可，两个分支共用。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "llm_opt"
WL_URL = "http://100.64.0.3:8765/api/ths/watchlist"
PER_COUNT = (30, 100)  # (分钟周期, 根数)


def load_watchlist() -> list[tuple[str, str, str]]:
    with urllib.request.urlopen(WL_URL, timeout=60) as r:
        wl = json.load(r)
    out = []
    for g in wl.get("groups", []):
        for it in g.get("items", []):
            out.append((it["sub_code"], it["market"], it.get("name", "")))
    # 去重（同一股票可出现在多个分组）
    seen, uniq = set(), []
    for c, m, n in out:
        if c not in seen:
            seen.add(c)
            uniq.append((c, m, n))
    return uniq


def stratify(codes: list[tuple[str, str, str]]) -> dict[str, list[tuple[str, str, str]]]:
    strata: dict[str, list[tuple[str, str, str]]] = {
        "SH_MAIN": [], "SZ_MAIN": [], "CY": [], "KC": [], "ETF": [], "HK": [],
    }
    for c, m, n in codes:
        mu = (m or "").upper()
        if mu in ("SHETF", "SZETF"):
            strata["ETF"].append((c, m, n))
        elif mu == "HK" or mu.isdigit():
            strata["HK"].append((c, m, n))
        elif mu in ("CY",) or (mu == "SZ" and c.startswith("30")):
            strata["CY"].append((c, m, n))
        elif mu in ("KC",) or (mu == "SH" and c.startswith("688")):
            strata["KC"].append((c, m, n))
        elif mu == "SZ":
            strata["SZ_MAIN"].append((c, m, n))
        elif mu in ("SH", "ST"):
            strata["SH_MAIN"].append((c, m, n))
    return strata


PLAN = {"SH_MAIN": 6, "SZ_MAIN": 4, "CY": 3, "KC": 3, "ETF": 2, "HK": 2}


def pick_sample(strata: dict[str, list]) -> list[tuple[str, str, str, str]]:
    sample = []
    for name, bucket in strata.items():
        bucket = sorted(bucket)  # 稳定抽样
        for c, m, n in bucket[: PLAN[name]]:
            sample.append((c, m, n, name))
    return sample


def fetch_bars(code: str, market: str, mac, ex):
    """返回 [(ts_open_ms, open, high, low, close, volume)]（时间升序）。"""
    from easy_tdx.mac.enums import Period

    if market == "HK" or market.isdigit():
        df = ex.goods_kline(31, code, Period.MIN_30, 0, 100)
    else:
        mkt = 1 if code.startswith(("5", "6", "68", "9")) else 0
        df = mac.get_stock_kline(mkt, code, Period.MIN_30, 0, 100)
    import pandas as pd

    df = df.dropna(subset=["close"])
    out = []
    for _, r in df.iterrows():
        ts = int(pd.Timestamp(r["datetime"]).timestamp() * 1000)
        out.append((ts, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["vol"])))
    return out  # 升序


def main() -> int:
    from easy_tdx import MacClient
    from easy_tdx.ex.mac_client import MacExClient
    from easy_tdx.mac.enums import Period

    codes = load_watchlist()
    strata = stratify(codes)
    sample = pick_sample(strata)
    print("抽样:", [(c, n or m) for c, m, n, _ in sample])

    mac = MacClient.from_best_host(timeout=15.0)
    mac.connect()
    ex = MacExClient.from_best_host()
    ex.connect()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for code, market, name, stratum in sample:
        try:
            bars = fetch_bars(code, market, mac, ex)
            if len(bars) < 50:
                print(f"  {code}: 仅 {len(bars)} 根，跳过", file=sys.stderr)
                continue
            bars = sorted(bars, key=lambda b: b[0], reverse=True)  # 存最新优先
            payload = {
                "symbol": code,
                "market": market,
                "name": name,
                "stratum": stratum,
                "timeframe": "30m",
                "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "bars": [
                    {"ts_open": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}
                    for ts, o, h, l, c, v in bars
                ],
            }
            path = OUT_DIR / f"{code}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            ok += 1
            print(f"  {code} {name}: {len(bars)} 根 → {path.name}")
            time.sleep(0.3)  # 对服务器礼貌一点
        except Exception as exc:  # noqa: BLE001
            print(f"  {code}: 失败 {str(exc)[:80]}", file=sys.stderr)
    mac.disconnect()
    try:
        ex.disconnect()
    except Exception:  # noqa: BLE001
        pass
    print(f"冻结完成: {ok}/{len(sample)}")
    return 0 if ok >= 18 else 1


if __name__ == "__main__":
    sys.exit(main())
