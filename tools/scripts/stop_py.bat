@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo   AgentFlow v2 [Python] - 停止服务 (Windows)
echo ============================================================
echo.

:: 停止 AgentFlow (Python)
echo [1/2] 停止 AgentFlow [Python]...

:: 查找运行 main.py 的 python 进程
set FOUND=0
for /f "tokens=2" %%p in ('wmic process where "commandline like '%%agentflow_py%%main.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /PID %%p /F >nul 2>&1
    set FOUND=1
)

if "%FOUND%"=="1" (
    echo       [√] AgentFlow [Python] 已停止
) else (
    echo       [i] AgentFlow [Python] 未在运行
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
