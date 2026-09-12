# AI分析 + 新闻AI配置修复 - 部署说明
## 修改文件清单
1. `backend/routers/analytics.py` - AI分析端点注入实时数据 + 修复新闻AI配置测试422错误
2. `frontend/src/views/AI.vue` - 前端显示实时价格核对面板

## 本次修复内容

### 修复1: 新闻AI配置测试422错误
**问题**: 在「新闻AI多接口配置」中点击「测试」按钮时返回 `Request failed with status code 422`

**根因**: `_load_news_ai_configs()` 函数在 `strip_encrypted=False` 模式下只设置了 `api_key_masked`（脱敏显示），但没有设置 `api_key`（明文），导致测试端点找不到有效的 API Key

**修复**:
- `strip_encrypted=False` 时，新增 `item["api_key"] = decrypted`（内部测试时使用明文key）
- `strip_encrypted=True` 时（前端展示），移除 `api_key` 字段防止明文泄露

### 修复2: AI分析实时价格核对
**问题**: AI分析结果与当天实时价格差距很大

**修复**: 分析前先拉取实时行情、K线数据、新闻数据，再传入AI

## 部署方式（二选一）

### 方式一：宝塔面板上传（推荐）
1. 登录宝塔面板 → 文件 → 进入 `/www/wwwroot/strategy-trade`
2. 上传并替换以下文件：
   - `backend/routers/analytics.py`（从本地复制完整文件覆盖）
   - `frontend/src/views/AI.vue`（从本地复制完整文件覆盖）
3. 终端执行：`bash deploy/deploy_ai_fix.sh`
   或手动执行：
   ```bash
   cd /www/wwwroot/strategy-trade
   source venv/bin/activate
   python -c "import ast; ast.parse(open('backend/routers/analytics.py').read()); print('OK')"
   (cd frontend && npm run build && cp -r dist ../)
   supervisorctl restart strategy-trade-api
   ```

### 方式二：直接替换文件
1. 从本地复制以下文件到服务器对应位置：
   - 本地: `strategy-trade-v1.2.0_20260831/backend/routers/analytics.py`
     → 服务器: `/www/wwwroot/strategy-trade/backend/routers/analytics.py`
   - 本地: `strategy-trade-v1.2.0_20260831/frontend/src/views/AI.vue`
     → 服务器: `/www/wwwroot/strategy-trade/frontend/src/views/AI.vue`
2. 重新构建前端并重启服务（同上）

## 验证方法
1. **新闻AI配置测试**: 进入AI页面 → 新闻AI多接口配置 → 点击任意配置的「测试」按钮 → 应显示「连接成功」
2. **AI分析页面**: 选择币种 → 点击分析 → 结果区域应显示「实时价格核对」面板，包含最新价/Bid/Ask
3. **新闻不足提示**: 若新闻不足，会显示黄色警告提示先采集新闻数据

## 修复说明
- 之前问题：AI分析调用时 `candles_snapshot` 和 `news_snapshot` 均为空字符串；新闻AI配置测试返回422
- 修复后：分析前先拉取实时行情/K线/新闻数据；测试时正确读取数据库中已加密的API Key
