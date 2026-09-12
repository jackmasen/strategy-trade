@echo off
chcp 65001 >nul
title [1/4] 解锁 PowerShell 脚本权限（只做一次！）
REM 作用：把当前用户的 ExecutionPolicy 设为 RemoteSigned（不用管理员）
REM 为什么要做？不做的话，你本机任何 .ps1 脚本都会被默认拒绝（包括 TRAE 内置工具尝试调用命令时）
echo.
echo ================================================================
echo   [Step 1 / 4] 解锁 PowerShell 脚本权限（仅需要做 1 次）
echo ================================================================
echo.
echo 正在执行：
echo    powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force"
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force"
echo.
echo 完成！
echo 现在你可以关闭本窗口，继续双击「Step2_启动后端服务_8000.bat」
echo.
pause
