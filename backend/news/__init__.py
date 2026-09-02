"""
新闻采集 + 分析管道（N-模块）

子模块：
- base.py           NewsCrawlerBase + 统一 RawNews 数据结构
- crawlers/*.py     6 个主流媒体爬虫（CoinDesk/CoinTelegraph/Reuters/Bloomberg/CNBC/OilPrice）+ FRED/EIA 宏观
- analyzer.py       英文情绪打分(VADER) + 关联品种标签生成(XAU/WTI/BTC/ETH/SOL) + 影响级别判断
- pipeline.py       统一调度：多源并发抓取 → 去重 → 情绪/标签 → 写 NewsArticle
"""
from .pipeline import NewsPipeline
