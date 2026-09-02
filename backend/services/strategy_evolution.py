"""
Strategy Evolution Service - 策略自我进化服务
====================================================
核心能力：
  1. 假信号自动识别   - 从历史验证信号中挖掘失效模式
  2. 因子重要性分析   - 计算各因子对胜率的贡献度
  3. 参数自适应优化   - 根据表现动态调整阈值和权重
  4. 进化方案生成     - AI分析历史数据，给出策略优化建议

设计原则：
  - 数据驱动：所有优化建议都基于历史验证数据
  - 保守进化：样本量不足时不调整，避免过拟合
  - 可追溯：每次进化都有完整记录，可回滚
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.core.logging_config import logger
from backend.models.analytics import (
    QuantSignalRecord,
    FalseSignalPattern,
    FactorPerformanceStat,
    EvolutionProposal,
    EvolutionRun,
)
from backend.models.strategy import StrategyConfig


class StrategyEvolutionService:
    """策略自我进化服务"""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()

    # ============================================================
    # 1. 假信号模式挖掘
    # ============================================================
    def analyze_false_signal_patterns(self, db: Session, symbol: str = "ALL",
                                       min_samples: int = 10) -> List[FalseSignalPattern]:
        """
        从已验证的历史信号中挖掘假信号模式

        分析维度：
        - 单因子极值：某因子极端看多但结果是假信号
        - 因子矛盾：多个因子方向不一致时的胜率
        - 市场状态：不同市场状态下的假信号率
        - 波动率环境：高波动/低波动下的假信号模式
        """
        # 获取已验证的信号
        query = db.query(QuantSignalRecord).filter(
            QuantSignalRecord.verified == True,
            QuantSignalRecord.direction.in_(["bullish", "bearish"]),
        )
        if symbol and symbol != "ALL":
            query = query.filter(QuantSignalRecord.symbol == symbol)
        records = query.order_by(QuantSignalRecord.timestamp.desc()).limit(500).all()

        if not records:
            return []

        patterns = []

        # ---- 模式1：单因子方向与结果的关系 ----
        factor_names = ["market_regime", "capital_flow", "leverage", "liquidation",
                       "volatility", "news_sentiment", "strategy_advantage"]

        for factor in factor_names:
            # 按因子方向分组统计
            bullish_correct = 0  # 因子看涨 & 结果止盈
            bullish_wrong = 0    # 因子看涨 & 结果止损/过期
            bearish_correct = 0
            bearish_wrong = 0
            neutral_total = 0

            for rec in records:
                fs = rec.factor_scores or {}
                score = fs.get(factor, 0)
                if score is None:
                    continue

                # 因子方向
                if score > 2:
                    f_dir = "bullish"
                elif score < -2:
                    f_dir = "bearish"
                else:
                    f_dir = "neutral"
                    neutral_total += 1
                    continue

                # 实际结果
                is_win = rec.outcome == "hit_tp"
                actual_dir = "bullish" if rec.direction == "bullish" else "bearish"

                # 只统计因子方向与信号方向一致的情况（因子支持了这个决策）
                if f_dir == rec.direction:
                    if is_win:
                        bullish_correct += 1 if f_dir == "bullish" else 0
                        bearish_correct += 1 if f_dir == "bearish" else 0
                    else:
                        bullish_wrong += 1 if f_dir == "bullish" else 0
                        bearish_wrong += 1 if f_dir == "bearish" else 0

            total_bullish = bullish_correct + bullish_wrong
            total_bearish = bearish_correct + bearish_wrong

            # 看涨假信号模式
            if total_bullish >= min_samples:
                wr = bullish_correct / total_bullish
                if wr < 0.4:  # 胜率低于40%，是危险模式
                    key = f"factor_{factor}_bullish_weak"
                    pat = self._get_or_create_pattern(db, key, "factor_combo")
                    pat.total_signals = total_bullish
                    pat.win_count = bullish_correct
                    pat.false_count = bullish_wrong
                    pat.win_rate = round(wr * 100, 1)
                    pat.description = f"{self._factor_cn(factor)}因子看涨时胜率仅{wr*100:.1f}%"
                    pat.factor_conditions = {factor: "bullish (>2分)"}
                    pat.suggestion = f"降低{self._factor_cn(factor)}因子看涨时的权重，或增加额外过滤条件"
                    pat.severity = self._calc_severity(wr, total_bullish)
                    patterns.append(pat)

            # 看跌假信号模式
            if total_bearish >= min_samples:
                wr = bearish_correct / total_bearish
                if wr < 0.4:
                    key = f"factor_{factor}_bearish_weak"
                    pat = self._get_or_create_pattern(db, key, "factor_combo")
                    pat.total_signals = total_bearish
                    pat.win_count = bearish_correct
                    pat.false_count = bearish_wrong
                    pat.win_rate = round(wr * 100, 1)
                    pat.description = f"{self._factor_cn(factor)}因子看跌时胜率仅{wr*100:.1f}%"
                    pat.factor_conditions = {factor: "bearish (<-2分)"}
                    pat.suggestion = f"降低{self._factor_cn(factor)}因子看跌时的权重"
                    pat.severity = self._calc_severity(wr, total_bearish)
                    patterns.append(pat)

        # ---- 模式2：因子矛盾模式（方向不一致的因子数 > 3） ----
        contradiction_wins = 0
        contradiction_losses = 0
        for rec in records:
            fs = rec.factor_scores or {}
            bullish_factors = sum(1 for v in fs.values() if v and v > 2)
            bearish_factors = sum(1 for v in fs.values() if v and v < -2)
            # 矛盾：看多和看空的因子都不少
            if bullish_factors >= 2 and bearish_factors >= 2:
                if rec.outcome == "hit_tp":
                    contradiction_wins += 1
                else:
                    contradiction_losses += 1

        contradiction_total = contradiction_wins + contradiction_losses
        if contradiction_total >= min_samples:
            wr = contradiction_wins / contradiction_total
            key = "multi_factor_contradiction"
            pat = self._get_or_create_pattern(db, key, "factor_combo")
            pat.total_signals = contradiction_total
            pat.win_count = contradiction_wins
            pat.false_count = contradiction_losses
            pat.win_rate = round(wr * 100, 1)
            pat.description = f"多因子矛盾（≥2个看涨且≥2个看跌）时胜率{wr*100:.1f}%"
            pat.factor_conditions = {"bullish_factors": "≥2", "bearish_factors": "≥2"}
            pat.suggestion = "因子矛盾时提高开单阈值，或等待更多因子达成一致"
            pat.severity = self._calc_severity(wr, contradiction_total)
            patterns.append(pat)

        # ---- 模式3：市场状态模式 ----
        regime_stats = {}
        for rec in records:
            regime = rec.market_regime or "unknown"
            if regime not in regime_stats:
                regime_stats[regime] = {"win": 0, "lose": 0, "total": 0}
            regime_stats[regime]["total"] += 1
            if rec.outcome == "hit_tp":
                regime_stats[regime]["win"] += 1
            else:
                regime_stats[regime]["lose"] += 1

        for regime, stats in regime_stats.items():
            if stats["total"] >= min_samples:
                wr = stats["win"] / stats["total"]
                if wr < 0.4:
                    key = f"regime_{regime}_weak"
                    pat = self._get_or_create_pattern(db, key, "regime")
                    pat.total_signals = stats["total"]
                    pat.win_count = stats["win"]
                    pat.false_count = stats["lose"]
                    pat.win_rate = round(wr * 100, 1)
                    pat.market_regime = regime
                    regime_cn = {"ranging": "震荡市", "strong_trend_up": "强势上涨",
                                "strong_trend_down": "强势下跌", "weak_trend_up": "弱势上涨",
                                "weak_trend_down": "弱势下跌"}
                    regime_name = regime_cn.get(regime, regime)
                    pat.description = f"{regime_name}下胜率仅{wr*100:.1f}%"
                    pat.suggestion = f"在{regime_name}中降低仓位或暂停开单"
                    pat.severity = self._calc_severity(wr, stats["total"])
                    patterns.append(pat)

        db.commit()
        return patterns

    def _get_or_create_pattern(self, db: Session, pattern_key: str,
                                pattern_type: str) -> FalseSignalPattern:
        pat = db.query(FalseSignalPattern).filter(
            FalseSignalPattern.pattern_key == pattern_key
        ).first()
        if not pat:
            pat = FalseSignalPattern(pattern_key=pattern_key, pattern_type=pattern_type)
            db.add(pat)
        pat.last_updated = datetime.utcnow()
        return pat

    def _calc_severity(self, win_rate: float, sample_size: int) -> str:
        """根据胜率和样本量计算严重程度"""
        if win_rate < 0.2 and sample_size >= 20:
            return "critical"
        elif win_rate < 0.3 and sample_size >= 15:
            return "high"
        elif win_rate < 0.4 and sample_size >= 10:
            return "medium"
        return "low"

    def _factor_cn(self, factor: str) -> str:
        """因子中文名"""
        names = {
            "market_regime": "市场状态",
            "capital_flow": "资金流向",
            "leverage": "杠杆集中度",
            "liquidation": "清算压力",
            "volatility": "波动率",
            "news_sentiment": "新闻情绪",
            "strategy_advantage": "策略优势",
        }
        return names.get(factor, factor)

    # ============================================================
    # 2. 因子重要性分析
    # ============================================================
    def analyze_factor_importance(self, db: Session, symbol: str = "ALL") -> List[FactorPerformanceStat]:
        """
        分析每个因子的重要性（对最终收益的贡献度）

        方法：
        - 方向准确率：因子方向与最终结果方向的一致率
        - 强度相关性：因子得分大小与收益幅度的相关系数
        - 综合重要性：准确率 * 相关性 * 样本量系数
        """
        query = db.query(QuantSignalRecord).filter(
            QuantSignalRecord.verified == True,
            QuantSignalRecord.direction.in_(["bullish", "bearish"]),
        )
        if symbol and symbol != "ALL":
            query = query.filter(QuantSignalRecord.symbol == symbol)
        records = query.order_by(QuantSignalRecord.timestamp.desc()).limit(500).all()

        if not records:
            return []

        factor_names = ["market_regime", "capital_flow", "leverage", "liquidation",
                       "volatility", "news_sentiment", "strategy_advantage"]

        # 当前默认权重
        current_weights = {
            "market_regime": 0.18, "capital_flow": 0.15, "leverage": 0.12,
            "liquidation": 0.10, "volatility": 0.15, "news_sentiment": 0.15,
            "strategy_advantage": 0.15,
        }

        stats_list = []

        for factor in factor_names:
            correct = 0
            wrong = 0
            scores = []  # 因子得分
            returns = []  # 对应收益率

            for rec in records:
                fs = rec.factor_scores or {}
                score = fs.get(factor, 0) or 0
                ret = rec.outcome_return_pct or 0

                if abs(score) < 1:
                    continue  # 中性信号不参与方向准确率统计

                scores.append(score)
                returns.append(ret)

                # 因子方向是否正确
                signal_dir = 1 if rec.direction == "bullish" else -1
                factor_dir = 1 if score > 0 else -1
                is_win = ret > 0

                # 因子与信号方向一致时，是否正确
                if factor_dir == signal_dir:
                    if is_win:
                        correct += 1
                    else:
                        wrong += 1

            total = correct + wrong
            accuracy = correct / total if total > 0 else 0.5

            # 计算相关系数
            correlation = 0
            if len(scores) >= 5:
                n = len(scores)
                mean_s = sum(scores) / n
                mean_r = sum(returns) / n
                num = sum((s - mean_s) * (r - mean_r) for s, r in zip(scores, returns))
                den_s = math.sqrt(sum((s - mean_s) ** 2 for s in scores))
                den_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns))
                if den_s > 0 and den_r > 0:
                    correlation = num / (den_s * den_r)

            # 重要性评分：准确率(50%) + 相关系数绝对值(30%) + 样本量(20%)
            sample_factor = min(1.0, total / 30.0)  # 30个样本以上给满分
            importance = (
                accuracy * 50
                + abs(correlation) * 30
                + sample_factor * 20
            )

            # 建议权重：基于重要性重新分配
            suggested = current_weights[factor] * (0.5 + importance / 100)

            # 写入DB
            stat = db.query(FactorPerformanceStat).filter(
                FactorPerformanceStat.factor_name == factor,
                FactorPerformanceStat.market_regime == "all",
                FactorPerformanceStat.symbol == symbol,
            ).first()
            if not stat:
                stat = FactorPerformanceStat(factor_name=factor, symbol=symbol)
                db.add(stat)

            stat.accuracy = round(accuracy * 100, 1)
            stat.correlation = round(correlation, 3)
            stat.importance_score = round(importance, 1)
            stat.current_weight = current_weights[factor]
            stat.suggested_weight = round(suggested, 3)
            stat.sample_size = total
            stat.bullish_correct = correct  # 简化：合并存储
            stat.bullish_wrong = wrong
            stat.last_updated = datetime.utcnow()

            stats_list.append(stat)

        db.commit()
        return stats_list

    # ============================================================
    # 3. 生成进化优化方案
    # ============================================================
    def generate_evolution_proposals(self, db: Session, strategy_id: Optional[int] = None) -> List[EvolutionProposal]:
        """
        基于假信号模式和因子重要性分析，生成优化方案

        方案类型：
        - weight: 因子权重调整
        - threshold: 开单阈值调整
        - parameter: TP/SL/杠杆参数调整
        - regime_filter: 市场状态过滤
        """
        proposals = []

        # 获取最新的假信号模式（中等以上严重程度）
        patterns = db.query(FalseSignalPattern).filter(
            FalseSignalPattern.severity.in_(["medium", "high", "critical"]),
            FalseSignalPattern.total_signals >= 10,
        ).order_by(FalseSignalPattern.win_rate.asc()).limit(10).all()

        # 获取因子重要性排名
        factor_stats = db.query(FactorPerformanceStat).filter(
            FactorPerformanceStat.symbol == "ALL",
            FactorPerformanceStat.market_regime == "all",
        ).order_by(FactorPerformanceStat.importance_score.desc()).all()

        # ---- 方案1：因子权重优化 ----
        if factor_stats and len(factor_stats) >= 5:
            top_factors = factor_stats[:3]
            bottom_factors = factor_stats[-2:]

            current_w = {s.factor_name: s.current_weight for s in factor_stats}
            proposed_w = dict(current_w)

            # 表现好的因子增加权重，表现差的减少权重
            total_top = sum(s.importance_score for s in top_factors)
            total_bottom = sum(s.importance_score for s in bottom_factors)

            if total_top > 0 and total_bottom > 0:
                # 从底部因子转移权重到顶部因子（每次最多调整2%）
                transfer = min(0.02, 0.02 * (total_top - total_bottom) / 100)
                for s in top_factors:
                    proposed_w[s.factor_name] = round(current_w[s.factor_name] + transfer / 3, 4)
                for s in bottom_factors:
                    proposed_w[s.factor_name] = round(max(0.05, current_w[s.factor_name] - transfer / 2), 4)

            # 归一化
            total_pw = sum(proposed_w.values())
            proposed_w = {k: round(v / total_pw, 4) for k, v in proposed_w.items()}

            # 计算预期提升（简化估算）
            avg_importance_top = sum(s.importance_score for s in top_factors) / 3
            avg_importance_bottom = sum(s.importance_score for s in bottom_factors) / 2
            expected_improve = max(0, (avg_importance_top - avg_importance_bottom) * 0.1)

            proposal = EvolutionProposal(
                proposal_type="weight",
                title="因子权重优化建议",
                description=f"根据历史表现，将更多权重分配给预测能力强的因子，同时降低表现差的因子权重。",
                current_config={"factor_weights": current_w},
                proposed_config={"factor_weights": proposed_w},
                expected_win_rate_improvement=round(expected_improve, 2),
                expected_profit_factor_improvement=round(expected_improve * 0.1, 2),
                confidence=round(min(95, 40 + len(patterns) * 3), 0),
                evidence_summary=f"基于{len(factor_stats)}个因子的历史表现分析，Top3因子重要性评分{avg_importance_top:.1f}，Bottom2因子{avg_importance_bottom:.1f}",
                supporting_patterns=[p.id for p in patterns[:3]],
            )
            db.add(proposal)
            proposals.append(proposal)

        # ---- 方案2：提高开单阈值 ----
        # 如果整体胜率低于45%，建议提高阈值
        verified_records = db.query(QuantSignalRecord).filter(
            QuantSignalRecord.verified == True,
            QuantSignalRecord.direction.in_(["bullish", "bearish"]),
        ).limit(100).all()

        if verified_records and len(verified_records) >= 20:
            wins = sum(1 for r in verified_records if r.outcome == "hit_tp")
            current_wr = wins / len(verified_records)

            if current_wr < 0.45:
                proposal = EvolutionProposal(
                    proposal_type="threshold",
                    title="提高开单阈值建议",
                    description=f"当前整体胜率{current_wr*100:.1f}%（{wins}/{len(verified_records)}），低于目标45%。建议将开单评分阈值从5.0提高到5.5，过滤掉边际信号。",
                    current_config={"score_threshold": 5.0},
                    proposed_config={"score_threshold": 5.5},
                    expected_win_rate_improvement=round((0.55 - current_wr) * 100, 1),
                    expected_drawdown_reduction=round((0.45 - current_wr) * 50, 1),
                    confidence=round(min(90, 50 + len(verified_records)), 0),
                    evidence_summary=f"分析了{len(verified_records)}个已验证信号，当前胜率{current_wr*100:.1f}%，低于目标值",
                )
                db.add(proposal)
                proposals.append(proposal)

        # ---- 方案3：震荡市降低仓位 ----
        ranging_patterns = [p for p in patterns if p.market_regime and "rang" in p.market_regime.lower()]
        if ranging_patterns:
            p = ranging_patterns[0]
            proposal = EvolutionProposal(
                proposal_type="regime_filter",
                title="震荡市仓位控制建议",
                description=f"震荡市下信号胜率仅{p.win_rate}%，显著低于趋势市。建议在震荡市中降低50%仓位，或提高开单阈值。",
                current_config={"ranging_position_pct": 100},
                proposed_config={"ranging_position_pct": 50, "ranging_threshold_bonus": 0.5},
                expected_win_rate_improvement=round((0.5 - p.win_rate / 100) * 20, 1),
                expected_drawdown_reduction=round((0.5 - p.win_rate / 100) * 30, 1),
                confidence=round(min(85, 40 + p.total_signals * 2), 0),
                evidence_summary=f"震荡市{p.total_signals}个信号，胜率{p.win_rate}%",
                supporting_patterns=[p.id],
            )
            db.add(proposal)
            proposals.append(proposal)

        # ---- 方案4：TP/SL优化 ----
        # 分析平均收益和亏损比例
        if verified_records and len(verified_records) >= 20:
            win_returns = [r.outcome_return_pct for r in verified_records
                          if r.outcome == "hit_tp" and r.outcome_return_pct]
            loss_returns = [abs(r.outcome_return_pct) for r in verified_records
                           if r.outcome == "hit_sl" and r.outcome_return_pct]

            if win_returns and loss_returns:
                avg_win = sum(win_returns) / len(win_returns)
                avg_loss = sum(loss_returns) / len(loss_returns)
                current_pf = avg_win / avg_loss if avg_loss > 0 else 1

                if current_pf < 1.2:
                    proposal = EvolutionProposal(
                        proposal_type="parameter",
                        title="止盈止损比例优化建议",
                        description=f"当前盈亏比{current_pf:.2f}（平均盈利{avg_win:.2f}% / 平均亏损{avg_loss:.2f}%），低于1.5的健康值。建议扩大止盈或缩小止损。",
                        current_config={"tp_ratio": 4.0, "sl_ratio": 2.0, "actual_pf": round(current_pf, 2)},
                        proposed_config={"tp_ratio": 5.0, "sl_ratio": 1.8},
                        expected_profit_factor_improvement=round(1.5 - current_pf, 2),
                        confidence=round(min(80, 40 + len(win_returns)), 0),
                        evidence_summary=f"{len(win_returns)}次止盈平均{avg_win:.2f}%，{len(loss_returns)}次止损平均{avg_loss:.2f}%",
                    )
                    db.add(proposal)
                    proposals.append(proposal)

        db.commit()
        return proposals

    # ============================================================
    # 4. 完整进化运行
    # ============================================================
    def run_full_evolution(self, db: Session, symbol: str = "ALL",
                            strategy_id: Optional[int] = None) -> EvolutionRun:
        """运行一次完整的进化分析"""
        if self._running:
            raise RuntimeError("进化分析正在运行中，请稍候")

        with self._lock:
            self._running = True

        run = EvolutionRun(run_type="full", status="running")
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            # 步骤1：假信号模式挖掘
            patterns = self.analyze_false_signal_patterns(db, symbol=symbol)
            run.patterns_found = len(patterns)

            # 步骤2：因子重要性分析
            factor_stats = self.analyze_factor_importance(db, symbol=symbol)

            # 步骤3：生成进化方案
            proposals = self.generate_evolution_proposals(db, strategy_id=strategy_id)
            run.proposals_generated = len(proposals)

            # 统计信号数
            signals_count = db.query(QuantSignalRecord).filter(
                QuantSignalRecord.verified == True
            ).count()
            run.signals_analyzed = signals_count
            run.symbols_analyzed = 1 if symbol != "ALL" else 5

            run.status = "completed"
            run.completed_at = datetime.utcnow()
            db.commit()

        except Exception as e:
            logger.error(f"[Evolution] 进化分析失败: {e}")
            run.status = "failed"
            run.error_message = str(e)
            run.completed_at = datetime.utcnow()
            db.commit()
            import traceback
            traceback.print_exc()
        finally:
            with self._lock:
                self._running = False

        return run

    # ============================================================
    # 5. 获取进化仪表盘数据
    # ============================================================
    def get_dashboard_data(self, db: Session, symbol: str = "ALL") -> dict:
        """获取进化仪表盘汇总数据"""
        try:
            # 基础统计
            total_signals = db.query(QuantSignalRecord).filter(
                QuantSignalRecord.verified == True,
                QuantSignalRecord.direction.in_(["bullish", "bearish"]),
            ).count()
            win_signals = db.query(QuantSignalRecord).filter(
                QuantSignalRecord.verified == True,
                QuantSignalRecord.outcome == "hit_tp",
            ).count()
            sl_signals = db.query(QuantSignalRecord).filter(
                QuantSignalRecord.verified == True,
                QuantSignalRecord.outcome == "hit_sl",
            ).count()
            expired_signals = db.query(QuantSignalRecord).filter(
                QuantSignalRecord.verified == True,
                QuantSignalRecord.outcome == "expired",
            ).count()

            win_rate = round(win_signals / total_signals * 100, 1) if total_signals > 0 else 0

            # 假信号模式（按严重程度排序）
            patterns = db.query(FalseSignalPattern).order_by(
                FalseSignalPattern.severity.desc(),
                FalseSignalPattern.win_rate.asc(),
            ).limit(10).all()

            # 因子重要性
            factor_stats = db.query(FactorPerformanceStat).filter(
                FactorPerformanceStat.symbol == symbol,
                FactorPerformanceStat.market_regime == "all",
            ).order_by(FactorPerformanceStat.importance_score.desc()).all()

            # 待处理的方案
            pending_proposals = db.query(EvolutionProposal).filter(
                EvolutionProposal.status == "pending",
            ).order_by(EvolutionProposal.confidence.desc()).limit(5).all()

            # 最近的进化运行
            last_run = db.query(EvolutionRun).order_by(EvolutionRun.started_at.desc()).first()
        except Exception as e:
            logger.warning(f"[Evolution] 仪表盘查询失败（表可能未创建）: {e}")
            return {
                "summary": {"total_verified_signals": 0, "win_signals": 0,
                           "loss_signals": 0, "expired_signals": 0, "win_rate": 0},
                "patterns": [], "factor_stats": [], "pending_proposals": [], "last_run": None,
            }

        return {
            "summary": {
                "total_verified_signals": total_signals,
                "win_signals": win_signals,
                "loss_signals": sl_signals,
                "expired_signals": expired_signals,
                "win_rate": win_rate,
            },
            "patterns": [self._pattern_to_dict(p) for p in patterns],
            "factor_stats": [self._factor_stat_to_dict(s) for s in factor_stats],
            "pending_proposals": [self._proposal_to_dict(p) for p in pending_proposals],
            "last_run": {
                "id": last_run.id if last_run else None,
                "status": last_run.status if last_run else None,
                "started_at": last_run.started_at.isoformat() if last_run else None,
                "patterns_found": last_run.patterns_found if last_run else 0,
                "proposals_generated": last_run.proposals_generated if last_run else 0,
            } if last_run else None,
        }

    def _pattern_to_dict(self, p: FalseSignalPattern) -> dict:
        severity_cn = {"low": "低", "medium": "中", "high": "高", "critical": "严重"}
        return {
            "id": p.id,
            "pattern_key": p.pattern_key,
            "pattern_type": p.pattern_type,
            "description": p.description,
            "total_signals": p.total_signals,
            "win_count": p.win_count,
            "false_count": p.false_count,
            "win_rate": p.win_rate,
            "severity": p.severity,
            "severity_cn": severity_cn.get(p.severity, p.severity),
            "suggestion": p.suggestion,
            "market_regime": p.market_regime,
            "factor_conditions": p.factor_conditions,
        }

    def _factor_stat_to_dict(self, s: FactorPerformanceStat) -> dict:
        factor_cn = {
            "market_regime": "市场状态", "capital_flow": "资金流向",
            "leverage": "杠杆集中度", "liquidation": "清算压力",
            "volatility": "波动率", "news_sentiment": "新闻情绪",
            "strategy_advantage": "策略优势",
        }
        return {
            "id": s.id,
            "factor_name": s.factor_name,
            "factor_name_cn": factor_cn.get(s.factor_name, s.factor_name),
            "accuracy": s.accuracy,
            "correlation": s.correlation,
            "importance_score": s.importance_score,
            "current_weight": s.current_weight,
            "suggested_weight": s.suggested_weight,
            "sample_size": s.sample_size,
        }

    def _proposal_to_dict(self, p: EvolutionProposal) -> dict:
        type_cn = {
            "weight": "权重调整", "threshold": "阈值调整",
            "parameter": "参数优化", "regime_filter": "状态过滤",
            "strategy": "策略更换", "new_factor": "新增因子",
        }
        return {
            "id": p.id,
            "proposal_type": p.proposal_type,
            "proposal_type_cn": type_cn.get(p.proposal_type, p.proposal_type),
            "title": p.title,
            "description": p.description,
            "current_config": p.current_config,
            "proposed_config": p.proposed_config,
            "expected_win_rate_improvement": p.expected_win_rate_improvement,
            "expected_profit_factor_improvement": p.expected_profit_factor_improvement,
            "expected_drawdown_reduction": p.expected_drawdown_reduction,
            "confidence": p.confidence,
            "status": p.status,
            "evidence_summary": p.evidence_summary,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }


# 单例
_evolution_service: Optional[StrategyEvolutionService] = None


def get_evolution_service() -> StrategyEvolutionService:
    global _evolution_service
    if _evolution_service is None:
        _evolution_service = StrategyEvolutionService()
    return _evolution_service
