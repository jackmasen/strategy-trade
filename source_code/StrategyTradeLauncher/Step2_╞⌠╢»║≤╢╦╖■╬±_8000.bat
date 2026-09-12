@echo off
chcp 65001 >nul
title [2/4] 后端服务 FastAPI :8000 (策略交易系统)

REM 切到项目根目录
cd /d "%~dp0.."
set "PROJ_ROOT=%CD%"
echo 项目根：%PROJ_ROOT%
echo.

REM 找 python：优先 .venv，否则系统 python
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=%PROJ_ROOT%\.venv\Scripts\python.exe"

REM 如果还没安装依赖，先尝试 requirements.txt（若失败也不致命，只提示）
%PY% -c "import uvicorn, fastapi, sqlalchemy" 2>nul
if errorlevel 1 (
    echo [!] 首次启动：检测到后端依赖（fastapi / sqlalchemy / uvicorn）未安装，正在安装...
    echo     如果 pip 拉不动，建议自行设置国内镜像。
    echo.
    %PY% -m pip install -r "%PROJ_ROOT%\requirements.txt" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
)

echo.
echo ================================================================
echo   [Step 2 / 4] 启动后端 FastAPI（端口 8000）
echo   健康检查：http://127.0.0.1:8000/health
echo   Swagger 文档：http://127.0.0.1:8000/docs  ← 你现在要访问的就是这个！
echo ================================================================
echo.

%PY% "%PROJ_ROOT%\_launch_backend.py"
echo.
echo 后端已退出。
pause
