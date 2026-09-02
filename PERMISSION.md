# 策略交易系统 v1.1.0 — 权限与数据隔离说明

> 生成日期：2026-08-30

---

## 一、角色体系

| 角色值 | 角色名 | 说明 |
|--------|--------|------|
| 1 | 超级管理员（Admin） | 全部权限，包括用户管理、系统设置、系统管理 |
| 2 | 运营（Trader） | 交易相关权限，不可管理用户 |
| 3 | 只读访客（Viewer） | 仅查看，不可操作（配置中较少使用） |

**密码规则：** 至少8位，必须同时包含字母和数字，加符号更安全。

---

## 二、页面/菜单权限对照表

### 客户（trader/运营）可见页面

| 页面 | 路径 | 功能 |
|------|------|------|
| 数据大屏 | /dashboard | 查看账户总览、收益曲线、持仓概况 |
| 交易所子账号 | /exchange | 查看/管理自己的交易所子账号 |
| 策略管理 | /strategy | 创建/管理自己的策略，查看新闻AI策略 |
| 交易订单 | /trade | 查看自己的交易订单 |
| K线行情 | /kline | 查看K线图表 |
| 当前持仓 | /positions | 查看自己的持仓（数据按user_id隔离） |
| 新闻情绪 | /news | 查看新闻列表和情绪评分 |
| AI实时分析 | /ai | 查看AI分析结果 |
| 历史回测 | /backtest | 执行和查看回测 |
| 风控中心 | /risk | 查看风控规则（只读） |
| 财务报表 | /reports | 查看自己的财务报表 |
| 个人中心 | /profile | 修改个人信息 |

### 仅超级管理员可见页面

| 页面 | 路径 | 功能 | 权限控制 |
|------|------|------|----------|
| 用户管理 | /users | 用户CRUD、启用/禁用、重置密码 | 路由adminOnly + API require_admin |
| 系统设置 | /settings | 全局系统配置、交易所API配置 | 路由adminOnly + API require_admin |
| 系统管理 | /system | 健康检测、缓存清理、备份恢复、版本更新 | 路由adminOnly + API require_admin |

### 不可见页面

| 页面 | 说明 |
|------|------|
| 登录页 /login | 公开，但登录成功后跳转 |
| 404页 | 公开 |

---

## 三、API权限层级

| 层级 | 装饰器/检查 | 适用范围 |
|------|------------|----------|
| 公开（无需Token） | 无装饰器 | /health, /install, /auth/login, /auth/register, /docs |
| 需要Token | `get_current_user` | 大部分业务API |
| 需要管理员 | `require_admin` | 用户管理、系统设置、系统管理、新闻采集/分析 |

**管理员专属API（require_admin）：**

```
POST   /api/v1/auth/register          # 注册（仅开发环境）
GET    /api/v1/users                  # 用户列表
POST   /api/v1/users                  # 创建用户
PUT    /api/v1/users/{uid}            # 更新用户
DELETE /api/v1/users/{uid}            # 删除用户
PUT    /api/v1/users/{uid}/toggle-status
PUT    /api/v1/users/{uid}/reset-password

GET    /api/v1/strategy/list          # 管理员可看全部策略
POST   /api/v1/strategy               # 创建策略

GET/POST /api/v1/exchange/accounts
PUT/DELETE /api/v1/exchange/accounts/{eid}

POST   /api/v1/news/crawl             # 手动采集
POST   /api/v1/news/articles/{aid}/analyze

GET/PUT  /api/v1/settings
GET/POST /api/v1/ai/config
GET/POST /api/v1/ai-keys
POST   /api/v1/trade/orders           # 下单（模拟）
POST   /api/v1/trade/close/{pid}

GET/POST /api/v1/risk/rules
GET    /api/v1/risk/events

POST   /api/v1/notifications/mark-read
POST   /api/v1/notifications/read-all

GET/POST /api/v1/system/*            # 系统管理全部需要admin
```

---

## 四、数据隔离机制

### 4.1 用户维度过滤（所有业务数据）

系统以 `user_id` 作为所有业务数据的隔离键，确保不同用户看不到彼此的数据：

