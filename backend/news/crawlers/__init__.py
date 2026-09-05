"""各媒体爬虫实现包"""
from .miniflux import MinifluxCrawler
from .coindesk import CoinDeskCrawler, CoinTelegraphCrawler
from .macro_media import ReutersCrawler, BloombergCrawler, CNBCCrawler, OilPriceCrawler
from .macro import FREDCrawler, EIAWeeklyCrawler
from .alphavantage import AlphaVantageCrawler
from .newsdata import NewsDataCrawler
from .cn_media import CLSCrawler, BishijieCrawler, WallStreetCNCrawler, DecryptCrawler, DailyFXCrawler

# Miniflux 优先（RSS聚合器不会被封锁，是最可靠的数据源）
ALL_CRAWLERS = [
    MinifluxCrawler,
    CoinDeskCrawler, CoinTelegraphCrawler, DecryptCrawler,
    ReutersCrawler, BloombergCrawler, CNBCCrawler,
    OilPriceCrawler,
    FREDCrawler, EIAWeeklyCrawler,
    AlphaVantageCrawler, NewsDataCrawler,
    CLSCrawler, BishijieCrawler, WallStreetCNCrawler, DailyFXCrawler,
]

__all__ = [
    "ALL_CRAWLERS",
    "MinifluxCrawler",
    "CoinDeskCrawler", "CoinTelegraphCrawler", "DecryptCrawler",
    "ReutersCrawler", "BloombergCrawler", "CNBCCrawler",
    "OilPriceCrawler", "FREDCrawler", "EIAWeeklyCrawler",
    "AlphaVantageCrawler", "NewsDataCrawler",
    "CLSCrawler", "BishijieCrawler", "WallStreetCNCrawler", "DailyFXCrawler",
]
