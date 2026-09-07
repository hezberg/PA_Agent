"""Unit tests for symbol name → code search (easytdx source)."""
from __future__ import annotations

import pytest

from pa_agent.data import symbol_search as ss


@pytest.fixture()
def tables(monkeypatch) -> None:
    """Fixed in-memory tables; no network involved."""
    ashare = [
        ("600519", "贵州茅台", "股票"),
        ("000001", "平安银行", "股票"),
        ("sh000001", "上证指数", "指数"),
        ("sh000300", "沪深300指数", "指数"),
        ("399006", "创业板指", "指数"),
        ("510300", "华泰柏瑞沪深300ETF", "ETF"),
        ("159915", "易方达创业板ETF", "ETF"),
        ("000700", "模塑科技", "股票"),
    ]
    hk = [
        ("00700", "腾讯控股", "港股"),
        ("09988", "阿里巴巴－Ｗ", "港股"),
        ("HSI", "恒生指数", "指数"),
    ]
    monkeypatch.setattr(ss, "_load_ashare", lambda: ashare)
    monkeypatch.setattr(ss, "_load_hk", lambda: hk)


def test_exact_name_single_candidate(tables) -> None:
    assert ss.search_symbols("贵州茅台") == [
        {"code": "600519", "name": "贵州茅台", "kind": "股票"}
    ]


def test_substring_name_multi_candidates(tables) -> None:
    hits = ss.search_symbols("指数")
    codes = [c["code"] for c in hits]
    assert set(codes) == {"sh000001", "sh000300", "HSI"}


def test_name_rank_exact_before_contains(tables) -> None:
    # 「上证指数」精确同名应排第一（其余为包含匹配）
    hits = ss.search_symbols("上证指数")
    assert hits[0]["code"] == "sh000001"


def test_digit_prefix_matches_code(tables) -> None:
    hits = ss.search_symbols("6005")
    assert [c["code"] for c in hits] == ["600519"]


def test_hk_digits_zero_padding(tables) -> None:
    assert ss.search_symbols("700")[0]["code"] == "00700"
    assert ss.search_symbols("0700")[0]["code"] == "00700"
    assert ss.search_symbols("00700")[0]["code"] == "00700"


def test_digit_000001_disambiguates_bank_and_index(tables) -> None:
    hits = ss.search_symbols("000001")
    codes = [c["code"] for c in hits]
    assert "000001" in codes       # 平安银行
    assert "sh000001" in codes     # 上证指数（尾 6 位对齐）


def test_full_digits_exact_only(tables) -> None:
    assert [c["code"] for c in ss.search_symbols("600519")] == ["600519"]
    # 000700 模塑科技（000 前缀不命中 700 的港股去零匹配）
    codes = [c["code"] for c in ss.search_symbols("700")]
    assert "000700" not in codes


def test_hk_name_lookup(tables) -> None:
    hits = ss.search_symbols("腾讯")
    assert hits == [{"code": "00700", "name": "腾讯控股", "kind": "港股"}]


def test_mixed_digit_query_hits_etf_and_index(tables) -> None:
    hits = ss.search_symbols("510300")
    assert [c["code"] for c in hits] == ["510300"]


def test_empty_and_no_match(tables) -> None:
    assert ss.search_symbols("") == []
    assert ss.search_symbols("不存在的名称xyz") == []


def test_kind_labels_present(tables) -> None:
    assert ss.search_symbols("易方达")[0]["kind"] == "ETF"
    hits = ss.search_symbols("0003")
    got = {c["code"]: c["kind"] for c in hits}
    assert got.get("sh000300") == "指数"


def test_limit_respected(tables, monkeypatch) -> None:
    big = [(f"{600000 + i}", f"名称{i}", "股票") for i in range(30)]
    monkeypatch.setattr(ss, "_load_ashare", lambda: big)
    monkeypatch.setattr(ss, "_load_hk", lambda: [])
    assert len(ss.search_symbols("名称")) == 12
    assert len(ss.search_symbols("名称", limit=5)) == 5
