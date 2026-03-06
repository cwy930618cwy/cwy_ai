@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   AgentFlow v2 - 一键启动 (Windows)
echo ============================================================
echo.

REM ============================================================
REM 配置区域
REM ============================================================
set PROJECT_DIR=%~dp0..
set CONFIG_FILE=%PROJECT_DIR%\configs\config.yaml
set EXE_FILE=%PROJECT_DIR%\agentflow.exe
set REDIS_PORT=6379

REM 可通过参数覆盖传输模式: start.bat stdio | start.bat sse
set TRANSPORT=%1
if "%TRANSPORT%"=="" set TRANSPORT=sse

REM ============================================================
REM Step 1: 检查 Redis 连接
REM ============================================================
echo [1/4] 检查 Redis...

REM 优先将本地 tools\redis 目录加入 PATH（setup-redis.bat 下载的 tporadowski Redis）
set REDIS_LOCAL_DIR=%PROJECT_DIR%\tools\redis
if exist "%REDIS_LOCAL_DIR%\redis-cli.exe" (
    set "PATH=%REDIS_LOCAL_DIR%;%PATH%"
)

REM 检查 redis-cli 是否存在
where redis-cli >nul 2>&1
if !errorlevel! neq 0 goto :no_redis_cli

REM redis-cli 存在，检查 Redis 是否已运行
redis-cli -p %REDIS_PORT% ping >nul 2>&1
if !errorlevel! neq 0 goto :redis_not_running

REM Redis 已运行
echo       [√] Redis 已运行 ^(端口 %REDIS_PORT%^)
goto :redis_ok

:redis_not_running
echo       [!] Redis 未运行，正在启动...
call "%~dp0setup-redis.bat"
if !errorlevel! neq 0 (
    echo       [×] Redis 启动失败
    pause
    exit /b 1
)
REM setup-redis.bat 安装后可能新增了本地 Redis，重新检测 PATH
if exist "%REDIS_LOCAL_DIR%\redis-cli.exe" (
    set "PATH=%REDIS_LOCAL_DIR%;%PATH%"
)
REM 再次验证 Redis 是否真正启动成功
redis-cli -p %REDIS_PORT% ping >nul 2>&1
if !errorlevel! neq 0 (
    echo       [×] Redis 启动后仍无法连接
    pause
    exit /b 1
)
echo       [√] Redis 启动成功
goto :redis_ok

:no_redis_cli
echo       [!] 未找到 redis-cli，正在自动安装 Redis...
call "%~dp0setup-redis.bat"
if !errorlevel! neq 0 (
    echo       [×] Redis 安装失败
    echo       请手动运行: scripts\setup-redis.bat
    pause
    exit /b 1
)
REM 安装后将本地 Redis 加入 PATH
if exist "%REDIS_LOCAL_DIR%\redis-cli.exe" (
    set "PATH=%REDIS_LOCAL_DIR%;%PATH%"
)
REM 安装脚本已启动 Redis，验证连接
redis-cli -p %REDIS_PORT% ping >nul 2>&1
if !errorlevel! neq 0 (
    echo       [×] Redis 安装后仍无法连接
    pause
    exit /b 1
)
echo       [√] Redis 安装并启动成功
goto :redis_ok

:redis_ok

REM ============================================================
REM Step 2: 检查/构建可执行文件
REM ============================================================
echo [2/4] 检查可执行文件...

if exist "%EXE_FILE%" (
    echo       [√] 已存在: agentflow.exe
    goto :build_ok
)

echo       [i] 构建中...
where go >nul 2>&1
if !errorlevel! neq 0 (
    echo       [×] 未找到 Go 编译器，请安装 Go 1.21+
    pause
    exit /b 1
)
pushd "%PROJECT_DIR%"
go build -o agentflow.exe .
popd
if !errorlevel! neq 0 (
    echo       [×] 构建失败
    pause
    exit /b 1
)
echo       [√] 构建成功

:build_ok

REM ============================================================
REM Step 3: 确保数据目录
REM ============================================================
echo [3/4] 检查数据目录...

if not exist "%PROJECT_DIR%\data" mkdir "%PROJECT_DIR%\data"
if not exist "%PROJECT_DIR%\data\test_cases" mkdir "%PROJECT_DIR%\data\test_cases"
if not exist "%PROJECT_DIR%\data\redis" mkdir "%PROJECT_DIR%\data\redis"
echo       [√] 数据目录就绪

REM ============================================================
REM Step 4: 启动 AgentFlow
REM ============================================================
echo [4/4] 启动 AgentFlow v2...
echo.
echo       传输模式: %TRANSPORT%
echo       配置文件: %CONFIG_FILE%
echo.

REM 设置传输模式环境变量
set AF_SERVER_TRANSPORT=%TRANSPORT%

echo ============================================================
echo   AgentFlow v2 已启动
echo   Dashboard: http://localhost:8081
if "%TRANSPORT%"=="sse" (
    echo   MCP URL:   http://localhost:8080/mcp
)
echo   按 Ctrl+C 停止
echo ============================================================
echo.

"%EXE_FILE%" -config "%CONFIG_FILE%"

endlocal
