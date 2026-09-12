#!/bin/bash
# ==========================================================
# 策略交易系统 v1.2.6 一键升级脚本
# 宝塔面板环境使用
# 使用：上传到服务器后执行 bash deploy_v1.2.6.sh
# ==========================================================

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

PROJECT_DIR="/www/wwwroot/strategy-trade"
VENV_DIR="$PROJECT_DIR/venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
NPM="npm"

log()    { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()     { echo -e "${GREEN}[OK]${NC} $1"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  策略交易系统 v1.2.6 升级脚本${NC}"
echo -e "${GREEN}========================================${NC}"

# ---------- 0. 检查环境 ----------
log "检查环境..."
[ "$(id -u)" -eq 0 ] || warn "非 root 用户，部分操作可能需要 sudo"
[ -d "$PROJECT_DIR" ] || error "项目目录不存在: $PROJECT_DIR"

# ---------- 1. 创建虚拟环境（如果不存在）----------
if [ ! -d "$VENV_DIR" ]; then
    log "创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    ok "虚拟环境创建完成"
else
    log "虚拟环境已存在"
fi

source "$VENV_DIR/bin/activate"

# ---------- 2. 备份当前 .env ----------
if [ -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env" "$PROJECT_DIR/.env.backup.$(date +%Y%m%d_%H%M%S)"
    ok ".env 已备份"
else
    warn "无 .env 文件"
fi

# ---------- 3. 安装/更新 Python 依赖 ----------
log "安装 Python 依赖..."
$PIP install --upgrade pip setuptools wheel -q
$PIP install -r "$PROJECT_DIR/requirements.txt" -q
ok "Python 依赖安装完成"

# ---------- 4. 数据库迁移 ----------
log "数据库迁移..."
$PYTHON -c "
from backend.db.session import engine, Base
from backend.models import user, exchange, strategy, trade, analytics
Base.metadata.create_all(bind=engine)
print('数据库表同步完成')
" 2>&1 || warn "数据库迁移跳过（非阻断）"
ok "数据库就绪"

# ---------- 5. 前端构建 ----------
log "前端构建..."
if [ -d "$PROJECT_DIR/frontend/node_modules" ]; then
    (cd "$PROJECT_DIR/frontend" && $NPM run build) 2>&1 | tail -5
    ok "前端构建完成"
    # 复制 dist 到项目根目录（宝塔通常从根目录的 dist 提供静态文件）
    if [ -d "$PROJECT_DIR/frontend/dist" ]; then
        rm -rf "$PROJECT_DIR/dist"
        cp -r "$PROJECT_DIR/frontend/dist" "$PROJECT_DIR/"
        ok "dist 已复制到项目根目录"
    fi
else
    warn "node_modules 不存在，先安装前端依赖..."
    (cd "$PROJECT_DIR/frontend" && $NPM install) 2>&1 | tail -5
    (cd "$PROJECT_DIR/frontend" && $NPM run build) 2>&1 | tail -5
    if [ -d "$PROJECT_DIR/frontend/dist" ]; then
        rm -rf "$PROJECT_DIR/dist"
        cp -r "$PROJECT_DIR/frontend/dist" "$PROJECT_DIR/"
    fi
    ok "前端构建完成"
fi

# ---------- 6. 修复版本检测逻辑（防止硬编码旧版本导致无法更新）----------
log "修复版本检测逻辑..."
python3 -c "
import re, os, sys
sm_path = os.path.join('$PROJECT_DIR', 'backend', 'services', 'system_manager.py')
with open(sm_path, 'r', encoding='utf-8') as f:
    content = f.read()
old_func = '''def _get_current_version() -> str:
    \"\"\"获取当前版本号\"\"\"
    try:
        import main as _main
        if hasattr(_main, \"_INSTALL_APP_VERSION\"):
            return f\"v{_main._INSTALL_APP_VERSION}\"
    except Exception:
        pass
    return \"v1.2.6\"'''
new_func = '''def _get_current_version() -> str:
    \"\"\"获取当前版本号（动态读取 main._INSTALL_APP_VERSION）\"\"\"
    try:
        import main as _main
        if hasattr(_main, \"_INSTALL_APP_VERSION\"):
            return f\"v{_main._INSTALL_APP_VERSION}\"
    except Exception:
        pass
    return \"v1.2.6\"'''
if 'return \"v1.2.5\"' in content:
    content = content.replace('return \"v1.2.5\"', 'return \"v1.2.6\"')
    with open(sm_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('  已修复硬编码版本号 v1.2.5 -> v1.2.6')
else:
    print('  版本检测逻辑正常，无需修复')
"
ok "版本检测修复完成"

# ---------- 7. 修复权限 ----------
log "修复权限..."
chown -R www:www "$PROJECT_DIR" 2>/dev/null || true
chmod 750 "$PROJECT_DIR/.env" 2>/dev/null || true
ok "权限修复完成"

# ---------- 8. 重启服务 ----------
log "重启服务..."
SUPERVISOR_CONF="/etc/supervisor/conf.d/strategy-trade.conf"
if [ -f "$SUPERVISOR_CONF" ] || command -v supervisorctl &>/dev/null; then
    supervisorctl reread 2>/dev/null || true
    supervisorctl update 2>/dev/null || true
    supervisorctl restart strategy-trade-api 2>/dev/null || warn "api 重启失败"
    supervisorctl restart strategy-trade-worker 2>/dev/null || warn "worker 重启失败"
    supervisorctl restart strategy-trade-beat 2>/dev/null || warn "beat 重启失败"
    ok "Supervisor 服务已重启"
else
    warn "未检测到 supervisorctl，请手动重启服务"
    pkill -f "uvicorn main:app" 2>/dev/null || true
    pkill -f "celery" 2>/dev/null || true
    sleep 2
    ok "旧进程已清理"
fi

# ---------- 9. 验证 ----------
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  升级完成！${NC}"
echo -e "${GREEN}========================================${NC}"

sleep 3
if curl -s http://127.0.0.1:8000/health &>/dev/null; then
    ok "后端 API 正常: http://127.0.0.1:8000"
else
    warn "后端 API 未响应，请检查日志: tail -50 $PROJECT_DIR/logs/api.log"
fi

if [ -d "$PROJECT_DIR/frontend/dist" ] || [ -d "$PROJECT_DIR/dist" ]; then
    ok "前端静态文件存在"
fi

echo ""
echo -e "  版本号: v1.2.6"
echo -e "  日志目录: $PROJECT_DIR/logs/"
echo -e "  备份目录: $PROJECT_DIR/backups/"
echo ""
