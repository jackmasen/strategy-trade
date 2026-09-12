# 策略交易系统 v1.1.0 — API接口文档

> 基础路径：`/api/v1`  
> 认证方式：Header `Authorization: Bearer <JWT Token>`  
> 统一响应包装：`{"code": 0, "msg": "ok", "data": {...}}`

---

## 一、认证模块 `/auth`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/auth/login` | 登录，返回accessToken+refreshToken | 公开 |
| POST | `/auth/register` | 注册（仅开发环境） | 公开 |
| POST | `/auth/refresh` | 刷新Token | 需要Token |
| POST | `/auth/logout` | 退出登录 | 需要Token |

**登录请求体：**
```json
{ "username": "admin", "password": "Admin@2024" }
```

**登录响应：**
```json
{
  "code": 0, "msg": "ok",
  "data": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 86400
  }
}
```

---

## 二、用户模块 `/users`（adminOnly）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/users` | 用户列表（分页） |
| GET | `/users/{uid}` | 用户详情 |
| POST | `/users` | 创建用户 |
| PUT | `/users/{uid}` | 更新用户 |
| DELETE | `/users/{uid}` | 删除用户 |
| PUT | `/users/{uid}/toggle-status` | 启用/禁用 |
| PUT | `/users/{uid}/reset-password` | 重置密码 |

---

## 三、交易所模块 `/exchange`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/exchange/accounts` | 子账号列表 | 全部 |
| POST | `/exchange/accounts` | 创建子账号 | admin |
| PUT | `/exchange/accounts/{eid}` | 更新子账号 | admin |
| DELETE | `/exchange/accounts/{eid}` | 删除子账号 | admin |
| GET | `/exchange/tickers/{symbol}` | 实时行情（Binance/OKX） | 全部 |
| GET | `/exchange/klines` | K线数据 | 全部 |

---

## 四、策略模块 `/strategy` + `/strategies`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/strategy/list` | 策略列表（按用户隔离） | 全部 |
| POST | `/strategy` | 创建策略 | 全部 |
| PUT | `/strategy/{sid}` | 更新策略 | 全部 |
| DELETE | `/strategy/{sid}` | 删除策略 | 全部 |
| PUT | `/strategy/{sid}/toggle` | 启用/禁用 | 全部 |
| GET | `/strategy/{sid}/scores` | 评分记录 | 全部 |
| POST | `/strategy/{sid}/run` | 手动执行评分 | 全部 |
| POST | `/strategies/news-sentiment/{symbol}` | **获取新闻情绪** | 全部 |
| POST | `/strategies/{sid}/run-news-ai` | **执行单条新闻AI策略** | 全部 |
| POST | `/strategies/news-ai/run-all` | **批量执行所有新闻AI策略** | 全部 |

**策略类型说明：**
- `standard`：5指标综合评分（MA/MACD/RSI/KDJ/BOLL），权重可配置
- `emv`：EMV趋势跟踪，趋势强度评分
- `news_ai`：新闻AI驱动，情绪评分≥阈值触发信号（v1.1.0新增）

**新闻AI策略创建请求体（示例）：**
```json
{
  "strategy_name": "BTC新闻AI策略",
  "strategy_type": "news_ai",
  "symbols": ["BTC", "ETH"],
  "direction_mode": 0,
  "score_threshold": 5.0,
  "is_active": true,
  "leverage_mode": 1,
  "leverage_fixed": 10
}
```

---

## 五、交易模块 `/trade`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/trade/orders` | 订单列表（用户隔离） | 全部 |
| GET | `/trade/positions` | 持仓列表（用户隔离） | 全部 |
| POST | `/trade/orders` | 下单（模拟） | admin |
| POST | `/trade/close/{pid}` | 平掉指定持仓 | admin |

---

## 六、AI分析模块 `/ai`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/ai/analyze` | AI实时分析单个品种 | 全部 |
| GET | `/ai/analysis-history` | AI分析历史 | 全部 |
| GET | `/ai/config` | AI全局配置 | admin |
| PUT | `/ai/config` | 更新AI配置 | admin |

---

## 七、新闻模块 `/news`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/news/articles` | 新闻列表（分页+筛选） | 全部 |
| GET | `/news/articles/{aid}` | 新闻详情 | 全部 |
| POST | `/news/articles/{aid}/analyze` | 手动触发AI分析 | admin |
| GET | `/news/keywords` | 关键词库管理 | admin |
| POST | `/news/crawl` | 手动触发新闻采集 | admin |

---

## 八、风控模块 `/risk`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/risk/rules` | 风控规则列表 | admin |
| POST | `/risk/rules` | 创建风控规则 | admin |
| PUT | `/risk/rules/{rid}` | 更新规则 | admin |
| DELETE | `/risk/rules/{rid}` | 删除规则 | admin |
| GET | `/risk/events` | 风控事件日志 | admin |

---

## 九、回测模块 `/backtest`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/backtest/run` | 执行回测 | 全部 |
| GET | `/backtest/runs` | 回测历史 | 全部 |
| GET | `/backtest/runs/{bid}` | 回测详情 | 全部 |

---

## 十、财务报表 `/report`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/report/daily` | 日报 | 全部 |
| GET | `/report/weekly` | 周报 | 全部 |
| GET | `/report/monthly` | 月报 | 全部 |
| GET | `/report/dashboard` | 仪表板汇总 | 全部 |

---

