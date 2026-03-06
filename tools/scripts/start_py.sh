#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  AgentFlow v2 [Python] - 一键启动 (Linux/macOS)"
echo "============================================================"
echo ""

# ============================================================
# 配置区域
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY_PROJECT_DIR="${PROJECT_DIR}/agentflow_py"
CONFIG_FILE="${PY_PROJECT_DIR}/configs/config.yaml"

# 可通过参数覆盖传输模式: ./start_py.sh stdio | ./start_py.sh sse
TRANSPORT="${1:-sse}"

# ============================================================
# Step 1: 检查 Python 环境
# ============================================================
echo "[1/3] 检查 Python 环境..."

# 优先使用 python3，回退到 python
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "      [×] 未找到 Python，请安装 Python 3.10+"
    exit 1
fi

PYVER=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "      [√] Python $PYVER ($PYTHON_CMD)"

# 检查依赖是否已安装
if ! $PYTHON_CMD -c "import aiosqlite; import pydantic; import yaml; import fastapi; import uvicorn; import aiohttp" &>/dev/null; then
    echo "      [i] 正在安装依赖..."
    $PYTHON_CMD -m pip install -r "$PY_PROJECT_DIR/requirements.txt" -q
    echo "      [√] 依赖安装成功"
else
    echo "      [√] 依赖已就绪"
fi

# ============================================================
# Step 2: 确保数据目录
# ============================================================
echo "[2/3] 检查数据目录..."

mkdir -p "$PY_PROJECT_DIR/data"
mkdir -p "$PY_PROJECT_DIR/data/test_cases"
echo "      [√] 数据目录就绪"

# ============================================================
# Step 3: 启动 AgentFlow (Python)
# ============================================================
echo "[3/3] 启动 AgentFlow v2 [Python]..."
echo ""
echo "      传输模式: $TRANSPORT"
echo "      配置文件: $CONFIG_FILE"
echo ""

# 设置传输模式环境变量
export AF_SERVER_TRANSPORT="$TRANSPORT"

echo "============================================================"
echo "  AgentFlow v2 [Python] 已启动"
echo "  Dashboard: http://localhost:8081"
if [[ "$TRANSPORT" == "sse" ]]; then
    echo "  MCP URL:   http://localhost:8080/mcp"
fi
echo "  按 Ctrl+C 停止"
echo "============================================================"
echo ""

exec $PYTHON_CMD "$PY_PROJECT_DIR/main.py" --config "$CONFIG_FILE"
