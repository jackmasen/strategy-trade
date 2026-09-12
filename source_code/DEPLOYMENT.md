# 策略交易系统 · 部署搭建使用教程（v1.1.0）

> 版本：v1.1.0  
> 新增功能：系统管理（健康检查/缓存清理/备份恢复/版本升级）+ 新闻AI策略（新闻情绪驱动信号）  
> 技术栈：FastAPI + Vue 3 + Element Plus + ECharts + APScheduler  
> 数据库：SQLite（本地演示） / MySQL 8.0（生产）

---

## 一、系统概述

### 1.1 功能模块

| 模块 | 功能 | 完成状态 |
|------|------|---------|
| 用户认证 | 登录/注册/JWT/token刷新 | ✅ |
| 交易所 | 币安/OKX API 对接（REST） | ✅ |
| 策略管理 | EMV策略 + 新闻AI策略（news_ai） | ✅ |
| 交易订单 | 下单/撤单/止盈止损 | ✅ |
| K线行情 | 实时行情 + K线图 | ✅ |
| 当前持仓 | 实时持仓监控 | ✅ |
| 新闻情绪 | 15+新闻源采集 + 情绪分析 | ✅ |
| AI实时分析 | 技术指标+新闻+AI综合评分 | ✅ |
| 历史回测 | 策略回测引擎 | ✅ |
| 风控中心 | 仓位/亏损/杠杆风控 | ✅ |
| 财务报表 | 收益曲线/资金曲线 | ✅ |
| 用户管理 | 角色分配/数据隔离（仅管理员） | ✅ |
| 系统设置 | AI密钥管理/风控参数/通知配置 | ✅ |
| 系统管理 | 健康检查/缓存清理/备份恢复/版本升级（v1.1.0新增） | ✅ |
| 数据大屏 | 实时数据可视化仪表盘 | ✅ |

### 1.2 前端页面（15个路由）

| 页面 | 路由 | 权限 | 说明 |
|------|------|------|------|
| 登录 | `/login` | 公开 | 账号密码登录 |
| 数据大屏 | `/dashboard` | 所有角色 | 实时行情+持仓+信号总览 |
| 交易所子账号 | `/exchange` | 所有角色 | 交易所账户配置与连接状态 |
| 策略管理 | `/strategy` | 所有角色 | EMV策略配置 + 新闻AI策略 |
| 交易订单 | `/trade` | 所有角色 | 历史订单/成交记录 |
| K线行情 | `/kline` | 所有角色 | 多周期K线图 |
| 当前持仓 | `/positions` | 所有角色 | 实时持仓与盈亏 |
| 新闻情绪 | `/news` | 所有角色 | 新闻源 + 情绪分数 |
| AI实时分析 | `/ai` | 所有角色 | 综合评分引擎 |
| 历史回测 | `/backtest` | 所有角色 | 策略回测结果 |
| 风控中心 | `/risk` | 所有角色 | 风控参数与预警 |
| 财务报表 | `/reports` | 所有角色 | 收益/资金/风控报表 |
| 用户管理 | `/users` | 管理员 | 用户CRUD + 角色分配 |
| 系统设置 | `/settings` | 管理员 | AI密钥/通知/风控参数 |
| 系统管理 | `/system` | 管理员 | 健康检查/缓存/备份/升级 |
| 个人中心 | `/profile` | 所有角色 | 修改密码/个人信息 |

---

## 二、本地开发环境搭建（Windows / macOS / Linux）

### 2.1 前置要求

| 环境 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.10+ | 必须 |
| Node.js | 18+ | 前端构建 |
| Git | - | 版本管理（可选） |

### 2.2 克隆/获取源码

```bash
# 方式1：从压缩包解压
# 方式2：Git拉取（如有仓库）
git clone <repository-url> strategy-trade
cd strategy-trade
```

### 2.3 安装 Python 依赖

