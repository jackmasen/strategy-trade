#!/bin/bash
# ==========================================================
# 策略交易系统 v1.1.0 - 增量升级脚本
# 适用于：拉取新代码后一键更新
# 使用：bash deploy/upgrade.sh
#
# ★ 增量迁移注意事项（升级前必读）：
#   1. .env 新增配置项（对照 .env.example 补全）：
#      - CELERY_ENABLED (默认 false，无需 Celery 即可闭环)
#      - CORS_ALLOW_ORIGINS (生产环境改为具体域名)
#   2. 数据库迁移：Base.metadata.create_all 自动建新表/新列，
#      不删旧列。如需重命名/删除列请手动执行 SQL。
#   3. EMV V7 迁移：如从旧版升级且使用 EMV 策略，运行：
#      python migrate_emv.py
#   4. 升级前会自动创建 pre_update 备份（zip 含 DB + .env）。
# ==========================================================

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

PROJECT_DIR="/www/wwwroot/strategy-trade"
VENV_DIR="$PROJECT_DIR/venv"

cd "$PROJECT_DIR"
source "$VENV_DIR/bin/activate"

# ---- 0) 升级前自动备份 ----
echo -e "${CYAN}[0/6]${NC} 创建升级前备份..."
python -c "
import zipfile, datetime, os, shutil
from pathlib import Path
BASE = Path('$PROJECT_DIR')
bk_dir = BASE / 'backups'
bk_dir.mkdir(parents=True, exist_ok=True)
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
bk_file = bk_dir / f'backup_pre_upgrade_{ts}.zip'
with zipfile.ZipFile(bk_file, 'w', zipfile.ZIP_DEFLATED) as zf:
    db = BASE / 'data' / 'app.db'
    if db.exists():
        zf.write(db, 'data/app.db')
    env = BASE / '.env'
    if env.exists():
        zf.write(env, '.env')
print(f'备份完成: {bk_file.name} ({bk_file.stat().st_size/1024/1024:.1f} MB)')
" && echo -e "${GREEN}备份完成${NC}" || echo -e "${YELLOW}备份跳过（非阻断）${NC}"

echo -e "${CYAN}[1/6]${NC} 更新 Python 依赖..."
pip install -r requirements.txt

echo -e "${CYAN}[2/6]${NC} 数据库迁移（create_all 自动建表/加列）..."
python -c "
from backend.db.session import engine, Base
from backend.models import user, exchange, strategy, trade, analytics
Base.metadata.create_all(bind=engine)
print('数据库表同步完成')
"

# ---- EMV V7 迁移（可选，仅在 migrate_emv.py 存在时执行） ----
if [ -f "migrate_emv.py" ]; then
    echo -e "${CYAN}[3/6]${NC} EMV V7 参数迁移..."
    python migrate_emv.py && echo -e "${GREEN}EMV 迁移完成${NC}" || echo -e "${YELLOW}EMV 迁移跳过（非阻断）${NC}"
else
    echo -e "${CYAN}[3/6]${NC} EMV 迁移脚本不存在，跳过"
fi

echo -e "${CYAN}[4/6]${NC} 前端构建..."
if [ -d frontend/node_modules ]; then
    (cd frontend && npm run build && cp -r dist "$PROJECT_DIR/")
    echo -e "${GREEN}前端构建完成${NC}"
else
    echo -e "${YELLOW}前端依赖未安装，跳过构建${NC}"
fi

echo -e "${CYAN}[5/6]${NC} 修复权限..."
chown -R www:www "$PROJECT_DIR"
chmod 750 "$PROJECT_DIR/.env" 2>/dev/null || true

echo -e "${CYAN}[6/6]${NC} 重启进程..."
if command -v supervisorctl >/dev/null 2>&1; then
    supervisorctl reread
    supervisorctl update
    # Celery 进程仅在 CELERY_ENABLED=True 且 supervisor.conf 中取消注释后才存在
    supervisorctl restart strategy-trade-api 2>/dev/null || true
    supervisorctl restart strategy-trade-worker 2>/dev/null || true
    supervisorctl restart strategy-trade-beat 2>/dev/null || true
    echo -e "${GREEN}进程已重启${NC}"
else
    echo -e "${YELLOW}未安装 supervisorctl，请在宝塔面板手动重启进程${NC}"
fi

echo -e "${GREEN}升级完成！v1.1.0${NC}"
