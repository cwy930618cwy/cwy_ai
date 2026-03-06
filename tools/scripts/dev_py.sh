#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  AgentFlow v2 [Python] - 开发模式启动 (Linux/macOS)"
echo "  自动安装依赖 + debug 日志 + 启动"
echo "============================================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY_PROJECT_DIR="${PROJECT_DIR}/agentflow_py"
CONFIG_FILE="${PY_PROJECT_DIR}/configs/config.yaml"
REDIS_PORT=${REDIS_PORT:-6379}

# 可通过参数覆盖: ./dev_py.sh stdio
TRANSPORT="${1:-sse}"

# 优先使用 python3，回退到 python
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[×] 未找到 Python，请安装 Python 3.10+"
    exit 1
fi

# 检查 Redis
if ! redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
    echo "[!] Redis 未运行，请先启动 Redis:"
    echo "    bash scripts/setup-redis.sh"
    exit 1
fi
echo "[√] Redis OK"

# 安装/更新依赖
echo "[i] 正在安装/更新依赖..."
$PYTHON_CMD -m pip install -r "$PY_PROJECT_DIR/requirements.txt" -q
echo "[√] 依赖就绪"

# 确保数据目录
mkdir -p "$PY_PROJECT_DIR/data"
mkdir -p "$PY_PROJECT_DIR/data/test_cases"
mkdir -p "$PY_PROJECT_DIR/data/redis"

# 设置开发环境变量
export AF_SERVER_TRANSPORT="$TRANSPORT"
export AF_SERVER_LOG_LEVEL="debug"

echo ""
echo "============================================================"
echo "  [DEV] AgentFlow v2 [Python] (日志级别: debug)"
echo "  Dashboard: http://localhost:8081"
if [[ "$TRANSPORT" == "sse" ]]; then
    echo "  MCP URL:   http://localhost:8080/mcp"
fi
echo "  按 Ctrl+C 停止"
echo "============================================================"
echo ""

exec $PYTHON_CMD "$PY_PROJECT_DIR/main.py" --config "$CONFIG_FILE"