```bash
# 创建虚拟环境（推荐）
python -m venv .venv

# 激活虚拟环境
# Windows：
.venv\Scripts\activate
# macOS/Linux：
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2.4 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件
# 必须修改的配置：
#   APP_SECRET_KEY    → 随机生成32位字符串
#   BINANCE_MAIN_API_KEY / BINANCE_MAIN_API_SECRET → 交易所API密钥
#   AI_API_KEY / AI_API_ENDPOINT → AI服务配置
```

### 2.5 构建前端

```bash
cd frontend
npm install
npm run build
# 构建产物输出到 frontend/dist/
cd ..
```

### 2.6 启动后端

```bash
# 开发模式（自动热重载）
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2.7 启动前端开发服务器（开发阶段）

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

浏览器访问：http://localhost:5173  
后端 API：http://localhost:8000  
API文档：http://localhost:8000/docs

### 2.8 默认账号

```
用户名：admin
密码：Admin@2024
```

> ⚠️ 上线前必须修改默认密码！

---

## 三、WordPress 风格一键安装向导

系统内置 `/install` 安装向导（WordPress风格），首次启动访问 `http://your-domain/install` 即可。

### 3.1 安装向导流程

```
Step 1: 环境检查
  - Python 版本 ✓
  - 必要依赖 ✓
  - 数据库连接 ✓
  - 目录权限 ✓

Step 2: 环境变量生成
  - 自动生成 APP_SECRET_KEY
  - 填写数据库连接信息
  - 填写交易所 API 密钥
  - 填写 AI 服务配置

Step 3: 数据库初始化
  - 自动建表（19张表）
  - 初始化种子数据（管理员/策略模板/演示新闻）
  - 生成 .installed 标记文件

Step 4: 完成
  - 显示访问地址
  - 提示修改默认密码
```

### 3.2 手动触发安装

```bash
# 方式1：浏览器访问
http://localhost:8000/install

# 方式2：命令行
python -c "import sys; sys.path.insert(0,'.'); from main import *; print('ready')"
```

### 3.3 安装后验证

```bash
# 健康检查
curl http://localhost:8000/health

# API文档
http://localhost:8000/docs

# 前端页面
http://localhost:8000
```

---

## 四、生产环境部署（宝塔面板 / Linux）

### 4.1 环境准备

宝塔面板需安装以下软件：
- Nginx 1.20+
- MySQL 8.0（或 SQLite 单机模式）
- Redis 6.0+
- Supervisor
- Python 3.10+
- Node.js 18+

### 4.2 上传源码

```bash
# 解压到网站目录
unzip strategy-trade-v1.1.0.zip -d /www/wwwroot/strategy-trade
cd /www/wwwroot/strategy-trade
chmod +x deploy/*.sh
```

### 4.3 创建数据库

```sql
-- 宝塔面板 → 数据库 → 新建
CREATE DATABASE trading_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'trading_user'@'127.0.0.1' IDENTIFIED BY 'your_strong_password';
GRANT ALL PRIVILEGES ON trading_system.* TO 'trading_user'@'127.0.0.1';
FLUSH PRIVILEGES;
```

### 4.4 配置环境变量

```bash
cd /www/wwwroot/strategy-trade
cp .env.example .env
vi .env
```

**必填配置项：**

| 变量 | 说明 | 示例 |
|------|------|------|
| `APP_SECRET_KEY` | JWT密钥（32位+） | 随机字符串 |
| `DB_HOST` | 数据库地址 | `127.0.0.1` |
| `DB_USER` | 数据库用户名 | `trading_user` |
| `DB_PASSWORD` | 数据库密码 | 强密码 |
| `DB_NAME` | 数据库名 | `trading_system` |
| `BINANCE_MAIN_API_KEY` | 币安API密钥 | 从币安获取 |
| `BINANCE_MAIN_API_SECRET` | 币安API密钥 | 从币安获取 |
| `AI_API_KEY` | AI服务密钥 | OpenAI/自定义 |
| `AI_API_ENDPOINT` | AI服务地址 | https://api.openai.com |

