@echo off
chcp 65001 >nul
title 策略交易系统 - 后端服务 (FastAPI :8000)
cd /d "%~dp0"

echo.
echo ==================================================
echo   策略交易系统 后端服务启动中...
echo   端口: 8000
echo   API 文档: http://127.0.0.1:8000/api/v1/docs
echo   健康检查: http://127.0.0.1:8000/health
echo   退出: Ctrl + C
echo ==================================================
echo.

REM ====== 选 Python ======
if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

REM ====== 启动前先建表 + 初始化种子（不依赖 lifespan，避免 worker fork 竞争）======
echo [初始化] 建表 + 种子数据（admin / Admin@2024）...
%PY_EXE% -c "import os,sys,pathlib; p=pathlib.Path(r'%~dp0'); os.chdir(str(p)); sys.path.insert(0,str(p)); from backend.db.session import SessionLocal, engine_sync; from backend.db.base import Base; from backend.db.seed_data import ensure_seed_data; from backend.models import *; Base.metadata.create_all(bind=engine_sync); db=SessionLocal(); s=ensure_seed_data(db, with_mock_trades=True); print('[初始化完成] stats=', s)" 2>&1

REM ====== 启动 uvicorn（1 worker 足够单用户单账号）======
echo.
echo [启动] uvicorn main:app --host 0.0.0.0 --port 8000
echo.
%PY_EXE% -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level info

pause
