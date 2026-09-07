UV ?= uv

# ===== 原有指令（直接使用当前环境的 python / pytest / ruff / npm）=====

# 启动 WebUI（FastAPI 后端 + 自动打开浏览器；需先 `make build-web` 或已有 web/dist）
run:
	python -m pa_agent.main

# 构建前端（web/dist）
build-web:
	cd web && npm install && npm run build

# 前端开发模式（Vite dev server，/api 代理到本地 8765）
dev-web:
	cd web && npm run dev

# 运行测试
test:
	pytest -q

# 代码检查
lint:
	ruff check . && black --check .

# ===== 对应 uv 隔离环境版本 =====

# 自动创建隔离环境并安装依赖（含 dev 工具）
.venv: pyproject.toml
	$(UV) sync --extra dev

# 使用 uv 启动 WebUI
uv-run: .venv
	$(UV) run python -m pa_agent.main

# 使用 uv 运行测试
uv-test: .venv
	$(UV) run --extra dev pytest -q

# 使用 uv 代码检查
uv-lint: .venv
	$(UV) run ruff check . && $(UV) run black --check .

# 启用 pre-commit，防止 settings / 日志 / 记录被提交
setup-secrets:
	powershell -ExecutionPolicy Bypass -File tools/setup_git_secrets.ps1

.PHONY: run build-web dev-web test lint uv-run uv-test uv-lint setup-secrets
