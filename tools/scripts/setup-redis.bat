@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   AgentFlow v2 - Redis 安装与启动 (Windows, 要求 Redis 5.0+)
echo ============================================================
echo.

REM ============================================================
REM 配置区域 (可按需修改)
REM ============================================================
set REDIS_PORT=6379
set REDIS_PASSWORD=
set REDIS_MAXMEMORY=256mb
REM Redis 持久化数据目录 — 与 Go 代码中 config.GetRedisDataDir() 保持一致 (data_dir/redis)
set REDIS_DIR=%~dp0..\data\redis
REM tporadowski Redis 本地安装目录
set REDIS_INSTALL_DIR=%~dp0..\tools\redis
REM tporadowski Redis 下载地址（Windows 原生移植，支持 5.0+ 命令集）
set REDIS_VER_MAJOR=5
set REDIS_VER_MINOR=0
set REDIS_VER_PATCH=14
set REDIS_VER_BUILD=1
set REDIS_VERSION=%REDIS_VER_MAJOR%.%REDIS_VER_MINOR%.%REDIS_VER_PATCH%.%REDIS_VER_BUILD%
set REDIS_DOWNLOAD_URL=https://github.com/tporadowski/redis/releases/download/v%REDIS_VERSION%/Redis-x64-%REDIS_VERSION%.zip
set REDIS_ZIP_NAME=Redis-x64-%REDIS_VERSION%.zip

REM ============================================================
REM 检测 Redis 是否已安装
REM ============================================================
set NEED_INSTALL=0

REM 优先检测本地 tools\redis 目录
if exist "%REDIS_INSTALL_DIR%\redis-server.exe" (
    set "PATH=%REDIS_INSTALL_DIR%;%PATH%"
)

where redis-server >nul 2>&1
if !errorlevel! equ 0 (
    echo [√] Redis 已安装
    redis-server --version
    REM 检查 Redis 版本是否 >= 5.0
    REM redis-server --version 输出格式: Redis server v=X.Y.Z ...
    REM 提取第3个空格分隔的token (v=X.Y.Z)，再按=分隔取版本号
    for /f "tokens=3 delims= " %%v in ('redis-server --version 2^>^&1') do (
        set REDIS_VER_RAW=%%v
    )
    REM 按 = 分隔，取第2个token得到纯版本号
    for /f "tokens=2 delims==" %%n in ("!REDIS_VER_RAW!") do set REDIS_VER_STR=%%n
    for /f "tokens=1 delims=." %%m in ("!REDIS_VER_STR!") do set REDIS_MAJOR=%%m
    if !REDIS_MAJOR! lss 5 (
        echo [^^!] Redis 版本过低^^！当前: !REDIS_VER_STR!，需要 5.0+
        echo [i] 将尝试卸载旧版本并重新安装...
        set NEED_INSTALL=1
        REM 尝试卸载旧版本（winget 的 Redis.Redis 只有 3.0.504，必须卸载）
        echo [i] 正在卸载旧版 Redis...
        REM 停止旧版 Redis 服务（如果作为 Windows 服务运行）
        net stop Redis >nul 2>&1
        sc delete Redis >nul 2>&1
        REM 通过 MSI 卸载（winget 安装的 3.0.504 是 MSI 包）
        wmic product where "name like '%%Redis%%'" call uninstall /nointeractive >nul 2>&1
        where winget >nul 2>&1 && winget uninstall Redis.Redis --silent >nul 2>&1
        where scoop >nul 2>&1 && scoop uninstall redis >nul 2>&1
        where choco >nul 2>&1 && choco uninstall redis-64 -y >nul 2>&1
        REM 清理旧版 PATH 中可能残留的 Redis 路径
        echo [i] 旧版本卸载完成
    ) else (
        echo [√] Redis 版本检查通过 ^(!REDIS_VER_STR!^)
        goto :start_redis
    )
) else (
    set NEED_INSTALL=1
)

