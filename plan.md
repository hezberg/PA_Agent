# PA_Agent 去除 PyQt6、迁移 WebUI 计划

> 状态：**已完成** · 2026-09-05
> 选型：React + Vite 前端；决策树可视化简化动画版；直接切换策略
>
> ## 实施结果
> - PyQt6 / pyqtgraph / pytest-qt 已从代码与依赖中完全移除（`grep` 零命中）
> - `pa_agent/gui/`（31 文件）与 16 个 Qt 测试文件已删除；纯逻辑迁移至 `pa_agent/services/`
> - 新增 `pa_agent/server/`（FastAPI + SSE）与 `web/`（React 18 + Vite + TS + lightweight-charts + zustand）
> - 全量测试：660 passed / 40 failed / 3 skipped —— 40 个失败经 HEAD 干净代码对照**全部为迁移前已存在**，迁移零新增失败
> - 端到端验证：服务启动、SPA 托管、演示回放 SSE 全链路（合成记录）、决策树动画、设置保存均通过浏览器实测

## 一、现状与结论

- Qt 集中在两处：
  1. `pa_agent/gui/`（31 个文件，约 1.4 万行）——最终整体删除
  2. 5 个核心文件的 QtCore 泄漏：`util/event_bus.py`、`ai/session_ledger.py`、`data/refresh_loop.py`、`demo/replayer.py`、`main.py`
- 业务层（`ai/`、`data/`、`orchestrator/`、`records/`、`notify/`，约 245 个文件）完全无 Qt，且编排器是回调驱动 + Qt-free 的 `CancelToken`（`util/threading.py`）——直接作为 Web 后端复用，**这些目录一行不改**
- 最大工作量：
  1. 从 4556 行的 `gui/main_window.py` 中抽出业务逻辑（分析状态机、增量分析、数据源切换、设置持久化、演示回放）
  2. 重建图表（pyqtgraph）、流式面板、决策树动画可视化
- 测试：约 750 个现有测试针对无 Qt 核心，全部保留；8 个 Qt GUI 测试文件在最后阶段删除或改写为服务层测试

## 二、目标架构

```
pa_agent/
├── main.py              # 改为 uvicorn 启动器：起服务 + webbrowser.open 打开页面
├── server/              # 新增 FastAPI 后端（复用 AppContext.bootstrap()）
│   ├── app.py           # 应用工厂、静态文件托管（web/dist）、生命周期管理
│   ├── state.py         # 进程内会话状态（分析任务表、刷新循环、SSE 订阅者队列）
│   ├── event_bridge.py  # 编排器回调(工作线程) → asyncio.Queue → SSE
│   └── routes/          # market / analysis / chat / settings / records / demo
├── services/            # 新增：从 main_window.py 抽出的无 Qt 业务逻辑
│   ├── analysis_flow.py       # 分析提交状态机、增量分析、bar-close 等待、中途切换
│   ├── data_source_service.py # 数据源切换/重连/订阅
│   ├── settings_service.py    # 设置读写（复用现有 pydantic settings）
│   └── demo_service.py        # 演示回放编排
└── web/                 # 新增 React + Vite + TypeScript 前端
    └── src/{api,store,components,theme}
```

**技术选型**

| 项 | 选择 | 说明 |
|---|---|---|
| 后端 | FastAPI + uvicorn | pydantic 已在依赖中；SSE 原生支持 |
| 前端 | React 18 + Vite + TypeScript | |
| K线图 | lightweight-charts | TradingView 官方开源库 |
| 决策树可视化 | SVG 动画 | 简化版：节点渐现、分支展开、播放控制 |
| 前端状态 | zustand | |
| 前后端类型 | openapi-typescript | 由 FastAPI OpenAPI schema 生成 TS 类型 |

**部署形态**：单用户本地应用——监听 `127.0.0.1`（端口可配置），无鉴权、无数据库；启动后自动打开浏览器。

## 三、实施阶段

### 阶段 1：服务层抽取（不动 gui/，测试保持绿色）

从 `gui/main_window.py` 抽出业务逻辑到 `pa_agent/services/`，每项配单元测试：

1. `analysis_flow.py`：分析提交流程、增量分析 / `keep_analysis` 决策、bar_close 等待、symbol 中途切换、错误记录持久化
2. `data_source_service.py`：数据源切换、订阅、重连状态
3. `settings_service.py`：各设置项保存（main_window 中 4 处 `save_settings` 逻辑归一）
4. `demo_service.py`：记录加载 + 回放事件序列

纯逻辑文件从 `gui/` 移到 `services/` 原样复用：`analysis_modes.py`、`speed_profiles.py`、`prediction_format.py`、`stage2_payload.py`、`support_resistance.py`、`chart_decision_overlay.py`（`order_opportunity.py` 去掉弹窗、保留判断逻辑）。

### 阶段 2：FastAPI 后端

