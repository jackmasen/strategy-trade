"""
媒体爬虫 3/3：宏观经济 / 能源官方数据源
- FREDCrawler：FRED（圣路易斯联储）发布的关键经济指标变动（CPI、PCE、非农、失业金、利率），
  这些数据一发布就直接影响 BTC / 黄金 / 原油（通过美联储加息预期）。
- EIAWeeklyCrawler：EIA Weekly Petroleum Status Report（每周三10:30 ET 发布），
  原油库存 + 汽油库存 + 原油产量，是 WTI 日内短线最关键的官方数据发布。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from backend.core.logging_config import logger
from backend.config import get_settings
from backend.models.analytics import NewsArticle
from ..base import NewsCrawlerBase, RawNews


class FREDCrawler(NewsCrawlerBase):
    """
    FRED 官方 API（免费，需 API_KEY，可在 .env 填 FRED_API_KEY；不填则退化到演示占位）。
    我们抓取 8 个最能影响金价/油价/币价的经济指标：
      DFF(联邦基金利率)、CPIAUCSL(CPI)、PCE(个人消费支出平减)、
      PAYEMS(非农就业)、UNRATE(失业率)、ICSA(周度首次失业金)、
      T10Y2Y(10Y-2Y 期限利差衰退预警)、DGS10(10Y 美债收益率)。
    """
    SOURCE_CODE = NewsArticle.SOURCE_FRED
    SOURCE_DISPLAY = "FRED"

    SERIES = [
        ("DFF",     "Federal Funds Effective Rate",             "macro", 4),  # impact_level 4：重大
        ("CPIAUCSL","Consumer Price Index(CPI)",                "macro", 4),
        ("PCEPI",   "PCE Price Index (Fed Favorite)",           "macro", 4),
        ("PAYEMS",  "Total Nonfarm Payrolls (NFP)",             "macro", 4),
        ("UNRATE",  "Unemployment Rate",                        "macro", 3),
        ("ICSA",    "Initial Jobless Claims (Weekly)",          "macro", 3),
        ("T10Y2Y",  "10Y-2Y Treasury Yield Spread",             "macro", 3),
        ("DGS10",   "10-Year Treasury Yield",                   "macro", 3),
    ]

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        out: List[RawNews] = []
        s = get_settings()
        api_key = getattr(s, "FRED_API_KEY", "") or ""
        cutoff = datetime.utcnow() - timedelta(hours=max(lookback_hours, 24*14))  # 宏观指标频率低，放宽到14天
        if not api_key:
            logger.info(f"[News/{self.SOURCE_DISPLAY}] 未配置 FRED_API_KEY，跳过（可在.env中添加）")
            return out

        for series_id, title_prefix, cat, impact in self.SERIES:
            # FRED observations: https://api.stlouisfed.org/fred/series/observations
            data = self._http_get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 3,
                },
                as_json=True,
            )
            if not data or "observations" not in data:
                continue
            obs = data["observations"]
            if not obs:
                continue
            # 取最新的 2 条（用来判断是否最新有发布）
            recent = [o for o in obs if o.get("value") not in (".", None, "")][:2]
            if not recent:
                continue
            latest = recent[0]
            try:
                date_str = latest["date"]  # "2024-05-31"
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                continue
            # FRED 指标是日/周/月发布日期格式，我们看最近有没有新的
            if dt < cutoff:
                continue
            try:
                val = float(latest["value"])
                prev = float(recent[1]["value"]) if len(recent) > 1 else val
            except Exception:
                continue
            delta = val - prev
            pct = (delta / prev * 100) if prev else 0.0
            direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            summary = (
                f"FRED {series_id}: {title_prefix} latest={val:.4f}, previous={prev:.4f}, "
                f"Δ={delta:+.4f} ({pct:+.2f}%) {direction}."
            )
            # 生成一条 NewsArticle，当作官方"新闻"
            sid = f"FRED-{series_id}-{date_str}"
            out.append(RawNews(
                source_id=sid,
                source_name=self.SOURCE_DISPLAY,
                title=f"{title_prefix}: {val:.4f} ({direction:+.4f})",
                summary=summary,
                content=summary,
                url=f"https://fred.stlouisfed.org/series/{series_id}",
                image_url="",
                author="FRED Federal Reserve Bank of St. Louis",
                published_at=dt,
                category=cat,
                tags=[cat, "fred", series_id, "official", "economic-indicator"],
            ))
            out[-1].tags.append("impact_level_4" if impact >= 4 else "impact_level_3")
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条官方经济指标")
        return out


class EIAWeeklyCrawler(NewsCrawlerBase):
    """
    EIA Weekly Petroleum Status Report：原油库存/WTI最重要的每周官方数据。
    EIA 提供免费公开 API，需注册 api_key（https://www.eia.gov/opendata/），
    未配置时降级到抓取 RSS。
    """
    SOURCE_CODE = NewsArticle.SOURCE_EIA
    SOURCE_DISPLAY = "EIA"

    def crawl(self, lookback_hours: int = 120) -> List[RawNews]:
        """
        默认放宽到 5 天(120h)：EIA 报告每周三一次；错过一次就看不到了。
        """
        out: List[RawNews] = []
        s = get_settings()
        api_key = getattr(s, "EIA_API_KEY", "") or ""
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)

        # 方式 A：EIA Weekly RSS（无 API key 也能用，库存摘要简讯）
        rss_url = "https://www.eia.gov/petroleum/supply/weekly/rss.php"
        xml = self._http_get(rss_url)
        if xml:
            try:
                from .coindesk import _parse_rss_feed, _parse_date  # 本地延迟引入
                items = _parse_rss_feed(xml, limit=20)
            except Exception:
                items = []
            for item in items:
                title = item["title"]
                link = item["link"]
                if not title:
                    continue
                import hashlib as _h
                sid = "EIA-RSS-" + _h.md5((title + link).encode("utf-8")).hexdigest()
                dt = _parse_date(item["pubDate"]) or datetime.utcnow()
                if dt < cutoff:
                    continue
                title_l = title.lower()
                cat = "energy"
                if any(k in title_l for k in ("crude", "inventory", "stock")):
                    tags = ["energy", "wti", "crude-inventory", "eia-report"]
                elif any(k in title_l for k in ("gasoline", "gas")):
                    tags = ["energy", "gasoline", "eia-report"]
                elif any(k in title_l for k in ("distillate", "diesel", "heating")):
                    tags = ["energy", "distillates", "eia-report"]
                else:
                    tags = ["energy", "eia-report"]
                out.append(RawNews(
                    source_id=sid,
                    source_name=self.SOURCE_DISPLAY,
                    title=title[:300],
                    summary=self._truncate(item["description"], 800),
                    content=self._truncate(item["content"], 4000),
                    url=link,
                    image_url=item.get("image", ""),
                    author="EIA U.S. Energy Information Administration",
                    published_at=dt,
                    category=cat,
                    tags=tags,
                ))

        # 方式 B：若配置了 EIA_API_KEY，再拉库存精确数字（生成 2-3 条结构化"数据新闻"）
        if api_key:
            self._append_eia_structured(api_key, cutoff, out)

        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条 EIA 报告")
        return out

    # ---------- 结构化数据 ----------
    def _append_eia_structured(self, api_key: str, cutoff: datetime, out: List[RawNews]) -> None:
        facets = {
            "PET.WCESTUS1.W":   ("Crude Oil Inventories (excl SPR)",  "WTI库存(不含战略储备)", "wti"),
            "PET.WGFSTUS1.W":   ("Gasoline Inventories",             "汽油库存", "gasoline"),
            "PET.WDISTUS1.W":   ("Distillate Fuel Inventories",      "馏分油库存", "distillates"),
            "PET.WCRFPUS2.W":   ("Crude Oil Field Production",       "美国周度原油产量", "production"),
            "PET.WCRSTUS1.W":   ("Weekly U.S. Ending Stocks Excl SPR","美国原油总库存", "wti"),
        }
        import hashlib as _h
        for facet, (title_en, title_cn, tag) in facets.items():
            data = self._http_get(
                "https://api.eia.gov/v2/petroleum/stoc/wstk/data",
                params={
                    "api_key": api_key,
                    "frequency": "weekly",
                    "data[0]": "value",
                    "facets[series][]": facet,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "length": 3,
                    "offset": 0,
                },
                as_json=True,
            )
            if not data:
                continue
            try:
                rows = (data.get("response") or {}).get("data") or []
            except Exception:
                rows = []
            rows = [r for r in rows if r.get("value") not in (None, "")][:2]
            if len(rows) < 1:
                continue
            r1 = rows[0]
            period = r1.get("period")  # "2024-06-07"
            try:
                dt = datetime.strptime(period, "%Y-%m-%d")
            except Exception:
                continue
            if dt < cutoff:
                continue
            try:
                v1 = float(r1.get("value") or 0)
                v0 = float(rows[1].get("value") or v1) if len(rows) > 1 else v1
            except Exception:
                continue
            delta = v1 - v0
            unit = r1.get("units") or "thousand bbl"
            summary = (
                f"EIA Weekly: {title_en} period={period}, current={v1:.0f} {unit}, "
                f"previous={v0:.0f} {unit}, change={delta:+.0f} {unit}. "
                f"Data source: EIA v2 petroleum/stoc/wstk, facet {facet}."
            )
            sid = f"EIA-{facet}-{period}"
            out.append(RawNews(
                source_id=sid,
                source_name=self.SOURCE_DISPLAY,
                title=f"{title_en}: {v1:.0f} ({delta:+.0f} {unit})",
                summary=summary,
                content=summary,
                url="https://www.eia.gov/petroleum/supply/weekly/",
                image_url="",
                author="EIA U.S. Energy Information Administration",
                published_at=dt,
                category="energy",
                tags=["energy", "eia-structured", "official", tag],
            ))