### 4.5 安装依赖并构建前端

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装Python依赖
pip install -r requirements.txt

# 构建前端
cd frontend
npm install
npm run build
cd ..

# 初始化数据库（创建表+种子数据）
# 启动一次后自动完成，或手动：
python -c "from backend.db.seed_data import ensure_seed_data; from backend.db.session import SessionLocal; db=SessionLocal(); ensure_seed_data(db); db.close()"
```

### 4.6 配置 Supervisor

```ini
# deploy/supervisor.conf
[program:trading-backend]
command=/www/wwwroot/strategy-trade/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
directory=/www/wwwroot/strategy-trade
autostart=true
autorestart=true
stderr_logfile=/www/wwwroot/strategy-trade/logs/backend.err.log
stdout_logfile=/www/wwwroot/strategy-trade/logs/backend.out.log
environment=APP_ENV="production"

[program:trading-scheduler]
command=/www/wwwroot/strategy-trade/.venv/bin/python -c "from main import scheduler; scheduler.start()"
directory=/www/wwwroot/strategy-trade
autostart=true
autorestart=true
stderr_logfile=/www/wwwroot/strategy-trade/logs/scheduler.err.log
stdout_logfile=/www/wwwroot/strategy-trade/logs/scheduler.out.log
```

```bash
# 添加守护进程
sudo cp deploy/supervisor.conf /etc/supervisor/conf.d/trading.conf
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start all
```

### 4.7 配置 Nginx 反向代理

```nginx
# deploy/nginx.conf
server {
    listen 80;
    server_name your-domain.com;
    root /www/wwwroot/strategy-trade;
    index index.html;

    # 静态资源
    location /static/ {
        alias /www/wwwroot/strategy-trade/frontend/dist/assets/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SPA 路由支持
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 禁止访问敏感文件
    location ~ /\.env { deny all; }
    location ~ /\.git { deny all; }
}
```

```bash
# 宝塔面板 → 网站 → 添加站点 → 配置Nginx → 替换为上述配置
# 保存并重载Nginx
sudo nginx -t && sudo nginx -s reload
```

### 4.8 验证部署

```bash
# 1. 检查服务状态
sudo supervisorctl status

# 2. 健康检查
curl http://localhost:8000/health

# 3. 浏览器访问
# http://your-domain.com → 前端页面
# http://your-domain.com/docs → API文档
# http://your-domain.com/install → 安装向导（首次）
```

---

## 五、Windows 本地一键启动（Launcher）

项目提供了 `StrategyTradeLauncher/` 启动器，双击即可启动：

| 文件 | 功能 |
|------|------|
| `Step0_一键启动后端_8000_HTA启动器.hta` | 双击启动后端+前端+浏览器 |
| `Step4_一键启动_后端+前端_自动打开浏览器.bat` | 命令行启动 |
| `Step2_启动后端服务_8000.bat` | 仅启动后端 |
| `Step3_启动前端服务_5173.bat` | 仅启动前端 |
| `0_把启动器复制到桌面.bat` | 一键复制到桌面 |

---

## 六、定时任务说明

系统内置 APScheduler 定时任务，启动后自动运行：

| 任务 | 频率 | 功能 |
|------|------|------|
| `news_crawl` | 每30分钟 | 新闻采集 + 关键词预筛选 |
| `news_ai_analysis` | 每2小时 | 重要新闻AI深度分析 |
| `news_ai_strategy` | 每小时 | 新闻情绪驱动策略信号生成 |
| `data_cleanup` | 每天03:00 | 清理过期数据 |

---

## 七、系统管理功能（v1.1.0 新增）

### 7.1 健康检查

访问 `/system/health` 或前端系统管理页面，系统自动检查：
- 数据库连接
- 磁盘空间
- 必要目录存在性
- 日志目录
- 数据库大小
- 备份数量

支持 `auto_fix=True` 自动修复（创建缺失目录）。

### 7.2 缓存清理

可清理的缓存类型：
- `pycache` - Python字节码缓存
- `pytest_cache` - pytest缓存
- `vite_cache` - Vite构建缓存
- `frontend_dist` - 前端构建产物
- `logs` - 旧日志文件

### 7.3 备份恢复

```bash
# 创建备份（通过API）
curl -X POST http://localhost:8000/api/v1/system-admin/backup \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"backup_type":"manual","include_db":true,"include_config":true}'

# 列出备份
curl http://localhost:8000/api/v1/system-admin/backups \
  -H "Authorization: Bearer YOUR_TOKEN"

# 恢复备份
curl -X POST http://localhost:8000/api/v1/system-admin/backup/1/restore \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 7.4 版本升级

1. 准备升级包（zip格式，包含更新后的代码）
2. 上传升级包：`POST /api/v1/system-admin/updates/upload`
3. 系统自动：备份 → 解压 → 验证 → 合并 → 替换前端dist
4. 重启服务生效

---

## 八、API 接口速查

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/refresh` | 刷新token |
| GET | `/api/v1/auth/me` | 当前用户 |
| POST | `/api/v1/auth/logout` | 登出 |

### 核心业务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/exchange/accounts` | 交易所账户列表 |
| POST | `/api/v1/exchange/accounts` | 添加交易所账户 |
| GET | `/api/v1/strategy/strategies` | 策略列表 |
| POST | `/api/v1/strategy/strategies` | 创建策略 |
| POST | `/api/v1/strategy/strategies/{id}/run` | 运行策略 |
| GET | `/api/v1/trade/orders` | 订单列表 |
| POST | `/api/v1/trade/orders` | 下单 |
| GET | `/api/v1/analytics/news/sentiment` | 新闻情绪分析 |
| POST | `/api/v1/analytics/backtest` | 执行回测 |

### 系统管理（v1.1.0 新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/system-admin/health` | 健康检查 |
| POST | `/api/v1/system-admin/health/check` | 执行健康检查 |
| GET | `/api/v1/system-admin/cache/cleanable` | 可清理缓存列表 |
| POST | `/api/v1/system-admin/cache/clean` | 清理缓存 |
| POST | `/api/v1/system-admin/backup` | 创建备份 |
| GET | `/api/v1/system-admin/backups` | 备份列表 |
| POST | `/api/v1/system-admin/backup/{id}/restore` | 恢复备份 |
| DELETE | `/api/v1/system-admin/backup/{id}` | 删除备份 |
| POST | `/api/v1/system-admin/updates/upload` | 上传升级包 |
| GET | `/api/v1/system-admin/updates` | 更新历史 |
| POST | `/api/v1/system-admin/updates/{id}/rollback` | 回滚更新 |

### 全局

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 服务健康检查 |
| GET | `/install` | 安装向导 |
| GET | `/docs` | Swagger API文档 |
| GET | `/openapi.json` | OpenAPI规范 |

---

## 九、常见问题排查

### 9.1 启动报错

```
# 1. 端口被占用
netstat -ano | findstr :8000
taskkill /f /pid <PID>

# 2. 数据库连接失败
# 检查 .env 中 DB_HOST/DB_USER/DB_PASSWORD 是否正确

# 3. 依赖缺失
pip install -r requirements.txt --force-reinstall
```

### 9.2 新闻采集失败

```
# 检查代理配置
curl http://localhost:8000/api/v1/news/proxy/health

# 手动触发采集（需登录）
curl -X POST http://localhost:8000/api/v1/news/collect \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 9.3 前端页面白屏

```bash
# 重新构建前端
cd frontend
rm -rf dist
npm run build
# 确保 dist/ 目录存在
ls frontend/dist/
```

### 9.4 定时任务未运行

```bash
# 检查 APScheduler 日志
tail -f logs/*.log | grep -i scheduler

# 手动触发一次新闻采集
curl -X POST http://localhost:8000/api/v1/news/collect \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 9.5 数据库表缺失

```bash
# 重启服务，lifespan 事件会自动建表
# 或手动执行
python -c "
from backend.db.base import Base
from backend.db.session import engine
from backend.models import *  # noqa
Base.metadata.create_all(bind=engine)
print('Tables created')
"
```

---

## 十、安全建议

1. **修改默认密码**：登录后台 → 个人中心 → 修改密码
2. **限制API密钥**：币安/OKX 子账号只允许从服务器IP白名单访问
3. **禁止提现**：在交易所后台移除子账号提现权限
3. **定期备份**：每周至少一次全量备份
4. **HTTPS**：生产环境务必配置SSL证书
5. **防火墙**：仅开放80/443端口，8000端口仅内网访问

---

## 十一、文件结构说明

```
strategy-trade/
├─ main.py                  # FastAPI 入口（/health, /install 路由）
├─ requirements.txt         # Python 依赖
├─ .env.example            # 环境变量模板
├─ .gitignore              # Git 忽略规则
├─ ARCHITECTURE.md         # 系统架构文档
├─ API_REFERENCE.md        # API接口文档
├─ PERMISSION.md           # 权限说明文档
├─ DEPLOYMENT.md           # 本文件（部署教程）
│
├─ backend/                # 后端代码
│  ├─ core/                # 核心模块（认证/异常/日志/代理）
│  ├─ db/                  # 数据库（模型/会话/种子数据）
│  ├─ models/              # 数据模型（19张表）
│  ├─ routers/             # API路由（12个模块）
│  ├─ services/            # 业务逻辑（新闻/AI/策略/系统管理）
│  ├─ news/                # 新闻采集（15+源）
│  ├─ exchanges/           # 交易所对接（币安/OKX）
│  ├─ strategy/            # 策略引擎（EMV/评分）
│  ├─ tasks/               # 定时任务（APScheduler）
│  └─ scripts/             # 运维脚本（健康检查）
│
├─ frontend/               # 前端代码
│  ├─ src/
│  │  ├─ views/            # 17个页面组件
│  │  ├─ layouts/          # 布局组件
│  │  ├─ router/           # 路由配置
│  │  ├─ store/            # Pinia状态管理
│  │  └─ utils/            # 工具函数
│  ├─ dist/               # 构建产物（部署用）
│  └─ package.json        # 前端依赖
│
├─ deploy/                 # 部署脚本
│  ├─ supervisor.conf      # Supervisor配置模板
│  ├─ nginx.conf           # Nginx配置模板
│  ├─ install.sh           # 一键安装脚本
│  └─ upgrade.sh           # 升级脚本
│
├─ StrategyTradeLauncher/  # Windows启动器
│  ├─ Step0_一键启动.hta
│  ├─ Step2_启动后端.bat
│  └─ Step3_启动前端.bat
│
└─ backups/                # 自动备份目录
```

---

## 十二、版本更新日志

### v1.1.0（当前版本）

**新增功能：**
- 系统管理模块：健康检查、缓存清理、备份恢复、版本升级
- 新闻AI策略：新闻情绪驱动交易信号生成
- 前端新增"系统管理"页面（仅管理员可见）

**修复问题：**
- 修复数据库健康检查SQL语法错误
- 修复新闻采集时间字段名称错误
- 修复新闻情绪分析API 500错误

**技术改进：**
- 新增 SystemBackupRecord / SystemUpdateRecord / SystemHealthReport 模型
- 新增 system_manager.py 系统管理服务
- 新增 news_strategy.py 新闻策略服务
- 前端新增 SystemAdmin.vue 页面

### v1.0.0（初始版本）

- 基础用户认证系统
- 交易所API对接（币安/OKX）
- EMV策略引擎
- 新闻采集与情绪分析
- AI综合评分
- 回测引擎
- 风控系统
- 15个前端页面
