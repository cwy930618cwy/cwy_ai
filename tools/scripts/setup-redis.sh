#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  AgentFlow v2 - Redis 安装与启动 (Linux/macOS, 要求 Redis 5.0+)"
echo "============================================================"
echo ""

# ============================================================
# 配置区域 (可按需修改)
# ============================================================
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_PASSWORD=${REDIS_PASSWORD:-""}
REDIS_MAXMEMORY=${REDIS_MAXMEMORY:-"256mb"}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Redis 持久化数据目录 — 与 Go 代码中 config.GetRedisDataDir() 保持一致 (data_dir/redis)
REDIS_DATA_DIR="${SCRIPT_DIR}/../data/redis"

# ============================================================
# 检测 Redis 是否已安装
# ============================================================
# ------------------------------------------------------------
# 安装 Redis 的函数 (支持各平台包管理器)
# ------------------------------------------------------------
install_redis() {
    echo "[i] 正在安装 Redis 5.0+..."

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &>/dev/null; then
            echo "[i] 通过 Homebrew 安装 Redis..."
            brew install redis
        else
            echo "[!] 请先安装 Homebrew: https://brew.sh"
            echo "    然后运行: brew install redis"
            exit 1
        fi
    elif [[ -f /etc/debian_version ]]; then
        # Debian/Ubuntu
        echo "[i] 通过 apt 安装 Redis..."
        sudo apt-get update && sudo apt-get install -y redis-server
    elif [[ -f /etc/redhat-release ]]; then
        # RHEL/CentOS/Fedora
        echo "[i] 通过 yum/dnf 安装 Redis..."
        if command -v dnf &>/dev/null; then
            sudo dnf install -y redis
        else
            sudo yum install -y redis
        fi
    elif [[ -f /etc/arch-release ]]; then
        # Arch Linux
        echo "[i] 通过 pacman 安装 Redis..."
        sudo pacman -S --noconfirm redis
    else
        echo "[!] 无法自动安装 Redis，请手动安装 (要求 5.0+):"
        echo "    Docker: docker run -d -p 6379:6379 redis:7-alpine"
        echo "    源码:   https://redis.io/download"
        exit 1
    fi

    echo "[√] Redis 安装成功"
}

# ------------------------------------------------------------
# 卸载旧版 Redis 的函数
# ------------------------------------------------------------
uninstall_redis() {
    echo "[i] 尝试卸载旧版 Redis..."

    if [[ "$OSTYPE" == "darwin"* ]]; then
        command -v brew &>/dev/null && brew uninstall redis 2>/dev/null || true
    elif [[ -f /etc/debian_version ]]; then
        sudo apt-get remove -y redis-server 2>/dev/null || true
    elif [[ -f /etc/redhat-release ]]; then
        if command -v dnf &>/dev/null; then
            sudo dnf remove -y redis 2>/dev/null || true
        else
            sudo yum remove -y redis 2>/dev/null || true
        fi
    elif [[ -f /etc/arch-release ]]; then
        sudo pacman -Rns --noconfirm redis 2>/dev/null || true
    fi
}

# ------------------------------------------------------------
# 验证 Redis 版本 >= 5.0
# ------------------------------------------------------------
verify_redis_version() {
    if ! command -v redis-server &>/dev/null; then
        echo "[×] 安装后仍无法找到 redis-server，请检查 PATH"
        exit 1
    fi
    local ver
    ver=$(redis-server --version | grep -oP 'v=\K[0-9]+\.[0-9]+' | head -1)
    local major
    major=$(echo "$ver" | cut -d. -f1)
    if [[ "$major" -lt 5 ]]; then
        echo "[×] Redis 版本仍低于 5.0 ($ver)，请手动安装 5.0+ 版本"
        exit 1
    fi
    echo "[√] Redis 版本检查通过 ($ver)"
}

# ============================================================
# 检测 Redis 是否已安装，版本过低则重新安装
# ============================================================
if command -v redis-server &>/dev/null; then
    echo "[√] Redis 已安装"
    redis-server --version
    # 检查 Redis 版本是否 >= 5.0
    REDIS_VER=$(redis-server --version | grep -oP 'v=\K[0-9]+\.[0-9]+' | head -1)
    REDIS_MAJOR=$(echo "$REDIS_VER" | cut -d. -f1)
    if [[ "$REDIS_MAJOR" -lt 5 ]]; then
        echo "[!] Redis 版本过低！当前: $REDIS_VER，需要 5.0+"
        echo "[i] 将自动卸载旧版本并重新安装..."
        uninstall_redis
        install_redis
        verify_redis_version
    else
        echo "[√] Redis 版本检查通过 ($REDIS_VER)"
    fi
else
    echo "[i] Redis 未安装，尝试自动安装..."
    install_redis
    verify_redis_version
fi

# ============================================================
# 启动 Redis
# ============================================================
echo ""
echo "============================================================"
echo "  启动 Redis Server"
echo "============================================================"
echo ""

# 确保数据目录存在
mkdir -p "$REDIS_DATA_DIR"

# 检查 Redis 是否已在运行
if redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
    echo "[√] Redis 已在运行 (端口 $REDIS_PORT)"
    redis-cli -p "$REDIS_PORT" INFO server | grep redis_version
    echo ""
    echo "跳过启动，Redis 已就绪。"
else
    echo "[i] 正在启动 Redis (端口: $REDIS_PORT)..."
    echo "[i] 数据目录: $REDIS_DATA_DIR"
    echo ""

    REDIS_ARGS=(
        --port "$REDIS_PORT"
        --dir "$REDIS_DATA_DIR"
        --maxmemory "$REDIS_MAXMEMORY"
        --maxmemory-policy allkeys-lru
        --lazyfree-lazy-eviction yes
        --lazyfree-lazy-expire yes
        --daemonize yes
        --save "60 1000"
        --save "300 100"
        --appendonly yes
        --appendfsync everysec
        --aof-use-rdb-preamble yes
        --loglevel notice
    )

    if [[ -n "$REDIS_PASSWORD" ]]; then
        REDIS_ARGS+=(--requirepass "$REDIS_PASSWORD")
    fi

    redis-server "${REDIS_ARGS[@]}"

    # 等待 Redis 启动
    echo "[i] 等待 Redis 启动..."
    sleep 1

    if redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
        echo ""
        echo "[√] Redis 已就绪！"
        echo "    地址: 127.0.0.1:$REDIS_PORT"
        echo "    密码: ${REDIS_PASSWORD:-<无>}"
        echo "    最大内存: $REDIS_MAXMEMORY"
        echo "    数据目录: $REDIS_DATA_DIR"
        echo ""
    else
        echo "[×] Redis 启动失败，请检查日志"
        exit 1
    fi
fi
