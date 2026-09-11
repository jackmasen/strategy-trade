# 新闻源扩展操作指南

## 架构说明

系统采用 **Miniflux + RSSHub** 双层架构，支持零代码扩展 1000+ 新闻源：

- **RSSHub**：将几乎任何网站转为 RSS 源（社交媒体、新闻站、论坛、GitHub 等）
- **Miniflux**：RSS 阅读器 + 采集器，系统定时拉取 Miniflux 中的未读文章

## 部署位置

参考 `deploy/docker-compose.news.yml` 和 `deploy/miniflux_rsshub_deploy.md`

- Miniflux 管理后台：`http://服务器IP:8080`（或配置的域名）
- RSSHub：`http://服务器IP:1200`

---

## 快速添加美股财经新闻源（5 分钟）

### 方法一：直接添加 RSS 订阅（推荐首选）

如果目标网站已经提供 RSS，直接在 Miniflux 中添加：

1. 登录 Miniflux 后台
2. 点击左侧 **"订阅"** → **"新建订阅"**
3. 粘贴 RSS 地址，点击 **"查找"**
4. 选择分类（如"美股财经"），点击 **"保存"**

### 常用美股财经 RSS 源

| 来源 | RSS 地址 | 说明 |
|------|----------|------|
| Yahoo Finance Market News | https://finance.yahoo.com/news/rssindex | 综合市场新闻 |
| Seeking Alpha Market News | https://seekingalpha.com/market_currents.xml | 市场动态 |
| MarketWatch Top Stories | https://feeds.content.dowjones.io/public/rss/mw_topstories | 头条新闻 |
| CNBC Finance | https://www.cnbc.com/id/10000664/device/rss/rss.html | 财经新闻 |
| Bloomberg Markets | https://feeds.bloomberg.com/markets/news.rss | 市场新闻 |
| WSJ Markets | https://feeds.a.dj.com/rss/RSSMarketsMain.xml | 华尔街日报 |
| Investopedia | https://www.investopedia.com/feedburner/fp-investingnews | 投资新闻 |
| The Motley Fool | https://www.fool.com/feeds/index.aspx | 投资建议 |
| Benzinga | https://www.benzinga.com/news/feed/ | 财经快讯 |
| Barron's | https://www.barrons.com/feed | 财经杂志 |
| StockTwits Trending | https://stocktwits.com/rss/trending | 社交情绪 |
| Reuters Business | https://feeds.reuters.com/reuters/businessNews | 路透商业 |

### 方法二：通过 RSSHub 生成 RSS（无原生 RSS 的网站）

对于没有原生 RSS 的网站，使用 RSSHub 路由生成：

**格式**：`http://<RSSHub地址>/<路由>/<参数>`

**常用美股相关路由**：

| 网站 | 路由格式 | 示例 |
|------|----------|------|
| 雪球热帖 | /xueqiu/today | 热门讨论 |
| 东方财富财经 | /eastmoney/news | A股+财经 |
| 财联社 | /cls/telegraph | 电报快讯 |
| Reddit r/stocks | /reddit/r/stocks | 美股讨论 |
| Reddit r/wallstreetbets | /reddit/r/wallstreetbets | WSB 情绪 |
| Twitter/X 用户 | /twitter/user/:id | 需配置 API |
| Telegram 频道 | /telegram/channel/:username | 电报频道 |

**示例**：添加 Reddit r/stocks 讨论
```
http://你的RSSHub地址:1200/reddit/r/stocks
```

### 方法三：加密货币新闻源（已接入，补充更多）

| 来源 | RSS 地址 |
|------|----------|
| The Block | https://www.theblock.co/rss |
| CoinDesk | https://www.coindesk.com/arc/outboundfeeds/rss/ |
| CoinTelegraph | https://cointelegraph.com/rss |
| Decrypt | https://decrypt.co/feed |
| Bitcoin Magazine | https://bitcoinmagazine.com/feed |

---

## Miniflux 配置优化

### 1. 创建分类（推荐）

在 Miniflux 中按类别组织订阅：
- 加密货币
- 美股科技
- 美股消费
- 宏观经济
- 能源商品
- 贵金属

系统会读取文章的分类信息用于展示过滤。

### 2. 设置抓取频率

Miniflux 默认每小时抓取一次，可在设置中调整：
- 快讯类（财联社、CoinDesk）：每 15 分钟
- 日报类（WSJ、Bloomberg）：每 1 小时
- 周更类：每 6 小时

### 3. 清理规则

设置自动清理已读文章（如保留 30 天），避免数据库膨胀。

---

## 系统侧配置

添加 RSS 订阅后，系统自动从 Miniflux 拉取新文章，**不需要修改任何代码**。

新闻处理流程：
1. Miniflux 抓取文章 → 2. 系统定时任务拉取未读 → 3. 关键词预筛选 → 4. 高影响级别的触发 AI 分析 → 5. 入库并关联品种

### 验证新源是否生效

1. 登录系统后台 → 新闻情绪页面
2. 等待下一轮新闻采集（默认 15 分钟）
3. 在新闻列表中查看是否有新来源的文章
4. 点击文章详情，确认 `related_symbols` 是否正确关联

### 如果新闻没有关联到对应品种

需要在 `backend/services/news_keywords.py` 的 `KEYWORD_LIBRARY` 中添加对应的关键词。
参考已有格式，每只股票 3-5 个关键词（公司名中英文 + 财报 + 产品）。

---

## 高级：新增独立爬虫（需要开发）

如果 RSS 方式无法满足需求（如需要深度解析、反爬严格的站点），可以开发独立爬虫：

1. 在 `backend/news/crawlers/` 下新建爬虫类
2. 继承 `NewsCrawlerBase`，实现 `crawl()` 方法
3. 基类已提供：UA 轮换、代理池、指数退避、频率控制、自动去重
4. 在 `NEWS_SOURCES` 中注册新源

工作量：每个独立爬虫约 0.5-1 人天。

---

## 注意事项

1. **版权合规**：使用 RSS 抓取时注意目标网站的 robots.txt 和使用条款
2. **抓取频率**：不要设置过高的抓取频率，避免被目标站点封禁
3. **内容去重**：系统已内置标题+链接去重，同一篇文章从多个源进入不会重复
4. **AI 成本**：新增大量源会增加 AI 分析调用量，关键词预筛选机制会过滤掉低影响级别的新闻
5. **Miniflux 数据库**：订阅量大时注意 PostgreSQL 数据库存储空间
