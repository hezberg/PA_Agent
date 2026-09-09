# PA Agent（fork 版）— AI K线分析辅助工具

基于 [rosemarycox5334-debug/PA_Agent](https://github.com/rosemarycox5334-debug/PA_Agent)（v1.37）的继续开发版本：价格行为（Price Action）AI 辅助决策工具，两阶段大模型分析（市场诊断 → 交易决策），不连接券商、不执行下单。

## 相对原仓库的改动

- **界面重写**：Qt GUI → FastAPI + React 单页应用（浏览器访问，支持 tailnet 内网远程使用）
- **同花顺自选股**：设置页登录账号，左侧面板显示自选分组与股票（中文名+代码），点击切票并自动展开 K 线，30 分钟自动刷新
- **全中文**：分析结果与飞书/PushPlus 推送中的专业术语全部中文化，界面术语悬停显示解释；推送附带股票名称
- **缺陷修复**：持续跟踪开关从未生效（405）；持续跟踪会锁死手动「开始分析」；图表 EMA 线与 K 线错位；重启被长连接卡死
- **依赖**：easy-tdx 上游已下架，改用 [hezberg/hard_tdx](https://github.com/hezberg/hard_tdx)；K 线周期默认 1d
- **部署**：`deploy/systemd/` 提供 systemd 常驻服务与前端自动构建

## 快速开始

```sh
git clone https://github.com/hezberg/PA_Agent.git
cd PA_Agent
uv sync
make build-web
uv run python -m pa_agent.main   # http://127.0.0.1:8765
```

首次启动在 ⚙ 设置 →「AI 模型设置」填写 API 信息。服务器常驻部署见 `deploy/systemd/`。

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux / macOS（MT5 数据源需 Windows） |
| Python | 3.11 – 3.13 |
| 数据源 | 通达信（A 股主力源）/ MT5 / TradingView 至少一种 |

## 致谢

- 原项目：[rosemarycox5334-debug/PA_Agent](https://github.com/rosemarycox5334-debug/PA_Agent)（作者 qq564020069，交流群 1063897401），使用文档见 [`PA_Agent使用文档.md`](PA_Agent使用文档.md)
- [sunnysab/ths-favorite](https://github.com/sunnysab/ths-favorite)、[hezberg/hard_tdx](https://github.com/hezberg/hard_tdx)

**免责声明**：仅供学习研究，不构成投资建议。本项目与 `pa_agent/vendor/ths_favorite/` 采用 AGPL-3.0 / GPL-3.0 许可。
