# 引擎总览定时任务状态修复 - 部署说明
## 修改文件
- `frontend/src/views/SystemMonitor.vue` - 定时任务状态显示修复

## 问题描述
引擎总览页面 → 定时任务状态区块：
- 任务列表缺少状态指示灯，只显示一个静态的「运行中」标签
- `.st-status` CSS 样式未定义，布局错乱

## 修复内容
1. 将每个任务的静态 `<el-tag type="success">运行中</el-tag>` 替换为 `<span class="status-light ok">` — 带绿灯闪烁动画
2. 新增下次执行时间显示（`next_run_time`）
3. 补全 `.st-status` 和 `.st-next-run` CSS 样式

## 部署方式

### 宝塔面板操作
1. 登录宝塔面板 → 文件 → 进入 `/www/wwwroot/strategy-trade`
2. 上传并替换 `frontend/src/views/SystemMonitor.vue`
3. 终端执行前端构建：
   ```bash
   cd /www/wwwroot/strategy-trade
   source venv/bin/activate
   (cd frontend && npm run build && cp -r dist ../)
   ```

### 验证
1. 刷新浏览器 → 系统监控 → 引擎总览
2. 定时任务状态卡片中，每个任务左侧应显示绿色闪烁圆点
3. 右侧应显示「下次: xxx 时间」
