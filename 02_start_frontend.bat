@echo off
chcp 65001 >nul
title 策略交易系统 - 前端服务 (Vite :5173)
cd /d "%~dp0\frontend"

echo.
echo ==================================================
echo   策略交易系统 前端服务启动中...
echo   访问地址: http://127.0.0.1:5173
echo   默认账号: admin / Admin@2024
echo   退出: Ctrl + C
echo ==================================================
echo.

REM ====== 检查 node_modules ======
if not exist "node_modules" (
    echo [首次启动] 未检测到前端依赖，开始安装（使用 npmmirror 国内镜像加速）...
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo ❌ 前端依赖安装失败，请确认已安装 Node.js 18+
        pause
        exit /b 1
    )
)

REM ====== 启动 Vite dev ======
echo [启动] npm run dev
echo.
call npm run dev

pause
