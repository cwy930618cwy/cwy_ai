@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   AgentFlow v2 [Python] - 一键启动 (Windows)
echo ============================================================
echo.

REM ============================================================
REM 配置区域
REM ============================================================
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set PY_PROJECT_DIR=%PROJECT_DIR%\agentflow_py
set CONFIG_FILE=%PY_PROJECT_DIR%\configs\config.yaml

REM 可通过参数覆盖传输模式: start_py.bat stdio | start_py.bat sse
set TRANSPORT=%1
if "%TRANSPORT%"=="" set TRANSPORT=sse

REM ============================================================
REM Step 1: 检查 Python 环境
REM ============================================================
echo [1/3] 检查 Python 环境...

where python >nul 2>&1
if !errorlevel! neq 0 (
    echo       [×] 未找到 Python，请安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查 Python 版本 (需要 3.10+)
for /f "tokens=*" %%v in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PYVER=%%v
echo       [√] Python %PYVER%

REM 检查依赖是否已安装
python -c "import aiosqlite; import pydantic; import yaml; import fastapi; import uvicorn; import aiohttp" >nul 2>&1
if !errorlevel! neq 0 (
    echo       [i] 正在安装依赖...
    pip install -r "%PY_PROJECT_DIR%\requirements.txt" -q
    if !errorlevel! neq 0 (
        echo       [×] 依赖安装失败
        pause
        exit /b 1
    )
    echo       [√] 依赖安装成功
) else (
    echo       [√] 依赖已就绪
)

REM ============================================================
REM Step 2: 确保数据目录
REM ============================================================
echo [2/3] 检查数据目录...

if not exist "%PY_PROJECT_DIR%\data" mkdir "%PY_PROJECT_DIR%\data"
if not exist "%PY_PROJECT_DIR%\data\test_cases" mkdir "%PY_PROJECT_DIR%\data\test_cases"
echo       [√] 数据目录就绪

REM ============================================================
REM Step 3: 启动 AgentFlow (Python)
REM ============================================================
echo [3/3] 启动 AgentFlow v2 [Python]...
echo.
echo       传输模式: %TRANSPORT%
echo       配置文件: %CONFIG_FILE%
echo.

REM 设置传输模式环境变量
set AF_SERVER_TRANSPORT=%TRANSPORT%

echo ============================================================
echo   AgentFlow v2 [Python] 已启动
echo   Dashboard: http://localhost:8081
if "%TRANSPORT%"=="sse" (
    echo   MCP URL:   http://localhost:8080/mcp
)
echo   按 Ctrl+C 停止
echo ============================================================
echo.

python "%PY_PROJECT_DIR%\main.py" --config "%CONFIG_FILE%"

endlocal