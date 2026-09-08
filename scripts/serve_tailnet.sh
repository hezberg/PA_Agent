#!/bin/sh
# 在 tailnet IP 上启动 PA Agent WebUI（供 deploy/systemd/pa-agent.service 使用）。
# 开机时 tailscaled 可能尚未分配 IP，此处轮询等待，超时则以非零退出交给 systemd 重试。
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$REPO_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo ".venv not found; run: uv sync --frozen" >&2
  exit 1
fi

TS_IP=""
i=0
while [ "$i" -lt 24 ]; do
  TS_IP="$(/usr/bin/tailscale ip -4 2>/dev/null | head -n1 || true)"
  [ -n "$TS_IP" ] && break
  i=$((i + 1))
  echo "waiting for tailnet IP... ($i)" >&2
  sleep 5
done

if [ -z "$TS_IP" ]; then
  echo "no tailnet IP available; aborting" >&2
  exit 1
fi

echo "serving PA Agent WebUI on http://$TS_IP:8765" >&2
cd "$REPO_DIR"
exec "$PYTHON" -m pa_agent.main --host "$TS_IP" --no-browser --reload