REM ============================================================
REM 安装 Redis 5.0+ (tporadowski 社区维护的 Windows 原生版本)
REM ============================================================
if !NEED_INSTALL! equ 0 goto :start_redis

echo [i] 正在安装 Redis 5.0+...
echo.
echo [i] 注意: winget 的 Redis.Redis 包只有 3.0.504（已停止维护），不使用 winget。
echo [i] 将从 GitHub 下载 tporadowski/redis 5.0.14（社区维护的 Windows 原生版本）。
echo.

REM ============================================================
REM 方式1: 直接从 GitHub 下载 tporadowski/redis（推荐）
REM ============================================================
:try_download
echo [i] 方式1: 从 GitHub 下载 tporadowski/redis 5.0.14...

REM 如果本地已经有解压好的 redis，直接跳过下载
if exist "%REDIS_INSTALL_DIR%\redis-server.exe" (
    echo [√] 已存在本地 Redis: %REDIS_INSTALL_DIR%
    set "PATH=%REDIS_INSTALL_DIR%;%PATH%"
    goto :verify_version
)

REM 创建 tools 目录
if not exist "%~dp0..\tools" mkdir "%~dp0..\tools"

set REDIS_ZIP_PATH=%~dp0..\tools\%REDIS_ZIP_NAME%

REM 尝试用 curl 下载
where curl >nul 2>&1
if !errorlevel! equ 0 (
    echo [i] 使用 curl 下载...
    echo [i] URL: %REDIS_DOWNLOAD_URL%
    curl -L -o "%REDIS_ZIP_PATH%" "%REDIS_DOWNLOAD_URL%" --progress-bar
    if !errorlevel! equ 0 goto :extract_redis
    echo [!] curl 下载失败，尝试 PowerShell...
)

REM 尝试用 PowerShell 下载
echo [i] 使用 PowerShell 下载...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%REDIS_DOWNLOAD_URL%' -OutFile '%REDIS_ZIP_PATH%' -UseBasicParsing"
if !errorlevel! equ 0 goto :extract_redis

echo [!] 下载失败，尝试其他安装方式...
goto :try_scoop

:extract_redis
REM 验证下载的文件存在且不为空
if not exist "%REDIS_ZIP_PATH%" (
    echo [!] 下载的文件不存在
    goto :try_scoop
)

echo [i] 正在解压到 %REDIS_INSTALL_DIR% ...

REM 如果目标目录已存在，先清理
if exist "%REDIS_INSTALL_DIR%" rmdir /s /q "%REDIS_INSTALL_DIR%"
mkdir "%REDIS_INSTALL_DIR%"

REM 使用 PowerShell 解压
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%REDIS_ZIP_PATH%' -DestinationPath '%REDIS_INSTALL_DIR%' -Force"
if !errorlevel! neq 0 (
    echo [!] 解压失败
    goto :try_scoop
)

REM 检查是否解压到了子目录中（zip 内可能有一层目录）
if not exist "%REDIS_INSTALL_DIR%\redis-server.exe" (
    REM 查找子目录中的 redis-server.exe
    for /d %%d in ("%REDIS_INSTALL_DIR%\*") do (
        if exist "%%d\redis-server.exe" (
            echo [i] 发现 Redis 在子目录 %%d，正在移动文件...
            xcopy /e /y "%%d\*" "%REDIS_INSTALL_DIR%\" >nul
            rmdir /s /q "%%d" >nul 2>&1
        )
    )
)

REM 再次检查
if not exist "%REDIS_INSTALL_DIR%\redis-server.exe" (
    echo [!] 解压后未找到 redis-server.exe
    goto :try_scoop
)

REM 将本地 Redis 添加到当前会话 PATH
set "PATH=%REDIS_INSTALL_DIR%;%PATH%"

REM 清理 zip 文件
del "%REDIS_ZIP_PATH%" >nul 2>&1

echo [√] Redis 下载并解压成功: %REDIS_INSTALL_DIR%
goto :verify_version

