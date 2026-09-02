@echo off
chcp 65001 >nul
title [4/4] 一键启动：后端 8000 + 前端 5173
cd /d "%~dp0"

echo ================================================================
echo   [Step 4 / 4] 一键启动策略交易系统（后端 + 前端）
echo   顺序：Step1（可选解锁）→ Step2（后端）→ Step3（前端）
echo ================================================================
echo.

REM Step1 只做一次，可选
echo [可选] 如果你是第一次启动，建议先按 Y 运行 Step1 解锁 PowerShell；如果之前已经做过，按 N 跳过。
choice /C YN /M "是否先运行 Step1（解锁 PowerShell，仅首次需要）"
if errorlevel 2 goto STEP2
call "Step1_解锁PowerShell_只做一次.bat"

:STEP2
echo.
echo 正在启动后端服务（新窗口运行，不要关闭那个黑框）...
start "[后端] FastAPI :8000" cmd /k ""%~dp0Step2_启动后端服务_8000.bat""
echo 后端窗口已打开，请等它滚动完「Uvicorn running on http://0.0.0.0:8000」再继续。
echo.
timeout /t 6 /nobreak >nul

echo 正在启动前端服务（新窗口运行，不要关闭那个黑框）...
start "[前端] Vite :5173" cmd /k ""%~dp0Step3_启动前端服务_5173.bat""

echo.
echo ✅ 后端+前端已启动（各自在独立窗口运行）
echo.
echo     后端健康 ： http://127.0.0.1:8000/health
echo     Swagger文档：http://127.0.0.1:8000/docs    ← 你要的地址就是这个
echo     前端页面   ：http://127.0.0.1:5173
echo     登录账号   ：admin / Admin@2024
echo.
echo  如果 8000/docs 打开是 404 / 连接拒绝，看后端窗口日志：
echo   · 看到「Uvicorn running on 0.0.0.0:8000」表示后端真启动了；
echo   · 如果看到 MySQL 连接报错也没关系，系统会自动降级到 SQLite 文件继续运行。
echo.
pause
