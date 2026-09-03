# 双重修复 - 部署说明
## 修复内容

### 修复1: 引擎总览定时任务状态显示（绿灯闪烁）
- **文件**: `frontend/src/views/SystemMonitor.vue`
- **问题**: 定时任务状态只显示静态「运行中」标签，无状态指示灯，`.st-status` CSS 未定义
- **修复**:
  1. 将 `<el-tag type="success">运行中</el-tag>` 替换为 `<span class="status-light ok" title="运行中"></span>` — 带绿灯闪烁动画
  2. 新增下次执行时间显示（`next_run_time`）
  3. 补全 `.st-status` 和 `.st-next-run` CSS 样式

### 修复2: 手动下单实时价格 404 "接口不存在" 报错
- **文件**: `frontend/src/views/Trade.vue`
- **问题**: 手动下单弹窗调用 `/trades/ticker/${symbol}`，该接口在无交易所子账号时返回 404（`NotFoundException`），前端映射为「接口不存在」
- **修复**:
  1. 将接口改为 `/exchange/ticker/${symbol}` — 有缓存 + mock 兜底，不会 404
  2. 新增 `change_pct_24h` → `change_pct` 字段兼容映射（后端 Ticker.to_dict() 返回 `change_pct_24h`，前端模板使用 `change_pct`）

## 部署方式

### 方式一：一键部署脚本（推荐）
```bash
# 上传 deploy/dual_fix 相关文件到服务器后执行
bash deploy/deploy_dual_fix.sh
```

### 方式二：宝塔面板手动操作
1. 登录宝塔面板 → 文件 → 进入 `/www/wwwroot/strategy-trade`
2. 上传并替换以下文件：
   - `frontend/src/views/SystemMonitor.vue`
   - `frontend/src/views/Trade.vue`
3. 终端执行前端构建：
   ```bash
   cd /www/wwwroot/strategy-trade
   (cd frontend && npm run build && cp -r dist ../)
   ```
4. 刷新浏览器（Ctrl+F5 强制刷新）即可生效

### 方式三：全量升级
如需同时部署 AI 分析修复，可使用 upgrade.sh 全量升级：
```bash
bash deploy/upgrade.sh
```

## 验证
1. **定时任务状态**: 系统监控 → 引擎总览 → 每个任务左侧应显示绿色闪烁圆点，右侧显示下次执行时间
2. **手动下单行情**: 交易订单 → 手动下单 → 选择币种后价格面板应正常显示实时价格（不再报「接口不存在」）