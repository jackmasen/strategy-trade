"""
新闻 → 情绪打分 + 关联品种 + 影响级别

核心 3 步（在落库前统一走 analyze(raw_news) -> NewsArticle 需要填的字段）：

1) **情绪 VADER (-1 ~ +1)**：优先 `vaderSentiment`（专门针对社交媒体/新闻/标题，40MB依赖极小）；
   若未安装则 fallback 到关键词词典规则（bullish/bearish/hawkish/dovish/surge/plunge 等）。

2) **关联品种 related_symbols**：本系统交易 BTC/ETH/SOL/XAU/WTI/SKHYNIX/SNDK 等，
   所以基于标题+摘要+分类做关键词命中映射，而不是 NER 命名实体（省内存省时间）。
   同时保留 `tags` 字段用于前端筛选。

3) **影响级别 impact_level (1~4)**：
   - 4：重大（官方数据发布、FOMC/鲍威尔讲话、OPEC+会议决议、ETF 通过/驳回）
   - 3：高（SEC 起诉币安/FTX 级、非农就业超预期、原油库存大幅偏离）
   - 2：中（行业高管发声、CPI 温和变动、OPEC 月报）
   - 1：低（普通行情回顾、小公司动态）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from backend.core.logging_config import logger


@dataclass
class AnalysisResult:
    sentiment: int            # -1 / 0 / 1
    sentiment_score: float    # -1.0 ~ +1.0
    sentiment_keywords: List[str]
    related_symbols: List[str]   # 本系统关心的：BTC/ETH/SOL/XAU/WTI/SKHYNIX/SNDK等（不关心的不写，保持 related_symbols 干净）
    tags: List[str]
    impact_level: int         # 1~4
    is_hot: bool


# =========================================================
#  币种 / 商品 关键词映射（命中一个即把品种加到 related_symbols）
# =========================================================
SYMBOL_KEYWORDS: List[Tuple[str, List[str]]] = [
    # Crypto
    ("BTC", ["bitcoin", " btc ", "btc/", "btc$", "#btc", "xbt", "satoshi"]),
    ("ETH", ["ethereum", " eth ", "eth/", "ether", "vitalik", "eip-", "erc-"]),
    ("SOL", ["solana", " sol ", "sol/", "sbf"]),

    # Precious metals
    ("XAU", ["gold ", "gold,", "golden", "xau", "precious metal", "rally in gold", "safe haven"]),
    ("XAG", ["silver", " xag ", "silver price", "white metal"]),
    # Energy / Oil
    ("WTI", ["wti", "crude oil", "u.s. crude", "us crude", "brent", "opec", "oil invent", "oil price",
             "eia weekly", "crude stock", "gasoline stock", "strategic petroleum reserve"]),
    # US Stocks - Tech
    ("TSLA", ["tesla", " tsla ", "tsla/", "musk", "elon", "gigafactory", "cybertruck", "model 3", "model y", "model s", "model x", "autopilot", "dojo", "megapack", "powerwall"]),
    ("NVDA", ["nvidia", " nvda ", "nvda/", "gpu", "graphic card", "ai chip", "h100", "a100", "h200", "b100", "gb200", "黄仁勋", "cuda", "geforce", "rtx", "data center", "accelerated computing"]),
    ("AAPL", ["apple", " aapl ", "aapl/", "iphone", "ipad", "macbook", "tim cook", "库克", "vision pro", "apple intelligence", "app store", "apple watch", "airpods", "macos", "ios"]),
    ("MSFT", ["microsoft", " msft ", "msft/", "azure", "windows", "office 365", "satya", "盖茨", "openai", "copilot", "bing", "github", "linkedin", "teams", "xbox", "surface", "active directory"]),
    # US Stocks - China
    ("TCEHY", ["tencent", " tcehy ", "tcehy/", "腾讯", "wechat", "微信", "pony ma", "马化腾", "honor of kings", "weixin", "tiktok", "pubg mobile", "league of legends"]),
    # Semiconductor / Memory
    ("SKHYNIX", ["sk hynix", "skhynix", "海力士", "hbm", "高带宽存储", "dram", "晶圆", "000660", "hbm3", "hbm3e", "ddr5", "lpddr"]),
    ("SNDK", ["sandisk", "sndk", "闪迪", "nand flash", "nand", "闪存", "ssd", "western digital", "wd", "uflash"]),
]

# 宏观类关键词：命中的会把品种扩散成全部（宏观对所有品种都可能有影响）
MACRO_KEYWORDS = [
    "fed", "fomc", "powell", "interest rate", "rate decision", "rate hike", "rate cut",
    "cpi", "inflation", "nonfarm", "nfp", "unemploy", "recession", "treasur", "yield",
    "debt ceiling", "dollar index", "dxy",
    "earnings season", "earnings report", "quarterly results", "guidance", "revenue miss",
    "revenue beat", "eps", "stock market", "s&p 500", "nasdaq", "dow jones", "bull market",
    "bear market", "market crash", "correction", "volatility index", "vix", "fear and greed",
    "risk appetite", "risk off", "risk on", "safe haven", "flight to safety",
    "geopolitical", "trade war", "tariff", "sanction", "embargo",
    "jobless claims", "job cuts", "layoff", "hiring freeze",
    "pmi", "manufacturing", "industrial production", "retail sales", "consumer confidence",
    "housing market", "mortgage", "real estate",
    "ai bubble", "tech sell-off", "tech rally", "magnificent seven", "mag 7",
]

# 加密宏观：比特币 ETF、监管类
REGULATION_CRYPTO_KEYWORDS = [
    "etf", "sec ", "securities and exchange commission", "approval", "reject", "court",
    "lawsuit", "sanction", "binance", "coinbase", "ftx", "cfc", "bankruptcy",
]


# =========================================================
# VADER 情绪打分（fallback 词典）
# =========================================================
_VADER_SIA = None
_VADER_INIT_TRY = False


def _get_vader():
    """延迟加载，避免没装依赖时 import 失败"""
    global _VADER_SIA, _VADER_INIT_TRY
    if _VADER_INIT_TRY:
        return _VADER_SIA
    _VADER_INIT_TRY = True
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore
        _VADER_SIA = SentimentIntensityAnalyzer()
    except ImportError:
        logger.info("[News/Analyzer] vaderSentiment 未安装，使用关键词 fallback 情绪打分。pip install vaderSentiment 可提升准确率。")
        _VADER_SIA = None
    except Exception as e:
        logger.debug(f"[News/Analyzer] VADER 初始化异常: {e}")
        _VADER_SIA = None
    return _VADER_SIA


# fallback 词典（新闻/宏观/能源/黄金 常见词极性）
_POS_WORDS = [
    "bullish", "bull", "soar", "surge", "rally", "jump", "gain", "climb", "rise", "boost",
    "support", "positive", "optimistic", "upgrade", "beat", "exceed", "strong",
    "cut rates", "rate cut", "dovish", "easing", "approval", "approved", "launch",
    "buy", "pivot", "cooling", "disinflation", "soft landing",
    "drawdown in inventories", "inventory draw", "supply cut", "opec+ cut", "production cut",
    "safe-haven buying",
]
_NEG_WORDS = [
    "bearish", "bear", "slump", "plunge", "crash", "drop", "fall", "decline", "tumble", "sink",
    "loss", "weak", "recession", "crisis", "downgrade", "miss", "disappoint", "negative",
    "pessimistic", "hawkish", "rate hike", "hikes", "restrictive", "higher for longer",
    "selloff", "sell-off", "sell off", "reject", "rejection", "lawsuit", "ban", "crackdown",
    "sec sues", "bankrupt", "default", "debt default", "contagion",
    "inventory build", "surplus", "gluts", "demand worry", "demand weakness",
]
_HOT_WORDS = [
    "breaking", "exclusive", "urgent", "just in", "live", "report: ",
    "cpi report", "nfp report", "non-farm", "fomc statement", "minutes", "fed chair",
    "powell", "opec meeting", "opec+", "eia weekly report", "etf decision",
]


def _score_sentiment_fallback(title: str, summary: str) -> float:
    text = f"{title}\n{summary}".lower()
    if not text.strip():
        return 0.0
    pos = sum(1 for w in _POS_WORDS if w in text)
    neg = sum(1 for w in _NEG_WORDS if w in text)
    total = pos + neg
    if total == 0:
        return 0.0
    # 归一化到 -1 ~ +1
    return round((pos - neg) / max(total, 3), 3)


def score_sentiment(title: str, summary: str) -> Tuple[float, List[str]]:
    """
    给标题 + 摘要打情绪分。
    返回：(sentiment_score [-1,1], hit_keywords list[str])
    """
    title = title or ""
    summary = summary or ""
    text = f"{title}. {summary}"
    sia = _get_vader()
    if sia is not None:
        try:
            vs = sia.polarity_scores(text)
            compound = float(vs.get("compound", 0.0))  # -1 ~ +1
        except Exception:
            compound = _score_sentiment_fallback(title, summary)
    else:
        compound = _score_sentiment_fallback(title, summary)

    # 命中关键词（用于前端展示 + 影响级别加成）
    text_l = text.lower()
    hits = [w for w in _POS_WORDS + _NEG_WORDS + _HOT_WORDS if w in text_l]
    # 去重保序
    seen = set()
    uniq = []
    for w in hits:
        if w not in seen:
            seen.add(w); uniq.append(w)
    return round(compound, 3), uniq[:10]


# =========================================================
# 关联品种识别（返回本系统关心的所有品种）
# =========================================================
def match_symbols(title: str, summary: str, category: str) -> Tuple[List[str], List[str]]:
    """
    返回：
      - related_symbols: ["BTC","XAU","WTI","TSLA",...]
      - extra_tags: ["regulation","macro",...]
    """
    text = f"{title}\n{summary}".lower()
    if not text:
        return [], []
    related: List[str] = []
    extra_tags: List[str] = []

    for sym, keywords in SYMBOL_KEYWORDS:
        if any(k in text for k in keywords):
            if sym not in related:
                related.append(sym)

    # 宏观关键词命中 → 扩散所有品种都加入（因为加息降息/股市大盘对所有品种都影响）
    hit_macro = any(k in text for k in MACRO_KEYWORDS)
    if hit_macro:
        for sym in ("BTC", "ETH", "SOL", "XAU", "WTI", "TSLA", "NVDA", "AAPL", "MSFT", "TCEHY", "SKHYNIX", "SNDK"):
            if sym not in related:
                related.append(sym)
        extra_tags.append("macro")

    # 加密监管：加到 BTC/ETH/SOL
    hit_reg = any(k in text for k in REGULATION_CRYPTO_KEYWORDS)
    if hit_reg:
        for sym in ("BTC", "ETH", "SOL"):
            if sym not in related:
                related.append(sym)
        extra_tags.append("regulation")

    if category == "energy":
        extra_tags.append("energy")
        if "WTI" not in related:
            related.append("WTI")
    elif category == "metals":
        extra_tags.append("metals")
        if "XAU" not in related:
            related.append("XAU")
    elif category == "crypto":
        extra_tags.append("crypto")
        # crypto 类但没提到具体币种 → 默认 BTC/ETH/SOL 都沾边
        if not any(s in related for s in ("BTC", "ETH", "SOL")):
            related.extend(["BTC", "ETH", "SOL"])

    return related, extra_tags


# =========================================================
# 影响级别 / 是否热点
# =========================================================
def estimate_impact(title: str, summary: str, category: str,
                    official_source: bool = False) -> int:
    """
    impact_level: 1(低) ~ 4(重大)，官方数据源如 FRED/EIA 直接从 2/3 起步
    """
    text = f"{title}\n{summary}".lower()
    level = 2 if official_source else 1

    # 官方经济数据发布（FRED 指标 / EIA 库存）
    if official_source:
        level = 3

    if category == "macro":
        level = max(level, 3)

    hot_keywords_hit = sum(1 for w in _HOT_WORDS if w in text)
    if hot_keywords_hit >= 1:
        level = max(level, 3)
    if hot_keywords_hit >= 2:
        level = max(level, 4)

    # 关键重大事件词 → 直接 4
    major_words = [
        "fomc statement", "fed chair powell", "fed decision", "powell speaks",
        "cpi (consumer", "nonfarm payroll", "nfp",
        "opec+ meeting", "opec meeting concludes",
        "etf approval", "etf denied", "etf rejected",
        "bankruptcy filing", "credit suisse", "silicon valley bank",
        "debt ceiling deal", "default risk",
    ]
    if any(w in text for w in major_words):
        level = 4

    return min(4, max(1, level))


def is_hot_news(title: str, summary: str, impact_level: int) -> bool:
    if impact_level >= 3:
        return True
    text = f"{title}\n{summary}".lower()
    return any(w in text for w in _HOT_WORDS)


# =========================================================
# 对外统一入口（落库前调用一次）
# =========================================================
def analyze(title: str, summary: str, category: str = "general",
            language: str = "en", official_source: bool = False,
            tags: Optional[List[str]] = None,
            source_name: str = "",
            published_at: Optional[datetime] = None
            ) -> AnalysisResult:
    """
    给一条新闻打情绪 + 关联品种 + 影响级别。
    language 目前只区分 en / zh，中文不跑 VADER，走 fallback 词典。
    """
    tags = list(tags or [])
    if language != "en":
        sentiment_score, keys = _score_sentiment_fallback(title, summary), []
    else:
        sentiment_score, keys = score_sentiment(title, summary)

    sentiment = (1 if sentiment_score >= 0.15 else (-1 if sentiment_score <= -0.15 else 0))

    related, extra_tags = match_symbols(title, summary, category)
    for t in extra_tags:
        if t not in tags:
            tags.append(t)

    # 来源分类信息附加 tags
    if source_name:
        src_tag = f"src:{source_name.lower().replace(' ', '_')}"
        if src_tag not in tags:
            tags.append(src_tag)

    # 官方数据源（FRED/EIA）判断
    official = official_source or source_name in ("FRED", "EIA")

    impact = estimate_impact(title, summary, category, official_source=official)
    hot = is_hot_news(title, summary, impact)

    return AnalysisResult(
        sentiment=sentiment,
        sentiment_score=round(sentiment_score, 3),
        sentiment_keywords=keys,
        related_symbols=sorted(set(related)),
        tags=tags,
        impact_level=impact,
        is_hot=hot,
    )
