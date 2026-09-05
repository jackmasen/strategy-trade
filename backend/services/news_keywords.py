"""
新闻关键词库
- 中英文双语关键词
- 按类别分组：宏观/加密/能源/贵金属/地缘
- 每个关键词带情绪倾向和影响级别
- 用于预筛选：只对命中关键词的新闻调用AI分析，节省90%+成本
"""

# 关键词库结构: (关键词, 情绪倾向[-1/0/1], 影响级别[1-4], 关联品种[], 分类)
KEYWORD_LIBRARY = [
    # ================= 宏观经济 =================
    # 非农就业
    ("非农", 0, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("nonfarm", 0, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("NFP", 0, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("就业数据", 0, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("unemployment", 0, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("失业率", 0, 3, ["BTC", "ETH", "XAU"], "macro"),

    # CPI/通胀
    ("CPI", 0, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("通胀", 0, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("inflation", 0, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("PCE", 0, 3, ["BTC", "ETH", "XAU"], "macro"),

    # 利率/美联储
    ("加息", -1, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("rate hike", -1, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("降息", 1, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("rate cut", 1, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("利率决议", 0, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("FOMC", 0, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("美联储", 0, 3, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("fed", 0, 3, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("Powell", 0, 3, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("鲍威尔", 0, 3, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("鹰派", -1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("hawkish", -1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("鸽派", 1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("dovish", 1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("缩表", -1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("quantitative tightening", -1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("量化宽松", 1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("QE", 1, 3, ["BTC", "ETH", "XAU"], "macro"),

    # GDP/经济衰退
    ("GDP", 0, 3, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("衰退", -1, 4, ["BTC", "ETH", "XAU"], "macro"),
    ("recession", -1, 4, ["BTC", "ETH", "XAU"], "macro"),
    ("经济危机", -1, 4, ["BTC", "ETH", "XAU", "WTI"], "macro"),
    ("软着陆", 1, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("soft landing", 1, 3, ["BTC", "ETH", "XAU"], "macro"),

    # 债务/美债
    ("债务上限", -1, 4, ["BTC", "ETH", "XAU"], "macro"),
    ("debt ceiling", -1, 4, ["BTC", "ETH", "XAU"], "macro"),
    ("美债", 0, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("treasury", 0, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("收益率", 0, 3, ["BTC", "ETH", "XAU"], "macro"),
    ("yield", 0, 3, ["BTC", "ETH", "XAU"], "macro"),

    # ================= 加密货币 =================
    # ETF
    ("ETF", 1, 4, ["BTC", "ETH"], "crypto"),
    ("ETF获批", 1, 4, ["BTC", "ETH"], "crypto"),
    ("ETF通过", 1, 4, ["BTC", "ETH"], "crypto"),
    ("ETF拒绝", -1, 4, ["BTC", "ETH"], "crypto"),
    ("ETF denied", -1, 4, ["BTC", "ETH"], "crypto"),
    ("现货ETF", 1, 4, ["BTC", "ETH"], "crypto"),
    ("spot ETF", 1, 4, ["BTC", "ETH"], "crypto"),

    # 监管
    ("SEC", -1, 3, ["BTC", "ETH", "SOL"], "crypto"),
    ("监管", -1, 3, ["BTC", "ETH", "SOL"], "crypto"),
    ("regulation", -1, 3, ["BTC", "ETH", "SOL"], "crypto"),
    ("起诉", -1, 3, ["BTC", "ETH"], "crypto"),
    ("lawsuit", -1, 3, ["BTC", "ETH"], "crypto"),
    ("禁令", -1, 4, ["BTC", "ETH"], "crypto"),
    ("ban", -1, 4, ["BTC", "ETH"], "crypto"),
    ("制裁", 0, 3, ["BTC", "ETH"], "crypto"),
    ("sanction", 0, 3, ["BTC", "ETH"], "crypto"),

    # 黑客/安全
    ("黑客", -1, 4, ["BTC", "ETH"], "crypto"),
    ("hack", -1, 4, ["BTC", "ETH"], "crypto"),
    ("被盗", -1, 4, ["BTC", "ETH"], "crypto"),
    ("漏洞", -1, 3, ["BTC", "ETH"], "crypto"),
    ("exploit", -1, 4, ["BTC", "ETH"], "crypto"),

    # 交易所
    ("破产", -1, 4, ["BTC", "ETH"], "crypto"),
    ("bankrupt", -1, 4, ["BTC", "ETH"], "crypto"),
    ("FTX", -1, 3, ["BTC", "ETH"], "crypto"),
    ("币安", 0, 3, ["BTC", "ETH"], "crypto"),
    ("Binance", 0, 3, ["BTC", "ETH"], "crypto"),
    ("Coinbase", 0, 2, ["BTC", "ETH"], "crypto"),

    # 减半/升级
    ("减半", 1, 3, ["BTC"], "crypto"),
    ("halving", 1, 3, ["BTC"], "crypto"),
    ("升级", 1, 2, ["ETH"], "crypto"),
    ("upgrade", 1, 2, ["ETH"], "crypto"),
    ("分叉", 0, 2, ["BTC", "ETH"], "crypto"),
    ("fork", 0, 2, ["BTC", "ETH"], "crypto"),

    # 机构入场
    ("机构", 1, 3, ["BTC", "ETH"], "crypto"),
    ("institutional", 1, 3, ["BTC", "ETH"], "crypto"),
    ("MicroStrategy", 1, 2, ["BTC"], "crypto"),
    ("特斯拉", 0, 2, ["BTC"], "crypto"),
    ("Tesla", 0, 2, ["BTC"], "crypto"),
    ("BlackRock", 1, 3, ["BTC", "ETH"], "crypto"),
    ("贝莱德", 1, 3, ["BTC", "ETH"], "crypto"),

    # ================= 能源/原油 =================
    ("OPEC", 0, 3, ["WTI"], "energy"),
    ("OPEC+", 0, 4, ["WTI"], "energy"),
    ("减产", 1, 3, ["WTI"], "energy"),
    ("production cut", 1, 3, ["WTI"], "energy"),
    ("增产", -1, 3, ["WTI"], "energy"),
    ("原油库存", 0, 3, ["WTI"], "energy"),
    ("crude inventory", 0, 3, ["WTI"], "energy"),
    ("EIA", 0, 3, ["WTI"], "energy"),
    ("油价", 0, 2, ["WTI"], "energy"),
    ("oil price", 0, 2, ["WTI"], "energy"),
    ("布伦特", 0, 2, ["WTI"], "energy"),
    ("Brent", 0, 2, ["WTI"], "energy"),
    ("WTI", 0, 2, ["WTI"], "energy"),
    ("天然气", 0, 2, ["WTI"], "energy"),
    ("natural gas", 0, 2, ["WTI"], "energy"),
    ("战略石油储备", 0, 3, ["WTI"], "energy"),
    ("strategic petroleum reserve", 0, 3, ["WTI"], "energy"),

    # ================= 贵金属/黄金 =================
    ("黄金", 0, 2, ["XAU"], "metals"),
    ("gold", 0, 2, ["XAU"], "metals"),
    ("金价", 0, 2, ["XAU"], "metals"),
    ("gold price", 0, 2, ["XAU"], "metals"),
    ("白银", 0, 2, ["XAU"], "metals"),
    ("silver", 0, 2, ["XAU"], "metals"),
    ("避险", 1, 3, ["XAU", "BTC"], "metals"),
    ("safe haven", 1, 3, ["XAU", "BTC"], "metals"),
    ("避险资产", 1, 3, ["XAU", "BTC"], "metals"),
    ("金库", 0, 2, ["XAU"], "metals"),
    ("贵金属", 0, 2, ["XAU"], "metals"),
    ("precious metal", 0, 2, ["XAU"], "metals"),

    # ================= 地缘政治/战争 =================
    ("战争", 1, 4, ["XAU", "WTI", "BTC"], "geopolitics"),
    ("war", 1, 4, ["XAU", "WTI", "BTC"], "geopolitics"),
    ("冲突", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("conflict", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("军事", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("military", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("袭击", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("attack", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("停火", -1, 3, ["XAU", "WTI"], "geopolitics"),
    ("ceasefire", -1, 3, ["XAU", "WTI"], "geopolitics"),
    ("核", 1, 4, ["XAU", "BTC"], "geopolitics"),
    ("nuclear", 1, 4, ["XAU", "BTC"], "geopolitics"),
    ("制裁", 0, 3, ["BTC", "ETH", "WTI"], "geopolitics"),
    ("sanction", 0, 3, ["BTC", "ETH", "WTI"], "geopolitics"),
    ("贸易战", -1, 3, ["BTC", "ETH", "XAU", "WTI"], "geopolitics"),
    ("trade war", -1, 3, ["BTC", "ETH", "XAU", "WTI"], "geopolitics"),
    ("关税", -1, 2, ["BTC", "ETH", "XAU"], "geopolitics"),
    ("tariff", -1, 2, ["BTC", "ETH", "XAU"], "geopolitics"),
    ("俄乌", 1, 3, ["XAU", "WTI", "BTC"], "geopolitics"),
    ("中东", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("Middle East", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("以色列", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("Israel", 1, 3, ["XAU", "WTI"], "geopolitics"),
    ("伊朗", 1, 3, ["WTI", "XAU"], "geopolitics"),
    ("Iran", 1, 3, ["WTI", "XAU"], "geopolitics"),

    # ================= 市场情绪 =================
    ("牛市", 1, 2, ["BTC", "ETH"], "sentiment"),
    ("bull market", 1, 2, ["BTC", "ETH"], "sentiment"),
    ("熊市", -1, 2, ["BTC", "ETH"], "sentiment"),
    ("bear market", -1, 2, ["BTC", "ETH"], "sentiment"),
    ("暴涨", 1, 3, ["BTC", "ETH"], "sentiment"),
    ("surge", 1, 3, ["BTC", "ETH"], "sentiment"),
    ("暴跌", -1, 3, ["BTC", "ETH"], "sentiment"),
    ("crash", -1, 4, ["BTC", "ETH"], "sentiment"),
    ("暴跌", -1, 4, ["BTC", "ETH"], "sentiment"),
    ("恐慌", -1, 3, ["BTC", "ETH", "XAU"], "sentiment"),
    ("panic", -1, 3, ["BTC", "ETH", "XAU"], "sentiment"),
    ("FUD", -1, 3, ["BTC", "ETH"], "sentiment"),
    ("FOMO", 1, 2, ["BTC", "ETH"], "sentiment"),
    ("抄底", 1, 2, ["BTC", "ETH"], "sentiment"),
    ("buy the dip", 1, 2, ["BTC", "ETH"], "sentiment"),
    ("抛售", -1, 3, ["BTC", "ETH", "XAU"], "sentiment"),
    ("selloff", -1, 3, ["BTC", "ETH", "XAU"], "sentiment"),
    ("止损", -1, 2, ["BTC", "ETH"], "sentiment"),
    ("清算", -1, 3, ["BTC", "ETH"], "sentiment"),
    ("liquidation", -1, 3, ["BTC", "ETH"], "sentiment"),

    # ================= 半导体/存储芯片 =================
    ("海力士", 0, 3, ["SKHYNIX"], "semiconductor"),
    ("SK Hynix", 0, 3, ["SKHYNIX"], "semiconductor"),
    ("SKHYNIX", 0, 3, ["SKHYNIX"], "semiconductor"),
    ("HBM", 0, 3, ["SKHYNIX", "SNDK"], "semiconductor"),
    ("高带宽存储", 0, 3, ["SKHYNIX"], "semiconductor"),
    ("存储芯片", 0, 2, ["SKHYNIX", "SNDK"], "semiconductor"),
    ("memory chip", 0, 2, ["SKHYNIX", "SNDK"], "semiconductor"),
    ("NAND", 0, 2, ["SNDK"], "semiconductor"),
    ("闪存", 0, 2, ["SNDK"], "semiconductor"),
    ("闪迪", 0, 3, ["SNDK"], "semiconductor"),
    ("SanDisk", 0, 3, ["SNDK"], "semiconductor"),
    ("SNDK", 0, 2, ["SNDK"], "semiconductor"),
    ("半导体", 0, 2, ["SKHYNIX", "SNDK"], "semiconductor"),
    ("semiconductor", 0, 2, ["SKHYNIX", "SNDK"], "semiconductor"),
    ("芯片", 0, 2, ["SKHYNIX", "SNDK"], "semiconductor"),
    ("chip", 0, 2, ["SKHYNIX", "SNDK"], "semiconductor"),
    ("晶圆", 0, 2, ["SKHYNIX"], "semiconductor"),
    ("wafer", 0, 2, ["SKHYNIX"], "semiconductor"),
    ("DRAM", 0, 2, ["SKHYNIX"], "semiconductor"),
    ("SSD", 0, 2, ["SNDK"], "semiconductor"),

    # ================= 美股-科技 =================
    ("Tesla earnings", 0, 3, ["TSLA"], "stock"),
    ("特斯拉财报", 0, 3, ["TSLA"], "stock"),
    ("Model 3", 0, 2, ["TSLA"], "stock"),
    ("Cybertruck", 0, 2, ["TSLA"], "stock"),
    ("Nvidia earnings", 0, 3, ["NVDA"], "stock"),
    ("英伟达财报", 0, 3, ["NVDA"], "stock"),
    ("GPU demand", 1, 3, ["NVDA"], "stock"),
    ("AI chip", 0, 3, ["NVDA", "SKHYNIX"], "stock"),
    ("Apple earnings", 0, 3, ["AAPL"], "stock"),
    ("苹果财报", 0, 3, ["AAPL"], "stock"),
    ("iPhone sales", 0, 2, ["AAPL"], "stock"),
    ("Microsoft earnings", 0, 3, ["MSFT"], "stock"),
    ("微软财报", 0, 3, ["MSFT"], "stock"),
    ("Azure growth", 1, 2, ["MSFT"], "stock"),
    ("Tencent earnings", 0, 3, ["TCEHY"], "stock"),
    ("腾讯财报", 0, 3, ["TCEHY"], "stock"),
    ("WeChat", 0, 2, ["TCEHY"], "stock"),
    ("earnings beat", 1, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("earnings miss", -1, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("财报超预期", 1, 3, ["TSLA", "NVDA", "AAPL", "MSFT", "TCEHY"], "stock"),
    ("财报不及预期", -1, 3, ["TSLA", "NVDA", "AAPL", "MSFT", "TCEHY"], "stock"),
    ("guidance", 0, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("stock split", 0, 3, ["TSLA", "NVDA", "AAPL"], "stock"),
    ("股票回购", 1, 2, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("share buyback", 1, 2, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("dividend", 0, 2, ["AAPL", "MSFT"], "stock"),
    ("Nasdaq", 0, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("S&P 500", 0, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("magnificent seven", 0, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("tech sell-off", -1, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("tech rally", 1, 3, ["TSLA", "NVDA", "AAPL", "MSFT"], "stock"),
    ("AI boom", 1, 3, ["NVDA", "MSFT", "SKHYNIX"], "stock"),
    ("AI bubble", -1, 3, ["NVDA", "MSFT"], "stock"),
]


def pre_filter_news(title: str, summary: str = "") -> dict:
    """
    关键词预筛选：判断新闻是否需要AI深度分析
    返回: {
        "need_ai": bool,           # 是否需要AI分析
        "matched_keywords": [],    # 命中的关键词
        "sentiment_hint": 0,       # 情绪倾向(-1/0/1)
        "impact_hint": 1,          # 影响级别(1-4)
        "symbols": [],             # 关联品种
        "category": "",            # 分类
    }
    """
    text = f"{title} {summary}".lower()
    if not text.strip():
        return {"need_ai": False, "matched_keywords": [], "sentiment_hint": 0, "impact_hint": 1, "symbols": [], "category": ""}

    matched = []
    sentiment_scores = []
    impact_levels = []
    symbols_set = set()
    categories = set()

    for kw, sentiment, impact, symbols, category in KEYWORD_LIBRARY:
        if kw.lower() in text:
            matched.append(kw)
            sentiment_scores.append(sentiment)
            impact_levels.append(impact)
            for s in symbols:
                symbols_set.add(s)
            categories.add(category)

    if not matched:
        return {"need_ai": False, "matched_keywords": [], "sentiment_hint": 0, "impact_hint": 1, "symbols": [], "category": ""}

    # 只有影响级别>=3的关键词命中才调AI
    max_impact = max(impact_levels) if impact_levels else 1
    need_ai = max_impact >= 3

    # 情绪倾向取平均
    avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
    sentiment_hint = 1 if avg_sentiment >= 0.3 else (-1 if avg_sentiment <= -0.3 else 0)

    return {
        "need_ai": need_ai,
        "matched_keywords": matched[:10],
        "sentiment_hint": sentiment_hint,
        "impact_hint": max_impact,
        "symbols": sorted(symbols_set),
        "category": list(categories)[0] if len(categories) == 1 else "mixed",
    }


def get_keyword_stats() -> dict:
    """获取关键词库统计信息"""
    categories = {}
    for _, _, impact, symbols, cat in KEYWORD_LIBRARY:
        if cat not in categories:
            categories[cat] = {"count": 0, "max_impact": 0, "symbols": set()}
        categories[cat]["count"] += 1
        categories[cat]["max_impact"] = max(categories[cat]["max_impact"], impact)
        for s in symbols:
            categories[cat]["symbols"].add(s)

    return {
        "total_keywords": len(KEYWORD_LIBRARY),
        "categories": {k: {"count": v["count"], "max_impact": v["max_impact"], "symbols": list(v["symbols"])}
                       for k, v in categories.items()},
    }
