"""各媒体爬虫实现包"""
from .coindesk import CoinDeskCrawler, CoinTelegraphCrawler
from .macro_media import ReutersCrawler, BloombergCrawler, CNBCCrawler, OilPriceCrawler
from .macro import FREDCrawler, EIAWeeklyCrawler
from .alphavantage import AlphaVantageCrawler
from .newsdata import NewsDataCrawler
from .cn_media import CLSCrawler, BishijieCrawler, WallStreetCNCrawler, DecryptCrawler, DailyFXCrawler

ALL_CRAWLERS = [
    CoinDeskCrawler, CoinTelegraphCrawler, DecryptCrawler,
    ReutersCrawler, BloombergCrawler, CNBCCrawler,
    OilPriceCrawler,
    FREDCrawler, EIAWeeklyCrawler,
    AlphaVantageCrawler, NewsDataCrawler,
    CLSCrawler, BishijieCrawler, WallStreetCNCrawler, DailyFXCrawler,
]

__all__ = [
    "ALL_CRAWLERS",
    "CoinDeskCrawler", "CoinTelegraphCrawler", "DecryptCrawler",
    "ReutersCrawler", "BloombergCrawler", "CNBCCrawler",
    "OilPriceCrawler", "FREDCrawler", "EIAWeeklyCrawler",
    "AlphaVantageCrawler", "NewsDataCrawler",
    "CLSCrawler", "BishijieCrawler", "WallStreetCNCrawler", "DailyFXCrawler",
]
