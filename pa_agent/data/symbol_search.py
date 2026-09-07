"""股票名称 → 代码反查（easytdx 数据源）。

数据源（决策 2026-09-06）：

- A股/ETF/指数：baostock ``query_all_stock``（实测 7373 条，含
  贵州茅台/沪深300指数/华泰柏瑞沪深300ETF 等，一次拿全）；交易日回退最多 10 天。
- 港股：easy_tdx ``MacExClient.goods_list(31)``（实测 2589 条带中文名，
  A 股 MAC 通道的证券列表命令在公共服务器上超时不可用）。

两级缓存：进程内 + 磁盘（data_cache/，按抓取日期失效）。匹配规则：
纯数字按代码前缀（港股自动补零对齐），否则按名称包含；排序为
精确同名 > 名称前缀 > 包含，再按代码。
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_CN_TZ = ZoneInfo("Asia/Shanghai")
_CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
_HK_PAGE = 1000  # goods_list 单页上限
_STATIC_HK_ROWS: tuple[tuple[str, str, str], ...] = (("HSI", "恒生指数", "指数"),)

# baostock 表里仅保留 resolve_market/resolve_hk 可路由的代码段。
_ASHARE_ALLOWED: tuple[tuple[str, str], ...] = (  # (市场前缀, 允许的代码前缀) → kind
    ("sh.", "60"), ("sh.", "68"),  # 股票
    ("sh.", "50"), ("sh.", "51"), ("sh.", "52"), ("sh.", "56"), ("sh.", "58"),  # ETF
    ("sz.", "00"), ("sz.", "30"),  # 股票
    ("sz.", "15"), ("sz.", "16"), ("sz.", "18"),  # ETF
    ("bj.", "43"), ("bj.", "83"), ("bj.", "87"), ("bj.", "92"),  # 股票
)
_INDEX_PREFIXES = ("sz.399", "sh.880")

_LOCK = threading.Lock()
_LAST_GOOD: dict[str, tuple[str, list[tuple[str, str, str]]]] = {}
_FAIL_MEM: dict[str, float] = {}
_FAIL_RETRY_S = 600.0  # 抓取失败后 10 分钟内不再重试，直接用历史缓存
_INFLIGHT: set[str] = set()


def _kind_for_ashare(bs_code: str, name: str) -> str:
    if bs_code.startswith(_INDEX_PREFIXES):
        return "指数"
    if bs_code.startswith("sh.000") and "指数" in name:
        return "指数"
    if bs_code[3:5] in ("50", "51", "52", "56", "58", "15", "16", "18"):
        return "ETF"
    return "股票"


def _cache_path(table: str, day: str) -> Path:
    return _CACHE_DIR / f"symbol_{table}_{day}.csv"


def _read_cache(table: str, day: str) -> list[tuple[str, str, str]] | None:
    path = _cache_path(table, day)
    if not path.exists():
        return None
    try:
        import csv

        with path.open(encoding="utf-8") as fh:
            return [(r["code"], r["name"], r["kind"]) for r in csv.DictReader(fh)]
    except Exception as exc:  # noqa: BLE001
        logger.debug("symbol cache read failed: %s", exc)
        return None


def _write_cache(table: str, day: str, rows: list[tuple[str, str, str]]) -> None:
    try:
        import csv

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(table, day)
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["code", "name", "kind"])
            w.writerows(rows)
    except Exception as exc:  # noqa: BLE001
        logger.debug("symbol cache write failed: %s", exc)


def _newest_cache(table: str) -> list[tuple[str, str, str]] | None:
    """Parse the newest cached table of any date (stale fallback when fetch fails)."""
    import csv

    files = sorted(_CACHE_DIR.glob(f"symbol_{table}_*.csv"))
    for path in reversed(files):
        try:
            with path.open(encoding="utf-8") as fh:
                rows = [(r["code"], r["name"], r["kind"]) for r in csv.DictReader(fh)]
            if rows:
                return rows
        except Exception as exc:  # noqa: BLE001
            logger.debug("stale cache %s unreadable: %s", path.name, exc)
    return None


def _refresh_async(table: str, fetcher) -> None:
    """后台线程刷新名称表；失败进入冷却，绝不阻塞搜索请求。"""

    def _run() -> None:
        try:
            rows = fetcher()
        except Exception as exc:  # noqa: BLE001
            with _LOCK:
                _FAIL_MEM[table] = _time.monotonic()
            logger.warning("symbol table %s refresh failed: %s", table, exc)
            return
        finally:
            with _LOCK:
                _INFLIGHT.discard(table)
        today = datetime.now(tz=_CN_TZ).strftime("%Y-%m-%d")
        with _LOCK:
            _LAST_GOOD[table] = (today, rows)
        _write_cache(table, today, rows)

    import time as _time

    with _LOCK:
        now = _time.monotonic()
        if table in _INFLIGHT or (now - _FAIL_MEM.get(table, float("-inf"))) < _FAIL_RETRY_S:
            return
        _INFLIGHT.add(table)
    threading.Thread(target=_run, name=f"symbol-refresh-{table}", daemon=True).start()


def _get_table(table: str, fetcher) -> list[tuple[str, str, str]]:
    """Load a name table: today's cache → in-process/stale cache (instant) + async refresh.

    本地映射优先：进程内 → 当日磁盘缓存 → 历史缓存即时返回，同时后台刷新。
    股票清单变化慢，旧表对搜索完全够用；远程抓取超时不能拖死搜索。
    """
    today = datetime.now(tz=_CN_TZ).strftime("%Y-%m-%d")
    with _LOCK:
        hit = _LAST_GOOD.get(table)
        if hit and hit[0] == today:
            return hit[1]
        rows = _read_cache(table, today)
        if rows is not None:
            _LAST_GOOD[table] = (today, rows)
            return rows
        if hit is not None:
            current = hit[1]
        else:
            current = _newest_cache(table)
            if current is not None:
                _LAST_GOOD[table] = ("stale", current)
    _refresh_async(table, fetcher)
    return current or []


def _fetch_ashare() -> list[tuple[str, str, str]]:
    """baostock 全量表；非交易日逐日回退（最多 10 天）。

    sh.000 指数（上证系列）以 ``sh000300`` 前缀形式存储，避免与深市
    000001 平安银行等同名 6 位代码歧义；其余存储可直订的裸代码。
    """
    import baostock as bs

    login = bs.login()
    if getattr(login, "error_code", None) not in (None, "0"):
        raise RuntimeError(f"baostock 登录失败: {login.error_msg}")
    try:
        day = datetime.now(tz=_CN_TZ).date()
        for _ in range(10):
            rs = bs.query_all_stock(day=day.strftime("%Y-%m-%d"))
            rows: list[tuple[str, str, str]] = []
            while rs.next():
                bs_code, _status, name = rs.get_row_data()
                if not name:
                    continue
                if bs_code.startswith("sh.000"):
                    if "指数" not in name:
                        continue
                    rows.append(("sh" + bs_code[3:], name, "指数"))
                    continue
                if bs_code.startswith(_INDEX_PREFIXES):
                    rows.append((bs_code[3:], name, "指数"))
                    continue
                if any(bs_code.startswith(p + prefix) for p, prefix in _ASHARE_ALLOWED):
                    rows.append((bs_code[3:], name, _kind_for_ashare(bs_code, name)))
            if rows:
                return rows
            day -= timedelta(days=1)
        return []
    finally:
        bs.logout()


def _fetch_hk() -> list[tuple[str, str, str]]:
    """easy_tdx 扩展行情港股主板列表（带中文名）。"""
    from easy_tdx import ExMarket, MacExClient

    ex = MacExClient.from_best_host(timeout=15.0, ping_timeout=2.0)
    ex.connect()
    try:
        total = int(ex.goods_count(ExMarket.HK_MAIN_BOARD) or 0)
        rows: list[tuple[str, str, str]] = []
        start = 0
        while start < max(total, 1) and start < 10000:
            df = ex.goods_list(ExMarket.HK_MAIN_BOARD, start=start, count=_HK_PAGE)
            if df is None or df.empty:
                break
            for code, name in zip(df["code"].astype(str), df["name"].astype(str)):
                if name.strip():
                    rows.append((code.zfill(5), name.strip(), "港股"))
            start += len(df)
        rows.extend(_STATIC_HK_ROWS)
        return rows
    finally:
        try:
            ex.close()
        except Exception:  # noqa: BLE001
            pass


def _hk_code_matches(hk_code: str, digits: str) -> bool:
    """00700 应能被 700/0700/00700 命中；600519 不应被 700 误命中。"""
    stripped = hk_code.lstrip("0")
    return bool(stripped) and stripped.startswith(digits.lstrip("0"))


def _load_ashare() -> list[tuple[str, str, str]]:
    return _get_table("ashare", _fetch_ashare)


def _load_hk() -> list[tuple[str, str, str]]:
    return _get_table("hk", _fetch_hk)


def search_symbols(query: str, *, limit: int = 12) -> list[dict[str, str]]:
    """名称/代码 → 候选列表 ``[{code, name, kind}]``（code 为可直接订阅的形式）。"""
    text = str(query or "").strip()
    if not text:
        return []
    digits = text if re.fullmatch(r"\d{1,6}", text) else ""
    low = text.lower()

    ranked: list[tuple[int, int, str, str, str]] = []  # (rank, order, code, name, kind)
    order = 0
    for table in (_load_ashare(), _load_hk()):
        for code, name, kind in table:
            if digits:
                # 代码前缀命中；sh 前缀指数行（sh000300）按尾 6 位对齐；
                # 港股按去前导零对齐（700 → 00700）。
                hit = (
                    code.startswith(digits)
                    or (kind == "指数" and code.startswith("sh") and code[-6:].startswith(digits))
                    or (kind == "港股" and _hk_code_matches(code, digits))
                )
            else:
                hit = low in name.lower()
            if not hit:
                continue
            name_low = name.lower()
            if name_low == low:
                rank = 0
            elif name_low.startswith(low):
                rank = 1
            else:
                rank = 2
            ranked.append((rank, order, code, name, kind))
            order += 1
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [
        {"code": code, "name": name, "kind": kind}
        for _rank, _order, code, name, kind in ranked[: max(int(limit), 1)]
    ]
