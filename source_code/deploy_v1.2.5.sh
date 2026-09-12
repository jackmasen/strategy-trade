#!/bin/bash
# ==========================================
# AI策略交易系统 v1.2.5 一键部署脚本
# 在服务器上执行：bash deploy_v1.2.5.sh
# ==========================================

set -e

PROJECT_DIR="/www/wwwroot/strategy-trade"
PYTHON="$PROJECT_DIR/venv/bin/python"
PIP="$PROJECT_DIR/venv/bin/pip"
NPM="npm"

echo "=========================================="
echo "  AI策略交易系统 v1.2.5 部署脚本"
echo "=========================================="

# ---------- 1. 进入项目目录 ----------
cd "$PROJECT_DIR"
echo "[1/7] 项目目录: $PROJECT_DIR"

# ---------- 2. 备份当前 .env ----------
if [ -f ".env" ]; then
    cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
    echo "[2/7] .env 已备份"
else
    echo "[2/7] 无 .env 文件（首次部署）"
fi

# ---------- 3. 安装后端依赖 ----------
echo "[3/7] 安装后端Python依赖..."
$PIP install -r requirements.txt -q 2>&1 | tail -5
echo "      [OK] Python依赖安装完成"

# ---------- 4. 构建前端 ----------
echo "[4/7] 构建前端..."
cd "$PROJECT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    echo "      首次安装node_modules..."
    $NPM install 2>&1 | tail -5
fi
$NPM run build 2>&1 | tail -10
echo "      [OK] 前端构建完成 -> dist/"
cd "$PROJECT_DIR"

# ---------- 5. 数据库迁移 ----------
echo "[5/7] 数据库检查..."
$PYTHON -c "
from backend.config import get_settings
from backend.db.session import engine_sync
from sqlalchemy import inspect
insp = inspect(engine_sync)
tables = insp.get_table_names()
print(f'      数据库连接成功，已有 {len(tables)} 张表')
if len(tables) == 0:
    print('      首次部署，自动建表...')
" 2>&1
echo "      [OK] 数据库就绪"

# ---------- 6. 重启服务 ----------
echo "[6/7] 重启服务..."
# 宝塔面板 + Supervisor
if command -v supervisorctl &> /dev/null; then
    supervisorctl restart all 2>&1 || {
        echo "      supervisorctl 不可用，尝试手动重启..."
        # 尝试kill旧进程
        pkill -f "uvicorn main:app" 2>/dev/null || true
        pkill -f "celery.*celery_app" 2>/dev/null || true
        sleep 2
    }
else
    echo "      未安装supervisorctl，手动重启..."
    pkill -f "uvicorn main:app" 2>/dev/null || true
    pkill -f "celery.*celery_app" 2>/dev/null || true
    sleep 2
fi
echo "      [OK] 旧进程已清理"

# ---------- 7. 启动服务 ----------
echo "[7/7] 启动服务..."

# 检查supervisor配置
SUPERVISOR_CONF="/etc/supervisor/conf.d/strategy-trade.conf"
if [ ! -f "$SUPERVISOR_CONF" ]; then
    SUPERVISOR_CONF="$PROJECT_DIR/deploy/supervisor.conf"
fi

if [ -f "$SUPERVISOR_CONF" ]; then
    echo "      使用Supervisor启动..."
    supervisorctl reread 2>/dev/null || true
    supervisorctl update 2>/dev/null || true
    supervisorctl restart all 2>/dev/null || {
        # 如果supervisor不可用，直接启动
        cd "$PROJECT_DIR"
        ENV_FOR_DYNACONF=production $PYTHON -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 &
        sleep 1
        $PYTHON -m celery -A backend.core.celery_app worker --loglevel=info -P prefork -c 4 -Q scheduled,trade,ai,backtest,default &
        sleep 1
        $PYTHON -m celery -A backend.core.celery_app beat --loglevel=info &
    }
else
    echo "      直接启动进程..."
    cd "$PROJECT_DIR"
    ENV_FOR_DYNACONF=production $PYTHON -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 &
    sleep 1
    $PYTHON -m celery -A backend.core.celery_app worker --loglevel=info -P prefork -c 4 -Q scheduled,trade,ai,backtest,default &
    sleep 1
    $PYTHON -m celery -A backend.core.celery_app beat --loglevel=info &
fi

sleep 5

# ---------- 验证 ----------
echo ""
echo "=========================================="
echo "  部署完成！验证服务状态..."
echo "=========================================="

# 检查后端
if curl -s http://127.0.0.1:8000/health | grep -q "status"; then
    echo "  [OK] 后端API: http://127.0.0.1:8000"
else
    echo "  [WARN] 后端API未响应，请检查日志:"
    echo "        tail -50 $PROJECT_DIR/logs/api.log"
fi

# 检查前端
if [ -d "$PROJECT_DIR/frontend/dist" ]; then
    echo "  [OK] 前端静态文件: $PROJECT_DIR/frontend/dist/"
fi

# 检查Celery
if pgrep -f "celery.*worker" > /dev/null; then
    echo "  [OK] Celery Worker 运行中"
else
    echo "  [WARN] Celery Worker 未运行"
fi

if pgrep -f "celery.*beat" > /dev/null; then
    echo "  [OK] Celery Beat 运行中"
else
    echo "  [WARN] Celery Beat 未运行"
fi

echo ""
echo "访问地址: https://你的域名/"
echo "API文档: https://你的域名/docs (production环境默认关闭)"
echo "=========================================="
