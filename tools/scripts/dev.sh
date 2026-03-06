#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  AgentFlow v2 - 开发模式启动 (Linux/macOS)"
echo "  自动构建 + 启动，每次运行都重新编译"
echo "============================================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="${PROJECT_DIR}/configs/config.yaml"
REDIS_PORT=${REDIS_PORT:-6379}

# 可通过参数覆盖: ./dev.sh stdio
TRANSPORT="${1:-sse}"

# 检查 Go
if ! command -v go &>/dev/null; then
    echo "[×] 未找到 Go 编译器，请安装 Go 1.21+"
    exit 1
fi

# 检查 Redis
if ! redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
    echo "[!] Redis 未运行，请先启动 Redis:"
    echo "    bash scripts/setup-redis.sh"
    exit 1
fi
echo "[√] Redis OK"

# 构建
echo "[i] 正在构建..."
pushd "$PROJECT_DIR" >/dev/null
go build -o agentflow .
popd >/dev/null
echo "[√] 构建成功"

# 设置开发环境变量
export AF_SERVER_TRANSPORT="$TRANSPORT"
export AF_SERVER_LOG_LEVEL="debug"

echo ""
echo "============================================================"
echo "  [DEV] AgentFlow v2 (日志级别: debug)"
echo "  Dashboard: http://localhost:8081"
if [[ "$TRANSPORT" == "sse" ]]; then
    echo "  MCP URL:   http://localhost:8080/mcp"
fi
echo "  按 Ctrl+C 停止"
echo "============================================================"
echo ""

exec "$PROJECT_DIR/agentflow" -config "$CONFIG_FILE"
