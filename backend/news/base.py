"""
新闻采集基类
- RawNews：所有爬虫输出的统一中间结构
- NewsCrawlerBase：RSS / HTML / API 三种抓取方式的抽象 + 通用 HTTP 会话 + UA
- 每个具体爬虫只需实现 crawl(lookback_hours) -> List[RawNews]

反屏蔽策略：
  1. 随机 User-Agent 轮换（8 种主流浏览器 UA）
  2. 随机请求间隔（0.5-2.5s jitter，避免固定频率被检测）
  3. Referer 头自动填充（模拟从搜索引擎跳转）
  4. Accept-Encoding / Sec-Fetch 等完整浏览器头
  5. 403/429 自动退避（指数退避重试 1 次）

代理注入：
  _http_get 自动走 backend.core.proxy_manager.requests_get_with_proxy，
  403/429/ProxyError 自动切代理，最后兜底直连；
  200 但内容过短 / JSON 解析失败判为业务失败，不杀代理（避免代理池自激耗尽）。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

import requests

from backend.core.logging_config import logger
from backend.core.proxy_manager import requests_get_with_proxy


# 8 种主流浏览器 UA，每次请求随机选一个（避免单一 UA 被封）
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]


def _build_headers(url: str = "") -> dict:
    """构建带随机 UA + Referer 的完整浏览器请求头"""
    ua = random.choice(_USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    # 自动填充 Referer（模拟从 Google 搜索跳转，降低被屏蔽概率）
    if url:
        domain = urlparse(url).netloc
        if domain:
            headers["Referer"] = f"https://www.google.com/"
    return headers


@dataclass
class RawNews:
    """爬虫原始输出（落库前统一用这个结构）"""
    source_id: str                  # 在同一 source 内唯一（用于去重）
    source_name: str                # 显示名，如 "Reuters"
    title: str
    summary: str = ""
    content: str = ""
    url: str = ""
    image_url: str = ""
    author: str = ""
    published_at: Optional[datetime] = None   # 若 None，用当前时间
    category: str = "general"        # macro / regulation / onchain / energy / metals / crypto
    tags: List[str] = field(default_factory=list)
    language: str = "en"             # 英文媒体统一 en，金十 zh


class NewsCrawlerBase:
    """所有媒体爬虫的基类（含反屏蔽策略）"""

    # 子类覆盖：对应 NewsArticle.SOURCE_* 常量
    SOURCE_CODE: int = 99
    SOURCE_DISPLAY: str = "Generic"

    def __init__(self, timeout: int = 15, request_interval: float = 0.6):
        self.timeout = timeout
        self.request_interval = request_interval
        self._session = requests.Session()

    # ============= 子类必须实现 =============
    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        """抓取最近 lookback_hours 小时内的文章；返回按时间倒序的 RawNews 列表"""
        raise NotImplementedError

    def _jitter_sleep(self):
        """随机延迟 0.5-2.5s，避免固定频率被网站检测"""
        delay = random.uniform(0.5, 2.5)
        time.sleep(delay)

    # ============= 通用工具 =============
    def _http_get(self, url: str, params: Optional[dict] = None,
                  headers: Optional[dict] = None, as_json: bool = False):
        """
        统一 HTTP GET（含反屏蔽策略）：
          - 每次请求随机 UA + Referer + 完整浏览器头
          - 随机延迟 0.5-2.5s（替代固定 interval）
          - 自动走 ProxyManager，代理失败即切；最后兜底直连
          - HTTP 200 但内容过短 / JSON 解析失败 → 业务失败（不杀代理）
          - 始终返回 None（不抛异常），单源失败不影响其他源
        """
        merged_headers = _build_headers(url)
        if headers:
            merged_headers.update(headers)
        try:
            if as_json:
                result = requests_get_with_proxy(
                    url, params=params, headers=merged_headers,
                    timeout=self.timeout, as_json=True,
                    retries_if_business_empty=0, session=self._session,
                )
                self._jitter_sleep()
                if result is None:
                    logger.debug(f"[News/{self.SOURCE_DISPLAY}] JSON 请求失败 {url}")
                return result

            # 文本类：expect_nonempty_html=True 做内容长度校验（RSS 通常 >1KB）
            resp = requests_get_with_proxy(
                url, params=params, headers=merged_headers,
                timeout=self.timeout, as_json=False,
                expect_nonempty_html=True,
                retries_if_business_empty=1,
                session=self._session,
            )
            self._jitter_sleep()
            if resp is None:
                logger.debug(f"[News/{self.SOURCE_DISPLAY}] 请求失败（代理+直连都失败） {url}")
                return None
            try:
                return resp.text
            except Exception:
                return getattr(resp, "content", b"").decode("utf-8", "ignore")
        except Exception as e:
            logger.debug(f"[News/{self.SOURCE_DISPLAY}] 请求异常 {url}: {e}")
            return None

    @staticmethod
    def _truncate(s: str, n: int) -> str:
        if not s:
            return ""
        s = s.strip()
        return s if len(s) <= n else s[:n - 1] + "…"