| 数据表 | 过滤字段 | 说明 |
|--------|----------|------|
| TradePosition | user_id | 持仓按用户隔离 |
| TradeOrder | user_id | 订单按用户隔离 |
| StrategyConfig | user_id | 策略按用户隔离（列表+详情） |
| ScoreRecord | strategy.user_id | 评分通过策略归属用户隔离 |
| Notification | user_id | 通知按用户隔离 |
| BacktestRun | user_id | 回测按用户隔离 |
| ExchangeAccount | owner_id | 交易所子账号按创建者隔离 |
| DailyFinancialReport | user_id | 日报按用户隔离 |
| WeeklyFinancialReport | user_id | 周报按用户隔离 |
| MonthlyFinancialReport | user_id | 月报按用户隔离 |

**新闻文章（NewsArticle）不隔离**：新闻是公共数据，所有用户都能看到相同的新闻。

### 4.2 前端隔离实现

```javascript
// router/index.js - 路由守卫
router.beforeEach((to, _from, next) => {
  const user = useUserStore()
  // 1. 未登录 → 跳登录页
  if (!user.isLoggedIn) return next({ path: '/login' })
  // 2. adminOnly 页面 → 非管理员跳首页
  if (to.meta?.adminOnly && !user.isAdmin) return next('/')
  next()
})
```

```javascript
// layouts/MainLayout.vue - 菜单过滤
// 后端 /auth/me/menu 已按 role 返回不同菜单
// adminOnly: true 的菜单项只对 role=1 返回
```

### 4.3 后端隔离实现（以策略为例）

```python
# routers/strategy.py - 策略列表
@router.get("/list")
def list_strategies(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
):
    if user.role == 1:
        # 管理员看全部
        query = db.query(StrategyConfig)
    else:
        # 普通用户只看自己的
        query = db.query(StrategyConfig).filter(StrategyConfig.user_id == user.id)
    ...
```

---

## 五、通知中心数据隔离

```python
# routers/notifications.py
@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 只返回当前用户的通知
    query = db.query(Notification).filter(Notification.user_id == user.id)
    ...
```

**通知触发场景：**
- 新闻AI策略触发交易信号 → 通知对应策略用户
- 风控规则触发告警 → 通知管理员
- 系统健康检测异常 → 通知管理员

---

## 六、系统管理模块权限

| 操作 | 需要权限 | 说明 |
|------|----------|------|
| 系统信息查看 | admin | GET /system/info |
| 健康检测 | admin | POST /system/health-check |
| 缓存清理 | admin | POST /system/cache/clean |
| 创建备份 | admin | POST /system/backups |
| 查看备份列表 | admin | GET /system/backups |
| 恢复备份 | admin | POST /system/backups/{bid}/restore |
| 删除备份 | admin | DELETE /system/backups/{bid} |
| 上传更新包 | admin | POST /system/updates/upload |
| 查看更新历史 | admin | GET /system/updates |
| 回滚更新 | admin | POST /system/updates/{uid}/rollback |

---

## 七、新闻AI策略用户隔离

```
策略创建 → 绑定当前用户（user_id）
定时任务 → run_all_news_ai_strategies()
         → 遍历所有 active news_ai 策略
         → 检查 TradePosition 时过滤 user_id == strategy.user_id
         → 生成信号后写入 ScoreRecord（绑定 strategy.user_id）
         → 发送通知（绑定 strategy.user_id）
```

**多用户场景：**
- 用户A创建了BTC新闻AI策略
- 用户B创建了ETH新闻AI策略
- 每小时定时任务同时执行两个策略
- 用户A只能看到自己的BTC策略信号，用户B只能看到自己的ETH策略信号

---

## 八、安全防护

| 防护项 | 实现方式 |
|--------|----------|
| 密码加密 | BCrypt（passlib） |
| Token防伪造 | JWT（HS256 + APP_SECRET_KEY签名） |
| API限流 | CORS白名单（生产环境建议配置具体域名） |
| 安装保护 | .installed标记文件（600权限），删除后可重装 |
| 数据库备份 | 备份前自动备份当前状态（update→rollback链路） |
| 管理员密码 | 首次安装强制8位+字母+数字 |
