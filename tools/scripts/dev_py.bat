@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   AgentFlow v2 [Python] - 开发模式启动 (Windows)
echo   自动安装依赖 + debug 日志 + 启动
echo ============================================================
echo.

set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set PY_PROJECT_DIR=%PROJECT_DIR%\agentflow_py
set CONFIG_FILE=%PY_PROJECT_DIR%\configs\config.yaml
set REDIS_PORT=6379

REM 可通过参数覆盖: dev_py.bat stdio
set TRANSPORT=%1
if "%TRANSPORT%"=="" set TRANSPORT=sse

REM 检查 Python
where python >nul 2>&1
if !errorlevel! neq 0 (
    echo [×] 未找到 Python，请安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查 Redis
set REDIS_LOCAL_DIR=%PROJECT_DIR%\tools\redis
if exist "%REDIS_LOCAL_DIR%\redis-cli.exe" (
    set "PATH=%REDIS_LOCAL_DIR%;%PATH%"
)

where redis-cli >nul 2>&1
if !errorlevel! neq 0 goto :dev_no_redis

redis-cli -p %REDIS_PORT% ping >nul 2>&1
if !errorlevel! neq 0 goto :dev_no_redis

echo [√] Redis OK
goto :dev_redis_ok

:dev_no_redis
echo [!] Redis 未运行或未安装，请先启动 Redis:
echo     scripts\setup-redis.bat
pause
exit /b 1

:dev_redis_ok

REM 安装/更新依赖
echo [i] 正在安装/更新依赖...
pip install -r "%PY_PROJECT_DIR%\requirements.txt" -q
if !errorlevel! neq 0 (
    echo [×] 依赖安装失败
    pause
    exit /b 1
)
echo [√] 依赖就绪

REM 确保数据目录
if not exist "%PY_PROJECT_DIR%\data" mkdir "%PY_PROJECT_DIR%\data"
if not exist "%PY_PROJECT_DIR%\data\test_cases" mkdir "%PY_PROJECT_DIR%\data\test_cases"
if not exist "%PY_PROJECT_DIR%\data\redis" mkdir "%PY_PROJECT_DIR%\data\redis"

REM 设置开发环境变量
set AF_SERVER_TRANSPORT=%TRANSPORT%
set AF_SERVER_LOG_LEVEL=debug

echo.
echo ============================================================
echo   [DEV] AgentFlow v2 [Python] (日志级别: debug)
echo   Dashboard: http://localhost:8081
if "%TRANSPORT%"=="sse" (
    echo   MCP URL:   http://localhost:8080/mcp
)
echo   按 Ctrl+C 停止
echo ============================================================
echo.

python "%PY_PROJECT_DIR%\main.py" --config "%CONFIG_FILE%"

endlocal
