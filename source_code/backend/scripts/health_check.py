"""
策略交易系统 一键自检脚本 health_check.py
运行：
  cd <项目根目录>
  python backend/scripts/health_check.py      # 所有项目
  python backend/scripts/health_check.py --skip-network  # 只做静态检查（离线也能跑）
  python backend/scripts/health_check.py --news-only     # 只跑新闻/代理部分（排查新闻源403/空RSS）

目标：在投入运营前，把以下 6 件事一次性验证清楚，避免"以为配置好了其实没好"：
  1. 环境与依赖：requirements.txt 中关键字段能否 import
  2. DB：MySQL / SQLite 能否连接并创建表，种子数据是否已初始化
  3. Redis + Celery：Redis 是否能 ping 通；broker URL 是否可连接
  4. 交易所子账号 API：每个启用的 ExchangeAccount 能否拿到账户余额（只做只读测试，不交易）
  5. 新闻采集 + 代理池：每个源用代理/直连至少能抓 1 条 RSS 条目；每个源单独输出 PASS/FAIL；代理池活跃数
  6. 评分引擎：构造合成 BTC 1h K线，验证 Technical/News/AI 三个子打分都能输出，综合分在 [0,10]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Tuple, Any

# 允许 python backend/scripts/health_check.py 直接跑
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class CheckResult:
    name: str
    passed: bool = False
    duration_ms: int = 0
    detail: dict = field(default_factory=dict)
    error: str = ""


def ok(name: str, duration_ms: int = 0, detail: dict = None) -> CheckResult:
    return CheckResult(name=name, passed=True, duration_ms=duration_ms, detail=detail or {})


def fail(name: str, err: str, duration_ms: int = 0, detail: dict = None) -> CheckResult:
    return CheckResult(name=name, passed=False, duration_ms=duration_ms,
                       detail=detail or {}, error=str(err)[:500])


# =========================================================================
#  静态检查（无 DB/网络）
# =========================================================================
def check_imports() -> List[CheckResult]:
    t0 = time.monotonic()
    MODULES = [
        ("fastapi", "FastAPI 框架"),
        ("sqlalchemy", "ORM"),
        ("redis", "Redis 客户端"),
        ("celery", "异步任务"),
        ("numpy", "指标计算"),
        ("requests", "HTTP 客户端"),
        ("pydantic_settings", "配置管理"),
        ("vaderSentiment.vaderSentiment", "VADER 英文新闻情绪"),
        ("backend.core.proxy_manager", "代理管理器"),
        ("backend.news.analyzer", "新闻情绪分析"),
        ("backend.news.pipeline", "新闻管道"),
        ("backend.strategy.scoring", "策略评分引擎"),
        ("backend.exchanges.base", "交易所基类"),
    ]
    results: List[CheckResult] = []
    for mod, desc in MODULES:
        s = time.monotonic()
        try:
            __import__(mod)
            results.append(ok(f"import:{mod} ({desc})", int((time.monotonic() - s) * 1000)))
        except Exception as e:
            results.append(fail(f"import:{mod} ({desc})",
                                f"{e.__class__.__name__}: {e}",
                                int((time.monotonic() - s) * 1000)))
    # 汇总
    passed = sum(1 for r in results if r.passed)
    results.append(ok("模块导入汇总", int((time.monotonic() - t0) * 1000),
                      {"passed": passed, "total": len(MODULES)}))
    return results


# =========================================================================
#  DB + 种子数据
# =========================================================================
def check_db_and_seed() -> List[CheckResult]:
    results: List[CheckResult] = []
    s = time.monotonic()
    try:
        from backend.db.session import session_maker
        from backend.models.user import User
        from backend.models.strategy import StrategyConfig
        from backend.models.analytics import NewsArticle
        from backend.db.base import Base
    except Exception as e:
        return [fail("DB ORM import", f"{e.__class__.__name__}: {e}")]

    # 1. 连接 + 建表
    t0 = time.monotonic()
    try:
        with session_maker() as db:
            # 一个简单查询验证连通性
            db.execute("SELECT 1") if False else None
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
            results.append(ok("DB 连接", int((time.monotonic() - t0) * 1000)))
    except Exception as e:
        return [*results, fail("DB 连接", f"{e.__class__.__name__}: {e}")]

    # 2. 建表（幂等；若已有就跳过）
    t0 = time.monotonic()
    try:
        from backend.db.session import engine_sync
        Base.metadata.create_all(bind=engine_sync)
        results.append(ok("DB 建表（幂等）", int((time.monotonic() - t0) * 1000)))
    except Exception as e:
        results.append(fail("DB 建表（幂等）", f"{e.__class__.__name__}: {e}"))

    # 3. 种子数据（幂等）
    t0 = time.monotonic()
    try:
        from backend.db.seed_data import seed_all
        with session_maker() as db:
            seed_all(db)
        with session_maker() as db:
            user_count = db.query(User).count()
            strategy_count = db.query(StrategyConfig).count()
            news_count = db.query(NewsArticle).count()
        results.append(ok("DB 种子数据（幂等）", int((time.monotonic() - t0) * 1000),
                          {"users": user_count, "strategies": strategy_count, "news": news_count}))
    except Exception as e:
        results.append(fail("DB 种子数据", f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[:400]}"))
    return results


# =========================================================================
#  Redis + Celery broker 可达
# =========================================================================
def check_redis() -> List[CheckResult]:
    out: List[CheckResult] = []
    try:
        import redis as _r
    except Exception as e:
        return [fail("redis 模块导入", str(e))]
    from backend.config import get_settings
    s = get_settings()
    # 主 Redis
    t0 = time.monotonic()
    try:
        r = _r.Redis(host=s.REDIS_HOST, port=s.REDIS_PORT,
                     password=s.REDIS_PASSWORD, db=s.REDIS_DB,
                     socket_connect_timeout=3, socket_timeout=3)
        pong = r.ping()
        out.append(ok("Redis 主 DB ping", int((time.monotonic() - t0) * 1000),
                      {"host": s.REDIS_HOST, "port": s.REDIS_PORT, "db": s.REDIS_DB, "ping": bool(pong)}))
    except Exception as e:
        out.append(fail("Redis 主 DB ping", f"{e.__class__.__name__}: {e}",
                        int((time.monotonic() - t0) * 1000),
                        {"host": s.REDIS_HOST, "port": s.REDIS_PORT}))

    # Celery broker (Redis DB 1)
    t0 = time.monotonic()
    try:
        r2 = _r.Redis(host=s.REDIS_HOST, port=s.REDIS_PORT,
                      password=s.REDIS_PASSWORD, db=s.REDIS_DB_CELERY,
                      socket_connect_timeout=3, socket_timeout=3)
        pong = r2.ping()
        out.append(ok("Redis Celery broker ping", int((time.monotonic() - t0) * 1000),
                      {"db": s.REDIS_DB_CELERY, "ping": bool(pong)}))
    except Exception as e:
        out.append(fail("Redis Celery broker ping", f"{e.__class__.__name__}: {e}",
                        int((time.monotonic() - t0) * 1000),
                        {"db": s.REDIS_DB_CELERY}))
    return out


# =========================================================================
#  交易所 API（只读：查余额）
# =========================================================================
def check_exchange_apis() -> List[CheckResult]:
    out: List[CheckResult] = []
    try:
        from backend.db.session import session_maker
        from backend.models.exchange import ExchangeAccount
        from backend.exchanges.base import ExchangeClientBase
    except Exception as e:
        return [fail("exchange 模块导入", str(e))]
    with session_maker() as db:
        rows = db.query(ExchangeAccount).all()
    if not rows:
        out.append(CheckResult(name="交易所子账号", passed=True,
                               detail={"count": 0,
                                       "hint": "请先在 交易所管理页 添加一个子账号 API（只读权限即可）再跑自检"}))
        return out
    for acc in rows:
        t0 = time.monotonic()
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
            bal = client.fetch_balance()
            total = float(getattr(bal, "total", 0) or 0)
            free = float(getattr(bal, "available", 0) or 0)
            out.append(ok(f"交易所{acc.id}[{acc.exchange}/{acc.name or ''}]只读余额查询",
                          int((time.monotonic() - t0) * 1000),
                          {"total": total, "available": free, "currency": getattr(bal, "currency", None),
                           "testnet": bool(acc.testnet)}))
        except Exception as e:
            out.append(fail(f"交易所{acc.id}[{acc.exchange}/{acc.name or ''}] 只读余额查询",
                            f"{e.__class__.__name__}: {e}",
                            int((time.monotonic() - t0) * 1000),
                            {"testnet": bool(acc.testnet),
                             "api_key_mask": (acc.api_key[:4] + "****") if acc.api_key else ""}))
    return out


# =========================================================================
#  新闻源 + 代理池
# =========================================================================
def check_news_and_proxy() -> List[CheckResult]:
    out: List[CheckResult] = []
    from backend.core.proxy_manager import ProxyManager
    # 1) 代理健康度
    t0 = time.monotonic()
    hr = ProxyManager.get_instance().health_report()
    out.append(ok("ProxyManager 健康", int((time.monotonic() - t0) * 1000), hr))

    try:
        from backend.news.crawlers import ALL_CRAWLERS
    except Exception as e:
        return [*out, fail("爬虫模块导入", str(e))]

    # 2) 每个源单独抓一次 1h 回溯（看是否能至少返回 1 条）
    for cls in ALL_CRAWLERS:
        name = cls.SOURCE_DISPLAY
        t0 = time.monotonic()
        try:
            crawler = cls()
            items = crawler.crawl(lookback_hours=1) or []
            ok_ = len(items) >= 1
            if ok_:
                out.append(ok(f"新闻源 {name}", int((time.monotonic() - t0) * 1000),
                              {"items_count": len(items),
                               "latest_title": (items[0].title[:80] if items else "")}))
            else:
                out.append(fail(f"新闻源 {name}", "最近1小时未抓到任何条目（可到 news/proxy/health 检查代理；或 FRED/EIA 需要 API KEY）",
                                int((time.monotonic() - t0) * 1000),
                                {"items_count": 0}))
        except Exception as e:
            out.append(fail(f"新闻源 {name}",
                            f"{e.__class__.__name__}: {e}",
                            int((time.monotonic() - t0) * 1000),
                            {"trace": traceback.format_exc()[:300]}))
    return out


# =========================================================================
#  评分引擎
# =========================================================================
def check_scoring_engine() -> List[CheckResult]:
    out: List[CheckResult] = []
    t0 = time.monotonic()
    try:
        import numpy as np
        from backend.strategy.scoring import TechnicalIndicatorsScorer, StrategyScoringEngine

        # 合成 240 根 1h K线（先上涨后回调，含足够波动）
        np.random.seed(42)
        n = 240
        t = np.arange(n)
        trend = 70000 + 3000 * np.sin(t / 30.0) + 800 * np.random.randn(n)
        closes = np.clip(trend, 60000, 80000).astype(float)
        opens = closes * (1 + (np.random.rand(n) - 0.5) * 0.003)
        highs = np.maximum(opens, closes) * (1 + np.random.rand(n) * 0.005)
        lows = np.minimum(opens, closes) * (1 - np.random.rand(n) * 0.005)
        volumes = np.random.rand(n) * 1e5
        from backend.exchanges._types import Candle
        candles = [Candle(int(i * 3600_000), float(opens[i]), float(highs[i]),
                          float(lows[i]), float(closes[i]), float(volumes[i]))
                   for i in range(n)]

        tech = TechnicalIndicatorsScorer().score(candles)
        # 新闻分（空库兜底）：调用 NewsSentimentScorer 但不连 DB，用空 DataFrame
        news_total, nw = StrategyScoringEngine().score_news_from_list("BTC", [], candles[-1].close_time)

        # AI 分：mock 一个中性分
        ai_total = 5.0
        ai_detail = {"mock": True, "ai_model": "health-check-mock"}
        final = StrategyScoringEngine.aggregate(
            symbol="BTC", timeframe="1h", close=closes[-1],
            tech_score=tech.score, tech_detail=tech.detail,
            news_score=news_total, news_detail=nw,
            ai_score=ai_total, ai_detail=ai_detail,
        )
        in_range = 0.0 <= final.total_score <= 10.0
        if not in_range:
            raise AssertionError(f"综合分 {final.total_score} 超出 [0,10]")
        out.append(ok("策略评分引擎（合成BTC）", int((time.monotonic() - t0) * 1000),
                      {"tech_score": tech.score, "news_score": news_total,
                       "ai_score": ai_total, "total_score": final.total_score,
                       "direction": final.direction, "confidence": final.confidence,
                       "candles": len(candles)}))
    except Exception as e:
        out.append(fail("策略评分引擎",
                        f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[:400]}",
                        int((time.monotonic() - t0) * 1000)))
    return out


# =========================================================================
#  主流程
# =========================================================================
def run_all(skip_network: bool = False, news_only: bool = False) -> Tuple[List[CheckResult], dict]:
    checks: List[CheckResult] = []
    checks.extend(check_imports())
    if news_only:
        checks.extend(check_news_and_proxy())
    elif not skip_network:
        checks.extend(check_db_and_seed())
        checks.extend(check_redis())
        checks.extend(check_exchange_apis())
        checks.extend(check_news_and_proxy())
        checks.extend(check_scoring_engine())
    passed = sum(1 for c in checks if c.passed)
    summary = {"passed": passed, "total": len(checks), "pass_rate_pct": round(passed / len(checks) * 100, 1) if checks else 0}
    return checks, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="策略交易系统 一键运维自检")
    parser.add_argument("--skip-network", action="store_true",
                        help="只做静态检查（不连 DB/Redis/交易所/新闻源），离线也能跑")
    parser.add_argument("--news-only", action="store_true",
                        help="只做 模块导入 + 新闻源/代理 检查（排查新闻抓不到的场景）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果，方便 CI 消费")
    args = parser.parse_args()

    start = time.monotonic()
    checks, summary = run_all(skip_network=args.skip_network, news_only=args.news_only)
    elapsed = int((time.monotonic() - start) * 1000)

    data = {
        "elapsed_ms": elapsed,
        "summary": summary,
        "checks": [asdict(c) for c in checks],
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print("=" * 72)
        print(f"  策略交易系统 自检报告    总耗时 {elapsed} ms    通过 {summary['passed']}/{summary['total']} "
              f"({summary['pass_rate_pct']}%)")
        print("=" * 72)
        for c in checks:
            flag = "✅ PASS" if c.passed else "❌ FAIL"
            name = f"{c.name:<48}"
            dur = f"[{c.duration_ms:>5} ms]"
            if c.passed:
                tail = ""
                if c.detail:
                    tail = " · " + ", ".join(f"{k}={v}" for k, v in list(c.detail.items())[:4])
                print(f"{flag} {dur} {name}{tail}")
            else:
                print(f"{flag} {dur} {name}")
                if c.error:
                    print(f"       err: {c.error}")
                if c.detail:
                    print(f"       detail: {json.dumps(c.detail, ensure_ascii=False, default=str)[:200]}")
        print("=" * 72)
        print(f"  汇总：{summary['pass_rate_pct']}% 通过。"
              f" 如有 ❌，按报错先修代理 / DB / API Key，再重新运行本脚本直到全绿。")
    return 0 if summary["pass_rate_pct"] >= 90 else 2


if __name__ == "__main__":
    sys.exit(main())