REM ============================================================
REM 方式2: Scoop
REM ============================================================
:try_scoop
where scoop >nul 2>&1
if !errorlevel! neq 0 goto :try_choco
echo [i] 方式2: 尝试通过 Scoop 安装 Redis...
scoop install redis
if !errorlevel! equ 0 (
    echo [√] Redis 安装成功
    goto :verify_version
)

REM ============================================================
REM 方式3: Chocolatey
REM ============================================================
:try_choco
where choco >nul 2>&1
if !errorlevel! neq 0 goto :no_pkg_mgr
echo [i] 方式3: 尝试通过 Chocolatey 安装 Redis...
choco install redis-64 -y
if !errorlevel! equ 0 (
    echo [√] Redis 安装成功
    goto :verify_version
)

:no_pkg_mgr
echo.
echo [×] 所有自动安装方式均失败！请手动安装 Redis 5.0+:
echo.
echo     方式1: 从 https://github.com/tporadowski/redis/releases 下载 5.0.14
echo            解压到 %REDIS_INSTALL_DIR% 目录
echo     方式2: scoop install redis
echo     方式3: choco install redis-64
echo     方式4: 使用 Docker: docker run -d -p 6379:6379 redis:7-alpine
echo     方式5: 使用 WSL2: sudo apt install redis-server
echo.
echo     注意: winget 的 Redis.Redis 只有 3.0.504，不要使用 winget 安装！
echo.
pause
exit /b 1

:verify_version
REM 安装后再次验证版本
REM 优先使用本地 tools\redis 目录中的版本
if exist "%REDIS_INSTALL_DIR%\redis-server.exe" (
    set "PATH=%REDIS_INSTALL_DIR%;%PATH%"
)
where redis-server >nul 2>&1
if !errorlevel! neq 0 (
    echo [x] 安装后仍无法找到 redis-server，请检查 PATH 环境变量
    echo [i] 如果刚通过包管理器安装，请重新打开终端后再试
    pause
    exit /b 1
)
for /f "tokens=3 delims= " %%v in ('redis-server --version 2^>^&1') do (
    set REDIS_VER_RAW=%%v
)
for /f "tokens=2 delims==" %%n in ("!REDIS_VER_RAW!") do set REDIS_VER_STR=%%n
for /f "tokens=1 delims=." %%m in ("!REDIS_VER_STR!") do set REDIS_MAJOR=%%m
if !REDIS_MAJOR! lss 5 (
    echo [x] 安装后 Redis 版本仍低于 5.0 ^(!REDIS_VER_STR!^)
    echo [i] 检测到系统中仍存在旧版 Redis，可能是 PATH 优先级问题
    REM 如果本地有 tporadowski 版本，直接用绝对路径检测
    if exist "%REDIS_INSTALL_DIR%\redis-server.exe" (
        echo [i] 尝试使用本地下载的版本...
        set "PATH=%REDIS_INSTALL_DIR%;%PATH%"
        for /f "tokens=3 delims= " %%v in ('"%REDIS_INSTALL_DIR%\redis-server.exe" --version 2^>^&1') do (
            set REDIS_VER_RAW2=%%v
        )
        for /f "tokens=2 delims==" %%n in ("!REDIS_VER_RAW2!") do set REDIS_VER_STR2=%%n
        for /f "tokens=1 delims=." %%m in ("!REDIS_VER_STR2!") do set REDIS_MAJOR2=%%m
        if !REDIS_MAJOR2! geq 5 (
            echo [v] 本地 Redis 版本检查通过 ^(!REDIS_VER_STR2!^)
            goto :start_redis
        )
    )
    echo [x] 无法获取 Redis 5.0+，请手动处理：
    echo     1. 卸载旧版: 控制面板卸载或删除 "C:\Program Files\Redis"
    echo     2. 从 https://github.com/tporadowski/redis/releases 下载 5.0.14
    echo     3. 或在 WSL2 中安装: sudo apt install redis-server
    pause
    exit /b 1
)
echo [v] 新安装的 Redis 版本检查通过 ^(!REDIS_VER_STR!^)

