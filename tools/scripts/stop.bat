@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo   AgentFlow v2 - 停止服务 (Windows)
echo ============================================================
echo.

:: 停止 AgentFlow
echo [1/2] 停止 AgentFlow...
tasklist /FI "IMAGENAME eq agentflow.exe" 2>NUL | find /I "agentflow.exe" >NUL
if %errorlevel%==0 (
    taskkill /IM agentflow.exe /F >nul 2>&1
    echo       [√] AgentFlow 已停止
) else (
    echo       [i] AgentFlow 未在运行
)

:: 询问是否停止 Redis
echo.
set /p STOP_REDIS="[2/2] 是否同时停止 Redis? (y/N): "
if /i "%STOP_REDIS%"=="y" (
    redis-cli shutdown nosave >nul 2>&1
    if %errorlevel%==0 (
        echo       [√] Redis 已停止
    ) else (
        echo       [i] Redis 未在运行或无法停止
    )
) else (
    echo       [i] 保留 Redis 运行
)

echo.
echo [√] 完成
endlocal
