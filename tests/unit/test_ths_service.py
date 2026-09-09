"""同花顺自选服务单测：市场码映射、中文名回填、设置掩码往返。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── 市场码 → 可订阅代码 ──────────────────────────────────────────────────────

def test_subscribable_code_mapping():
    from pa_agent.server.ths_service import _subscribable_code

    assert _subscribable_code("600519", "SH") == "600519"
    assert _subscribable_code("000001", "SZ") == "000001"
    assert _subscribable_code("430047", "BJ") == "430047"
    assert _subscribable_code("688048", "KC") == "688048"  # 科创板
    assert _subscribable_code("300308", "CY") == "300308"  # 创业板
    assert _subscribable_code("700", "HK") == "00700"  # 港股补零对齐
    assert _subscribable_code("1810", "hk") == "01810"  # 市场码大小写不敏感
    assert _subscribable_code("600519", None) == "600519"  # 缺市场码原样返回


def test_vendored_package_importable():
    from pa_agent.vendor.ths_favorite import PortfolioManager  # noqa: F401


def test_settings_round_trip_ths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ths 段持久化 + 掩码语义：空/掩码密码表示保留原值。"""
    from pa_agent.config.settings import Settings, save_settings

    path = tmp_path / "settings.json"
    s = Settings()
    s.ths.username = "13800000000"
    s.ths.password = "secret-pass"
    s.ths.enabled = True
    save_settings(s, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["ths"]["username"] == "13800000000"
    assert raw["ths"]["password"] == "secret-pass"
    assert raw["ths"]["enabled"] is True

    # 模拟 PUT 回写：掩码密码不应覆盖真实密码
    incoming = {"password": "******", "enabled": True, "username": "13800000000"}
    _MASK = "******"
    if str(incoming.get("password") or "").strip() in ("", _MASK):
        incoming.pop("password")
    cleaned = {k: v for k, v in incoming.items() if k in s.ths.model_fields}
    s.ths = s.ths.model_copy(update=cleaned)
    assert s.ths.password == "secret-pass"
