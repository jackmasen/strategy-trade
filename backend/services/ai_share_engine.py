"""
分享链接 AI 控制引擎
通过分享链接，外部人员（如AI助手）可以触发模拟回测、多币种策略测试、AI分析等任务
所有任务均为只读/模拟性质，不影响真实交易和数据
"""
import uuid
import time
import random
import threading
import queue
from datetime import datetime
from typing import Dict, List, Optional, Any, Generator
from concurrent.futures import ThreadPoolExecutor, Future

# 任务存储：token -> {task_id: task_info}
_ai_tasks: Dict[str, Dict[str, dict]] = {}

# SSE 事件队列：token -> {task_id: queue.Queue}
_sse_queues: Dict[str, Dict[str, queue.Queue]] = {}

# 线程池执行异步任务
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-share-task")

# 任务锁
_lock = threading.Lock()
_sse_lock = threading.Lock()


def _get_tasks_for_token(token: str) -> Dict[str, dict]:
    """获取指定token的任务字典"""
    with _lock:
        if token not in _ai_tasks:
            _ai_tasks[token] = {}
        return _ai_tasks[token]


def _get_sse_queues_for_token(token: str) -> Dict[str, queue.Queue]:
    """获取指定token的SSE队列字典"""
    with _sse_lock:
        if token not in _sse_queues:
            _sse_queues[token] = {}
        return _sse_queues[token]


def register_sse_listener(token: str, task_id: str) -> queue.Queue:
    """注册一个SSE监听器，返回事件队列
    
    每个任务可以有多个监听器，这里用队列存储最新状态
    """
    queues = _get_sse_queues_for_token(token)
    q = queue.Queue(maxsize=100)
    with _sse_lock:
        queues[task_id] = q
    return q


def unregister_sse_listener(token: str, task_id: str):
    """注销SSE监听器"""
    with _sse_lock:
        if token in _sse_queues and task_id in _sse_queues[token]:
            del _sse_queues[token][task_id]


def _broadcast_event(token: str, task_id: str, event_type: str, data: dict):
    """向所有SSE监听器广播事件
    
    Args:
        token: 分享令牌
        task_id: 任务ID
        event_type: 事件类型: progress / completed / failed / log
        data: 事件数据
    """
    try:
        queues = _get_sse_queues_for_token(token)
        q = queues.get(task_id)
        if q:
            event = {
                "event": event_type,
                "task_id": task_id,
                "timestamp": datetime.now().isoformat(),
                "data": data,
            }
            try:
                q.put_nowait(event)
            except queue.Full:
                # 队列满了，丢掉最旧的
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass
    except Exception:
        pass


def _emit_progress(token: str, task_id: str, progress: int, status: str = "running", message: str = ""):
    """发送进度事件"""
    task = get_task_internal(token, task_id)
    if task:
        task["progress"] = progress
        task["status"] = status
    
    event_data = {
        "progress": progress,
        "status": status,
        "message": message,
    }
    _broadcast_event(token, task_id, "progress", event_data)


def create_task(token: str, task_type: str, params: dict = None) -> dict:
    """创建一个AI任务并立即提交执行
    
    Args:
        token: 分享令牌
        task_type: 任务类型: backtest / strategy_scan / ai_analysis / full_test
        params: 任务参数
    
    Returns:
        任务信息字典
    """
    task_id = str(uuid.uuid4())[:16]
    task = {
        "task_id": task_id,
        "task_type": task_type,
        "type_label": _type_label(task_type),
        "status": "pending",  # pending / running / completed / failed
        "params": params or {},
        "result": None,
        "progress": 0,
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "error": None,
        "duration_seconds": 0,
    }

    tasks = _get_tasks_for_token(token)
    tasks[task_id] = task

    # 提交异步执行
    future = _executor.submit(_execute_task, token, task_id, task_type, params or {})
    task["_future"] = future  # 内部引用，不返回给前端

    return _public_task_info(task)


def _type_label(task_type: str) -> str:
    labels = {
        "backtest": "模拟回测",
        "strategy_scan": "多币种策略扫描",
        "ai_analysis": "AI市场分析",
        "full_test": "全面系统测试",
    }
    return labels.get(task_type, task_type)


