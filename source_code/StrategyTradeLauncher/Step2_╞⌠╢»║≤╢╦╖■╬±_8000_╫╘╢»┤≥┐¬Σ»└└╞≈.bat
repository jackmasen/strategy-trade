@echo off
chcp 65001 >nul
title Step2_启动后端 FastAPI 8000（新版：自动杀旧占用 + 成功自动打开浏览器/docs）
REM ================================================================
REM  纯 cmd 脚本，不经过 PowerShell  → 100% 不受 ExecutionPolicy 限制
REM  功能：
REM    1) 自动杀掉占用 8000 端口的旧进程（避免 10048 占用报错）
REM    2) 首次启动自动走清华镜像 pip install requirements.txt
REM    3) 启动 uvicorn 后端，日志同时写控制台 + _logs_backend.log
REM    4) 后台循环探测 /health：探测成功就自动打开 /docs 页面（用户能看到明确成功信号）
REM ================================================================
setlocal enableDelayedExpansion

cd /d "%~dp0.."
set "PROJ_ROOT=%CD%"
cd /d "%PROJ_ROOT%"

echo ================================================================
echo   策略交易系统 - 启动后端 FastAPI :8000
echo   项目根：%PROJ_ROOT%
echo ================================================================
echo.

REM ---------- 1) 杀 8000 端口占用 ----------
echo [1/5] 清理 8000 端口旧占用（如存在）...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /R /C:":8000 .*LISTENING"') do (
    set PID_KILL=%%a
    if not "!PID_KILL!"=="" (
        echo        发现占用 PID !PID_KILL!，正在终止...
        taskkill /PID !PID_KILL! /F >nul 2>nul
        timeout /t 1 /nobreak >nul
    )
)
echo        清理完成。
echo.

REM ---------- 2) 找 python ----------
echo [2/5] 检测 Python 环境...
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=%PROJ_ROOT%\.venv\Scripts\python.exe"

"%PY%" --version >nul 2>nul
if errorlevel 1 (
    echo ❌ 未找到 Python。
    echo.
    echo    方案 A（推荐，5 分钟）：去 https://www.python.org/downloads/ 下载 Python 3.10+ 安装包，
    echo       安装时务必勾选「Add Python to PATH」，装完重启电脑再运行本脚本。
    echo.
    echo    方案 B（绿色免安装，1 分钟）：下载 embeddable python：
    echo       打开下载页：https://www.python.org/downloads/windows/
    echo       找 Python 3.10 / 3.11 的 "Windows embeddable package (64-bit)"，
    echo       下载 zip 后解压到：%PROJ_ROOT%\_python\  （解压后目录里有 python.exe）
    echo       然后重开本脚本即可（本脚本会自动优先使用 _python\python.exe）。
    echo.
    if exist "%PROJ_ROOT%\_python\python.exe" (
        echo        ✅ 检测到已解压 embeddable python：%PROJ_ROOT%\_python\python.exe
        set "PY=%PROJ_ROOT%\_python\python.exe"
        goto PY_OK
    )
    pause
    exit /b 1
)
:PY_OK
for /f "tokens=*" %%i in ('"%PY%" --version 2^>^&1') do set PV=%%i
echo        使用 Python：%PV%   ^( %PY% ^)
echo.

REM ---------- 3) 后端依赖安装 ----------
echo [3/5] 检查并安装后端依赖（首次启动需要）...
"%PY%" -c "import fastapi, uvicorn, sqlalchemy" >nul 2>nul
if errorlevel 1 (
    echo        检测到依赖缺失，正在 pip install（清华镜像加速）...
    "%PY%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>nul
    "%PY%" -m pip install -r "%PROJ_ROOT%\requirements.txt" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo ⚠️ pip 部分依赖安装失败，尝试不使用镜像重试一次...
        "%PY%" -m pip install -r "%PROJ_ROOT%\requirements.txt"
    )
    echo        依赖安装完成。
) else (
    echo        依赖 OK。
)
echo.

REM ---------- 4) 启动后端（另开一个窗口常驻，不要阻塞当前脚本探测） ----------
echo [4/5] 启动 uvicorn :8000 ...
set "LOGFILE=%PROJ_ROOT%\_logs_backend.log"

REM 兼容：
REM   - 如果系统里有 tee（新版 Windows 默认已附带）→ 控制台+日志双通道
REM   - 无 tee（老版 Windows 家庭版等）→ 仍保证写日志文件，不影响功能
where tee >nul 2>nul
if errorlevel 1 (
    start "[后端] FastAPI :8000" cmd /k ""%PY%" "%PROJ_ROOT%\_launch_backend.py" >> "%LOGFILE%" 2>&1"
) else (
    start "[后端] FastAPI :8000" cmd /k ""%PY%" "%PROJ_ROOT%\_launch_backend.py" 2>&1 | tee "%LOGFILE%""
)
echo        后端窗口已打开，日志也会写到：%LOGFILE%
echo.

REM ---------- 5) 轮询 /health，成功自动打开 /docs ----------
echo [5/5] 探测后端是否启动成功（最多 60 秒）...
set MAX=30
set I=0
set OK=0

REM 检查 curl 是否可用；老版 Windows 没有 curl 时，用 Python 自带 urllib 兜底探测，保证功能可用
where curl >nul 2>nul
set HAS_CURL=%ERRORLEVEL%

:LOOP
set /a I=I+1
if %I% gtr %MAX% goto LOOP_END

if %HAS_CURL%==0 (
    curl -s --max-time 2 "http://127.0.0.1:8000/health" >nul 2>nul
    set PROBE_ERR=%ERRORLEVEL%
) else (
    "%PY%" -c "import urllib.request,sys;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).read();sys.exit(0)" >nul 2>nul
    set PROBE_ERR=%ERRORLEVEL%
)

if %PROBE_ERR%==0 (
    set OK=1
    echo ✅ 探测成功！/health 返回 200
    echo.
    echo 正在打开 Swagger 文档：http://127.0.0.1:8000/docs  ...
    start "" "http://127.0.0.1:8000/docs"
    echo.
    echo 也可以手动访问：
    echo     Swagger ：http://127.0.0.1:8000/docs
    echo     健康检查 ：http://127.0.0.1:8000/health
    echo     ReDoc  ：http://127.0.0.1:8000/redoc
    echo.
    goto END
)
<nul set /p=.
timeout /t 2 /nobreak >nul
goto LOOP

:LOOP_END
echo.
if %OK%==0 (
    echo ⚠️  60 秒内仍未能访问 http://127.0.0.1:8000/health，请排查：
    echo     1) 打开后端黑框窗口，看最后一行报错
    echo     2) 或者查看日志：%LOGFILE%
    echo 常见原因：
    echo     - MySQL 连接不上（系统会自动降级 SQLite，通常会自动恢复，再等 10 秒即可）
    echo     - uvicorn 正在装依赖导致时间过长
    echo     - 8000 被其它软件占用（可以改 main.py 或 .env 的 SERVER_PORT）
)

:END
endlocal
echo.
pause
