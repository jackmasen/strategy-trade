"""
CryptoPanic WebSocket 实时新闻客户端
- 维持持久 WebSocket 连接，秒级接收突发新闻
- 新闻 → 情绪分析 → 关联品种 → 影响级别
- 高影响新闻 → 触发策略评分 → 方向相反 → 自动平仓
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import websockets

from backend.core.logging_config import logger
from backend.db.session import SessionLocal
from backend.news.analyzer import analyze as analyze_news, AnalysisResult
from backend.models.analytics import NewsArticle, RiskEventLog
from backend.models.strategy import StrategyConfig
from backend.models.trade import TradePosition
from backend.models.exchange import ExchangeAccount
from backend.strategy.engine import StrategyEngine

CRYPTOPANIC_SOURCE_CODE = 2  # 与 NewsArticle.SOURCE_NAME_MAP 一致


class CryptoPanicWSClient:
    _instance: Optional["CryptoPanicWSClient"] = None

    def __init__(self):
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._fallback_task: Optional[asyncio.Task] = None
        self._running = False
        self._token: str = ""
        self._auto_close: bool = True
        self._auto_trade: bool = True
        self._status: str = "disconnected"  # disconnected / connecting / connected / error / fallback
        self._last_news_at: Optional[str] = None
        self._news_count: int = 0
        self._auto_close_count: int = 0
        self._fallback_interval: int = 180  # RSS fallback 间隔（秒）
        self._engine = StrategyEngine()

    @classmethod
    def get_instance(cls) -> "CryptoPanicWSClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def status(self) -> Dict[str, Any]:
        mode = "rss_fallback"
        if self._status == "connected":
            mode = "websocket"
        elif self._status == "fallback":
            mode = "rss_fallback"
        return {
            "status": self._status,
            "news_source_mode": mode,
            "token_configured": bool(self._token),
            "running": self._running,
            "auto_close_enabled": self._auto_close,
            "auto_trade_enabled": self._auto_trade,
            "last_news_at": self._last_news_at,
            "news_count": self._news_count,
            "auto_close_count": self._auto_close_count,
            "fallback_interval_sec": self._fallback_interval,
        }

    def configure(self, token: str, auto_close: bool = True, auto_trade: bool = True):
        self._token = token
        self._auto_close = auto_close
        self._auto_trade = auto_trade

    async def test_connection(self, token: str) -> Dict[str, Any]:
        """测试 CryptoPanic WebSocket 连通性（不保持长连接）"""
        try:
            url = f"wss://socket.cryptopanic.com/api/v1/posts/?token={token}"
            async with websockets.connect(url, close_timeout=5) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(raw)
                title = data.get("title", "")[:80]
                return {
                    "success": True,
                    "message": f"连接成功，收到实时新闻: {title}",
                    "first_news": data,
                }
        except asyncio.TimeoutError:
            return {"success": True, "message": "连接成功（10秒内无新新闻推送，连接正常）"}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {type(e).__name__}: {e}"}

    async def start(self):
        if self._running:
            return {"success": False, "message": "已在运行中"}
        self._running = True
        if self._token:
            self._task = asyncio.create_task(self._run_loop())
            return {"success": True, "message": "WebSocket 客户端已启动，优先使用实时推送"}
        else:
            self._status = "fallback"
            self._fallback_task = asyncio.create_task(self._run_rss_fallback())
            return {"success": True, "message": "未配置Token，已启动RSS轮询模式（3分钟间隔）"}

    async def stop(self):
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._fallback_task and not self._fallback_task.done():
            self._fallback_task.cancel()
            try:
                await self._fallback_task
            except asyncio.CancelledError:
                pass
        self._status = "disconnected"
        return {"success": True, "message": "新闻服务已停止"}

    async def _run_loop(self):
        """主循环：连接 → 接收 → 断线重连"""
        url = f"wss://socket.cryptopanic.com/api/v1/posts/?token={self._token}"
        while self._running:
            try:
                self._status = "connecting"
                logger.info("[CryptoPanic] 正在连接 WebSocket...")
                async with websockets.connect(
                    url,
                    ping_interval=30,
                    ping_timeout=60,
                    close_timeout=10,
                    open_timeout=15,
                ) as ws:
                    self._ws = ws
                    self._status = "connected"
                    logger.info("[CryptoPanic] WebSocket 已连接，等待新闻推送...")
                    while self._running:
                        raw = await ws.recv()
                        try:
                            data = json.loads(raw)
                            await self._on_news(data)
                        except json.JSONDecodeError:
                            logger.warning(f"[CryptoPanic] 非JSON消息: {raw[:200]}")
                        except Exception as e:
                            logger.error(f"[CryptoPanic] 处理新闻异常: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._status = "error"
                logger.error(f"[CryptoPanic] 连接断开: {type(e).__name__}: {e}")
                if self._running:
                    logger.info("[CryptoPanic] 5秒后自动重连，同时启动RSS轮询兜底...")
                    self._status = "fallback"
                    if not self._fallback_task or self._fallback_task.done():
                        self._fallback_task = asyncio.create_task(self._run_rss_fallback())
                    await asyncio.sleep(5)

    async def _run_rss_fallback(self):
        """RSS 轮询兜底模式：WebSocket 不可用时自动采集新闻"""
        from backend.news.pipeline import NewsPipeline

        logger.info(f"[CryptoPanic] RSS 轮询兜底已启动，间隔 {self._fallback_interval}秒")
        while self._running and self._status != "connected":
            try:
                db = SessionLocal()
                pipeline = NewsPipeline(lookback_hours=6, max_workers=4)
                res = pipeline.run_once(db=db)
                if res.total_inserted > 0:
                    self._news_count += res.total_inserted
                    self._last_news_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"[CryptoPanic-RSS] 采集完成: 新增{res.total_inserted}条")

                    # 检查是否有高影响新闻需要触发平仓
                    if self._auto_close:
                        await self._check_recent_news(db)
                db.close()
            except Exception as e:
                logger.error(f"[CryptoPanic-RSS] 采集失败: {e}")

            # 等待下一轮
            for _ in range(self._fallback_interval):
                if not self._running or self._status == "connected":
                    break
                await asyncio.sleep(1)

    async def _check_recent_news(self, db):
        """检查最近5分钟的高影响新闻，触发自动平仓"""
        recent_news = db.query(NewsArticle).filter(
            NewsArticle.impact_level >= 3,
            NewsArticle.published_at >= datetime.now() - timedelta(minutes=5),
        ).all()

        for article in recent_news:
            if not article.related_symbols:
                continue
            try:
                result = AnalysisResult(
                    sentiment=article.sentiment or 0,
                    sentiment_score=article.sentiment_score or 0,
                    sentiment_keywords=article.sentiment_keywords or [],
                    related_symbols=article.related_symbols or [],
                    tags=article.tags or [],
                    impact_level=article.impact_level or 1,
                    is_hot=article.is_hot or False,
                )
                await self._check_and_close(db, article, result)
            except Exception as e:
                logger.warning(f"[CryptoPanic-RSS] 检查新闻失败: {e}")

    async def _on_news(self, data: dict):
        """处理单条 CryptoPanic 新闻"""
        title = data.get("title", "").strip()
        if not title:
            return

        source_info = data.get("source", {})
        source_name = source_info.get("name", "CryptoPanic")
        source_domain = source_info.get("domain", "")
        published_str = data.get("published_at", "")
        post_id = str(data.get("id", ""))
        slug = data.get("slug", "")
        currencies = data.get("currencies", [])
        kind = data.get("kind", "news")
        votes = data.get("votes", {})

        # 解析时间
        try:
            published_at = datetime.fromisoformat(
                published_str.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except Exception:
            published_at = datetime.now()

        # CryptoPanic currencies → 相关品种
        crypto_codes = [c.get("code", "").upper() for c in currencies if c.get("code")]

        # 调用新闻分析器
        result: AnalysisResult = analyze_news(
            title=title,
            summary="",
            category=kind,
            language="en",
            source_name=source_name,
            published_at=published_at,
        )

        # 补充 CryptoPanic 的币种关联
        code_map = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL"}
        for code in crypto_codes:
            mapped = code_map.get(code)
            if mapped and mapped not in result.related_symbols:
                result.related_symbols.append(mapped)

        # 写入数据库
        db = SessionLocal()
        try:
            existing = db.query(NewsArticle).filter(
                NewsArticle.source_code == CRYPTOPANIC_SOURCE_CODE,
                NewsArticle.source_id == post_id,
            ).first()
            if existing:
                return

            article = NewsArticle(
                source_code=CRYPTOPANIC_SOURCE_CODE,
                source_id=post_id,
                title=title,
                summary="",
                url=f"https://cryptopanic.com/news/{slug}/" if slug else "",
                source_name=source_name,
                source_domain=source_domain,
                published_at=published_at,
                language="en",
                category=kind,
                sentiment=result.sentiment,
                sentiment_score=result.sentiment_score,
                sentiment_keywords=result.sentiment_keywords,
                related_symbols=result.related_symbols,
                tags=result.tags + [f"cp:{source_domain}"] if source_domain else result.tags,
                impact_level=result.impact_level,
                is_hot=result.is_hot or bool(votes.get("positive", 0) > 5),
                crawled_at=datetime.now(),
            )
            db.add(article)
            db.commit()
            db.refresh(article)

            self._news_count += 1
            self._last_news_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            logger.info(
                f"[CryptoPanic] 新闻入库: [{source_name}] {title[:60]}... "
                f"品种={result.related_symbols} 情绪={result.sentiment} "
                f"影响={result.impact_level} 热点={result.is_hot}"
            )

            # 高影响 + 有关联品种 → 触发自动交易链路
            if result.impact_level >= 3 and result.related_symbols and self._auto_close:
                await self._check_and_close(db, article, result)
        except Exception as e:
            logger.error(f"[CryptoPanic] 新闻处理失败: {e}")
            db.rollback()
        finally:
            db.close()

    async def _check_and_close(self, db, article: NewsArticle, result: AnalysisResult):
        """高影响新闻 → 重新评分 → 方向相反 → 自动平仓"""
        for symbol in result.related_symbols:
            if symbol not in ("BTC", "ETH", "SOL"):
                continue

            # 查找该品种的活跃持仓
            positions = db.query(TradePosition).filter(
                TradePosition.symbol == symbol,
                TradePosition.status == 1,
            ).all()

            if not positions:
                continue

            # 查找一个活跃策略来评分
            strat = db.query(StrategyConfig).filter(
                StrategyConfig.is_active == True,
            ).first()

            if not strat:
                continue

            # 重新评分
            try:
                score_result, _ = self._engine.score_symbol(
                    db, strat, symbol, "1h", account_id=strat.exchange_id
                )
            except Exception as e:
                logger.warning(f"[CryptoPanic] {symbol} 重新评分失败: {e}")
                continue

            new_direction = score_result.direction  # 0=观望 1=多 2=空
            score_total = score_result.score_total

            logger.info(
                f"[CryptoPanic] {symbol} 重新评分: 方向={new_direction} "
                f"总分={score_total} (新闻情绪={result.sentiment})"
            )

            # 方向必须明确（非0）且与持仓方向相反
            if new_direction == 0:
                continue

            for pos in positions:
                pos_side = pos.side  # 1=多 2=空
                if new_direction != pos_side:
                    # 方向相反 → 自动平仓
                    await self._close_position(db, pos, article, result, score_result)
                    self._auto_close_count += 1

    async def _close_position(self, db, pos: TradePosition, article: NewsArticle,
                               result: AnalysisResult, score_result):
        """执行自动平仓 + 记录风控事件"""
        try:
            # 获取交易所客户端
            acc = db.query(ExchangeAccount).filter(
                ExchangeAccount.id == pos.exchange_account_id
            ).first()
            if not acc or acc.status != 1:
                logger.warning(f"[CryptoPanic] 持仓 {pos.id} 的交易所账号不可用")
                return

            from backend.exchanges.base import ExchangeClientBase
            client = ExchangeClientBase.create(
                exchange=acc.exchange,
                api_key=acc.api_key or "",
                api_secret=acc.api_secret or "",
                passphrase=acc.api_passphrase or "",
                testnet=bool(acc.testnet),
                exchange_account_id=acc.id,
            )
            client.connect()

            # 市价平仓
            close_side = 2 if pos.side == 1 else 1  # 反向
            client.place_order(
                symbol=pos.symbol,
                side=close_side,
                quantity=float(pos.quantity_contracts or 0),
                order_type="market",
                price=0,
                leverage=pos.leverage or 3,
            )

            # 更新持仓状态
            pos.status = 2
            pos.close_time = datetime.now()
            pos.close_reason = f"新闻止损: [{article.source_name}] {article.title[:80]}"
            pos.realized_pnl = float(pos.unrealized_pnl or 0)
            db.commit()

            # 记录风控事件
            log = RiskEventLog(
                user_id=pos.user_id,
                exchange_account_id=pos.exchange_account_id,
                strategy_id=pos.strategy_id,
                symbol=pos.symbol,
                event_type=RiskEventLog.TYPE_FORCE_CLOSE,
                severity=3,
                title=f"突发新闻自动止损: {pos.symbol}",
                detail=(
                    f"新闻: [{article.source_name}] {article.title[:200]}\n"
                    f"情绪: {'正面' if result.sentiment == 1 else '负面' if result.sentiment == -1 else '中性'} "
                    f"(score={result.sentiment_score}), 影响级别: {result.impact_level}\n"
                    f"重新评分: 总分={score_result.score_total}, 方向="
                    f"{'做多' if score_result.direction == 1 else '做空'}\n"
                    f"持仓方向: {'做多' if pos.side == 1 else '做空'} → 方向相反, 自动平仓"
                ),
                snapshot={
                    "news_id": article.id,
                    "news_title": article.title[:200],
                    "score_total": score_result.score_total,
                    "new_direction": score_result.direction,
                    "position_side": pos.side,
                    "position_id": pos.id,
                },
                action_taken=2,
                notified=False,
            )
            db.add(log)
            db.commit()

            logger.warning(
                f"[CryptoPanic] ⚡ 突发新闻止损: {pos.symbol} "
                f"持仓{pos.side} → 评分方向{score_result.direction} → 已平仓"
            )
        except Exception as e:
            logger.error(f"[CryptoPanic] 自动平仓失败 {pos.symbol}: {e}")
            db.rollback()
