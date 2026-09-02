# 策略交易系统 v1.1.0 — 系统架构文档

> 生成日期：2026-08-30  
> 版本：v1.1.0（系统管理 + 新闻AI策略新增）

---

## 一、技术栈总览

| 层级 | 技术选型 |
|------|----------|
| **前端框架** | Vue 3 + Element Plus + ECharts + Vue Router (Hash模式) |
| **后端框架** | FastAPI (Python 3.10+) + Uvicorn + SQLAlchemy 2.0 |
| **数据库** | SQLite（开发）/ MySQL 8.0（生产），可选切换 |
| **缓存/队列** | Redis + Celery（可选） |
| **任务调度** | APScheduler（后台定时任务） |
| **新闻爬虫** | 15个数据源（中英文媒体、RSS、API），支持反屏蔽 |
| **AI能力** | 多API轮询（自定义/OpenAI/Anthropic/本地），失败自动切换 |
| **交易所** | Binance Futures + OKX，支持测试网/实盘 |
| **部署** | 宝塔 WordPress式一键安装 + Nginx反代 + Supervisor |

---

## 二、目录结构

```
strategy-trade/
├── main.py                          # FastAPI入口 + WordPress式安装向导
├── requirements.txt                 # Python依赖
├── .env.example                     # 环境变量模板
├── .installed                       # 安装标记（600权限，删除可重装）
│
├── backend/
│   ├── config.py                    # pydantic-settings配置读取
│   ├── core/
│   │   ├── auth.py                  # JWT认证中间件
│   │   ├── security.py              # BCrypt密码哈希
│   │   ├── exceptions.py            # 全局异常处理 + success()包装
│   │   ├── proxy_manager.py         # 代理池管理
│   │   └── logging_config.py        # 日志配置
│   ├── db/
│   │   ├── base.py                  # SQLAlchemy Base
│   │   ├── session.py               # 数据库连接/会话
│   │   └── seed_data.py             # 种子数据（管理员/策略模板/演示数据）
│   ├── models/
│   │   ├── user.py                  # User + OperationLog
│   │   ├── exchange.py              # ExchangeAccount
│   │   ├── strategy.py              # StrategyConfig + ScoreRecord
│   │   ├── trade.py                 # TradeOrder + TradePosition
│   │   ├── analytics.py             # NewsArticle/AIAnalysisRecord/RiskEventLog/BacktestRun/财务报表
│   │   ├── ai_config.py             # AIConfig（全局AI配置）
│   │   ├── ai_api_key.py            # AiApiKey（多API轮询）
│   │   ├── system_config.py         # SystemConfig（全局系统配置）
│   │   └── system_admin.py          # SystemHealthReport/BackupRecord/UpdateRecord
│   ├── news/
│   │   ├── base.py                  # 爬虫基类
│   │   ├── analyzer.py              # 新闻分类器
│   │   ├── pipeline.py              # 新闻采集流水线
│   │   └── crawlers/                # 15个数据源实现
│   ├── strategy/
│   │   ├── engine.py                # 策略引擎
│   │   ├── scoring.py               # 5指标评分系统
│   │   ├── emv_strategy.py          # EMV趋势跟踪
│   │   └── indicators.py            # 技术指标计算
│   ├── services/
│   │   ├── ai_client.py             # AI多API客户端（轮询+故障转移）
│   │   ├── backtest_engine.py       # 回测引擎
│   │   ├── news_ai_analyzer.py      # 新闻AI深度分析
│   │   ├── news_keywords.py         # 关键词库（中英双语）
│   │   ├── news_strategy.py         # 新闻AI策略执行（v1.1.0新增）
│   │   └── system_manager.py        # 系统管理（v1.1.0新增）
│   ├── routers/                     # 12个路由模块
│   │   ├── auth.py                  # 登录/注册/Token刷新
│   │   ├── exchange.py              # 交易所子账号管理
│   │   ├── strategy.py              # 策略管理 + 新闻AI策略API
│   │   ├── trade.py                 # 交易订单/持仓
│   │   ├── analytics.py             # AI/新闻/风控/回测/报表（5个子路由）
│   │   ├── settings.py              # 系统设置
│   │   ├── ai_keys.py               # AI API密钥管理
│   │   ├── notifications.py         # 通知中心（用户维度隔离）
│   │   └── system_admin.py          # 系统管理（管理员）
│   └── tasks/
│       └── scheduled.py             # APScheduler定时任务定义
│
├── frontend/
│   ├── src/
│   │   ├── main.js                  # Vue应用入口
│   │   ├── App.vue                  # 根组件
│   │   ├── router/index.js          # 路由配置（15个页面，adminOnly控制）
│   │   ├── store/user.js            # 用户状态（role/isAdmin）
│   │   ├── layouts/MainLayout.vue   # 侧边栏+顶部导航
│   │   ├── views/                   # 15个页面组件
│   │   └── utils/
│   │       ├── request.js           # Axios封装（JWT拦截器）
│   │       └── env.js               # 环境变量
│   ├── dist/                        # npm run build 产物（Vercel/CDN部署）
│   └── vite.config.js
│
├── deploy/                          # 部署脚本（nginx/supervisor/onepress）
├── backups/                         # 系统备份目录
└── logs/                            # 日志目录
```

