# Miniflux + RSSHub 自托管新闻源部署指南

## 优势
- 自托管、免费、无限制
- 配合 RSSHub 可扩展到 1000+ 新闻源
- 通过 API 对接策略系统，不影响现有架构
- Docker 隔离部署，不干扰策略系统

## 一、部署 RSSHub + Miniflux（10分钟）

### 1. 创建 Docker 网络
```bash
docker network create news-net
```

### 2. 启动 PostgreSQL（Miniflux 数据库）
```bash
docker run -d --name miniflux-db --network news-net \
  -e POSTGRES_USER=miniflux \
  -e POSTGRES_PASSWORD=miniflux \
  -e POSTGRES_DB=miniflux \
  postgres:15
```

### 3. 启动 Miniflux
```bash
docker run -d --name miniflux --network news-net \
  -p 127.0.0.1:8080:8080 \
  -e "DATABASE_URL=postgres://miniflux:miniflux@miniflux-db/miniflux?sslmode=disable" \
  -e "RUN_MIGRATIONS=1" \
  -e "CREATE_ADMIN=1" \
  -e "ADMIN_USERNAME=admin" \
  -e "ADMIN_PASSWORD=admin123" \
  -e "CLEANUP_ARCHIVE_READ_DAYS=30" \
  -e "CLEANUP_REMOVE_SESSIONS_DAYS=30" \
  miniflux/miniflux
```

### 4. 启动 RSSHub
```bash
docker run -d --name rsshub --network news-net \
  -p 1200:1200 \
  diygod/rsshub
```

### 5. 设置开机自启
```bash
docker update --restart=always miniflux-db miniflux rsshub
```

## 二、配置 Miniflux 订阅源（30分钟）

### 1. 登录 Miniflux
打开 `http://服务器IP:8080`，用 `admin / admin123` 登录

### 2. 生成 API Key
设置 → API Keys → Create a new API key → 复制保存

### 3. 添加 RSS 订阅源
订阅 → 添加订阅 → 填入 RSSHub 生成的 RSS 链接

### 推荐的 RSS 源（通过 RSSHub 生成）

| 新闻源 | RSSHub 路由 | 说明 |
|--------|------------|------|
| CoinDesk | `/coindesk` | 加密货币权威 |
| CoinTelegraph | `/cointelegraph` | 加密货币新闻 |
| The Block | `/theblock` | 区块链行业 |
| Decrypt | `/decrypt` | 加密货币 |
| Bloomberg Markets | `/bloomberg/markets` | 金融市场 |
| Reuters | `/reuters/category/world` | 国际新闻 |
| CNBC | `/cnbc/id/100003114` | 财经新闻 |
| OilPrice | `/oilprice` | 原油能源 |
| WallStreetCN | `/wallstreetcn/live` | 华尔街见闻 |
| 金十数据 | `/jin10` | 财经快讯 |
| Twitter 用户 | `/twitter/user/:username` | 推特动态 |
| Reddit | `/reddit/subreddit/:name` | 社区讨论 |

使用方式：`http://服务器IP:1200` + 上面的路由
例如：`http://服务器IP:1200/coindesk`

## 三、对接策略系统

### 1. 在 .env 中添加配置
```ini
MINIFLUX_URL=http://127.0.0.1:8080
MINIFLUX_API_KEY=你的API_Key
# 或使用用户名密码（二选一）
# MINIFLUX_USERNAME=admin
# MINIFLUX_PASSWORD=admin123
```

### 2. 重启策略系统
```bash
# 宝塔面板 → Python项目管理器 → 重启
# 或手动重启
```

### 3. 验证
登录策略系统 → 系统监控 → 功能自检 → 查看"Miniflux RSS"项状态

## 四、资源占用参考

| 组件 | 内存 | 硬盘 | 网络 |
|------|------|------|------|
| RSSHub | 80-150MB | 150MB | 按需拉取，极小 |
| Miniflux | 30-50MB | 50MB | 定时拉取，每天几十MB |
| PostgreSQL | 100-200MB | 200-500MB | 无 |
| 合计 | 250-400MB | 400MB-1G | 可忽略 |

## 五、维护

### 查看日志
```bash
docker logs -f miniflux
docker logs -f rsshub
```

### 更新
```bash
docker pull miniflux/miniflux && docker restart miniflux
docker pull diygod/rsshub && docker restart rsshub
```

### 备份 Miniflux 数据库
```bash
docker exec miniflux-db pg_dump -U miniflux miniflux > miniflux_backup.sql
```
