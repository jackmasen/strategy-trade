@echo off
chcp 65001 >nul
title Step3_启动前端 Vite 5173（新版：成功自动打开浏览器）
REM 纯 cmd 脚本，不经过 PowerShell → ExecutionPolicy 完全不影响
setlocal enableDelayedExpansion

cd /d "%~dp0.."
set "PROJ_ROOT=%CD%"
cd /d "%PROJ_ROOT%\frontend"

echo ================================================================
echo   策略交易系统 - 启动前端 Vite :5173
echo   项目根：%PROJ_ROOT%
echo ================================================================
echo.

REM 1) 清旧占用 5173
echo [1/4] 清理 5173 端口旧占用...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /R /C:":5173 .*LISTENING"') do (
    set PID_KILL=%%a
    if not "!PID_KILL!"=="" (
        echo        发现占用 PID !PID_KILL!，正在终止...
        taskkill /PID !PID_KILL! /F >nul 2>nul
    )
)
echo        完成。
echo.

REM 2) 查 node/npm
echo [2/4] 检查 Node.js / npm...
where node >nul 2>nul
if errorlevel 1 (
    echo ❌ 未检测到 Node.js。请先安装 Node.js 18+（下载 https://nodejs.org/，安装时务必勾选「Add to PATH」）。
    echo    安装完重启电脑，再运行本脚本。
    echo.
    echo    暂时先看 UI 骨架？打开：%PROJ_ROOT%\StrategyTradeLauncher\preview\index.html
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version 2^>^&1') do set NV=%%i
for /f "tokens=*" %%i in ('npm --version 2^>^&1') do set NPMV=%%i
echo        node %NV%   npm %NPMV%
echo.

REM 3) 缺 node_modules 就装
echo [3/4] 安装前端依赖（缺 node_modules 时才执行）...
if not exist "node_modules\" (
    echo        node_modules 不存在 → npm install（国内镜像加速）...
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo ⚠️  镜像安装失败，尝试官方源...
        call npm install
        if errorlevel 1 (
            echo ❌ npm install 失败，请检查 Node 版本（建议 18+）或网络。
            pause
            exit /b 1
        )
    )
    echo        依赖安装完成。
) else (
    echo        已检测到 node_modules，跳过 npm install。
)
echo.

REM 4) 启动前端：新黑框常驻 + 当前脚本轮询，成功自动打开浏览器
echo [4/4] 启动 Vite :5173 ...
set "LOGFILE=%PROJ_ROOT%\_logs_frontend.log"
start "[前端] Vite :5173" cmd /k "call npm run dev 2>&1 | tee ""%LOGFILE%"""
echo        前端窗口已打开，日志也写到：%LOGFILE%
echo.

echo        探测页面是否可访问（最多 60 秒）...
set MAX=30
set I=0
set OK=0
:LOOP
set /a I=I+1
if %I% gtr %MAX% goto LOOP_END

curl -s --max-time 2 "http://127.0.0.1:5173/" >nul 2>nul
if not errorlevel 1 (
    set OK=1
    echo ✅ 探测成功！前端服务可用
    echo.
    start "" "http://127.0.0.1:5173/"
    echo 浏览器已打开 5173 页面，默认账号：admin / Admin@2024
    goto END
)
<nul set /p=.
timeout /t 2 /nobreak >nul
goto LOOP

:LOOP_END
echo.
if %OK%==0 (
    echo ⚠️  60 秒内页面仍不可用。请查看前端黑框日志：%LOGFILE%
    echo    常见原因：首次 npm install 仍在进行 / Vite 正在预构建 / 5173 被其他应用占用。
)

:END
endlocal
echo.
pause
