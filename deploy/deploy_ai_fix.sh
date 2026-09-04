#!/bin/bash
# ==========================================================
# AI分析 + 新闻AI配置422修复 - 部署脚本
# 修改内容:
# 1. backend/routers/analytics.py - 注入实时价格/K线/新闻数据
#    - 修复 _load_news_ai_configs: strip_encrypted=False 时返回明文 api_key
#    - 修复测试端点: config_id + __USE_EXISTING__ 时从数据库读取 key
# 2. frontend/src/views/AI.vue - 显示实时价格核对面板
# ==========================================================

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PROJECT_DIR="/www/wwwroot/strategy-trade"

cd "$PROJECT_DIR"

echo -e "${CYAN}[1/4]${NC} 验证修改文件完整性..."
grep -q "candles_snapshot=candles_snapshot" backend/routers/analytics.py && echo -e "${GREEN}analytics.py 实时价格修复已存在${NC}" || echo -e "${YELLOW}analytics.py 实时价格修复未找到${NC}"
grep -q 'if not strip_encrypted:' backend/routers/analytics.py && echo -e "${GREEN}analytics.py 422修复已存在${NC}" || echo -e "${YELLOW}analytics.py 422修复未找到${NC}"
grep -q "price-check-panel" frontend/src/views/AI.vue && echo -e "${GREEN}AI.vue 已更新${NC}" || echo -e "${YELLOW}AI.vue 未找到修改${NC}"

echo -e "${CYAN}[2/4]${NC} 后端检查语法..."
python -c "import ast; ast.parse(open('backend/routers/analytics.py').read()); print('语法检查通过')"

echo -e "${CYAN}[3/4]${NC} 前端构建..."
if [ -d frontend/node_modules ]; then
    (cd frontend && npm run build && cp -r dist "$PROJECT_DIR/") && echo -e "${GREEN}前端构建成功${NC}" || echo -e "${YELLOW}前端构建失败${NC}"
else
    echo -e "${YELLOW}前端依赖未安装，跳过构建（请手动在服务器上 npm run build）${NC}"
fi

echo -e "${CYAN}[4/4]${NC} 重启后端服务..."
if command -v supervisorctl >/dev/null 2>&1; then
    supervisorctl restart strategy-trade-api 2>/dev/null && echo -e "${GREEN}API服务已重启${NC}" || echo -e "${YELLOW}supervisor重启失败，请手动重启${NC}"
else
    echo -e "${YELLOW}未检测到supervisor，请在宝塔面板手动重启进程${NC}"
fi

echo -e "${GREEN}部署完成！请刷新浏览器验证：${NC}"
echo -e "  1. AI分析页面 - 应显示实时价格核对面板"
echo -e "  2. 新闻AI多接口配置 - 点击测试按钮应返回连接成功（不再422）"