## 十一、AI API密钥 `/ai-keys`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/ai-keys` | API密钥列表 | admin |
| POST | `/ai-keys` | 添加API密钥 | admin |
| PUT | `/ai-keys/{aid}` | 更新密钥 | admin |
| DELETE | `/ai-keys/{aid}` | 删除密钥 | admin |

---

## 十二、通知中心 `/notifications`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/notifications` | 我的通知列表（用户隔离） | 全部 |
| PUT | `/notifications/{nid}/read` | 标记已读 | 全部 |
| PUT | `/notifications/read-all` | 全部已读 | 全部 |
| GET | `/notifications/unread-count` | 未读数量 | 全部 |

---

## 十三、系统设置 `/settings`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/settings` | 读取系统配置 | admin |
| PUT | `/settings` | 更新系统配置 | admin |

---

## 十四、系统管理 `/system`（adminOnly，v1.1.0新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/system/info` | 系统基本信息（版本/数据库/用户数/备份数） |
| POST | `/system/health-check` | 健康检测（可带 `auto_fix=true` 自动修复） |
| GET | `/system/cache/items` | 可清理缓存项列表 |
| POST | `/system/cache/clean` | 清理缓存（请求体 `{"keys": ["pycache","logs"]}`） |
| POST | `/system/backups` | 创建备份（请求体 `{"backup_type":"manual","description":"xxx"}`） |
| GET | `/system/backups` | 备份列表（分页） |
| POST | `/system/backups/{bid}/restore` | 恢复备份 |
| DELETE | `/system/backups/{bid}` | 删除备份 |
| POST | `/system/updates/upload` | 上传更新包（multipart/form-data，字段 `file`） |
| GET | `/system/updates` | 更新历史记录（分页） |
| POST | `/system/updates/{uid}/rollback` | 回滚到更新前状态 |

**健康检测响应示例：**
```json
{
  "code": 0,
  "data": {
    "overall_status": "healthy",
    "checks": [
      {"key": "db_connection", "name": "数据库连接", "status": "healthy", "detail": "连接正常"},
      {"key": "disk_space", "name": "磁盘空间", "status": "healthy", "detail": "剩余 120.5 GB (45.2%)"},
      {"key": "dir_backups", "name": "备份目录", "status": "healthy", "detail": "backups/ 存在"},
      {"key": "dir_logs", "name": "日志目录", "status": "healthy", "detail": "logs/ 存在"},
      {"key": "dir_data", "name": "数据目录", "status": "healthy", "detail": "data/ 存在"},
      {"key": "dir_uploads", "name": "上传目录", "status": "healthy", "detail": "uploads/ 存在"},
      {"key": "log_size", "name": "日志文件", "status": "healthy", "detail": "3 个文件，共 12.5 MB"},
      {"key": "db_size", "name": "数据库大小", "status": "healthy", "detail": "SQLite 数据库 28.3 MB"},
      {"key": "backups", "name": "备份文件", "status": "healthy", "detail": "2 个备份，共 56.8 MB"}
    ],
    "fixed": [],
    "report_id": 1
  }
}
```

**缓存清理响应示例：**
```json
{
  "code": 0,
  "data": {
    "freed_mb": 7.23,
    "cleared_count": 3,
    "cleared_items": [
      {"key": "pycache", "path": "__pycache__", "freed_bytes": 3145728},
      {"key": "logs", "path": "logs", "freed_bytes": 5242880}
    ]
  }
}
```

**新闻情绪查询响应示例：**
```json
{
  "code": 0,
  "data": {
    "symbol": "BTC",
    "score": 34.17,
    "direction": "short",
    "positive_count": 1,
    "negative_count": 2,
    "neutral_count": 0,
    "articles_count": 3,
    "analyzed_count": 3,
    "articles": [
      {"id": 1, "title": "Bitcoin Drops Below $60K...", "source": "CoinDesk", "sentiment": 28.5, "direction": "bearish", "publish_time": "2026-08-30T10:00:00"}
    ]
  }
}
```

---

## 十五、菜单权限接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/auth/me/menu` | 获取当前用户菜单（含role过滤） |

**响应示例（admin）：**
```json
{
  "code": 0,
  "data": {
    "menus": [
      {"key": "dashboard", "title": "数据大屏", "icon": "Monitor"},
      {"key": "exchange", "title": "交易所子账号", "icon": "Wallet"},
      {"key": "strategy", "title": "策略管理", "icon": "DataAnalysis"},
      {"key": "trade", "title": "交易订单", "icon": "TrendCharts"},
      {"key": "positions", "title": "当前持仓", "icon": "PieChart"},
      {"key": "news", "title": "新闻情绪", "icon": "Reading"},
      {"key": "ai", "title": "AI实时分析", "icon": "Cpu"},
      {"key": "backtest", "title": "历史回测", "icon": "Histogram"},
      {"key": "risk", "title": "风控中心", "icon": "Warning"},
      {"key": "reports", "title": "财务报表", "icon": "Document"},
      {"key": "settings", "title": "系统设置", "icon": "Setting"},
      {"key": "users", "title": "用户管理", "icon": "User", "adminOnly": true},
      {"key": "system", "title": "系统管理", "icon": "Monitor", "adminOnly": true}
    ],
    "role": 1,
    "username": "admin",
    "nickname": "超级管理员"
  }
}
```

---

## 十六、全局接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 存活探测（无需Token） |
| GET | `/install` | 安装向导（未安装时307自动跳转） |
| GET | `/install/api/precheck` | 环境预检 |
| POST | `/install/api/go` | 执行安装 |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc文档 |
