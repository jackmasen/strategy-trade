#!/bin/bash
# 创建分享令牌并测试监控API

ADMIN_TOKEN=$(curl -sk https://aicl.tgjsbot.kdns.fr/api/v1/auth/login \
  -X POST -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@2024"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

echo "Admin token: ${ADMIN_TOKEN:0:30}..."

# 创建分享令牌 (720小时=30天)
SHARE_RESULT=$(curl -sk https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share \
  -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"ttl_hours":720}')
echo "Share result: $SHARE_RESULT"

# 提取token
SHARE_TOKEN=$(echo "$SHARE_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['token'])")
echo "Share token: $SHARE_TOKEN"

echo ""
echo "=== 1. 系统状态 ==="
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/status" | python3 -m json.tool 2>/dev/null

echo ""
echo "=== 2. 功能自检 ==="
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/self-check" | python3 -m json.tool 2>/dev/null

echo ""
echo "=== 3. 运行日志 ==="
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/logs?page=1&page_size=10" | python3 -m json.tool 2>/dev/null | head -40

echo ""
echo "=== 4. AI控制中心 - 模拟回测 ==="
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/ai/tasks/backtest" \
  -X POST -H 'Content-Type: application/json' \
  -d '{"symbol":"BTCUSDT","timeframe":"1h","strategy":"emv","start_date":"2026-08-01","end_date":"2026-08-31"}' | python3 -m json.tool 2>/dev/null

echo ""
echo "=== 5. AI控制中心 - 策略扫描 ==="
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/ai/tasks/strategy-scan" \
  -X POST -H 'Content-Type: application/json' \
  -d '{"symbols":["BTCUSDT","ETHUSDT"],"timeframes":["1h","4h"]}' | python3 -m json.tool 2>/dev/null

echo ""
echo "=== 6. AI控制中心 - AI市场分析 ==="
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/ai/tasks/ai-analysis" \
  -X POST -H 'Content-Type: application/json' \
  -d '{"symbol":"BTCUSDT","timeframe":"1h"}' | python3 -m json.tool 2>/dev/null

echo ""
echo "=== 7. AI控制中心 - 全面测试 ==="
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/ai/tasks/full-test" \
  -X POST -H 'Content-Type: application/json' \
  -d '{"symbols":["BTCUSDT"]}' | python3 -m json.tool 2>/dev/null

echo ""
echo "=== 8. AI任务列表 ==="
sleep 3
curl -sk "https://aicl.tgjsbot.kdns.fr/api/v1/monitor/share/$SHARE_TOKEN/ai/tasks" | python3 -m json.tool 2>/dev/null

echo ""
echo "ALL TESTS DONE"
