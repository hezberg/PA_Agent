#!/bin/sh
# 前端源码变化时自动重建 web/dist（供 deploy/systemd/pa-agent-webbuild.service 使用）。
# FastAPI 每次请求都从磁盘读取 index.html/assets，因此重建后刷新浏览器即生效。
# vite 配置了 emptyOutDir:false，增量构建不会清空正在被伺服的 dist。
set -eu

cd "$(dirname "$0")/../web"

if [ ! -d node_modules ]; then
  echo "node_modules not found; run: npm ci" >&2
  exit 1
fi

# node 装在带版本号的用户目录，glob 取最新版本，避免 node 升级后 systemd 单元失效。
NODE_DIR="$(ls -d "$HOME"/.local/share/pi-node/node-v*/bin 2>/dev/null | sort -V | tail -n1 || true)"
if [ -n "$NODE_DIR" ]; then
  PATH="$NODE_DIR:$PATH"
  export PATH
fi

exec node_modules/.bin/vite build --watch
