@echo off
chcp 65001 >nul
title [3/4] 前端服务 Vite :5173 (策略交易系统)

cd /d "%~dp0.."
set "PROJ_ROOT=%CD%"
cd /d "%PROJ_ROOT%\frontend"

echo ================================================================
echo   [Step 3 / 4] 启动前端 Vite (端口 5173)
echo   访问地址：http://127.0.0.1:5173
echo   默认账号：admin / Admin@2024
echo ================================================================
echo.

REM 检查 node / npm
where node >nul 2>nul
if errorlevel 1 (
    echo ❌ 未检测到 Node.js。请先安装 Node.js 18+（https://nodejs.org/ ，安装时勾选 Add to PATH），
    echo    安装完重启电脑后再运行本脚本。
    echo.
    echo    （可选）暂时不想装 Node？直接打开本目录下 preview\index.html 看 UI 骨架
    echo.
    pause
    exit /b 1
)

REM 首次启动：没 node_modules 就装依赖（国内镜像加速）
if not exist "node_modules\" (
    echo [!] 首次启动：node_modules 不存在，开始 npm install ...
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo ❌ npm install 失败，请检查 Node 版本或网络。
        pause
        exit /b 1
    )
    echo ✅ 依赖安装完成。
)

REM 启动 Vite，启动成功后自动打开浏览器
set BROWSER=none
call npm run dev

pause
