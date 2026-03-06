#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  AgentFlow v2 [Python] - 停止服务 (Linux/macOS)"
echo "============================================================"
echo ""

# 停止 AgentFlow (Python)
echo "[1/2] 停止 AgentFlow [Python]..."
if pgrep -f "agentflow_py/main.py" &>/dev/null; then
    pkill -f "agentflow_py/main.py"
    echo "      [√] AgentFlow [Python] 已停止"
else
    echo "      [i] AgentFlow [Python] 未在运行"
fi

# 询问是否停止 Redis
echo ""
read -r -p "[2/2] 是否同时停止 Redis? (y/N): " STOP_REDIS
if [[ "${STOP_REDIS,,}" == "y" ]]; then
    redis-cli shutdown nosave &>/dev/null || true
    echo "      [√] Redis 已停止"
else
    echo "      [i] 保留 Redis 运行"
fi

echo ""
echo "[√] 完成"
