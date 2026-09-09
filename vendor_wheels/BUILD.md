# easy_tdx wheel 构建说明

**来源**: https://github.com/hezberg/hard_tdx （main @ 2026-09-08 快照，v1.32.5）
**许可**: 见 LICENSE（随源分发）

## 为何是本地 wheel

上游已从 PyPI 下架；且 main 分支构建有两处问题，`git+https` 直接安装会失败：

1. pyproject 声明 `readme = "README.md"` 但仓库里只有 `README_origin.md`（已改名修复，经用户批准）
2. hatch 强制打包 `web-ui/dist/`（前端构建产物，仓库中不存在）——本构建放置了占位
   `index.html`（PA Agent 只用 easy_tdx 的行情协议客户端，不用其 Web UI）

## 重新构建步骤

```sh
git clone --depth 1 https://github.com/hezberg/hard_tdx /tmp/hard_tdx && cd /tmp/hard_tdx
mv README_origin.md README.md            # 若上游仍未修复
mkdir -p web-ui/dist && echo '<!doctype html><meta charset="utf-8">' > web-ui/dist/index.html
uv build --wheel
cp dist/easy_tdx-*.whl <PA_Agent>/vendor_wheels/
```

然后更新 pyproject `[tool.uv.sources]` 里的文件名并 `uv lock && uv sync`。

## 何时切回 git 依赖

仓库把 README.md 与 web-ui/dist 占位提交到 main 后，把 pyproject 的
`[tool.uv.sources] easy-tdx = ...` 改回 `{ git = "https://github.com/hezberg/hard_tdx.git" }`。
