"""
C-4: 策略引擎（评分写入DB + 触发下单信号闭环）

主流程：
1) StrategyEngine.run_once() 被 Celery 定时任务（每小时/每4小时K线收盘后）调用
2) 对每个激活的 StrategyConfig，遍历它的 symbols × timeframes
3) 调用 StrategyScoringEngine 做评分
4) 写入 ScoreRecord
5) 若 trigger_trade=True 且运行模式是全自动 → 调用 exchange 下单，生成 TradeOrder + TradePosition

另外：风控检查（日亏损限额 / 连续亏损 / 最大同时持仓数）
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func

from .scoring import StrategyScoringEngine, ScoreResult
from backend.models.strategy import StrategyConfig, ScoreRecord
from backend.models.trade import TradeOrder, TradePosition
from backend.models.exchange import ExchangeAccount
from backend.models.analytics import RiskEventLog
from backend.models.user import User
from backend.db.session import get_db
from backend.exchanges.market import MarketManager
from backend.exchanges.base import ExchangeClientBase
from backend.exchanges._types import ORDER_TYPE_MARKET, SIDE_LONG, SIDE_SHORT
from backend.core.distributed_lock import StrategyLock
from backend.core.logging_config import logger
from backend.core.utils import gen_client_order_id


# =========================================================
# Engine
# =========================================================
class StrategyEngine:
    def __init__(self):
        self.scoring = StrategyScoringEngine()
        self._last_run_per_key: Dict[Tuple[int, str, str], datetime] = {}

    # ---------- 外部：手动对某个策略+品种+周期评分 ----------
    def score_symbol(
        self,
        db: Session,
        strategy: StrategyConfig,
        symbol: str,
        timeframe: str,
        account_id: Optional[int] = None,
    ) -> Tuple[ScoreResult, Optional[ScoreRecord]]:
        """
        评分 + 持久化 ScoreRecord（幂等：同一 strategy+symbol+tf+收盘价 不重复写）
        """
        symbol = symbol.upper()
        # 1) 取 K 线：优先 MarketManager 内存，否则指定 account_id client REST
        mm = MarketManager.get_instance()
        client = self._choose_client(db, strategy, mm, account_id)
        limit = 200
        klines = mm.get_klines(symbol, timeframe, limit=limit)
        if len(klines) < 100 and client is not None:
            try:
                mm.register_client(client)
                if not mm._running:
                    mm.start(list(strategy.symbols) or ["BTC", "ETH", "SOL", "XAU", "WTI"])
                klines = client.fetch_klines(symbol, timeframe, limit=limit)
            except Exception:
                pass
        if len(klines) < 80:
            raise ValueError(
                f"{symbol} {timeframe} K线样本不足 ({len(klines)} < 80)。请先绑定交易所子账号并点击[同步余额/行情]。"
            )

        # 2) 取最近一根已闭合K线的 close_time
        last_closed = klines[-2] if len(klines) >= 2 else klines[-1]
        close_time_ms = getattr(last_closed, "close_time_ms", 0)
        close_price = float(getattr(last_closed, "close", 0) or 0)
        close_time = (
            datetime.fromtimestamp(close_time_ms / 1000)
            if close_time_ms > 0
            else datetime.now()
        )

        # 3) 评分
        result = self.scoring.compute(
            db=db,
            symbol=symbol,
            klines=klines,
            timeframe=timeframe,
            strategy=strategy,
            as_of=close_time,
            candle_close_price=close_price,
        )

        # 4) 幂等写 DB
        record = (
            db.query(ScoreRecord)
            .filter(
                ScoreRecord.strategy_id == strategy.id,
                ScoreRecord.symbol == symbol,
                ScoreRecord.timeframe == timeframe,
                ScoreRecord.candle_close_time == close_time,
            )
            .first()
        )
        if not record:
            payload = result.as_record_dict()
            record = ScoreRecord(
                strategy_id=strategy.id,
                symbol=symbol,
                timeframe=timeframe,
                candle_close_time=close_time,
                candle_close_price=Decimal(str(close_price or result.candle_close_price)),
                **payload,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
        else:
            # 已存在 → 只更新触发字段
            payload = result.as_record_dict()
            for k, v in payload.items():
                setattr(record, k, v)
            record.candle_close_price = Decimal(str(close_price or result.candle_close_price))
            db.commit()

        return result, record

    # ---------- 外部：整个策略一键跑（所有 symbol × timeframe） ----------
    def run_strategy(
        self,
        db: Session,
        strategy_id: int,
        execute_trade: bool = True,
        run_by_user: Optional[User] = None,
    ) -> dict:
        strategy = db.query(StrategyConfig).filter(StrategyConfig.id == strategy_id).first()
        if not strategy:
            return {"error": "策略不存在"}
        if not strategy.is_active:
            return {"error": "策略已停用"}
        owner = db.query(User).filter(User.id == strategy.user_id).first()
        if not owner:
            return {"error": "策略所属用户不存在"}

        # 分布式锁：防止多 Worker 重复执行同一策略
        with StrategyLock(strategy.id, expire_seconds=180) as acquired:
            if not acquired:
                logger.info(f"[Engine] 策略 {strategy_id} 已被其他 Worker 锁定，跳过")
                return {"error": "策略正在被其他进程执行", "strategy_id": strategy_id}

            symbols = list(strategy.symbols or [])
            timeframes = [t.strip() for t in (strategy.timeframe or "1h,4h").split(",") if t.strip()]

            score_results: List[ScoreResult] = []
            triggered: List[dict] = []
            errors: List[str] = []

            for tf in timeframes:
                for sym in symbols:
                    # 去重：避免过于频繁
                    k = (strategy.id, sym, tf)
                    now = datetime.now()
                    if self._last_run_per_key.get(k) and (now - self._last_run_per_key[k]).total_seconds() < 60:
                        continue
                    self._last_run_per_key[k] = now
                    try:
                        r, record = self.score_symbol(db, strategy, sym, tf, account_id=strategy.exchange_id)
                    except Exception as e:
                        errors.append(f"{sym} {tf}: {e}")
                        continue
                    score_results.append(r)
                    if r.trigger_trade and execute_trade:
                        # 风控
                        risk_ok, risk_msg = self._check_risk(db, strategy, owner, r.symbol, r.direction)
                        if not risk_ok:
                            # 记录风控事件
                            self._log_risk(db, owner, strategy, RiskEventLog.TYPE_COOLDOWN_START,
                                           2, f"{sym} {tf} {risk_msg}", record.id)
                            errors.append(risk_msg)
                            continue
                        if strategy.run_mode == StrategyConfig.MODE_AUTO:
                            # 全自动 → 下单
                            try:
                                order = self._execute_trade(db, owner, strategy, r)
                                triggered.append({
                                    "symbol": r.symbol,
                                    "timeframe": tf,
                                    "score": r.score_total,
                                    "direction": r.direction,
                                    "leverage": r.suggested_leverage,
                                    "order_id": order.id if order else None,
                                })
                            except Exception as e:
                                errors.append(f"{sym} {tf} 执行下单失败: {e}")
                        elif strategy.run_mode == StrategyConfig.MODE_SEMIAUTO:
                            triggered.append({
                                "symbol": r.symbol,
                                "timeframe": tf,
                                "score": r.score_total,
                                "direction": r.direction,
                                "leverage": r.suggested_leverage,
                                "mode": "semiauto",
                                "message": "半自动模式：请前往[策略详情]确认后下单",
                            })
                        else:  # 模拟盘
                            triggered.append({
                                "symbol": r.symbol,
                                "timeframe": tf,
                                "score": r.score_total,
                                "direction": r.direction,
                                "leverage": r.suggested_leverage,
                                "mode": "simulate",
                            })

            return {
                "strategy_id": strategy.id,
                "strategy_name": strategy.strategy_name,
                "scored": len(score_results),
                "triggered": triggered,
                "errors": errors,
                "total_score_avg": (
                    round(sum(r.score_total for r in score_results) / len(score_results), 2)
                    if score_results else 0.0
                ),
            }

    # =========================================================
    #  辅助
    # =========================================================
    def _choose_client(
        self, db: Session, strategy: StrategyConfig, mm: MarketManager, account_id: Optional[int]
    ) -> Optional[ExchangeClientBase]:
        # 优先直接指定的 account_id
        if account_id:
            acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == account_id).first()
            if acc and acc.status == 1:
                return self._build_client(acc)
        # 否则策略的 exchange_id
        if strategy.exchange_id:
            acc = db.query(ExchangeAccount).filter(
                ExchangeAccount.id == strategy.exchange_id
            ).first()
            if acc and acc.status == 1:
                return self._build_client(acc)
        # 回退：用户任意一个启用的账号
        acc = db.query(ExchangeAccount).filter(
            ExchangeAccount.user_id == strategy.user_id,
            ExchangeAccount.status == 1,
        ).first()
        if acc:
            return self._build_client(acc)
        # 最后：内存中已有的 client
        if mm.has_client():
            return mm._primary_client
        return None

    @staticmethod
    def _build_client(acc: ExchangeAccount) -> ExchangeClientBase:
        client = ExchangeClientBase.create(
            exchange=acc.exchange,
            api_key=acc.api_key or "",
            api_secret=acc.api_secret or "",
            passphrase=acc.api_passphrase or "",
            testnet=bool(acc.testnet),
            exchange_account_id=acc.id,
        )
        client.connect()
        MarketManager.get_instance().register_client(client)
        return client

    # ---------- 风控 ----------
    def _check_risk(
        self, db: Session, strategy: StrategyConfig, user: User, symbol: str, direction: int
    ) -> Tuple[bool, str]:
        # 1) 反向持仓冲突
        opposite = 2 if direction == 1 else 1
        same_symbol_pos = db.query(TradePosition).filter(
            TradePosition.exchange_account_id == strategy.exchange_id,
            TradePosition.symbol == symbol,
            TradePosition.status == 1,
        ).all()
        for p in same_symbol_pos:
            if p.side == opposite:
                return False, f"{symbol} 已有反向持仓，请先平仓再下单"

        # 2) 最大同时持仓数
        if strategy.exchange_id:
            open_count = db.query(TradePosition).filter(
                TradePosition.exchange_account_id == strategy.exchange_id,
                TradePosition.status == 1,
            ).count()
            if open_count >= int(strategy.max_position_count or 3):
                return False, f"当前同时持仓 {open_count} 个，已达上限 {strategy.max_position_count}"

        # 3) 日亏损限额
        today_start = datetime.combine(datetime.now().date(), datetime.min.time())
        today_pnl = (
            db.query(func.coalesce(func.sum(TradePosition.realized_pnl), 0))
            .filter(
                TradePosition.exchange_account_id == strategy.exchange_id,
                TradePosition.status == 2,
                TradePosition.close_time >= today_start,
            )
            .scalar()
        ) or 0
        if strategy.exchange_id:
            acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == strategy.exchange_id).first()
            if acc and float(acc.current_balance or 0) > 0:
                daily_loss_pct = (-float(today_pnl) / float(acc.current_balance)) * 100
                if daily_loss_pct >= float(strategy.daily_max_loss or 5.0):
                    return False, f"当日已亏损 {daily_loss_pct:.2f}%，触及日亏损上限 {strategy.daily_max_loss}%"

        # 4) 连续亏损 + 冷却期：最近N笔全亏则进入冷静期，冷静期内禁止开仓，
        #    冷静期过后自动恢复（以最近一笔亏损平仓时间起算 cooldown_hours），
        #    避免旧实现"连亏即永久拒绝、无盈利单则死锁"的问题。
        consec_limit = int(strategy.consecutive_loss_pause or 3)
        cooldown_hours = float(strategy.cooldown_hours or 24)
        recent_closed = (
            db.query(TradePosition)
            .filter(
                TradePosition.exchange_account_id == strategy.exchange_id,
                TradePosition.status == 2,
            )
            .order_by(TradePosition.id.desc())
            .limit(consec_limit)
            .all()
        )
        consec = 0
        for p in recent_closed:
            if float(p.realized_pnl or 0) < 0:
                consec += 1
            else:
                break
        if consec >= consec_limit:
            cooldown_since = recent_closed[0].close_time or datetime.now()
            elapsed_h = (datetime.now() - cooldown_since).total_seconds() / 3600
            if elapsed_h < cooldown_hours:
                remain = cooldown_hours - elapsed_h
                return False, (
                    f"连续 {consec} 单亏损，冷静期剩余 {remain:.1f}h（共 {cooldown_hours}h）"
                )
            # 冷静期已过，放行

        return True, "OK"

    def _log_risk(
        self, db: Session, user: User, strategy: StrategyConfig,
        event_type: int, severity: int, detail: str,
        score_record_id: Optional[int] = None, symbol: Optional[str] = None,
    ):
        log = RiskEventLog(
            user_id=user.id,
            exchange_account_id=strategy.exchange_id,
            strategy_id=strategy.id,
            symbol=symbol,
            event_type=event_type,
            severity=severity,
            title=f"{strategy.strategy_name or '策略'} 风控事件",
            detail=detail[:2000],
            snapshot={"score_record_id": score_record_id},
            action_taken=0,
            notified=False,
        )
        db.add(log)
        try:
            db.commit()
        except Exception:
            db.rollback()

    # ---------- 执行交易 ----------
    def _execute_trade(
        self, db: Session, user: User, strategy: StrategyConfig, r: ScoreResult
    ) -> Optional[TradeOrder]:
        if not strategy.exchange_id:
            return None
        acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == strategy.exchange_id).first()
        if not acc or acc.status != 1:
            raise ValueError("策略未绑定交易所子账号或已禁用")
        client = self._build_client(acc)

        # 1) 获取最新价 & 计算 TP/SL
        ticker = client.fetch_ticker(r.symbol)
        entry = ticker.last_price or r.candle_close_price
        if entry <= 0:
            raise ValueError("无效的最新价")
        if r.direction == SIDE_LONG:
            tp = entry * (1 + r.suggested_tp_pct / 100)
            sl = entry * (1 - r.suggested_sl_pct / 100)
        else:
            tp = entry * (1 - r.suggested_tp_pct / 100)
            sl = entry * (1 + r.suggested_sl_pct / 100)

        # 2) 仓位大小 = 账户权益 * single_position_ratio(%) / entry * 杠杆
        bal = client.fetch_balance()
        total_usdt = float(bal.total) if float(bal.total) > 0 else float(acc.current_balance or 1000)
        nominal = total_usdt * float(strategy.single_position_ratio or 10) / 100
        nominal = max(10.0, min(2000.0, nominal))
        qty = nominal / entry
        leverage = max(3, min(10, min(int(r.suggested_leverage), int(acc.leverage_max or 10))))

        # 3) 设置杠杆（交易所侧）
        try:
            client.set_leverage(r.symbol, leverage)
        except Exception:
            pass

        # 4) 预生成 client_order_id（用于后续精确匹配持仓）
        client_oid = gen_client_order_id("S")

        # 5) 写 TradeOrder（仅 flush 不 commit，保证后续与持仓原子提交）
        order = TradeOrder(
            exchange_account_id=acc.id,
            strategy_id=strategy.id,
            user_id=user.id,
            exchange=acc.exchange,
            client_order_id=client_oid,
            symbol=r.symbol,
            side=r.direction,
            order_type=1,
            leverage=leverage,
            quantity_contracts=Decimal(str(qty)),
            quantity_usdt=Decimal(str(nominal)),
            avg_fill_price=Decimal(str(entry)),
            order_price=Decimal(str(entry)),
            tp_price=Decimal(str(round(tp, 8))),
            sl_price=Decimal(str(round(sl, 8))),
            margin_used=Decimal(str(nominal / leverage)),
            trigger_reason=2,
            trigger_score=float(r.score_total),
            status=0,
            error_msg="",
        )
        db.add(order)
        db.flush()  # 获取 order.id，不 commit

        # 6) 调用交易所下单
        try:
            created = client.place_order(
                symbol=r.symbol,
                side=r.direction,
                order_type=ORDER_TYPE_MARKET,
                quantity=qty,
                price=0,
                take_profit_price=round(tp, 8),
                stop_loss_price=round(sl, 8),
                leverage=leverage,
                client_order_id=client_oid,
            )
            order.client_order_id = created.client_order_id or client_oid
            order.exchange_order_id = created.exchange_order_id or ""
            order.status = 2
            order.avg_fill_price = Decimal(str(created.avg_fill_price or entry))
            order.quantity_contracts = Decimal(str(created.filled_quantity or qty))
            order.filled_at = datetime.now()
            order.submitted_at = datetime.now()
        except Exception as e:
            # 交易所下单失败：仅回写失败状态，不创建持仓
            order.status = 5
            order.error_msg = str(e)[:500]
            db.commit()
            raise e

        # 7) 持仓落库 — 用 client_order_id 精确匹配，避免多仓位关联错误
        try:
            positions = client.fetch_positions()
            # 查询已关联的持仓 ID，避免匹配到已有订单的持仓
            linked_pos_ids = set(
                row[0] for row in db.query(TradeOrder.position_id)
                .filter(TradeOrder.position_id.isnot(None))
                .all()
            )
            # 优先用 client_order_id / raw_position_id 匹配
            matched = None
            for p in positions:
                if p.symbol != r.symbol or p.side != r.direction:
                    continue
                # 如果交易所返回了 raw_position_id 且已在 DB 关联，跳过
                if p.raw_position_id and p.raw_position_id in linked_pos_ids:
                    continue
                # 优先选择有 raw_position_id 且未关联的
                if p.raw_position_id:
                    matched = p
                    break
            # 回退：取 symbol+side 匹配且未关联的最后一个
            if not matched:
                candidates = [
                    p for p in positions
                    if p.symbol == r.symbol and p.side == r.direction
                ]
                if candidates:
                    matched = candidates[-1]

            if matched:
                pos_obj = TradePosition(
                    user_id=user.id,
                    exchange_account_id=acc.id,
                    strategy_id=strategy.id,
                    exchange=acc.exchange,
                    symbol=r.symbol,
                    side=r.direction,
                    leverage=leverage,
                    entry_price=Decimal(str(matched.entry_price or entry)),
                    mark_price=Decimal(str(matched.mark_price or entry)),
                    quantity_contracts=Decimal(str(matched.quantity or qty)),
                    quantity_usdt=Decimal(str(nominal)),
                    margin_used=Decimal(str(matched.margin or (nominal / leverage))),
                    tp_price=Decimal(str(round(tp, 8))),
                    sl_price=Decimal(str(round(sl, 8))),
                    unrealized_pnl=Decimal(str(matched.unrealized_pnl or 0)),
                    realized_pnl=Decimal(0),
                    pnl_ratio=float(matched.unrealized_pnl_pct or 0),
                    max_drawdown_ratio=0.0,
                    fee_total=Decimal(0),
                    status=1,
                    entry_score=float(r.score_total),
                    entry_time=datetime.now(),
                    close_time=None,
                    close_price=None,
                    holding_minutes=0,
                )
                db.add(pos_obj)
                db.flush()
                order.position_id = pos_obj.id
            else:
                logger.warning(
                    f"[Engine] 订单 {order.id} 下单成功但未匹配到持仓 "
                    f"(symbol={r.symbol}, side={r.direction})，可能为模拟盘或仓位已被平仓"
                )
        except Exception as e:
            # 持仓匹配失败不影响订单记录，但需要记录异常
            logger.exception(f"[Engine] 订单 {order.id} 持仓匹配异常: {e}")

        # 8) 原子提交：订单 + 持仓一起 commit
        db.commit()
        db.refresh(order)
        return order