---

## 三、后端架构

### 3.1 路由注册（main.py）

```
/api/v1/auth/*          认证模块（登录、注册、Token）
/api/v1/users/*         用户管理（超级管理员）
/api/v1/exchange/*      交易所子账号
/api/v1/strategy/*      策略管理（含新闻AI）
/api/v1/trade/*         交易订单与持仓
/api/v1/ai/*            AI实时分析
/api/v1/news/*          新闻管理
/api/v1/risk/*          风控规则与事件
/api/v1/backtest/*      历史回测
/api/v1/report/*        财务报表
/api/v1/settings/*      系统设置
/api/v1/ai-keys/*       AI API密钥管理
/api/v1/notifications/* 通知中心（用户隔离）
/api/v1/system/*        系统管理（管理员）
```

### 3.2 模型层（10个模块，19张表）

| 模块 | 模型类 | 说明 |
|------|--------|------|
| user | User | 系统用户，role: 1=管理员,2=运营,3=访客 |
| user | OperationLog | 操作审计日志 |
| exchange | ExchangeAccount | 交易所子账号配置 |
| strategy | StrategyConfig | 策略配置（standard/emv/news_ai） |
| strategy | ScoreRecord | 评分记录 |
| trade | TradeOrder | 交易订单 |
| trade | TradePosition | 持仓记录 |
| analytics | NewsArticle | 新闻文章（含sentiment_score） |
| analytics | AIAnalysisRecord | AI分析记录 |
| analytics | RiskEventLog | 风控事件日志 |
| analytics | BacktestRun | 回测记录 |
| analytics | Daily/Weekly/MonthlyFinancialReport | 财务报表 |
| ai_config | AIConfig | AI全局配置 |
| ai_api_key | AiApiKey | AI多API密钥（轮询用） |
| system_config | SystemConfig | 系统全局配置（键值对） |
| system_admin | SystemHealthReport | 健康检测报告 |
| system_admin | SystemBackupRecord | 备份记录 |
| system_admin | SystemUpdateRecord | 版本更新记录 |

### 3.3 数据模型关键关系

```
User (role=1) ←→ OperationLog
User 1:N ExchangeAccount
User 1:N StrategyConfig
StrategyConfig 1:N ScoreRecord
ExchangeAccount 1:N TradeOrder
ExchangeAccount 1:N TradePosition
NewsArticle N:1 AIAnalysisRecord
StrategyConfig is_active → TradePosition（持仓过滤）
```

---

## 四、前端架构

### 4.1 页面列表（15个）

| 页面 | 路径 | 菜单Key | 权限 | 说明 |
|------|------|---------|------|------|
| 登录 | /login | — | public | 公开页面 |
| 数据大屏 | /dashboard | dashboard | 全部 | 核心指标总览 |
| 交易所子账号 | /exchange | exchange | 全部 | 多交易所配置 |
| 策略管理 | /strategy | strategy | 全部 | 策略CRUD+评分+新闻AI |
| 交易订单 | /trade | trade | 全部 | 订单列表+详情 |
| K线行情 | /kline | kline | 全部 | K线图表 |
| 当前持仓 | /positions | positions | 全部 | 实时持仓（用户隔离） |
| 新闻情绪 | /news | news | 全部 | 新闻列表+情绪分 |
| AI实时分析 | /ai | ai | 全部 | AI分析面板 |
| 历史回测 | /backtest | backtest | 全部 | 回测配置+结果 |
| 风控中心 | /risk | risk | 全部 | 风控规则+事件 |
| 财务报表 | /reports | reports | 全部 | 日/周/月报表 |
| **用户管理** | /users | **users** | **adminOnly** | 用户CRUD+角色 |
| **系统设置** | /settings | **settings** | **adminOnly** | 系统全局配置 |
| **系统管理** | /system | **system** | **adminOnly** | 健康检测+备份+更新 |
| 个人中心 | /profile | — | 全部 | 无菜单 |

### 4.2 权限控制

- **路由守卫**（`router/index.js`）：登录检查 + adminOnly 路由权限拦截
- **菜单显示**（`MainLayout.vue`）：后端 `/api/v1/auth/me/menu` 返回菜单，前端按 `adminOnly` 字段过滤
- **API权限**（`auth.py`）：`require_admin` 装饰器，role != 1 返回403

