#!/bin/bash
# ==========================================================
# 策略交易系统 - 宝塔环境一键部署脚本
# 执行方式：
#   1. 在宝塔面板中上传项目到 /www/wwwroot/strategy-trade
#   2. 终端执行：
#      cd /www/wwwroot/strategy-trade
#      chmod +x deploy/install.sh
#      bash deploy/install.sh
# ==========================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="/www/wwwroot/strategy-trade"
PYTHON_VERSION="3.10.12"
VENV_DIR="${PROJECT_DIR}/venv"

log()    { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()     { echo -e "${GREEN}[OK]${NC} $1"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

cd "$PROJECT_DIR"

# ---------------- 1. 基础检查 ----------------
log "检查运行环境..."
[ "$(id -u)" -eq 0 ] || warn "建议使用 root 运行，否则可能权限不足"
[ -d "$PROJECT_DIR" ] || error "项目目录不存在: $PROJECT_DIR"

command -v python3 >/dev/null 2>&1 || error "未检测到 Python3，请先在宝塔安装 Python 3.10+"
PY=$(command -v python3)
log "使用 Python: $($PY --version)"

mkdir -p logs uploads

# ---------------- 2. 虚拟环境 ----------------
log "创建虚拟环境..."
if [ ! -d "$VENV_DIR" ]; then
    $PY -m venv "$VENV_DIR"
    ok "虚拟环境创建完成: $VENV_DIR"
else
    warn "虚拟环境已存在，跳过创建"
fi
source "$VENV_DIR/bin/activate"

# ---------------- 3. 系统依赖 ----------------
log "安装系统依赖 (MySQL Redis)..."
# (宝塔一般已自带，这里仅尝试安装编译依赖)
yum install -y gcc gcc-c++ make mysql-devel python3-devel redis >/dev/null 2>&1 || \
apt-get install -y gcc g++ make libmysqlclient-dev python3-dev redis-server >/dev/null 2>&1 || \
warn "跳过系统依赖安装，如安装TA-Lib失败请手动执行 yum install -y gcc"

# ---------------- 4. Python 依赖 ----------------
log "安装 Python 依赖包..."
pip install --upgrade pip setuptools wheel
pip install -r "$PROJECT_DIR/requirements.txt"

# 安装 TA-Lib (较慢，失败不中断)
if ! python -c "import talib" 2>/dev/null; then
    warn "TA-Lib 未安装，正在尝试编译安装（约3分钟）..."
    (
        cd /tmp
        wget -q https://sourceforge.net/projects/ta-lib/files/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz || true
        tar -xzf ta-lib-0.4.0-src.tar.gz 2>/dev/null && \
        cd ta-lib 2>/dev/null && ./configure --prefix=/usr && make -j4 && make install && \
        ldconfig && pip install TA-Lib
    ) || warn "TA-Lib 编译失败，技术分析功能将降级，请参考 deploy/TA-LIB.md 手动安装"
fi
ok "Python 依赖安装完成"

# ---------------- 5. 环境变量 ----------------
log "配置环境变量..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    warn "已生成 .env 文件，请编辑配置 DB/Redis/交易所API/AI API"
else
    warn ".env 已存在，跳过生成"
fi

# ---------------- 6. 数据库初始化 ----------------
log "初始化数据库..."
python -c "
from backend.db.session import engine, Base
from backend.models import user, exchange, strategy, trade, analytics
Base.metadata.create_all(bind=engine)
print('数据库表创建完成')
" || warn "数据库初始化失败，请检查 .env 中的数据库配置后重试"

# ---------------- 7. 创建默认管理员 ----------------
log "创建默认管理员账户 admin/Admin@2024 (请尽快修改)..."
python -c "
from backend.db.session import SessionLocal
from backend.models.user import User
from backend.core.utils import hash_password
db = SessionLocal()
if not db.query(User).filter(User.username == 'admin').first():
    u = User(username='admin', password_hash=hash_password('Admin@2024'), role=1, status=1)
    db.add(u); db.commit()
    print('默认管理员创建成功')
else:
    print('管理员已存在，跳过')
db.close()
" || warn "默认管理员创建失败"

# ---------------- 8. 前端构建 ----------------
log "检查前端构建..."
if command -v node >/dev/null 2>&1 && [ -d "$PROJECT_DIR/frontend/node_modules" ]; then
    if [ ! -d "$PROJECT_DIR/dist" ]; then
        warn "前端未构建，开始构建..."
        (cd "$PROJECT_DIR/frontend" && npm run build && cp -r dist "$PROJECT_DIR/")
        ok "前端构建完成"
    else
        warn "前端 dist 已存在，跳过构建"
    fi
else
    warn "未检测到 Node 或依赖未安装，请执行：
       cd ${PROJECT_DIR}/frontend
       npm install
       npm run build
       cp -r dist ${PROJECT_DIR}/"
fi

# ---------------- 9. 权限修复 ----------------
log "修复目录权限..."
chown -R www:www "$PROJECT_DIR"
chmod -R 755 "$PROJECT_DIR"
find "$PROJECT_DIR" -type f -name "*.py" -exec chmod 644 {} \;
chmod 750 "$PROJECT_DIR/.env"

# ---------------- 10. Supervisor 配置提示 ----------------
ok "基础部署完成！"
echo ""
echo -e "${GREEN}==================== 后续步骤 ====================${NC}"
echo -e "1. 编辑 ${YELLOW}.env${NC} 文件，填入数据库/Redis/币安API/OKX API/AI API Key"
echo -e "2. 打开宝塔 → 软件商店 → 安装 ${YELLOW}Supervisor 管理器${NC}"
echo -e "3. 在 Supervisor 中添加三个进程，配置参考：${YELLOW}deploy/supervisor.conf${NC}"
echo -e "   - strategy-trade-api    :8000"
echo -e "   - strategy-trade-worker 异步任务"
echo -e "   - strategy-trade-beat   定时任务"
echo -e "4. 宝塔 → 网站 → 添加站点 → 配置文件替换为：${YELLOW}deploy/nginx.conf${NC}"
echo -e "   并修改 your_domain.com 为实际域名"
echo -e "5. 启动服务后访问 http://域名 登录 ${YELLOW}admin / Admin@2024${NC}"
echo ""
echo -e "启动(手动测试):"
echo -e "  source ${VENV_DIR}/bin/activate"
echo -e "  uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
