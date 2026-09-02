"""
D-1 / D-2: 种子数据 + 数据库初始化脚本（幂等）

使用方式：
  1) 作为脚本直接运行：  `python -m backend.db.seed_data`
  2) 从 main.py lifespan 调用：`from backend.db.seed_data import ensure_seed_data; ensure_seed_data()`
  3) 幂等：已存在的 admin 用户 / 策略模板 / 字典数据不会重复插入

内容：
- 创建默认 admin 用户（密码 admin123，若不存在）
- 插入默认策略模板（普通用户登录后可直接"一键复制使用"）
- 插入演示新闻 demo（首次运行空库时）
- 生成若干条 demo 交易历史（供仪表盘展示测试）
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import random

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.db.base import Base
from backend.core.utils import hash_password
from backend.models.user import User, OperationLog
from backend.models.exchange import ExchangeAccount
from backend.models.strategy import StrategyConfig
from backend.models.analytics import NewsArticle, AIAnalysisRecord
from backend.models.trade import TradeOrder, TradePosition


# ===========================
# 常量
# ===========================
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@2024"
DEFAULT_EDITOR_USERNAME = "trader"
DEFAULT_EDITOR_PASSWORD = "Trader@2024"

SUPPORTED_SYMBOLS = [
    {"symbol": "BTC", "name": "比特币", "type": "crypto",
     "default_price": 70000.0, "binance": "BTCUSDT", "okx": "BTC-USDT-SWAP"},
    {"symbol": "ETH", "name": "以太坊", "type": "crypto",
     "default_price": 3500.0, "binance": "ETHUSDT", "okx": "ETH-USDT-SWAP"},
    {"symbol": "SOL", "name": "索拉纳", "type": "crypto",
     "default_price": 180.0, "binance": "SOLUSDT", "okx": "SOL-USDT-SWAP"},
    {"symbol": "XAU", "name": "黄金",   "type": "commodity",
     "default_price": 2350.0, "binance": "",        "okx": "XAU-USDT-SWAP"},
    {"symbol": "WTI", "name": "石油",   "type": "commodity",
     "default_price": 82.0,   "binance": "",        "okx": "WTI-USDT-SWAP"},
]


# ===========================
# 幂等 初始化 入口
# ===========================
def ensure_all(
    db: Session | None = None,
    with_mock_trades: bool = True,
    admin_username: str | None = None,
    admin_password: str | None = None,
    admin_nickname: str | None = None,
    editor_username: str | None = None,
    editor_password: str | None = None,
) -> dict:
    """幂等写入所有种子数据；返回统计信息字典。
    支持通过安装向导传入自定义管理员账号密码（WordPress 式自定义，不强制默认 Admin@2024）
    """
    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True
    stats = {"admin_user": False, "editor_user": False, "strategies": 0,
             "news": 0, "mock_trades": 0, "ts": datetime.now().isoformat()}
    try:
        # 1) 用户（支持传入自定义管理员/交易员账号密码；传入的只有在 DB 不存在该用户时才会生效）
        admin = _ensure_admin_user(
            db, username=admin_username, password=admin_password, nickname=admin_nickname
        )
        if admin:
            stats["admin_user"] = True
            stats["admin_username"] = admin.username
        editor = _ensure_editor_user(
            db, username=editor_username, password=editor_password
        )
        if editor:
            stats["editor_user"] = True
            stats["editor_username"] = editor.username
        # 2) 策略模板（admin 拥有，公开给其它用户复制使用）
        stats["strategies"] = _ensure_default_strategy_templates(db, owner_user=admin or editor)
        # 3) 演示新闻
        stats["news"] = _ensure_demo_news(db)
        # 4) Mock 交易数据（只有空库时写入）
        if with_mock_trades:
            trader = editor or admin
            stats["mock_trades"] = _ensure_mock_trades(db, trader)
        db.commit()
        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


# 对外多个别名，避免不同调用方记混（health_check.py 用 seed_all，main.py 用 ensure_all / ensure_seed_data）
seed_all = ensure_all
ensure_seed_data = ensure_all


# ===========================
# 各具体项
# ===========================
def _ensure_admin_user(
    db: Session,
    username: str | None = None,
    password: str | None = None,
    nickname: str | None = None,
) -> User | None:
    """创建管理员账号；支持通过安装向导传入自定义账号密码（只有当用户名为空/默认才用默认 admin/Admin@2024）"""
    final_username = (username or DEFAULT_ADMIN_USERNAME).strip() or DEFAULT_ADMIN_USERNAME
    final_password = (password or DEFAULT_ADMIN_PASSWORD) or DEFAULT_ADMIN_PASSWORD
    final_nickname = (nickname or "超级管理员") or "超级管理员"
    # 已存在同名用户就跳过（幂等）
    exists = db.query(User).filter(User.username == final_username).first()
    if exists:
        # 如果传入了新密码，就强制更新密码 hash（安装向导改密需要）
        if password:
            exists.password_hash = hash_password(final_password)
            db.flush()
            db.add(OperationLog(
                user_id=exists.id, action="SYSTEM_INIT", module="seed_data",
                detail=f"安装向导更新管理员密码：{final_username}",
                ip="127.0.0.1",
            ))
            return exists
        return None
    u = User(
        username=final_username,
        nickname=final_nickname,
        password_hash=hash_password(final_password),
        role=1,                    # 超级管理员
        status=1,
        email="admin@example.com",
        phone="13800000000",
    )
    db.add(u)
    db.flush()
    db.add(OperationLog(
        user_id=u.id, action="SYSTEM_INIT", module="seed_data",
        detail=f"安装向导创建管理员账号 {final_username}",
        ip="127.0.0.1",
    ))
    return u


def _ensure_editor_user(
    db: Session,
    username: str | None = None,
    password: str | None = None,
) -> User | None:
    final_username = (username or DEFAULT_EDITOR_USERNAME).strip() or DEFAULT_EDITOR_USERNAME
    final_password = (password or DEFAULT_EDITOR_PASSWORD) or DEFAULT_EDITOR_PASSWORD
    exists = db.query(User).filter(User.username == final_username).first()
    if exists:
        if password:
            exists.password_hash = hash_password(final_password)
            db.flush()
        return None
    u = User(
        username=final_username,
        nickname="交易员演示账号",
        password_hash=hash_password(final_password),
        role=2,  # 编辑/交易员
        status=1,
        email="trader@example.com",
        phone="13900000000",
    )
    db.add(u)
    db.flush()
    db.add(OperationLog(
        user_id=u.id, action="SYSTEM_INIT", module="seed_data",
        detail=f"创建默认演示账号 {final_username}",
        ip="127.0.0.1",
    ))
    return u


def _ensure_default_strategy_templates(db: Session, owner_user: User | None) -> int:
    """写入 3 套策略模板，供复制使用"""
    if not owner_user:
        return 0
    tpls = [
        {
            "name": "保守型 BTC/ETH 1H/4H 智能跟随",
            "desc": "低波动率品种3x杠杆，5%TP/1.5%SL，日亏损上限3%",
            "symbols": ["BTC", "ETH"],
            "leverage_mode": 1, "leverage_fixed": 3,
            "tp_ratio": 5.0, "sl_ratio": 1.5,
            "single_position_ratio": 5.0,
            "max_position_count": 2,
            "daily_max_loss": 3.0,
        },
        {
            "name": "平衡型 5大主流币动态杠杆",
            "desc": "BTC/ETH/SOL/XAU/WTI 全品种，动态杠杆3-8x，4%TP/2%SL",
            "symbols": ["BTC", "ETH", "SOL", "XAU", "WTI"],
            "leverage_mode": 2, "leverage_fixed": 3,
            "leverage_low_score": 3, "leverage_mid_score": 5, "leverage_high_score": 8,
            "tp_ratio": 4.0, "sl_ratio": 2.0,
            "single_position_ratio": 10.0,
            "max_position_count": 3,
            "daily_max_loss": 5.0,
        },
        {
            "name": "激进型 SOL 短线 15M/1H",
            "desc": "仅SOL，评分阈值 6，动态杠杆最高10x，3%TP/1.2%SL",
            "symbols": ["SOL"],
            "timeframe": "15m,1h",
            "score_threshold": 6.0,
            "direction_mode": 0,
            "leverage_mode": 2, "leverage_fixed": 5,
            "leverage_low_score": 4, "leverage_mid_score": 8, "leverage_high_score": 10,
            "tp_ratio": 3.0, "sl_ratio": 1.2,
            "single_position_ratio": 12.0,
            "max_position_count": 2,
            "max_single_drawdown": 1.5,
            "daily_max_loss": 7.0,
        },
    ]
    inserted = 0
    for t in tpls:
        # 幂等：同名
        exists = db.query(StrategyConfig).filter(
            StrategyConfig.user_id == owner_user.id,
            StrategyConfig.strategy_name == t["name"],
        ).first()
        if exists:
            continue
        s = StrategyConfig(
            user_id=owner_user.id,
            strategy_name=t["name"],
            description=t.get("desc", ""),
            symbols=t["symbols"],
            timeframe=t.get("timeframe", "1h,4h"),
            direction_mode=t.get("direction_mode", 0),
            run_mode=3,   # 默认模拟盘
            score_threshold=t.get("score_threshold", 5.0),
            strong_score_threshold=t.get("strong_score_threshold", 8.0),
            weight_technical=0.4, weight_news=0.3, weight_ai=0.3,
            leverage_mode=t.get("leverage_mode", 1),
            leverage_fixed=t.get("leverage_fixed", 3),
            leverage_low_score=t.get("leverage_low_score", 3),
            leverage_mid_score=t.get("leverage_mid_score", 5),
            leverage_high_score=t.get("leverage_high_score", 8),
            tp_ratio=t.get("tp_ratio", 4.0),
            sl_ratio=t.get("sl_ratio", 2.0),
            use_exchange_tpsl=True,
            single_position_ratio=t.get("single_position_ratio", 10.0),
            total_position_ratio=50.0,
            max_position_count=t.get("max_position_count", 3),
            max_single_drawdown=t.get("max_single_drawdown", 2.0),
            daily_max_loss=t.get("daily_max_loss", 5.0),
            consecutive_loss_pause=3,
            cooldown_hours=24,
            is_active=True,
            priority=0,
        )
        db.add(s)
        inserted += 1
    return inserted


def _ensure_demo_news(db: Session) -> int:
    cnt = db.query(func.count()).select_from(NewsArticle).scalar() or 0
    if cnt > 0:
        return 0
    now = datetime.now()
    demo = [
        dict(source=3, source_id="seed-1",
             title="美联储暗示暂停加息，风险资产集体走强",
             summary="FOMC会议纪要显示多数委员赞成维持利率不变，年底或开始降息讨论",
             category="macro", tags=["Fed","interest","BTC","ETH"],
             related_symbols=["BTC","ETH","SOL"],
             sentiment=1, sentiment_score=0.7, impact_level=3, is_hot=True,
             published_at=now - timedelta(hours=2)),
        dict(source=2, source_id="seed-2",
             title="贝莱德申请SOL现货ETF，SOL应声大涨",
             summary="SOL生态活跃度激增，DeFi锁仓量月增20%",
             category="exchange", tags=["ETF","SOL"],
             related_symbols=["SOL"],
             sentiment=1, sentiment_score=0.8, impact_level=3, is_hot=True,
             published_at=now - timedelta(hours=5)),
        dict(source=3, source_id="seed-3",
             title="美国SEC推迟BTC现货ETF审批至年底",
             summary="市场担忧监管不确定性，BTC短线插针回撤",
             category="regulation", tags=["SEC","ETF","BTC"],
             related_symbols=["BTC"],
             sentiment=-1, sentiment_score=-0.55, impact_level=3, is_hot=True,
             published_at=now - timedelta(hours=8)),
        dict(source=3, source_id="seed-4",
             title="OPEC+月度会议决定延续减产，WTI突破82美元",
             summary="OPEC+成员国一致同意延长减产期限至2026年Q1，油价创近3月新高",
             category="macro", tags=["OPEC","oil","WTI"],
             related_symbols=["WTI","XAU"],
             sentiment=1, sentiment_score=0.65, impact_level=4, is_hot=True,
             published_at=now - timedelta(hours=1)),
        dict(source=1, source_id="seed-5",
             title="中东地缘冲突加剧，黄金避险需求升温",
             summary="黄金现货突破2350美元/盎司，创历史新高附近",
             category="macro", tags=["gold","geopolitics"],
             related_symbols=["XAU"],
             sentiment=1, sentiment_score=0.6, impact_level=3, is_hot=False,
             published_at=now - timedelta(hours=3)),
        dict(source=4, source_id="seed-6",
             title="ETH坎昆升级尘埃落定，Layer2手续费大幅下降",
             summary="坎昆升级主网上线满1周，Arbitrum/Optimism日活跃地址增长2位数",
             category="onchain", tags=["ETH","Layer2","坎昆"],
             related_symbols=["ETH"],
             sentiment=1, sentiment_score=0.45, impact_level=2, is_hot=False,
             published_at=now - timedelta(hours=10)),
        dict(source=5, source_id="seed-7",
             title="华尔街分析师警告BTC短期超买，RSI逼近80",
             summary="多家机构分析师指出BTC日线KDJ严重超买，或有回调风险",
             category="macro", tags=["BTC","超买","技术分析"],
             related_symbols=["BTC","ETH"],
             sentiment=-1, sentiment_score=-0.4, impact_level=2, is_hot=False,
             published_at=now - timedelta(hours=4)),
    ]
    for d in demo:
        db.add(NewsArticle(analyzed_at=now, **d))
    return len(demo)


def _ensure_mock_trades(db: Session, user: User | None) -> int:
    """空库时生成最近 30 天 约 60 条历史仓位记录，用于 Dashboard 展示测试"""
    if not user:
        return 0
    cnt = db.query(func.count()).select_from(TradePosition).scalar() or 0
    if cnt > 0:
        return 0
    random.seed(42)
    # 1) 先给用户建一个"模拟演示子账号"（无需真实API）
    acc = ExchangeAccount(
        user_id=user.id,
        exchange=2,  # OKX
        sub_account_name="演示OKX子账号（Mock）",
        sub_account_id="mock-okx-001",
        api_key="MOCK_" + "A" * 32,
        api_secret="MOCK_" + "B" * 32,
        api_passphrase="",
        ip_whitelist="",
        initial_balance=Decimal("10000.0"),
        current_balance=Decimal("11234.56"),
        available_balance=Decimal("7654.32"),
        margin_balance=Decimal("3580.24"),
        unrealized_pnl=Decimal("123.45"),
        realized_pnl_total=Decimal("1234.56"),
        leverage_max=10,
        balance_updated_at=datetime.now(),
        status=1,
        testnet=True,
        remark="自动创建的演示子账号，仅供前端展示数据使用",
    )
    db.add(acc); db.flush()

    # 2) 给这个用户也关联上一套策略
    strategy = db.query(StrategyConfig).filter(
        StrategyConfig.user_id == user.id
    ).first()
    if not strategy:
        strategy = StrategyConfig(
            user_id=user.id,
            strategy_name="演示策略 · 5大主流币平衡型",
            description="用于前端展示的演示策略（实际不产生真实交易）",
            symbols=["BTC","ETH","SOL","XAU","WTI"],
            timeframe="1h,4h",
            run_mode=3,
            exchange_id=acc.id,
            is_active=True,
            score_threshold=5.0,
            weight_technical=0.4, weight_news=0.3, weight_ai=0.3,
            leverage_mode=2, leverage_fixed=3,
            leverage_low_score=3, leverage_mid_score=5, leverage_high_score=8,
            tp_ratio=4.0, sl_ratio=2.0,
            single_position_ratio=10.0, max_position_count=3,
            max_single_drawdown=2.0, daily_max_loss=5.0,
        )
        db.add(strategy); db.flush()

    # 3) 生成过去30天内 60 条历史仓位（约每天2条）
    symbols = SUPPORTED_SYMBOLS
    now = datetime.now()
    n = 60
    created = 0
    for i in range(n):
        s = random.choice(symbols)
        side = random.choice([1, 2])
        # 时间分布：倒序往前推，每天2条
        days_back = int(i / 2)
        hours_back = (i % 2) * 8 + random.randint(0, 7)
        entry_dt = now - timedelta(days=days_back, hours=hours_back)
        close_dt = entry_dt + timedelta(hours=random.randint(2, 36))
        base_price = s["default_price"]
        noise = random.uniform(-0.05, 0.05)    # ±5%
        entry_price = base_price * (1 + noise)
        # 每笔 pnl_ratio 正态分布，均值正一点点，std 偏大
        pnl_ratio = random.gauss(1.5, 6.0)       # 期望 +1.5%，σ=6%
        leverage = random.choice([3, 3, 4, 5, 5, 8, 10])
        if side == 1:
            close_price = entry_price * (1 + pnl_ratio / 100 / leverage)
        else:
            close_price = entry_price * (1 - pnl_ratio / 100 / leverage)
        qty_usdt = float(random.choice([300, 500, 800, 1000, 1500]))
        qty_contracts = qty_usdt / entry_price
        margin = qty_usdt / leverage
        realized = margin * pnl_ratio / 100.0
        # 平仓原因
        if pnl_ratio >= 3.8:
            close_reason = 3   # TP
        elif pnl_ratio <= -1.8:
            close_reason = 4   # SL
        else:
            close_reason = random.choice([1, 8, 2])  # 手动/评分反转/其它

        pos = TradePosition(
            user_id=user.id,
            exchange_account_id=acc.id,
            strategy_id=strategy.id if strategy else None,
            exchange=acc.exchange,
            symbol=s["symbol"],
            side=side,
            leverage=leverage,
            entry_price=Decimal(str(round(entry_price, 8))),
            mark_price=Decimal(str(round(close_price, 8))),
            quantity_contracts=Decimal(str(round(qty_contracts, 8))),
            quantity_usdt=Decimal(str(qty_usdt)),
            margin_used=Decimal(str(round(margin, 8))),
            tp_price=Decimal(str(round(entry_price * (1 + (4/100)/leverage if side==1 else 1-(4/100)/leverage), 8))),
            sl_price=Decimal(str(round(entry_price * (1 - (2/100)/leverage if side==1 else 1+(2/100)/leverage), 8))),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal(str(round(realized, 8))),
            pnl_ratio=float(pnl_ratio),
            max_drawdown_ratio=float(abs(pnl_ratio)) if pnl_ratio < 0 else random.uniform(0.5, 2.0),
            fee_total=Decimal(str(round(qty_usdt * 0.0004, 6))),
            status=2,
            close_reason=close_reason,
            entry_score=round(random.uniform(5.0, 9.5), 2),
            entry_time=entry_dt,
            close_time=close_dt,
            close_price=Decimal(str(round(close_price, 8))),
            holding_minutes=int((close_dt - entry_dt).total_seconds() // 60),
        )
        db.add(pos)
        created += 1

        # 对应订单（可选）
        order = TradeOrder(
            exchange_account_id=acc.id,
            strategy_id=strategy.id if strategy else None,
            user_id=user.id,
            exchange=acc.exchange,
            client_order_id=f"MOCK{i:05d}",
            exchange_order_id=f"EX{i:08d}",
            symbol=s["symbol"],
            side=side,
            order_type=1,
            leverage=leverage,
            quantity_contracts=Decimal(str(round(qty_contracts, 8))),
            quantity_usdt=Decimal(str(qty_usdt)),
            avg_fill_price=Decimal(str(round(entry_price, 8))),
            order_price=Decimal(str(round(entry_price, 8))),
            tp_price=pos.tp_price,
            sl_price=pos.sl_price,
            margin_used=Decimal(str(round(margin, 8))),
            trigger_reason=2 if random.random() < 0.7 else 1,
            trigger_score=float(pos.entry_score or 5.0),
            status=2,
            realized_pnl=Decimal(str(round(realized, 8))),
            fee=Decimal(str(round(qty_usdt * 0.0004, 6))),
            submitted_at=entry_dt,
            filled_at=entry_dt,
        )
        db.add(order)
    # 还加 1-2 个持仓中
    for i in range(min(2, len(symbols))):
        s = symbols[i]
        entry_dt = now - timedelta(hours=random.randint(2, 30))
        base_price = s["default_price"]
        noise = random.uniform(-0.02, 0.02)
        entry_price = base_price * (1 + noise)
        mark_price = entry_price * (1 + random.uniform(-0.01, 0.02))
        leverage = random.choice([3, 5])
        qty_usdt = 800
        qty_contracts = qty_usdt / entry_price
        margin = qty_usdt / leverage
        db.add(TradePosition(
            user_id=user.id,
            exchange_account_id=acc.id,
            strategy_id=strategy.id if strategy else None,
            exchange=acc.exchange,
            symbol=s["symbol"],
            side=random.choice([1, 2]),
            leverage=leverage,
            entry_price=Decimal(str(round(entry_price, 8))),
            mark_price=Decimal(str(round(mark_price, 8))),
            quantity_contracts=Decimal(str(round(qty_contracts, 8))),
            quantity_usdt=Decimal(str(qty_usdt)),
            margin_used=Decimal(str(round(margin, 8))),
            unrealized_pnl=Decimal(str(round((mark_price - entry_price) * qty_contracts, 8))),
            realized_pnl=Decimal(0),
            pnl_ratio=float((mark_price - entry_price) / entry_price * 100 * leverage * (1 if random.random()<0.5 else -1)),
            status=1,
            entry_time=entry_dt,
            holding_minutes=int((now - entry_dt).total_seconds() // 60),
        ))
    return created


# ===========================
# CLI
# ===========================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-mock", action="store_true", help="不生成 Mock 交易数据")
    args = parser.parse_args()

    # 1) 创建表结构（Base.metadata.create_all）；生产环境一般用 alembic
    from backend.db.session import engine
    Base.metadata.create_all(bind=engine)
    print("[Seed] 数据库表结构同步（create_all if not exists）")

    stats = ensure_all(with_mock_trades=not args.no_mock)
    print("[Seed] 写入结果:", stats)
    if stats["admin_user"]:
        print(f"[Seed] 管理员账号已创建: {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")
    if stats["editor_user"]:
        print(f"[Seed] 交易员演示账号已创建: {DEFAULT_EDITOR_USERNAME} / {DEFAULT_EDITOR_PASSWORD}")
