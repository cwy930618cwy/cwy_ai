@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   AgentFlow v2 - 开发模式启动 (Windows)
echo   自动构建 + 启动，每次运行都重新编译
echo ============================================================
echo.

set PROJECT_DIR=%~dp0..
set CONFIG_FILE=%PROJECT_DIR%\configs\config.yaml
set REDIS_PORT=6379

REM 可通过参数覆盖: dev.bat stdio
set TRANSPORT=%1
if "%TRANSPORT%"=="" set TRANSPORT=sse

REM 检查 Go
where go >nul 2>&1
if !errorlevel! neq 0 (
    echo [×] 未找到 Go 编译器，请安装 Go 1.21+
    pause
    exit /b 1
)

REM 检查 Redis
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

REM 构建
echo [i] 正在构建...
pushd "%PROJECT_DIR%"
go build -o agentflow.exe .
if !errorlevel! neq 0 (
    echo [×] 构建失败
    popd
    pause
    exit /b 1
)
popd
echo [√] 构建成功

REM 设置开发环境变量
set AF_SERVER_TRANSPORT=%TRANSPORT%
set AF_SERVER_LOG_LEVEL=debug

echo.
echo ============================================================
echo   [DEV] AgentFlow v2 (日志级别: debug)
echo   Dashboard: http://localhost:8081
if "%TRANSPORT%"=="sse" (
    echo   MCP URL:   http://localhost:8080/mcp
)
echo   按 Ctrl+C 停止
echo ============================================================
echo.

"%PROJECT_DIR%\agentflow.exe" -config "%CONFIG_FILE%"

endlocal
