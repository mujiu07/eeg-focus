#!/usr/bin/env bash
# 双击启动「专注小蛙」（macOS）。关闭这个终端窗口就会停止服务。
# 想跳过自动打开浏览器：SKIP_OPEN=1 bash start.command
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

# 已经启动过：直接开页面，不再起第二个进程
if curl -fsS -m 1 "${URL}/api/env" >/dev/null 2>&1; then
  echo "服务已在运行：${URL}"
  [ "${SKIP_OPEN:-0}" = "1" ] || open "${URL}"
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "首次运行：创建虚拟环境并安装依赖（需要联网，约 1-3 分钟）……"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
fi

mkdir -p .run

echo ""
echo "  专注小蛙  ${URL}"
echo "  关闭窗口即可停止服务；心率默认不启用，需要时在校准页手动选。"
echo ""

if [ "${SKIP_OPEN:-0}" != "1" ]; then
  ( sleep 2; open "${URL}" ) &
fi

exec .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port "${PORT}"
