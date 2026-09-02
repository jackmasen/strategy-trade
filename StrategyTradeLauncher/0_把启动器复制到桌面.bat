@echo off
chcp 65001 >nul
title 把启动器复制到桌面（方便双击）
cd /d "%~dp0"
set "SRC=%~dp0"
set "DST=C:\Users\AI\Desktop\StrategyTradeLauncher"

echo.
echo 正在把这个文件夹里的所有启动脚本，复制到：
echo    %DST%
echo.

if exist "%DST%\" (
    echo [!] 检测到桌面已有旧的 StrategyTradeLauncher 文件夹
    choice /C YN /M "是否删除并重新复制（Y）/ 取消（N）"
    if errorlevel 2 goto END
    rmdir /s /q "%DST%"
)

REM xcopy: /E=子目录 /H=隐藏 /I=目标是目录 /Y=不提示
xcopy "%SRC%*" "%DST%\" /E /H /I /Y

echo.
echo ✅ 已复制到桌面！接下来在桌面上打开 StrategyTradeLauncher 文件夹，
echo    按 1 → 2 → 3 顺序双击 .bat 即可。
echo.
echo 或者直接双击桌面上的 Step4_一键启动后端+前端.bat
echo.

REM 打开桌面 StrategyTradeLauncher 文件夹
start explorer.exe "%DST%"

:END
pause