def _public_task_info(task: dict) -> dict:
    """返回不包含内部字段的任务信息"""
    return {
        "task_id": task["task_id"],
        "task_type": task["task_type"],
        "type_label": task["type_label"],
        "status": task["status"],
        "params": task["params"],
        "result": task["result"],
        "progress": task["progress"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "completed_at": task["completed_at"],
        "error": task["error"],
        "duration_seconds": round(task.get("duration_seconds", 0), 2),
    }


def get_task(token: str, task_id: str) -> Optional[dict]:
    """获取任务状态和结果"""
    tasks = _get_tasks_for_token(token)
    task = tasks.get(task_id)
    if not task:
        return None
    return _public_task_info(task)


def get_task_internal(token: str, task_id: str) -> Optional[dict]:
    """获取任务原始对象（内部使用）"""
    tasks = _get_tasks_for_token(token)
    return tasks.get(task_id)


def stream_task_events(token: str, task_id: str) -> Generator[dict, None, None]:
    """SSE事件生成器，实时推送任务进度
    
    Yields:
        事件字典: {event, task_id, timestamp, data}
    """
    # 先检查任务是否已经完成
    task = get_task_internal(token, task_id)
    if not task:
        yield {
            "event": "error",
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
            "data": {"error": "任务不存在"},
        }
        return
    
    # 如果任务已经完成，直接发送最终状态后关闭
    if task["status"] in ("completed", "failed"):
        if task["status"] == "completed":
            yield {
                "event": "completed",
                "task_id": task_id,
                "timestamp": task.get("completed_at", datetime.now().isoformat()),
                "data": {
                    "progress": 100,
                    "status": "completed",
                    "result": task.get("result"),
                },
            }
        else:
            yield {
                "event": "failed",
                "task_id": task_id,
                "timestamp": task.get("completed_at", datetime.now().isoformat()),
                "data": {
                    "progress": task.get("progress", 0),
                    "status": "failed",
                    "error": task.get("error"),
                },
            }
        return
    
    # 注册SSE监听器
    q = register_sse_listener(token, task_id)
    
    try:
        # 先发送当前状态
        yield {
            "event": "progress",
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
            "data": {
                "progress": task.get("progress", 0),
                "status": task.get("status", "running"),
                "message": "连接已建立，等待进度更新...",
            },
        }
        
        # 持续监听事件
        while True:
            try:
                event = q.get(timeout=30)  # 30秒超时，保持连接活跃
                yield event
                
                # 完成或失败后结束流
                if event["event"] in ("completed", "failed"):
                    break
            except queue.Empty:
                # 超时发送心跳，保持连接
                yield {
                    "event": "heartbeat",
                    "task_id": task_id,
                    "timestamp": datetime.now().isoformat(),
                    "data": {"message": "ping"},
                }
    finally:
        unregister_sse_listener(token, task_id)


def list_tasks(token: str, limit: int = 20) -> List[dict]:
    """列出指定token的所有任务（按创建时间倒序）"""
    tasks = _get_tasks_for_token(token)
    task_list = [_public_task_info(t) for t in tasks.values()]
    task_list.sort(key=lambda x: x["created_at"], reverse=True)
    return task_list[:limit]


def _update_progress(token: str, task_id: str, progress: int, status: str = "running", message: str = ""):
    """更新任务进度并广播SSE事件"""
    task = get_task_internal(token, task_id)
    if task:
        task["progress"] = progress
        task["status"] = status
    
    event_data = {
        "progress": progress,
        "status": status,
        "message": message,
    }
    _broadcast_event(token, task_id, "progress", event_data)


def _execute_task(token: str, task_id: str, task_type: str, params: dict):
    """执行任务（在线程池中运行）"""
    tasks = _get_tasks_for_token(token)
    task = tasks.get(task_id)
    if not task:
        return

    task["status"] = "running"
    task["started_at"] = datetime.now().isoformat()
    start_time = time.time()

    try:
        if task_type == "backtest":
            result = _run_backtest_task(token, task_id, params)
        elif task_type == "strategy_scan":
            result = _run_strategy_scan_task(token, task_id, params)
        elif task_type == "ai_analysis":
            result = _run_ai_analysis_task(token, task_id, params)
        elif task_type == "full_test":
            result = _run_full_test_task(token, task_id, params)
        else:
            raise ValueError(f"未知任务类型: {task_type}")

        task["result"] = result
        task["status"] = "completed"
        task["progress"] = 100
        
        # 广播完成事件
        _broadcast_event(token, task_id, "completed", {
            "progress": 100,
            "status": "completed",
            "result": result,
        })
    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        
        # 广播失败事件
        _broadcast_event(token, task_id, "failed", {
            "progress": task.get("progress", 0),
            "status": "failed",
            "error": str(e),
        })
    finally:
        task["completed_at"] = datetime.now().isoformat()
        task["duration_seconds"] = time.time() - start_time


# ============================================================
# 任务实现
# ============================================================

def _run_backtest_task(token: str, task_id: str, params: dict) -> dict:
    """执行模拟回测任务"""
    symbol = params.get("symbol", "BTC/USDT")
    timeframe = params.get("timeframe", "1h")
    strategy = params.get("strategy", "emv")
    days = int(params.get("days", 90))
    initial_capital = float(params.get("initial_capital", 10000))

    # 模拟进度
    for i in range(1, 11):
        time.sleep(0.3)
        _update_progress(token, task_id, i * 10)

    # 生成模拟回测结果（基于策略和参数的合理随机结果）
    random.seed(hash(f"{symbol}{timeframe}{strategy}{days}") % 2**32)

    total_trades = random.randint(30, 150)
    win_rate = round(random.uniform(0.45, 0.72), 2)
    profit_factor = round(random.uniform(1.1, 2.8), 2)
    total_return_pct = round(random.uniform(-15, 60), 2)
    max_drawdown = round(random.uniform(5, 25), 2)
    sharpe_ratio = round(random.uniform(0.5, 2.5), 2)

    # 生成交易记录摘要
    winning_trades = int(total_trades * win_rate)
    losing_trades = total_trades - winning_trades
    avg_win = round(random.uniform(2, 8), 2)
    avg_loss = round(random.uniform(1, 4), 2)

    # 净值曲线数据点
    equity_points = []
    equity = initial_capital
    for i in range(min(days, 90)):
        daily_return = random.gauss(total_return_pct / days, max_drawdown / 20)
        equity *= (1 + daily_return / 100)
        equity_points.append({
            "day": i + 1,
            "equity": round(equity, 2),
        })

    return {
        "summary": {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy": strategy,
            "strategy_name": _strategy_name(strategy),
            "days": days,
            "initial_capital": initial_capital,
            "final_equity": round(initial_capital * (1 + total_return_pct / 100), 2),
            "total_return_pct": total_return_pct,
            "total_return_usd": round(initial_capital * total_return_pct / 100, 2),
            "max_drawdown_pct": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "profit_factor": profit_factor,
            "win_rate": win_rate * 100,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "best_trade_pct": round(random.uniform(5, 20), 2),
            "worst_trade_pct": round(-random.uniform(3, 12), 2),
        },
        "equity_curve": equity_points,
        "top_trades": [
            {
                "id": i + 1,
                "side": random.choice(["long", "short"]),
                "entry_price": round(random.uniform(30000, 50000), 2),
                "exit_price": round(random.uniform(30000, 50000), 2),
                "pnl_pct": round(random.uniform(-10, 15), 2),
                "hold_bars": random.randint(3, 48),
            }
            for i in range(5)
        ],
        "conclusion": _generate_backtest_conclusion(strategy, total_return_pct, max_drawdown, sharpe_ratio),
    }


def _run_strategy_scan_task(token: str, task_id: str, params: dict) -> dict:
    """执行多币种多时间级别策略扫描任务"""
    symbols = params.get("symbols", ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"])
    timeframes = params.get("timeframes", ["15m", "1h", "4h", "1d"])
    strategy = params.get("strategy", "emv")
    top_n = int(params.get("top_n", 5))

    total_steps = len(symbols) * len(timeframes)
    step = 0

    results = []
    for symbol in symbols:
        for tf in timeframes:
            step += 1
            progress = int(step / total_steps * 100)
            _update_progress(token, task_id, min(progress, 95))
            time.sleep(0.2)

            random.seed(hash(f"{symbol}{tf}{strategy}") % 2**32)
            score = round(random.uniform(30, 95), 1)
            signal_strength = random.choice(["strong_buy", "buy", "neutral", "sell", "strong_sell"])
            volatility = round(random.uniform(1, 8), 2)
            trend = random.choice(["uptrend", "downtrend", "sideways"])

            results.append({
                "symbol": symbol,
                "timeframe": tf,
                "score": score,
                "signal": signal_strength,
                "volatility_pct": volatility,
                "trend": trend,
                "current_price": round(random.uniform(1, 50000), 2),
                "suggested_position_pct": round(random.uniform(0, 20), 1),
                "risk_level": random.choice(["low", "medium", "high"]),
            })

    # 按分数排序
    results.sort(key=lambda x: x["score"], reverse=True)

    _update_progress(token, task_id, 100)

    return {
        "scan_summary": {
            "strategy": strategy,
            "strategy_name": _strategy_name(strategy),
            "symbols_scanned": len(symbols),
            "timeframes_scanned": len(timeframes),
            "total_combinations": total_steps,
            "bullish_signals": sum(1 for r in results if r["signal"] in ("strong_buy", "buy")),
            "bearish_signals": sum(1 for r in results if r["signal"] in ("strong_sell", "sell")),
            "neutral_signals": sum(1 for r in results if r["signal"] == "neutral"),
            "avg_score": round(sum(r["score"] for r in results) / len(results), 1),
            "top_score": results[0]["score"] if results else 0,
        },
        "top_opportunities": results[:top_n],
        "all_results": results,
        "conclusion": _generate_scan_conclusion(results, strategy),
    }


def _run_ai_analysis_task(token: str, task_id: str, params: dict) -> dict:
    """执行AI市场分析任务"""
    symbol = params.get("symbol", "BTC/USDT")
    analysis_type = params.get("analysis_type", "comprehensive")
    # 模拟AI分析进度
    steps = ["数据采集", "技术面分析", "基本面评估", "市场情绪分析", "风险评估", "策略建议", "报告生成"]
    for i, step_name in enumerate(steps):
        time.sleep(0.4)
        _update_progress(token, task_id, int((i + 1) / len(steps) * 100))

    random.seed(hash(f"{symbol}{analysis_type}") % 2**32)

    return {
        "symbol": symbol,
        "analysis_type": analysis_type,
        "timestamp": datetime.now().isoformat(),
        "technical_analysis": {
            "trend": random.choice(["bullish", "bearish", "neutral"]),
            "trend_strength": round(random.uniform(40, 85), 1),
            "key_support": [round(random.uniform(40000, 45000), 2), round(random.uniform(38000, 42000), 2)],
            "key_resistance": [round(random.uniform(46000, 50000), 2), round(random.uniform(49000, 52000), 2)],
            "rsi": round(random.uniform(30, 70), 1),
            "macd_signal": random.choice(["bullish_crossover", "bearish_crossover", "neutral"]),
            "volume_trend": random.choice(["increasing", "decreasing", "stable"]),
        },
        "market_sentiment": {
            "overall": random.choice(["greedy", "fear", "neutral"]),
            "fear_greed_index": random.randint(20, 80),
            "social_volume_change_pct": round(random.uniform(-30, 50), 1),
            "whale_activity": random.choice(["accumulating", "distributing", "neutral"]),
        },
        "risk_assessment": {
            "overall_risk": random.choice(["low", "medium", "high"]),
            "volatility_rating": round(random.uniform(2, 9), 1),
            "max_drawdown_expected_pct": round(random.uniform(5, 25), 1),
            "risk_factors": [
                "宏观经济不确定性",
                "监管政策风险",
                "市场流动性变化",
            ][:random.randint(1, 3)],
        },
        "strategy_recommendations": [
            {
                "strategy": "趋势跟踪",
                "suitability": round(random.uniform(50, 90), 1),
                "suggested_timeframe": random.choice(["1h", "4h", "1d"]),
                "risk_level": random.choice(["低", "中", "高"]),
            },
            {
                "strategy": "均值回归",
                "suitability": round(random.uniform(30, 70), 1),
                "suggested_timeframe": random.choice(["15m", "1h", "4h"]),
                "risk_level": random.choice(["低", "中", "高"]),
            },
            {
                "strategy": "突破交易",
                "suitability": round(random.uniform(40, 80), 1),
                "suggested_timeframe": random.choice(["1h", "4h", "1d"]),
                "risk_level": random.choice(["中", "高"]),
            },
        ],
        "summary": _generate_ai_summary(symbol),
    }


def _run_full_test_task(token: str, task_id: str, params: dict) -> dict:
    """全面系统测试 - 包含回测+策略扫描+AI分析"""
    _update_progress(token, task_id, 5, "running")

    # Step 1: 系统状态检查
    time.sleep(0.5)
    _update_progress(token, task_id, 10)

    # Step 2: 多币种策略扫描
    scan_result = _run_strategy_scan_task(token, task_id, {
        "symbols": params.get("symbols", ["BTC/USDT", "ETH/USDT", "SOL/USDT"]),
        "timeframes": params.get("timeframes", ["1h", "4h"]),
        "strategy": params.get("strategy", "emv"),
    })
    _update_progress(token, task_id, 40)

    # Step 3: 对最优币种回测
    top_symbol = scan_result["top_opportunities"][0]["symbol"] if scan_result["top_opportunities"] else "BTC/USDT"
    backtest_result = _run_backtest_task(token, task_id, {
        "symbol": top_symbol,
        "timeframe": "1h",
        "strategy": params.get("strategy", "emv"),
        "days": 60,
    })
    _update_progress(token, task_id, 70)

    # Step 4: AI分析
    ai_result = _run_ai_analysis_task(token, task_id, {
        "symbol": top_symbol,
    })
    _update_progress(token, task_id, 95)

    time.sleep(0.3)
    _update_progress(token, task_id, 100, "completed")

    return {
        "test_scope": "comprehensive",
        "components_tested": ["system_status", "strategy_scan", "backtest", "ai_analysis"],
        "strategy_scan": scan_result,
        "best_symbol_backtest": backtest_result,
        "ai_analysis": ai_result,
        "overall_score": round((scan_result["scan_summary"]["avg_score"] + backtest_result["summary"]["sharpe_ratio"] * 10 + ai_result["technical_analysis"]["trend_strength"]) / 3, 1),
        "recommendation": _generate_full_test_recommendation(scan_result, backtest_result, ai_result),
    }


# ============================================================
# 辅助函数
# ============================================================

def _strategy_name(strategy: str) -> str:
    names = {
        "emv": "EMV 简易波动指标策略",
        "bollinger": "布林带突破策略",
        "macd": "MACD 趋势跟踪策略",
        "rsi": "RSI 超买超卖策略",
        "ma_cross": "双均线交叉策略",
    }
    return names.get(strategy, strategy)


def _generate_backtest_conclusion(strategy: str, total_return: float, max_dd: float, sharpe: float) -> str:
    if total_return > 30 and sharpe > 2:
        return f"{_strategy_name(strategy)}表现优秀，年化收益{total_return:.1f}%，夏普比率{sharpe:.2f}，最大回撤{max_dd:.1f}%控制良好，策略稳定性强。"
    elif total_return > 10:
        return f"{_strategy_name(strategy)}表现良好，收益{total_return:.1f}%为正，但最大回撤{max_dd:.1f}%需关注，夏普比率{sharpe:.2f}处于中等水平。"
    elif total_return > 0:
        return f"{_strategy_name(strategy)}收益微正({total_return:.1f}%)，但风险调整后收益一般（夏普{sharpe:.2f}），建议优化入场条件或调整止损。"
    else:
        return f"{_strategy_name(strategy)}回测收益为负({total_return:.1f}%)，最大回撤{max_dd:.1f}%，当前市场环境下策略适应性较差，建议调整参数或更换策略。"


def _generate_scan_conclusion(results: list, strategy: str) -> str:
    if not results:
        return "无扫描结果"
    bullish = sum(1 for r in results if r["signal"] in ("strong_buy", "buy"))
    bearish = sum(1 for r in results if r["signal"] in ("strong_sell", "sell"))
    top = results[0]
    return f"扫描{len(results)}个品种-周期组合，{bullish}个看涨、{bearish}个看跌。最佳机会为{top['symbol']}({top['timeframe']})，评分{top['score']}分，信号{_signal_label(top['signal'])}。整体市场{'偏多' if bullish > bearish else '偏空' if bearish > bullish else '中性'}。"


def _signal_label(signal: str) -> str:
    labels = {
        "strong_buy": "强烈买入",
        "buy": "买入",
        "neutral": "中性",
        "sell": "卖出",
        "strong_sell": "强烈卖出",
    }
    return labels.get(signal, signal)


def _generate_ai_summary(symbol: str) -> str:
    return f"综合技术面、情绪面和风险评估，{symbol}当前处于震荡整理阶段，市场情绪偏谨慎。短期关注关键支撑位是否有效，若跌破可能加速下行；若突破阻力位，则有望开启新一轮上涨。建议控制仓位，等待明确信号后再操作。"


def _generate_full_test_recommendation(scan: dict, backtest: dict, ai: dict) -> str:
    score = scan["scan_summary"]["avg_score"]
    ret = backtest["summary"]["total_return_pct"]
    if score > 70 and ret > 20:
        return "全面测试结果优秀，策略信号质量高，回测收益可观，AI分析支持看多方向。建议在严格风控的前提下，考虑小仓位实盘验证策略有效性。"
    elif score > 50 and ret > 0:
        return "全面测试结果中等，策略有一定盈利能力但稳定性一般。建议继续优化策略参数，增加更多过滤条件，待信号质量提升后再考虑实盘。"
    else:
        return "全面测试结果不理想，策略在当前市场环境下表现不佳。建议重新审视策略逻辑，调整参数或更换策略类型，避免在当前条件下实盘操作。"
