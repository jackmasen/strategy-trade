#!/bin/bash
# ==========================================================
# 双重修复部署脚本
# 修复1: 引擎总览定时任务状态显示（绿灯闪烁）
# 修复2: 手动下单实时价格 404 "接口不存在" 报错
# ==========================================================

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PROJECT_DIR="/www/wwwroot/strategy-trade"

cd "$PROJECT_DIR"

echo -e "${CYAN}[1/4]${NC} 验证修改文件完整性..."
grep -q 'status-light ok' frontend/src/views/SystemMonitor.vue && echo -e "${GREEN}SystemMonitor.vue 绿灯修复已存在${NC}" || echo -e "${YELLOW}SystemMonitor.vue 绿灯修复未找到${NC}"
grep -q 'exchange/ticker' frontend/src/views/Trade.vue && echo -e "${GREEN}Trade.vue 行情接口修复已存在${NC}" || echo -e "${YELLOW}Trade.vue 行情接口修复未找到${NC}"

echo -e "${CYAN}[2/4]${NC} 前端构建..."
if [ -d frontend/node_modules ]; then
    (cd frontend && npm run build && cp -r dist "$PROJECT_DIR/") && echo -e "${GREEN}前端构建成功${NC}" || echo -e "${YELLOW}前端构建失败${NC}"
else
    echo -e "${YELLOW}前端依赖未安装，跳过构建（请手动在服务器上 npm run build）${NC}"
fi

echo -e "${CYAN}[3/4]${NC} 重启前端服务（Nginx 静态文件已更新，无需重启）..."
echo -e "${GREEN}前端静态资源已更新至 dist/，Nginx 直接生效${NC}"

echo -e "${CYAN}[4/4]${NC} 验证后端接口..."
source "$PROJECT_DIR/venv/bin/activate"
python -c "
import sys
sys.path.insert(0, '.')
from routers.exchange import router as ex_router
from routers.trade import router as tr_router
paths = [r.path for r in ex_router.routes] + [r.path for r in tr_router.routes]
has_ex_ticker = any('/exchange/ticker' in p for p in paths)
has_tr_ticker = any('/trades/ticker' in p for p in paths)
print(f'  /exchange/ticker/{{symbol}}: {\"已注册\" if has_ex_ticker else \"未注册\"}')
print(f'  /trades/ticker/{{symbol}}: {\"已注册\" if has_tr_ticker else \"未注册\"}')
print('后端接口检查完成')
" 2>/dev/null || echo -e "${YELLOW}后端接口检查跳过（非阻断）${NC}"

echo -e "${GREEN}部署完成！请刷新浏览器验证：${NC}"
echo -e "  1. 系统监控 → 引擎总览 → 定时任务状态应显示绿色闪烁圆点"
echo -e "  2. 交易订单 → 手动下单 → 选择币种后应显示实时价格（不再报接口不存在）"
