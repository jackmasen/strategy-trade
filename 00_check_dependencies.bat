@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 策略交易系统 - 依赖检查与安装
cd /d "%~dp0"

echo.
echo ==================================================
echo   策略交易系统 依赖检查与一键安装
echo ==================================================
echo.

REM ====== 1. 检查 Python ======
echo [1/4] 检查 Python 环境...
where python >nul 2>nul
if errorlevel 1 (
    echo ❌ 未检测到 Python，请先安装 Python 3.10+ 并加入 PATH
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo ✅ Python 版本: %PY_VER%

REM ====== 2. 创建虚拟环境（可选）======
echo.
echo [2/4] 检查 Python 依赖...
if not exist ".venv\Scripts\python.exe" (
    echo   - 未发现虚拟环境，使用系统 Python（如需隔离可手动 python -m venv .venv）
    set "PY_EXE=python"
) else (
    echo   - 发现虚拟环境 .venv，使用虚拟环境 Python
    set "PY_EXE=.venv\Scripts\python.exe"
)

REM ====== 3. 安装后端依赖 ======
echo.
echo [3/4] 安装后端依赖（requirements.txt）...
%PY_EXE% -m pip install --upgrade pip >nul
%PY_EXE% -m pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ 后端依赖安装失败，请检查网络或 pip 源
    pause
    exit /b 1
)
echo ✅ 后端依赖安装完成

REM ====== 4. 检查并安装前端依赖 ======
echo.
echo [4/4] 检查前端依赖...
cd frontend
if not exist "node_modules" (
    echo   - 未发现 node_modules，开始 npm install...
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo ❌ 前端依赖安装失败，请检查 Node.js 版本（建议 18+）
        pause
        exit /b 1
    )
    echo ✅ 前端依赖安装完成
) else (
    echo ✅ 前端依赖已存在（如需重装可删除 frontend\node_modules 再跑本脚本）
)
cd ..

echo.
echo ==================================================
echo   ✅ 全部依赖检查通过，下一步：
echo      - 双击 01_start_backend.bat 启动后端
echo      - 双击 02_start_frontend.bat 启动前端
echo      - 浏览器访问 http://127.0.0.1:5173
echo      - 默认账号：admin / Admin@2024
echo ==================================================
echo.
pause
