"""
定时任务 - Celery Beat 调度
对应 backend.core.celery_app.beat_schedule 中定义的任务

本文件依赖 DB session (通过 backend.db.session)，因为 Celery worker 是独立进程，
不通过依赖注入拿 DB。
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List

from celery import current_app as celery
from sqlalchemy import func

from backend.core.logging_config import logger
from backend.db.session import session_maker  # sync session factory
from backend.models.strategy import StrategyConfig, ScoreRecord
from backend.models.trade import TradeOrder, TradePosition
from backend.models.exchange import ExchangeAccount
from backend.models.user import User
from backend.models.analytics import DailyFinancialReport, RiskEventLog
from backend.strategy.engine import StrategyEngine
from backend.strategy.scoring import StrategyScoringEngine
from backend.exchanges.market import MarketManager
from backend.core.distributed_lock import acquire_lock, release_lock


# ==========================================================================
# Task 1: 综合评分更新（1h 一次，也可每小时K线收盘后触发）
# ==========================================================================
@celery.task(name="backend.tasks.scheduled.update_all_scores", bind=True)
def update_all_scores(self):
    """
    全量刷新所有「启用」的策略的 品种×周期 综合评分；
    若策略模式 = AUTO 且 评分≥阈值 → 自动下单
    """
    # 全局锁：防止多 Worker 同时执行定时评分任务
    lock_key = "scheduled:update_all_scores"
    lock_token = __import__("uuid").uuid4().hex
    if not acquire_lock(lock_key, expire_seconds=300, token=lock_token):
        logger.info("[Scheduled] update_all_scores 已被其他 Worker 锁定，跳过")
        return {"status": "skipped", "reason": "another worker is running"}

    logger.info("[Scheduled] 开始刷新策略评分...")
    engine = StrategyEngine()
    updated = 0
    triggered_total = []
    errors_total = []
    try:
        with session_maker() as db:
            active_strategies = (
                db.query(StrategyConfig).filter(StrategyConfig.is_active == 1).all()
            )
            for st in active_strategies:
                try:
                    res = engine.run_strategy(db, st.id, execute_trade=True)
                    updated += res.get("scored", 0)
                    triggered_total.extend(res.get("triggered", []))
                    errors_total.extend(res.get("errors", []))
                except Exception as e:
                    logger.exception(f"策略 {st.id} 评分失败: {e}")
                    errors_total.append(f"策略 {st.id or st.strategy_name}: {e}")
    finally:
        release_lock(lock_key, lock_token)
    logger.info(
        f"[Scheduled] 评分刷新完成，更新 {updated} 条，触发 {len(triggered_total)} 个信号，"
        f"错误 {len(errors_total)} 条"
    )
    return {
        "status": "ok",
        "updated": updated,
        "triggered": triggered_total[:100],
        "errors": errors_total[:100],
    }


# ==========================================================================
# Task 2: 风控巡检（每30s一次）
#   - 检查每个持仓的 单笔最大回撤、TP/SL、日亏损限额、冷静期
#   - 若触发：交易所侧平仓 + 写 TradePosition / RiskEventLog
# ==========================================================================
@celery.task(name="backend.tasks.scheduled.risk_monitor", bind=True)
def risk_monitor(self):
    # 全局锁：防止多 Worker 同时执行风控巡检，避免重复平仓
    lock_key = "scheduled:risk_monitor"
    lock_token = __import__("uuid").uuid4().hex
    if not acquire_lock(lock_key, expire_seconds=60, token=lock_token):
        logger.debug("[Scheduled] risk_monitor 已被其他 Worker 锁定，跳过")
        return {"status": "skipped", "reason": "another worker is running"}

    logger.debug("[Scheduled] 风控巡检...")
    checked = 0
    closed = 0
    close_details = []
    from collections import defaultdict
    from backend.exchanges.base import ExchangeClientBase

    try:
        with session_maker() as db:
            open_positions = (
                db.query(TradePosition).filter(TradePosition.status == 1).all()
            )  # status=99（处理中）的持仓会被跳过，防止重复平仓
            # Group positions by exchange account to reuse a single client per account
            positions_by_account = defaultdict(list)
            for pos in open_positions:
                positions_by_account[pos.exchange_account_id].append(pos)

            for acc_id, positions in positions_by_account.items():
                acc = db.query(ExchangeAccount).filter(
                    ExchangeAccount.id == acc_id
                ).first()
                if not acc or acc.status != 1:
                    continue
                # Build client once per account (not per position)
                client = None
                try:
                    client = ExchangeClientBase.create(
                        exchange=acc.exchange,
                        api_key=acc.api_key or "",
                        api_secret=acc.api_secret or "",
                        passphrase=acc.api_passphrase or "",
                        testnet=bool(acc.testnet),
                        exchange_account_id=acc.id,
                    )
                    client.connect()
                    mm = MarketManager.get_instance()
                    mm.register_client(client)
                except Exception:
                    client = None

                try:
                    for pos in positions:
                        checked += 1
                        # 1) 刷新最新行情（内存 + 交易所REST 回退）
                        mm = MarketManager.get_instance()
                        mark_price = None
                        t = mm.get_ticker(pos.symbol)
                        if t:
                            mark_price = t.last_price
                        if not mark_price and client:
                            try:
                                ticker = client.fetch_ticker(pos.symbol)
                                mark_price = ticker.last_price
                                mm.on_ws_ticker(ticker)
                            except Exception:
                                mark_price = float(pos.mark_price or 0)
                        if not mark_price:
                            mark_price = float(pos.mark_price or 0)
                        if not mark_price or mark_price <= 0:
                            continue
                        # 2) 计算当前浮盈浮亏%
                        entry = float(pos.entry_price or 0)
                        if entry <= 0:
                            continue
                        if pos.side == 1:  # 多
                            cur_pnl_pct = (mark_price - entry) / entry * 100 * pos.leverage
                        else:
                            cur_pnl_pct = (entry - mark_price) / entry * 100 * pos.leverage
                        pos.mark_price = Decimal(str(mark_price))
                        pos.unrealized_pnl = Decimal(str(
                            (mark_price - entry) * float(pos.quantity_contracts) * (1 if pos.side == 1 else -1)
                        ))
                        pos.pnl_ratio = float(cur_pnl_pct)
                        # 记录最大回撤
                        if cur_pnl_pct < 0:
                            pos.max_drawdown_ratio = max(
                                float(pos.max_drawdown_ratio or 0),
                                abs(cur_pnl_pct),
                            )

                        # 2.5) Trailing Stop 移动止损
                        if pos.trailing_enabled == 1:
                            activation = float(pos.trailing_activation_pct or 1.0)
                            distance = float(pos.trailing_distance_pct or 0.5)
                            trailing_extreme = float(pos.trailing_high_price or 0)

                            if pos.side == 1:  # 多
                                if mark_price > trailing_extreme:
                                    pos.trailing_high_price = Decimal(str(mark_price))
                                    trailing_extreme = mark_price
                                if trailing_extreme > entry:
                                    profit_pct = (trailing_extreme - entry) / entry * 100
                                    if profit_pct >= activation:
                                        new_sl = trailing_extreme * (1 - distance / 100)
                                        current_sl = float(pos.sl_price or 0)
                                        if new_sl > current_sl:
                                            pos.sl_price = Decimal(str(round(new_sl, 8)))
                                            logger.debug(
                                                f"[Trailing] pos={pos.id} {pos.symbol} LONG "
                                                f"SL上移 {current_sl:.4f} → {new_sl:.4f} "
                                                f"(extreme={trailing_extreme:.4f})"
                                            )
                            else:  # 空
                                if trailing_extreme == 0 or mark_price < trailing_extreme:
                                    pos.trailing_high_price = Decimal(str(mark_price))
                                    trailing_extreme = mark_price
                                if trailing_extreme > 0 and trailing_extreme < entry:
                                    profit_pct = (entry - trailing_extreme) / entry * 100
                                    if profit_pct >= activation:
                                        new_sl = trailing_extreme * (1 + distance / 100)
                                        current_sl = float(pos.sl_price or 0)
                                        if current_sl == 0 or new_sl < current_sl:
                                            pos.sl_price = Decimal(str(round(new_sl, 8)))
                                            logger.debug(
                                                f"[Trailing] pos={pos.id} {pos.symbol} SHORT "
                                                f"SL下移 {current_sl:.4f} → {new_sl:.4f} "
                                                f"(extreme={trailing_extreme:.4f})"
                                            )

                        # 3) TP / SL
                        sl_hit = False
                        tp_hit = False
                        tp_price = float(pos.tp_price or 0)
                        sl_price = float(pos.sl_price or 0)
                        if pos.side == 1:
                            if tp_price > 0 and mark_price >= tp_price:
                                tp_hit = True
                            if sl_price > 0 and mark_price <= sl_price:
                                sl_hit = True
                        else:
                            if tp_price > 0 and mark_price <= tp_price:
                                tp_hit = True
                            if sl_price > 0 and mark_price >= sl_price:
                                sl_hit = True

                        strategy = db.query(StrategyConfig).filter(
                            StrategyConfig.id == pos.strategy_id
                        ).first() if pos.strategy_id else None
                        max_drawdown_limit = float(strategy.max_single_drawdown or 2) if strategy else 2.0
                        drawdown_hit = (cur_pnl_pct < 0) and (abs(cur_pnl_pct) >= max_drawdown_limit)

                        # 日亏损限额检查（用户维度）
                        user = db.query(User).filter(User.id == pos.user_id).first()
                        daily_limit_hit = False
                        if user and strategy:
                            today_start = datetime.combine(date.today(), datetime.min.time())
                            today_pnl = db.query(func.coalesce(func.sum(TradePosition.realized_pnl), 0)).filter(
                                TradePosition.exchange_account_id == pos.exchange_account_id,
                                TradePosition.status == 2,
                                TradePosition.close_time >= today_start,
                            ).scalar() or 0
                            if float(acc.current_balance or 0) > 0:
                                loss_pct = (-float(today_pnl) / float(acc.current_balance)) * 100
                                if loss_pct >= float(strategy.daily_max_loss or 5):
                                    daily_limit_hit = True

                        if tp_hit or sl_hit or drawdown_hit or daily_limit_hit:
                            try:
                                result = _close_position_for_risk(db, pos, acc, mark_price,
                                    tp_hit=tp_hit, sl_hit=sl_hit,
                                    drawdown_hit=drawdown_hit, daily_limit_hit=daily_limit_hit,
                                    strategy=strategy, client=client,
                                )
                                if result is False:
                                    continue
                                closed += 1
                                close_details.append({
                                    "pos_id": pos.id,
                                    "symbol": pos.symbol,
                                    "reason": {
                                        "tp": tp_hit, "sl": sl_hit,
                                        "drawdown": drawdown_hit, "daily_limit": daily_limit_hit,
                                    },
                                    "close_price": mark_price,
                                })
                            except Exception as e:
                                logger.exception(f"风控平仓失败 pos_id={pos.id}: {e}")
                                db.rollback()  # Clear any pending rollback state
                        else:
                            try:
                                db.commit()
                            except Exception:
                                db.rollback()
                            continue
                finally:
                    if client:
                        try:
                            client.close()
                        except Exception:
                            pass
    finally:
        release_lock(lock_key, lock_token)
    logger.info(f"[Scheduled] 风控巡检完成，检查 {checked} 个持仓，平仓 {closed} 个")
    return {"status": "ok", "checked": checked, "closed": closed, "details": close_details}


def _close_position_for_risk(
    db, pos: TradePosition, acc: ExchangeAccount, close_price: float,
    *, tp_hit: bool, sl_hit: bool, drawdown_hit: bool, daily_limit_hit: bool,
    strategy, client=None,
):
    from backend.exchanges.base import ExchangeClientBase
    from backend.exchanges._types import ORDER_TYPE_MARKET, SIDE_LONG, SIDE_SHORT
    _close_client = False
    if client is None:
        client = ExchangeClientBase.create(
            exchange=acc.exchange,
            api_key=acc.api_key or "",
            api_secret=acc.api_secret or "",
            passphrase=acc.api_passphrase or "",
            testnet=bool(acc.testnet),
            exchange_account_id=acc.id,
        )
        client.connect()
        _close_client = True
    try:
        client.cancel_all_open_orders(pos.symbol)
    except Exception:
        pass

    # 反向市价平仓
    close_side = SIDE_SHORT if pos.side == SIDE_LONG else SIDE_LONG
    close_success = False
    try:
        client.place_order(
            symbol=pos.symbol, side=close_side,
            order_type=ORDER_TYPE_MARKET,
            quantity=float(pos.quantity_contracts),
            leverage=pos.leverage,
            client_order_id=f"risk_{pos.id}_{datetime.now().strftime('%H%M%S')}",
        )
        close_success = True
    except Exception as e:
        logger.error(f"风险平仓交易所API失败(position_id={pos.id}): {e} — 跳过DB标记,下轮重试")
        if _close_client:
            try:
                client.close()
            except Exception:
                pass
        return False  # Don't mark as closed

    if close_success:
        # 更新仓位
        pos.status = 2
        pos.close_time = datetime.now()
        pos.close_price = Decimal(str(close_price))
        entry = float(pos.entry_price or 0)
        qty = float(pos.quantity_contracts or 0)
        if pos.side == 1:
            realized = (close_price - entry) * qty
        else:
            realized = (entry - close_price) * qty
        pos.realized_pnl = Decimal(str(realized))
        margin_used = float(pos.margin_used) or 1e-9
        pos.pnl_ratio = realized / margin_used * 100 if margin_used > 0 else 0
        if pos.entry_time:
            pos.holding_minutes = int((pos.close_time - pos.entry_time).total_seconds() // 60)
        # 平仓原因
        if tp_hit:
            reason = "tp"
            pos.close_reason = 3
        elif sl_hit:
            reason = "sl"
            pos.close_reason = 4
        elif drawdown_hit:
            reason = "drawdown"
            pos.close_reason = 5
        elif daily_limit_hit:
            reason = "daily_limit"
            pos.close_reason = 6
        else:
            reason = "risk"
            pos.close_reason = 8

        # 写风控事件
        severity = 1
        if sl_hit or drawdown_hit or daily_limit_hit:
            severity = 3
        elif tp_hit:
            severity = 1
        log = RiskEventLog(
            user_id=pos.user_id,
            exchange_account_id=pos.exchange_account_id,
            strategy_id=pos.strategy_id,
            symbol=pos.symbol,
            position_id=pos.id,
            event_type={
                "tp": RiskEventLog.TYPE_FORCE_CLOSE,
                "sl": RiskEventLog.TYPE_FORCE_CLOSE,
                "drawdown": RiskEventLog.TYPE_SINGLE_DRAWDOWN,
                "daily_limit": RiskEventLog.TYPE_DAILY_LOSS,
            }.get(reason, RiskEventLog.TYPE_FORCE_CLOSE),
            severity=severity,
            title=f"风控触发 - {pos.symbol} {reason.upper()}",
            detail=(
                f"持仓 {pos.id} 在 {close_price:.4f} 因 {reason} 平仓。"
                f"盈亏 {realized:.4f} USDT ({pos.pnl_ratio:.2f}%)，"
                f"entry={entry:.4f} 杠杆 {pos.leverage}x"
            ),
            snapshot={
                "close_price": close_price,
                "entry": entry,
                "qty": qty,
                "leverage": pos.leverage,
                "realized": realized,
                "pnl_ratio": pos.pnl_ratio,
            },
            action_taken=2,  # 已平仓
            notified=False,
        )
        db.add(log)
        try:
            db.commit()
        except Exception as e:
            logger.critical(f"风险平仓DB提交失败(position_id={pos.id}): {e}")
            db.rollback()
    if _close_client:
        try:
            client.close()
        except Exception:
            pass


# ==========================================================================
# Task 3: 新闻采集 + 情绪分析入库（每 15min 一次）
#   - 多源：CoinDesk/CoinTelegraph(币) + Reuters/Bloomberg/CNBC/OilPrice(宏观能源金)
#   - 官方数据：FRED（联储/NFP/CPI 等）、EIA Weekly Petroleum
#   - VADER 情绪打分 → related_symbols 关联 BTC/ETH/SOL/XAU/WTI → impact_level 级别
# ==========================================================================
@celery.task(name="backend.tasks.scheduled.crawl_news", bind=True)
def crawl_news(self, lookback_hours: int = 48):
    """
    生产环境真实新闻管道：
      1) NewsPipeline 并发抓取所有源
      2) analyzer.analyze() 做情绪 + 品种关联 + 影响级别
      3) 批量写入 NewsArticle

    参数 lookback_hours 控制每个源的回溯时长（默认48h，用于首次/补漏）；
    每 15min 增量执行时，数据库 (source, source_id) 联合唯一已经天然去重。
    """
    logger.info("[Scheduled] 新闻采集（多源国际媒体 + VADER 情绪）...")
    try:
        from backend.news.pipeline import NewsPipeline
    except Exception as e:
        logger.warning(f"[Scheduled] NewsPipeline 导入失败: {e}，退化为 demo 新闻初始化。")
        return _seed_demo_news_if_empty()

    with session_maker() as db:
        try:
            pipeline = NewsPipeline(lookback_hours=int(lookback_hours), max_workers=4)
            res = pipeline.run_once(db=db)
        except Exception as e:
            logger.exception(f"[Scheduled] NewsPipeline 运行异常: {e}")
            db.rollback()
            return {"status": "error", "error": str(e)}
        payload = {
            "fetched": res.total_fetched,
            "inserted": res.total_inserted,
            "skipped_dup": res.total_skipped_dup,
            "per_source": res.per_source,
        }
        if res.errors:
            payload["errors"] = res.errors[-20:]
        logger.info(
            f"[Scheduled] 新闻采集完成，抓取={payload['fetched']} "
            f"新增={payload['inserted']} 跳过重复={payload['skipped_dup']}"
        )
        # 首次空库兜底：如果 pipeline 因为没装 RSS/网络，抓取结果为 0，就塞 demo 新闻
        if payload["fetched"] == 0 and payload["inserted"] == 0:
            _seed_demo_news_if_empty(db=db)
        return {"status": "ok", **payload}


def _seed_demo_news_if_empty(db=None):
    """空库兜底：db 没新闻就塞 demo（老的 crawl_news 逻辑迁移到这里）"""
    from backend.models.analytics import NewsArticle
    _close = False
    if db is None:
        db = session_maker()
        _close = True
    try:
        cnt = db.query(func.count()).select_from(NewsArticle).scalar() or 0
        if cnt > 0:
            return {"status": "skip", "reason": f"已存在 {cnt} 条新闻"}
        now = datetime.now()
        demo = [
            NewsArticle(
                source=NewsArticle.SOURCE_FRED, source_id="demo-1", source_name="FRED",
                title="Federal Reserve hints pause rate hikes, BTC rebounds past 70000 USD",
                summary="Market risk appetite strengthened; BTC spot ETF saw net capital inflows.",
                category="macro", tags=["Fed", "rate", "ETF", "macro"],
                related_symbols=["BTC", "ETH", "SOL", "XAU", "WTI"],
                sentiment=1, sentiment_score=0.65, impact_level=4, is_hot=True,
                published_at=now - timedelta(hours=2), analyzed_at=now,
            ),
            NewsArticle(
                source=NewsArticle.SOURCE_BLOOMBERG, source_id="demo-2", source_name="Bloomberg",
                title="OKX launches SOL Perpetual with improved liquidity",
                summary="OKX announced SOL-USDT perpetual contract, deeper order book.",
                category="crypto", tags=["OKX", "SOL"],
                related_symbols=["SOL"],
                sentiment=1, sentiment_score=0.35, impact_level=2, is_hot=False,
                published_at=now - timedelta(hours=4), analyzed_at=now,
            ),
            NewsArticle(
                source=NewsArticle.SOURCE_REUTERS, source_id="demo-3", source_name="Reuters",
                title="SEC delays decision on BTC spot ETF applications",
                summary="Regulatory uncertainty weighs on short-term crypto sentiment.",
                category="regulation", tags=["SEC", "ETF", "regulation"],
                related_symbols=["BTC", "ETH", "SOL"],
                sentiment=-1, sentiment_score=-0.5, impact_level=3, is_hot=True,
                published_at=now - timedelta(hours=6), analyzed_at=now,
            ),
            NewsArticle(
                source=NewsArticle.SOURCE_EIA, source_id="demo-4", source_name="EIA",
                title="OPEC+ cuts push WTI crude toward 85 USD/bbl, gold rallies",
                summary="Geopolitical risk + production cuts supported both oil and safe-haven gold.",
                category="energy", tags=["OPEC", "oil", "gold", "energy"],
                related_symbols=["WTI", "XAU"],
                sentiment=1, sentiment_score=0.7, impact_level=4, is_hot=True,
                published_at=now - timedelta(hours=1), analyzed_at=now,
            ),
        ]
        db.add_all(demo)
        db.commit()
        return {"status": "seeded", "inserted": len(demo)}
    finally:
        if _close:
            db.close()


# ==========================================================================
# Task 4: 生成每日财务报表（凌晨 00:05 执行）
# ==========================================================================
@celery.task(name="backend.tasks.scheduled.generate_daily_report", bind=True)
def generate_daily_report(self):
    logger.info("[Scheduled] 生成每日财务报表...")
    report_date = (date.today() - timedelta(days=0)).isoformat()  # 当天报表(收盘后的)
    reports_written = 0
    with session_maker() as db:
        users = db.query(User).all()
        for u in users:
            # 1) 按子账号 + 一条汇总行 (exchange_account_id=None) 共写 N+1 条
            accs = db.query(ExchangeAccount).filter(ExchangeAccount.user_id == u.id).all()
            rows = [(a.id) for a in accs] + [None]
            for acc_id in rows:
                _build_daily_report(db, u.id, acc_id, report_date)
                reports_written += 1
    return {"status": "ok", "date": report_date, "reports": reports_written}


def _build_daily_report(db, user_id: int, acc_id, report_date: str):
    """构建单条日报（幂等：若同日已存在就 UPDATE）"""
    from backend.models.analytics import DailyFinancialReport as R
    day_start = datetime.combine(date.fromisoformat(report_date), datetime.min.time())
    day_end = day_start + timedelta(days=1)

    pos_q = db.query(TradePosition).filter(TradePosition.user_id == user_id)
    order_q = db.query(TradeOrder).filter(TradeOrder.user_id == user_id)
    acc_q = db.query(ExchangeAccount).filter(ExchangeAccount.user_id == user_id)
    if acc_id is not None:
        pos_q = pos_q.filter(TradePosition.exchange_account_id == acc_id)
        order_q = order_q.filter(TradeOrder.exchange_account_id == acc_id)
        acc_q = acc_q.filter(ExchangeAccount.id == acc_id)

    # 日内平仓的
    closed_today = pos_q.filter(
        TradePosition.status == 2,
        TradePosition.close_time >= day_start,
        TradePosition.close_time < day_end,
    ).all()
    # 日内任意时间开的持仓中 (用于 max position count)
    open_at_dayend = pos_q.filter(TradePosition.status == 1).all()

    start_balance = 0.0
    end_balance = 0.0
    for a in acc_q.all():
        start_balance += float(a.initial_balance or 0)
        end_balance += float(a.current_balance or 0)

    realized = sum(float(p.realized_pnl or 0) for p in closed_today)
    unrealized = sum(float(p.unrealized_pnl or 0) for p in open_at_dayend)
    total_pnl = realized + unrealized
    trade_count = len(closed_today)
    order_count = order_q.filter(
        TradeOrder.created_at >= day_start, TradeOrder.created_at < day_end
    ).count()
    long_count = sum(1 for p in closed_today if p.side == 1)
    short_count = trade_count - long_count
    wins = sum(1 for p in closed_today if float(p.realized_pnl or 0) > 0)
    losses = sum(1 for p in closed_today if float(p.realized_pnl or 0) < 0)
    win_rate = round(wins / trade_count * 100, 2) if trade_count > 0 else 0
    wins_total = sum(float(p.realized_pnl) for p in closed_today if float(p.realized_pnl or 0) > 0)
    losses_total = abs(sum(float(p.realized_pnl) for p in closed_today if float(p.realized_pnl or 0) < 0))
    profit_factor = round(wins_total / losses_total, 3) if losses_total > 0 else 0

    pnl_pcts = [float(p.pnl_ratio or 0) for p in closed_today]
    max_single_win_pct = max(pnl_pcts) if pnl_pcts else 0.0
    max_single_loss_pct = abs(min(pnl_pcts)) if pnl_pcts else 0.0
    holding_mins = [
        ((p.close_time - p.entry_time).total_seconds() // 60)
        for p in closed_today if p.close_time and p.entry_time
    ]
    avg_holding = int(sum(holding_mins) / len(holding_mins)) if holding_mins else 0

    risk_cnt = db.query(RiskEventLog).filter(
        RiskEventLog.user_id == user_id,
        RiskEventLog.created_at >= day_start,
        RiskEventLog.created_at < day_end,
        *((RiskEventLog.exchange_account_id == acc_id,) if acc_id else ()),
    ).count() if True else 0

    # 分品种汇总
    per_sym = {}
    for p in closed_today:
        s = p.symbol
        if s not in per_sym:
            per_sym[s] = {"count": 0, "win": 0, "loss": 0, "pnl": 0.0, "pnl_pct_avg": 0.0,
                          "wins_sum_pct": 0.0, "losses_sum_pct": 0.0}
        per_sym[s]["count"] += 1
        rl = float(p.realized_pnl or 0)
        per_sym[s]["pnl"] += rl
        rt = float(p.pnl_ratio or 0)
        if rl > 0:
            per_sym[s]["win"] += 1
            per_sym[s]["wins_sum_pct"] += rt
        else:
            per_sym[s]["loss"] += 1
            per_sym[s]["losses_sum_pct"] += rt
    for s in per_sym:
        v = per_sym[s]
        total = v["win"] + v["loss"]
        if total > 0:
            v["pnl_pct_avg"] = (v["wins_sum_pct"] + v["losses_sum_pct"]) / total
        v.pop("wins_sum_pct", None); v.pop("losses_sum_pct", None)

    total_pnl_pct = (total_pnl / start_balance * 100) if start_balance > 0 else 0.0

    # 幂等写入：先查后写
    obj = db.query(R).filter(
        R.user_id == user_id,
        R.exchange_account_id == acc_id,
        R.report_date == report_date,
    ).first()
    if not obj:
        obj = R(user_id=user_id, exchange_account_id=acc_id, report_date=report_date)
        db.add(obj)
    obj.start_balance = Decimal(str(start_balance))
    obj.end_balance = Decimal(str(end_balance))
    obj.realized_pnl = Decimal(str(realized))
    obj.unrealized_pnl = Decimal(str(unrealized))
    obj.total_pnl = Decimal(str(total_pnl))
    obj.total_pnl_pct = round(total_pnl_pct, 4)
    obj.trade_count = trade_count
    obj.order_count = order_count
    obj.long_count = long_count
    obj.short_count = short_count
    obj.win_count = wins
    obj.loss_count = losses
    obj.win_rate = win_rate
    obj.profit_factor = profit_factor
    obj.avg_holding_minutes = avg_holding
    obj.max_position_count = len(open_at_dayend)
    obj.max_drawdown_daily = round(max_single_loss_pct, 3)
    obj.max_single_win_pct = round(max_single_win_pct, 3)
    obj.max_single_loss_pct = round(max_single_loss_pct, 3)
    obj.risk_event_count = risk_cnt
    obj.per_symbol_summary = per_sym
    db.commit()


# ==========================================================================
# Task 5: 数据清理（每天 3:00 执行）
#   - 清理30天前的新闻、90天前的AI分析记录、180天前的评分记录
# ==========================================================================
@celery.task(name="backend.tasks.scheduled.data_cleanup", bind=True)
def data_cleanup(self):
    """清理过期数据，保持数据库体积合理"""
    from sqlalchemy import delete
    from backend.models.analytics import NewsArticle, AIAnalysisRecord, ScoreRecord as ARScoreRecord
    from backend.models.strategy import ScoreRecord

    logger.info("[Scheduled] 开始数据清理...")
    cleaned = {}

    try:
        with session_maker() as db:
            now = datetime.utcnow()

            # 30天前的新闻（保留高影响级别的）
            cutoff_news = now - timedelta(days=30)
            news_del = db.query(NewsArticle).filter(
                NewsArticle.published_at < cutoff_news,
                NewsArticle.impact_level < 3,
            ).delete(synchronize_session=False)
            cleaned["news_30d"] = news_del

            # 90天前的新闻（全量清理）
            cutoff_news_all = now - timedelta(days=90)
            news_all_del = db.query(NewsArticle).filter(
                NewsArticle.published_at < cutoff_news_all,
            ).delete(synchronize_session=False)
            cleaned["news_90d"] = news_all_del

            # 180天前的AI分析记录
            cutoff_ai = now - timedelta(days=180)
            ai_del = db.query(AIAnalysisRecord).filter(
                AIAnalysisRecord.created_at < cutoff_ai,
            ).delete(synchronize_session=False)
            cleaned["ai_records_180d"] = ai_del

            # 180天前的评分记录
            score_del = db.query(ScoreRecord).filter(
                ScoreRecord.created_at < cutoff_ai,
            ).delete(synchronize_session=False)
            cleaned["score_records_180d"] = score_del

            # 超时订单清理（24小时前的Pending订单）
            cutoff_order = now - timedelta(hours=24)
            from backend.models.trade import TradeOrder
            order_del = db.query(TradeOrder).filter(
                TradeOrder.created_at < cutoff_order,
                TradeOrder.status == 0,
            ).update({TradeOrder.status: 4}, synchronize_session=False)
            cleaned["timeout_orders"] = order_del

            db.commit()
            logger.info(f"[Scheduled] 数据清理完成: {cleaned}")
    except Exception as e:
        logger.exception(f"[Scheduled] 数据清理失败: {e}")
        return {"status": "error", "msg": str(e)}

    return {"status": "ok", "cleaned": cleaned}


# ==========================================================================
# Task 6: 自动备份（每天 2:00 执行）
#   - 备份数据库到 data/backups/ 目录
# ==========================================================================
@celery.task(name="backend.tasks.scheduled.auto_backup", bind=True)
def auto_backup(self):
    """自动备份数据库"""
    import os
    import shutil
    import gzip

    logger.info("[Scheduled] 开始自动备份...")

    try:
        from backend.config import get_settings
        settings = get_settings()

        backup_dir = os.path.join(os.getcwd(), "data", "backups")
        os.makedirs(backup_dir, exist_ok=True)

        today = datetime.now().strftime("%Y%m%d")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # SQLite 备份
        db_url = str(settings.DATABASE_URL or settings.DB_SQLITE_FALLBACK or "")
        backed_up = []

        if "sqlite" in db_url:
            db_path = db_url.replace("sqlite:///", "").replace("sqlite:///", "")
            if os.path.exists(db_path):
                backup_path = os.path.join(backup_dir, f"db_{timestamp}.db.gz")
                with open(db_path, "rb") as f_in:
                    with gzip.open(backup_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                backed_up.append(f"SQLite -> {backup_path}")
                logger.info(f"[Scheduled] SQLite备份完成: {backup_path}")

        # 清理7天前的备份
        for f in os.listdir(backup_dir):
            fpath = os.path.join(backup_dir, f)
            if os.path.isfile(fpath):
                file_mtime = os.path.getmtime(fpath)
                if (datetime.now().timestamp() - file_mtime) > 7 * 86400:
                    os.remove(fpath)
                    logger.info(f"[Scheduled] 清理过期备份: {f}")

        # 保留最近10个备份
        backups = sorted(
            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
             if os.path.isfile(os.path.join(backup_dir, f))],
            key=os.path.getmtime,
            reverse=True
        )
        for old in backups[10:]:
            os.remove(old)

        return {"status": "ok", "backed_up": backed_up, "backup_dir": backup_dir}
    except Exception as e:
        logger.exception(f"[Scheduled] 自动备份失败: {e}")
        return {"status": "error", "msg": str(e)}


def daily_strategy_evolution():
    """
    每日策略自我进化（盘后执行）
    1. 分析假信号模式
    2. 分析因子重要性
    3. 生成优化方案
    4. 高置信度方案自动应用到策略配置
    """
    logger.info("[Scheduled] ===== 每日策略自我进化开始 =====")
    try:
        from backend.services.strategy_evolution import get_evolution_service
        from backend.db.session import SessionLocal

        db = SessionLocal()
        try:
            svc = get_evolution_service()
            result = svc.auto_evolve(db, auto_apply_threshold=75.0)

            logger.info(
                f"[Scheduled] 进化完成: run_id={result.get('run_id')}, "
                f"模式={result.get('patterns_found')}, "
                f"方案={result.get('proposals_generated')}, "
                f"自动应用={result.get('auto_applied')}, "
                f"跳过(低置信)={result.get('skipped_low_confidence')}"
            )
            for r in result.get("apply_results", []):
                logger.info(
                    f"[Scheduled]   方案#{r['proposal_id']}({r['type']}) "
                    f"置信度={r['confidence']} → {'✓' if r['success'] else '✗'} {r['message']}"
                )
            return result
        finally:
            db.close()
    except Exception as e:
        logger.exception(f"[Scheduled] 每日进化失败: {e}")
        return {"status": "error", "msg": str(e)}
