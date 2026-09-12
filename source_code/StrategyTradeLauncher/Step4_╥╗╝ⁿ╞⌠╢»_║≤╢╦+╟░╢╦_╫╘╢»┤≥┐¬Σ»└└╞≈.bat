@echo off
chcp 65001 >nul
title Step4_一键启动（后端 8000 + 前端 5173，成功自动打开两个浏览器窗口）
cd /d "%~dp0"

echo ================================================================
echo   策略交易系统 一键启动
echo   顺序：Step1（只做1次解锁PS）→ Step2（后端）→ Step3（前端）
echo ================================================================
echo.

REM Step1 只做 1 次，用户可选
echo 如果你是第一次在本机启动，建议先按 Y 执行 Step1 解锁 PowerShell（仅当前用户，不要求管理员）
echo 如果之前已经做过 Step1，按 N 直接启动后端+前端。
echo.
choice /C YN /M "是否运行 Step1（仅首次需要）"
if errorlevel 2 goto START
call "Step1_解锁PowerShell_只做一次.bat"

:START
echo.
echo 正在启动后端 ...
call "Step2_启动后端服务_8000_自动打开浏览器.bat" start_in_background
echo.
echo 正在启动前端 ...
call "Step3_启动前端服务_5173_自动打开浏览器.bat" start_in_background
echo.
echo ✅ 后端和前端已在独立黑框窗口中启动：
echo      · 后端成功后会自动打开 http://127.0.0.1:8000/docs
echo      · 前端成功后会自动打开 http://127.0.0.1:5173
echo.
echo  没有自动打开？手动访问：
echo      Swagger ：http://127.0.0.1:8000/docs
echo      前端    ：http://127.0.0.1:5173
echo      登录账号：admin / Admin@2024
pause