---

## 五、核心业务流程

### 5.1 新闻AI策略流程（v1.1.0新增）

```
[定时任务 每小时]
    ↓
run_all_news_ai_strategies(db)
    ↓
for each active news_ai strategy:
    ↓
    calc_news_sentiment_score(symbol, hours=24)
        ↓
        查询24小时内相关新闻（标题关键词匹配）
        ↓
        读取 NewsArticle.sentiment_score (-1.0~1.0)
        ↓
        转换为 0~100 分，计算均值
    ↓
    检查是否已有同方向持仓
    ↓
    abs(score-50)/5 >= threshold ?
        ↓ 是
        生成交易信号 (direction/sentiment_score/leverage)
        ↓
        写入 ScoreRecord（news分项）
        ↓
        发送通知（通知中心，用户维度过滤）
```

### 5.2 系统管理流程（v1.1.0新增）

```
[健康检测]
    GET /system/health-check 或 POST /system/health-check?auto_fix=true
    ↓
    检测：数据库连接 / 磁盘空间 / 必要目录 / 日志大小 / DB大小 / 备份数
    ↓
    保存 SystemHealthReport，返回 overall_status(healthy/warning/critical)

[缓存清理]
    GET /system/cache/items  →  列出5类可清理项
    POST /system/cache/clean  →  勾选清理，释放空间

[备份管理]
    POST /system/backups  →  创建zip备份（含DB+配置+uploads）
    GET /system/backups   →  备份列表
    POST /system/backups/{bid}/restore  →  恢复（先自动备份当前状态）
    DELETE /system/backups/{bid}

[版本更新]
    POST /system/updates/upload  →  上传更新包zip
    ↓
    自动备份 → 解压 → 校验结构 → 合并backend → 替换frontend/dist
    ↓
    删除上传包，返回更新记录
    GET /system/updates  →  更新历史
    POST /system/updates/{uid}/rollback  →  回滚（从备份恢复）
```

---

## 六、定时任务

| 任务 | 频率 | 功能 | 代码位置 |
|------|------|------|----------|
| 新闻采集 | 每30分钟 | 15源爬虫+关键词预筛选+入库 | main.py `_scheduled_news_crawl` |
| AI深度分析 | 每2小时 | 高影响新闻→AI情绪评分 | main.py `_scheduled_ai_analysis` |
| 新闻AI策略 | 每1小时 | 执行所有news_ai策略→生成信号 | main.py `_scheduled_news_strategy` |
| 数据清理 | 每天3:00 | 清理30/90/180天过期数据 | main.py `_scheduled_cleanup` |

---

## 七、关键配置（.env）

```ini
# 基础
APP_NAME=TradingStrategySystem
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=<64位随机字符串>
API_PREFIX=/api/v1
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# 数据库（MySQL 或 SQLite 二选一）
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=trading_user
DB_PASSWORD=
DB_NAME=trading_system
DB_CHARSET=utf8mb4
DB_SQLITE_FALLBACK=sqlite:///./data/app.db

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

# 交易所
BINANCE_MAIN_API_KEY=
BINANCE_MAIN_API_SECRET=
BINANCE_TESTNET=true          # true=测试网(推荐)，false=实盘
BINANCE_BASE_URL=https://testnet.binancefuture.com

OKX_MAIN_API_KEY=
OKX_MAIN_API_SECRET=
OKX_MAIN_PASSPHRASE=
OKX_TESTNET=false
OKX_BASE_URL=https://www.okx.com

# AI配置
AI_PROVIDER=custom
AI_API_KEY=
AI_API_ENDPOINT=
AI_MODEL_NAME=gpt-4o

# 代理（新闻爬取用）
PROXY_ENABLED=false
PROXY_HTTP_LIST=http://127.0.0.1:7890

# 告警
DINGTALK_WEBHOOK=
FEISHU_WEBHOOK=
```

---

## 八、版本更新日志

### v1.1.0（2026-08-30）新增功能
- **系统管理模块**：健康检测+自动修复、缓存清理、备份恢复、版本更新
- **新闻AI策略**：news_ai类型策略，情绪评分驱动交易信号，每小时自动执行
- **前端新增**：SystemAdmin.vue（系统管理页面）
- **路由新增**：/system（adminOnly）

### v1.0.0（2026-08-03）初始版本
- 认证授权（JWT+BCrypt）
- 交易所子账号管理
- 策略管理（standard/emv两种）
- 新闻爬虫（15源）+ AI分析
- 交易订单 + 持仓管理
- K线行情 + 回测引擎
- 风控中心 + 财务报表
- WordPress式一键安装向导
- 用户管理（adminOnly）
- 系统设置
