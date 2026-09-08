#!/bin/sh
# 同步构建一次 web/dist：清空后全量构建。
# flock 防止 pa-agent.service 的 ExecStartPre 与 pa-agent-webbuild.service 并发构建互相覆盖。
set -eu

cd "$(dirname "$0")/../web"

if [ ! -d node_modules ]; then
  echo "node_modules not found; run: npm ci" >&2
  exit 1
fi

NODE_DIR="$(ls -d "$HOME"/.local/share/pi-node/node-v*/bin 2>/dev/null | sort -V | tail -n1 || true)"
if [ -n "$NODE_DIR" ]; then
  PATH="$NODE_DIR:$PATH"
  export PATH
fi

exec 9>/tmp/pa-agent-vite.lock
flock 9
rm -rf dist
exec node_modules/.bin/vite build
