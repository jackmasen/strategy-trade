"""
信号验证服务 - 回测验证历史信号的有效性
定期扫描未验证的信号，检查后续K线是否命中止盈/止损
"""
import time
import threading
from typing import Optional
from sqlalchemy import desc

from backend.core.logging_config import logger
from backend.db.session import SessionLocal
from backend.models.analytics import QuantSignalRecord
from backend.exchanges.market import MarketManager


class SignalVerificationService:
    """信号验证服务
    
    工作原理：
    1. 定期从 quant_signal_records 表中取出未验证的信号
    2. 检查信号发出后，后续K线是否先触及止盈或止损
    3. 回填验证结果（hit_tp / hit_sl / expired）
    """

    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SignalVerificationService":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._verify_loop, name="signal_verify", daemon=True)
        self._thread.start()
        logger.info("[SignalVerify] 信号验证服务已启动")

    def stop(self):
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("[SignalVerify] 信号验证服务已停止")

    def _verify_loop(self):
        """验证循环：每5分钟验证一次"""
        while not self._stop_event.is_set():
            try:
                self._verify_pending_signals()
            except Exception as e:
                logger.error(f"[SignalVerify] 验证异常: {e}")
            
            # 每5分钟跑一次
            for _ in range(300):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

    def _verify_pending_signals(self):
        """验证所有待验证的信号"""
        db = SessionLocal()
        mm = MarketManager.get_instance()
        try:
            # 取出未验证的信号（有明确方向的）
            pending = db.query(QuantSignalRecord).filter(
                QuantSignalRecord.verified == False,
                QuantSignalRecord.direction.in_(["bullish", "bearish"]),
            ).order_by(QuantSignalRecord.timestamp.asc()).limit(100).all()

            if not pending:
                return

            verified_count = 0
            for record in pending:
                try:
                    result = self._verify_single_signal(record, mm)
                    if result:
                        verified_count += 1
                except Exception as e:
                    logger.debug(f"[SignalVerify] 验证信号 {record.id} 失败: {e}")

            db.commit()
            if verified_count > 0:
                logger.info(f"[SignalVerify] 完成验证 {verified_count} 个信号")
        finally:
            db.close()

    def _verify_single_signal(self, record: QuantSignalRecord, mm: MarketManager) -> bool:
        """验证单个信号
        
        Returns:
            True if verified, False otherwise
        """
        # 获取信号发出后的K线
        klines = mm.get_klines(record.symbol, record.timeframe, limit=200)
        if not klines or len(klines) < 2:
            return False

        # 找到信号时间点之后的K线
        signal_ts_ms = record.timestamp * 1000
        future_klines = [k for k in klines if k.open_time_ms > signal_ts_ms]

        if not future_klines:
            return False  # 还没有足够的后续K线

        entry_price = record.entry_price
        stop_loss = record.stop_loss
        take_profit = record.take_profit
        is_long = record.direction == "bullish"

        # 检查每根K线的最高/最低价，看先触及TP还是SL
        for i, k in enumerate(future_klines[:50]):  # 最多看50根K线
            high = k.high
            low = k.low

            if is_long:
                # 做多：先检查止损（最低价跌破SL）还是止盈（最高价突破TP）
                if low <= stop_loss:
                    record.outcome = "hit_sl"
                    record.outcome_return_pct = -(take_profit - entry_price) / entry_price * 100 / (record.risk_reward_ratio or 2)
                    record.outcome_bars = i + 1
                    record.verified = True
                    return True
                if high >= take_profit:
                    record.outcome = "hit_tp"
                    record.outcome_return_pct = (take_profit - entry_price) / entry_price * 100
                    record.outcome_bars = i + 1
                    record.verified = True
                    return True
            else:
                # 做空：先检查止损（最高价突破SL）还是止盈（最低价跌破TP）
                if high >= stop_loss:
                    record.outcome = "hit_sl"
                    record.outcome_return_pct = -(entry_price - take_profit) / entry_price * 100 / (record.risk_reward_ratio or 2)
                    record.outcome_bars = i + 1
                    record.verified = True
                    return True
                if low <= take_profit:
                    record.outcome = "hit_tp"
                    record.outcome_return_pct = (entry_price - take_profit) / entry_price * 100
                    record.outcome_bars = i + 1
                    record.verified = True
                    return True

        # 50根K线内未触发，标记为过期
        # 但只有当确实有足够多的K线时才标记
        if len(future_klines) >= 30:
            # 用收盘价计算最终收益
            last_close = future_klines[-1].close
            if is_long:
                pnl_pct = (last_close - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - last_close) / entry_price * 100

            record.outcome = "expired"
            record.outcome_return_pct = round(pnl_pct, 2)
            record.outcome_bars = min(len(future_klines), 50)
            record.verified = True
            return True

        return False
