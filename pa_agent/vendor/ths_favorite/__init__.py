"""同花顺自选股库（vendored）。

来源: https://github.com/sunnysab/ths-favorite (commit: main @ 2026-09)
许可: GPL-3.0-or-later（与本项目 AGPL-3.0 兼容；原始仓库未附带 LICENSE 文件，
      许可声明见其 pyproject.toml）。
改动: 仅将顶层裸模块导入改写为本包内相对导入，其余保持原样。

仅暴露只读能力（登录 + 分组/自选列表）；写入操作（增删自选/分组）本包未使用。
"""
from pa_agent.vendor.ths_favorite.service import PortfolioManager

__all__ = ["PortfolioManager"]