新增 `pa_agent/server/`，事件名与现有编排器回调 1:1 对应：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/klines` | GET | 按 symbol/timeframe/source 拉取快照 |
| `/api/data-source` | POST | 切换 mt5/tv/yf/ak/tushare/eastmoney |
| `/api/stream/frames` | GET(SSE) | 刷新循环的 K 线推送 |
| `/api/analysis` | POST | 启动两阶段分析，返回 task_id |
| `/api/analysis/{id}/stream` | GET(SSE) | `reasoning_token / content_token / stage_prompt_ready / stage2_files_ready / retry_occurred / record_ready / status / finished / error` |
| `/api/analysis/{id}/cancel` | POST | 触发 CancelToken |
| `/api/chat` + `/api/chat/{id}/stream` | POST/GET(SSE) | 自由聊天流式输出 |
| `/api/settings` | GET/PUT | AI provider / 常规 / 飞书；API key 加密沿用现有逻辑 |
| `/api/settings/feishu/test` | POST | 后端线程执行测试发送 |
| `/api/records`、`/api/prompts` | GET | 历史记录、prompt 文件列表 |
| `/api/demo/replay` | POST(SSE) | 演示回放事件流 |

同时完成 4 个核心文件去 Qt：

- `util/event_bus.py` → 纯回调分发
- `ai/session_ledger.py` → 去 QObject（信号从未被 connect）
- `data/refresh_loop.py` → `threading.Thread` + 回调（保留指数退避与 in-flight 防重）
- `demo/replayer.py` → 时间驱动

### 阶段 3：React 前端

`web/` 下新建。主题移植：`gui/theme/tokens.py` 十六进制色 → CSS 变量，`dark.qss` → 全局样式，保持暗色交易终端观感。

- **K线图**：lightweight-charts 蜡烛图 + EMA20 + 入场/止盈/止损价格线 + 支撑阻力区 + 序列标签
- **顶部控制条**：品种、周期、数据源、分析模式、开始/取消、FlowBar 五步进度、SummaryStrip 指标卡
- **侧栏页签**：实时（双流 + token 进度 + 自由聊天）、决策、决策树（路径表 + 完整树）、决策树可视化（简化动画）、未来走势预期、原始调试、prompt 文件列表
- **设置弹窗**：AI 模型 / 常规 / 飞书三个 modal
- **交互替换**：QMessageBox → toast/modal；文件选择 → `<input type=file>`；外链 → `<a target=_blank>`；剪贴板 → `navigator.clipboard`

### 阶段 4：删除 Qt、收尾

1. `git rm -r pa_agent/gui/`；删除 8 个 Qt 测试文件
2. `pyproject.toml`：移除 `PyQt6`、`pyqtgraph`、`pytest-qt`；新增 `fastapi`、`uvicorn`、`sse-starlette`
3. 重写 `pa_agent/main.py`（uvicorn 启动 + 自动开浏览器）；简化 `run.py`；更新 `Makefile`、`start_pa_agent.bat`、CI（加 Node 构建）
4. 更新 `README.md`、`PA_Agent使用文档.md`
5. 全量回归：`pytest` + `npm run build` + 手工过验收清单

## 四、验收清单（Web 版与 Qt 版功能对齐）

- [ ] K线图：蜡烛 + EMA20 + 入场/止盈/止损线 + 支撑阻力 + 序列标签
- [ ] 控制条：品种/周期/数据源切换、分析模式、开始/取消
- [ ] FlowBar 五步进度 + SummaryStrip 指标卡
- [ ] 实时面板：推理流 + 内容流 + token 统计进度
- [ ] 自由聊天（流式输出、多轮）
- [ ] 决策面板：决策 + 市场诊断 + 交易者方程
- [ ] 决策树：路径表 + 完整树
- [ ] 决策树可视化（简化动画）
- [ ] 未来走势预期
- [ ] 原始调试面板：查看/复制每轮 prompt 与 response
- [ ] 调试面板：prompt 文件列表
- [ ] 设置：AI 模型 / 常规 / 飞书（含测试发送）
- [ ] 演示回放：加载记录文件并回放
- [ ] 状态栏：数据延迟/连接状态提示
- [ ] `grep -r "PyQt6"` 在 `pa_agent/`、`tests/`、`tools/`、`scripts/` 下零命中
- [ ] pyproject.toml 无 PyQt6/pyqtgraph/pytest-qt

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| `main_window.py` 逻辑抽取遗漏 | 以演示回放的事件序列为基准（回放与真实分析走同一套信号），是天然验收用例 |
| SSE 与 Qt 信号语义差异 | 统一走 `event_bridge` 单一入口入队，避免多处直接触线程 |
| MT5 数据源仅 Windows | 保持现状，Web 化不改变各数据源的平台限制 |
| 过渡期 CI 红 | 阶段 1 只加不改保持绿色；阶段 2 起 CI 临时跳过 GUI 测试，阶段 4 恢复 |