:start_redis
echo.
echo ============================================================
echo   启动 Redis Server
echo ============================================================
echo.

REM 确保数据目录存在
if not exist "%REDIS_DIR%" mkdir "%REDIS_DIR%"

REM 检查 Redis 是否已在运行
redis-cli -p %REDIS_PORT% ping >nul 2>&1
if !errorlevel! neq 0 goto :do_start

REM Redis 已在运行
echo [√] Redis 已在运行 ^(端口 %REDIS_PORT%^)
redis-cli -p %REDIS_PORT% INFO server | findstr redis_version
echo.
echo 跳过启动，Redis 已就绪。
goto :done

:do_start
echo [i] Redis 未运行，正在启动...
echo [i] 端口: %REDIS_PORT%
echo [i] 数据目录: %REDIS_DIR%
echo.

REM 检查端口是否被其他进程占用
netstat -ano 2>nul | findstr ":%REDIS_PORT% " | findstr "LISTENING" >nul 2>&1
if !errorlevel! neq 0 goto :port_ok

echo [!] 警告: 端口 %REDIS_PORT% 已被其他进程占用！
netstat -ano | findstr ":%REDIS_PORT% " | findstr "LISTENING"
echo.
echo 请先释放端口或修改 REDIS_PORT 配置
pause
exit /b 1

:port_ok
REM 启动 Redis（要求 Redis 5.0+，启用 LRU 淘汰策略和 lazyfree）
if "%REDIS_PASSWORD%"=="" (
    start "Redis Server" /MIN redis-server --port %REDIS_PORT% --dir "%REDIS_DIR%" --maxmemory %REDIS_MAXMEMORY% --maxmemory-policy allkeys-lru --lazyfree-lazy-eviction yes --lazyfree-lazy-expire yes --save 60 1000 --save 300 100 --appendonly yes --appendfsync everysec --aof-use-rdb-preamble yes --loglevel notice
) else (
    start "Redis Server" /MIN redis-server --port %REDIS_PORT% --dir "%REDIS_DIR%" --maxmemory %REDIS_MAXMEMORY% --maxmemory-policy allkeys-lru --lazyfree-lazy-eviction yes --lazyfree-lazy-expire yes --requirepass %REDIS_PASSWORD% --save 60 1000 --save 300 100 --appendonly yes --appendfsync everysec --aof-use-rdb-preamble yes --loglevel notice
)

REM 等待 Redis 启动（最多重试 5 次，每次间隔 2 秒）
echo [i] 等待 Redis 启动...
set RETRY=0

:wait_loop
timeout /t 2 /nobreak >nul
set /a RETRY+=1

redis-cli -p %REDIS_PORT% ping >nul 2>&1
if !errorlevel! equ 0 goto :started

echo       尝试 !RETRY!/5 ...
if !RETRY! lss 5 goto :wait_loop

REM 5 次都失败了
echo.
echo [×] Redis 启动失败！
echo.
echo     可能的原因:
echo     1. Redis 配置文件有误
echo     2. 端口 %REDIS_PORT% 被占用
echo     3. Redis 版本低于 5.0 不兼容某些参数
echo.
echo     诊断步骤:
echo     a) 手动运行 redis-server --port %REDIS_PORT% 观察是否有报错
echo     b) 检查 Windows 事件日志
echo     c) 尝试不带参数直接运行 redis-server
echo.
pause
exit /b 1

:started
echo.
echo [√] Redis 已就绪！
echo     地址: 127.0.0.1:%REDIS_PORT%
if "%REDIS_PASSWORD%"=="" (
    echo     密码: ^<无^>
) else (
    echo     密码: %REDIS_PASSWORD%
)
echo     最大内存: %REDIS_MAXMEMORY%
echo     数据目录: %REDIS_DIR%
echo.

:done
endlocal
