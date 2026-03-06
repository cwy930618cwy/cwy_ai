#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  AgentFlow v2 - 一键启动 (Linux/macOS)"
echo "============================================================"
echo ""

# ============================================================
# 配置区域
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="${PROJECT_DIR}/configs/config.yaml"
EXE_FILE="${PROJECT_DIR}/agentflow"
REDIS_PORT=${REDIS_PORT:-6379}

# 可通过参数覆盖传输模式: ./start.sh stdio | ./start.sh sse
TRANSPORT="${1:-sse}"

# ============================================================
# Step 1: 检查 Redis 连接
# ============================================================
echo "[1/4] 检查 Redis..."

if command -v redis-cli &>/dev/null; then
    if redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
        echo "      [√] Redis 已运行 (端口 $REDIS_PORT)"
    else
        echo "      [!] Redis 未运行，正在启动..."
        bash "$SCRIPT_DIR/setup-redis.sh"
    fi
else
    echo "      [!] 未找到 redis-cli，请先安装 Redis"
    echo "      运行: bash scripts/setup-redis.sh"
    exit 1
fi

# ============================================================
# Step 2: 检查/构建可执行文件
# ============================================================
echo "[2/4] 检查可执行文件..."

if [[ -f "$EXE_FILE" ]]; then
    echo "      [√] 已存在: agentflow"
else
    echo "      [i] 构建中..."
    if ! command -v go &>/dev/null; then
        echo "      [×] 未找到 Go 编译器，请安装 Go 1.21+"
        exit 1
    fi
    pushd "$PROJECT_DIR" >/dev/null
    go build -o agentflow .
    popd >/dev/null
    echo "      [√] 构建成功"
fi

# ============================================================
# Step 3: 确保数据目录
# ============================================================
echo "[3/4] 检查数据目录..."

mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/data/test_cases"
mkdir -p "$PROJECT_DIR/data/redis"
echo "      [√] 数据目录就绪"

# ============================================================
# Step 4: 启动 AgentFlow
# ============================================================
echo "[4/4] 启动 AgentFlow v2..."
echo ""
echo "      传输模式: $TRANSPORT"
echo "      配置文件: $CONFIG_FILE"
echo ""

# 设置传输模式环境变量
export AF_SERVER_TRANSPORT="$TRANSPORT"

echo "============================================================"
echo "  AgentFlow v2 已启动"
echo "  Dashboard: http://localhost:8081"
if [[ "$TRANSPORT" == "sse" ]]; then
    echo "  MCP URL:   http://localhost:8080/mcp"
fi
echo "  按 Ctrl+C 停止"
echo "============================================================"
echo ""

exec "$EXE_FILE" -config "$CONFIG_FILE"
