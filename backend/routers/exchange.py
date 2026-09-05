"""
交易所子账号管理 路由
GET    /exchange/accounts           子账号列表
POST   /exchange/accounts           绑定子账号
PUT    /exchange/accounts/{id}      更新子账号
DELETE /exchange/accounts/{id}      删除子账号
POST   /exchange/accounts/{id}/sync 同步余额/持仓
GET    /exchange/accounts/{id}/balance 余额
GET    /exchange/accounts/{id}/positions 持仓
POST   /exchange/accounts/{id}/test-connection 连通性测试
POST   /exchange/accounts/{id}/cancel-all-open-orders 撤销全部挂单
GET    /exchange/supported-symbols  支持的交易品种
GET    /exchange/ticker/{symbol}    最新价格
"""
import time
import threading
from datetime import datetime
from fastapi import APIRouter, Depends

from backend.core.logging_config import logger
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.db.session import get_db
from backend.core.auth import get_current_user, require_editor
from backend.core.exceptions import (
    NotFoundException, ParameterException, RiskControlException, success, BizException,
)
from backend.core.security import encrypt_api_key, decrypt_api_key
from backend.core.schemas import ApiResponse, PaginationParams, paginate
from backend.models.user import User
from backend.models.exchange import ExchangeAccount
from backend.models.trade import TradeOrder, TradePosition
from backend.exchanges.base import ExchangeClientBase
from backend.exchanges.market import MarketManager
from backend.exchanges._types import (
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, SIDE_LONG, SIDE_SHORT,
)
from backend.exchanges._types import Ticker as TickerType
from backend.exchanges._types import Candle as CandleType

router = APIRouter(prefix="/exchange", tags=["交易所子账号"])

_MOCK_PRICES = {
    "BTC": 78000, "ETH": 2400, "SOL": 100,
    "XAU": 2500, "XAG": 30, "WTI": 75,
    "TSLA": 250, "NVDA": 120, "AAPL": 220, "MSFT": 420, "TCEHY": 60,
    "SKHYNIX": 1219.75, "SNDK": 1555.05,
}

def _gen_mock_ticker(symbol):
    import random
    base = _MOCK_PRICES.get(symbol, 100)
    change = random.uniform(-0.02, 0.02)
    last = base * (1 + change)
    return TickerType(
        symbol=symbol,
        last_price=round(last, 2),
        bid_price=round(last * 0.999, 2),
        ask_price=round(last * 1.001, 2),
        high_24h=round(last * 1.01, 2),
        low_24h=round(last * 0.99, 2),
        volume_24h=round(random.uniform(10000, 100000), 2),
        change_pct_24h=round(change * 100, 3),
        timestamp_ms=int(time.time() * 1000),
    )

_TF_MS = {"1m":60000,"5m":300000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000,"1w":604800000,"1M":2592000000,"1y":31536000000}

def _gen_mock_klines(symbol, timeframe, limit):
    import random
    base = _MOCK_PRICES.get(symbol, 100)
    interval = _TF_MS.get(timeframe, 3600000)
    now_ms = int(time.time() * 1000)
    candles = []
    price = base
    for i in range(limit):
        ts = now_ms - (limit - i) * interval
        o = price
        change = random.uniform(-0.005, 0.005)
        c = round(o * (1 + change), 2)
        h = round(max(o, c) * (1 + random.uniform(0, 0.003)), 2)
        l = round(min(o, c) * (1 - random.uniform(0, 0.003)), 2)
        v = round(random.uniform(1000, 50000), 2)
        candles.append(CandleType(
            symbol=symbol, timeframe=timeframe,
            open_time_ms=ts, open=o, high=h, low=l, close=c, volume=v,
            close_time_ms=ts + interval - 1,
        ))
        price = c
    return candles

SUPPORTED_SYMBOLS = [
    {"symbol": "BTC", "name": "比特币", "binance": "BTCUSDT", "okx": "BTC-USDT-SWAP", "bybit": "BTCUSDT", "type": "crypto"},
    {"symbol": "ETH", "name": "以太坊", "binance": "ETHUSDT", "okx": "ETH-USDT-SWAP", "bybit": "ETHUSDT", "type": "crypto"},
    {"symbol": "SOL", "name": "索拉纳", "binance": "SOLUSDT", "okx": "SOL-USDT-SWAP", "bybit": "SOLUSDT", "type": "crypto"},
    {"symbol": "XAU", "name": "黄金",   "binance": "",        "okx": "XAU-USDT-SWAP", "bybit": "XAUUSDT", "type": "commodity"},
    {"symbol": "WTI", "name": "石油",   "binance": "",        "okx": "WTI-USDT-SWAP", "bybit": "CLUSDT",  "type": "commodity"},
    {"symbol": "TSLA", "name": "特斯拉", "binance": "", "okx": "TSLA-USDT-SWAP", "bybit": "TSLAUSDT", "type": "stock"},
    {"symbol": "NVDA", "name": "英伟达", "binance": "", "okx": "NVDA-USDT-SWAP", "bybit": "NVDAUSDT", "type": "stock"},
    {"symbol": "AAPL", "name": "苹果",   "binance": "", "okx": "AAPL-USDT-SWAP", "bybit": "AAPLUSDT", "type": "stock"},
    {"symbol": "MSFT", "name": "微软",   "binance": "", "okx": "MSFT-USDT-SWAP", "bybit": "MSFTUSDT", "type": "stock"},
    {"symbol": "TCEHY", "name": "腾讯",  "binance": "", "okx": "TCEHY-USDT-SWAP", "bybit": "TCEHYUSDT", "type": "stock"},
    {"symbol": "SKHYNIX", "name": "SK海力士", "binance": "", "okx": "SKHYNIX-USDT-SWAP", "bybit": "SKHYNIXUSDT", "type": "stock"},
    {"symbol": "SNDK", "name": "闪迪",   "binance": "", "okx": "SNDK-USDT-SWAP", "bybit": "SNDKUSDT", "type": "stock"},
]


# ==========================================================
#  K线缓存（短 TTL，避免频繁请求交易所）
# ==========================================================
_kline_cache = {}  # key: (symbol, timeframe, limit) -> (timestamp, data)
_kline_cache_lock = threading.Lock()
KLINE_CACHE_TTL = 10  # 秒，主周期缓存10秒
DAILY_CACHE_TTL = 300  # 秒，日线数据缓存5分钟（变化慢）


def _cached_fetch_klines(client, symbol, timeframe, limit, ttl=None):
    """带缓存的 K 线拉取，相同参数在 TTL 内直接返回缓存"""
    if ttl is None:
        ttl = DAILY_CACHE_TTL if timeframe in ("1d", "1w", "1M", "1y") else KLINE_CACHE_TTL
    key = (symbol, timeframe, limit)
    now = time.time()
    with _kline_cache_lock:
        if key in _kline_cache:
            ts, data = _kline_cache[key]
            if now - ts < ttl:
                return data

    # 年线特殊处理：从日线数据聚合成年线
    if timeframe == "1y":
        daily_limit = max(limit * 365, 365)
        try:
            daily_data = client.fetch_klines(symbol, "1d", limit=daily_limit)
            data = _aggregate_yearly_klines(daily_data, symbol)
        except Exception as e:
            logger.warning(f"[Exchange] 年线聚合失败(symbol={symbol}): {e} — 返回模拟数据")
            data = _gen_mock_klines(symbol, timeframe, limit)
        with _kline_cache_lock:
            _kline_cache[key] = (now, data)
        return data

    # 缓存未命中，实际请求
    try:
        data = client.fetch_klines(symbol, timeframe, limit=limit)
    except Exception as e:
        logger.warning(f"[Exchange] K线拉取失败(symbol={symbol} tf={timeframe}): {e} — 返回模拟数据")
        data = _gen_mock_klines(symbol, timeframe, limit)
    with _kline_cache_lock:
        _kline_cache[key] = (now, data)
    return data


def _aggregate_yearly_klines(daily_candles, symbol):
    """将日线K线聚合成年线K线"""
    from datetime import datetime as _dt
    yearly = {}
    for c in daily_candles:
        dt = _dt.fromtimestamp(c.open_time_ms / 1000)
        year = dt.year
        if year not in yearly:
            yearly[year] = {
                "open_time_ms": c.open_time_ms,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "close_time_ms": c.close_time_ms,
            }
        else:
            y = yearly[year]
            y["high"] = max(y["high"], c.high)
            y["low"] = min(y["low"], c.low)
            y["close"] = c.close
            y["volume"] += c.volume
            y["close_time_ms"] = c.close_time_ms

    candles = []
    for year in sorted(yearly.keys()):
        y = yearly[year]
        candles.append(CandleType(
            symbol=symbol, timeframe="1y",
            open_time_ms=y["open_time_ms"],
            open=y["open"], high=y["high"], low=y["low"],
            close=y["close"], volume=y["volume"],
            close_time_ms=y["close_time_ms"],
        ))
    logger.info(f"[Exchange] 年线聚合完成: {len(daily_candles)} 根日线 -> {len(candles)} 根年线")
    return candles


# ==========================================================
#  辅助：构建交易所 client + 权限校验
# ==========================================================
def _get_account(db: Session, user: User, aid: int) -> ExchangeAccount:
    account = db.query(ExchangeAccount).filter(
        ExchangeAccount.id == aid,
        (ExchangeAccount.user_id == user.id) | (user.role == 1),
    ).first()
    if not account:
        raise NotFoundException("子账号不存在")
    if account.status == 0:
        raise BizException("该子账号已被禁用")
    # 审计日志：管理员操作他人账号时记录
    if user.role == 1 and account.user_id != user.id:
        logger.warning(
            f"[AUDIT] 管理员 {user.username}(id={user.id}) 访问了用户 "
            f"id={account.user_id} 的交易所子账号 id={account.id} ({account.sub_account_name})"
        )
    return account


def _build_client(account: ExchangeAccount) -> ExchangeClientBase:
    client = ExchangeClientBase.create(
        exchange=account.exchange,
        api_key=decrypt_api_key(account.api_key) or "",
        api_secret=decrypt_api_key(account.api_secret) or "",
        passphrase=decrypt_api_key(account.api_passphrase) or "",
        testnet=bool(account.testnet),
        exchange_account_id=account.id,
    )
    client.connect()
    return client


# ==========================================================
#  基础 CRUD
# ==========================================================
class CreateAccountReq(BaseModel):
    exchange: int = Field(..., ge=1, le=3, description="1-币安 2-OKX 3-Bybit")
    sub_account_name: str = Field(..., min_length=1, max_length=64)
    sub_account_id: str = ""
    api_key: str = Field(..., min_length=8)
    api_secret: str = Field(..., min_length=8)
    api_passphrase: str = ""
    ip_whitelist: str = ""
    leverage_max: int = Field(default=5, ge=1, le=10)
    testnet: bool = True
    remark: str = ""


class UpdateAccountReq(BaseModel):
    sub_account_name: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    ip_whitelist: str = ""
    leverage_max: int | None = None
    status: int | None = None
    remark: str = ""


@router.get("/supported-symbols")
def supported_symbols():
    """系统支持的5个交易品种"""
    return success(SUPPORTED_SYMBOLS)


@router.get("/accounts", response_model=ApiResponse[dict])
def list_accounts(
    q: PaginationParams = Depends(),
    exchange: int | None = None,
    status: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """子账号列表（管理员看全部，其他看自己）"""
    query = db.query(ExchangeAccount)
    if user.role != 1:
        query = query.filter(ExchangeAccount.user_id == user.id)
    if exchange is not None:
        query = query.filter(ExchangeAccount.exchange == exchange)
    if status is not None:
        query = query.filter(ExchangeAccount.status == status)
    data = paginate(query, q.page, q.page_size, q.order_by)
    # 附加交易中状态
    for item in data["items"]:
        item["trading_enabled"] = item["status"] == 1
    return success(data)


@router.post("/accounts")
def create_account(
    req: CreateAccountReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """绑定交易所子账号"""
    if req.leverage_max > 10:
        raise ParameterException("系统最大杠杆不得超过10倍")
    account = ExchangeAccount(
        user_id=user.id,
        exchange=req.exchange,
        sub_account_name=req.sub_account_name,
        sub_account_id=req.sub_account_id,
        api_key=encrypt_api_key(req.api_key),
        api_secret=encrypt_api_key(req.api_secret),
        api_passphrase=encrypt_api_key(req.api_passphrase) if req.api_passphrase else "",
        ip_whitelist=req.ip_whitelist,
        leverage_max=req.leverage_max,
        testnet=req.testnet,
        remark=req.remark,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return success({"id": account.id}, message="子账号绑定成功")


@router.put("/accounts/{aid}")
def update_account(
    aid: int,
    req: UpdateAccountReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新子账号配置"""
    account = _get_account(db, user, aid)
    if req.sub_account_name:
        account.sub_account_name = req.sub_account_name
    if req.api_key:
        account.api_key = encrypt_api_key(req.api_key)
    if req.api_secret:
        account.api_secret = encrypt_api_key(req.api_secret)
    if req.api_passphrase is not None:
        account.api_passphrase = encrypt_api_key(req.api_passphrase) if req.api_passphrase else ""
    if req.ip_whitelist is not None:
        account.ip_whitelist = req.ip_whitelist
    if req.leverage_max is not None:
        if req.leverage_max > 10:
            raise ParameterException("最大杠杆不得超过10倍")
        account.leverage_max = req.leverage_max
    if req.status is not None:
        account.status = req.status
    if req.remark is not None:
        account.remark = req.remark
    db.commit()
    return success(message="修改成功")


@router.delete("/accounts/{aid}")
def delete_account(
    aid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """删除子账号（若有持仓禁止删除）"""
    account = _get_account(db, user, aid)
    # 若有活跃持仓禁止删除
    holding = db.query(TradePosition).filter(
        TradePosition.exchange_account_id == aid,
        TradePosition.status == 1,  # 持仓中
    ).first()
    if holding:
        raise RiskControlException("该账号仍有未平仓持仓，请先平仓后再删除")
    db.delete(account)
    db.commit()
    return success(message="删除成功")


# ==========================================================
#  对接真实交易所
# ==========================================================
@router.post("/accounts/{aid}/test-connection")
def test_connection(aid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """连通性测试：拉取账户余额，若异常将 status 置为 2(API异常)"""
    account = _get_account(db, user, aid)
    try:
        client = _build_client(account)
        bal = client.fetch_balance()
        # 成功
        account.status = 1
        account.current_balance = bal.total
        account.available_balance = bal.available
        account.margin_balance = bal.used_margin
        account.unrealized_pnl = bal.unrealized_pnl
        account.balance_updated_at = datetime.now()
        db.commit()
        # 注册到 MarketManager
        MarketManager.get_instance().register_client(client)
        return success({
            "exchange": account.exchange,
            "balance": bal.to_dict(),
            "api_ok": True,
        }, message="API 连接正常")
    except Exception as e:
        account.status = 2
        db.commit()
        raise BizException(f"API连接失败: {e}", code=5010)


@router.post("/accounts/{aid}/sync")
def sync_balance(aid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """同步余额+持仓 → 落库 + 返回结果"""
    account = _get_account(db, user, aid)
    try:
        client = _build_client(account)
        bal = client.fetch_balance()
        positions = client.fetch_positions()
    except Exception as e:
        account.status = 2
        db.commit()
        raise BizException(f"从交易所同步失败: {e}", code=5010)

    # 1) 余额
    account.current_balance = bal.total
    account.available_balance = bal.available
    account.margin_balance = bal.balance
    account.unrealized_pnl = bal.unrealized_pnl
    account.balance_updated_at = datetime.now()
    account.status = 1

    # 2) 持仓 → upsert TradePosition
    # 先把所有该账号旧持仓标记为 closed（待会再把仍持仓中的改回）
    db.query(TradePosition).filter(
        TradePosition.exchange_account_id == aid,
        TradePosition.status == 1,
    ).update({TradePosition.status: 2}, synchronize_session=False)
    db.commit()

    for p in positions:
        # 查询是否已有同 symbol + side 的仓位记录(最近一条)
        old = db.query(TradePosition).filter(
            TradePosition.exchange_account_id == aid,
            TradePosition.symbol == p.symbol,
            TradePosition.side == p.side,
        ).order_by(TradePosition.id.desc()).first()
        if old and old.status == 2:
            # 可能它就是当前仓位，恢复 + 更新字段
            old.status = 1
            old.entry_price = p.entry_price
            old.mark_price = p.mark_price
            old.quantity_contracts = p.quantity
            old.leverage = p.leverage
            old.margin_used = p.margin
            old.unrealized_pnl = p.unrealized_pnl
            old.pnl_ratio = p.unrealized_pnl_pct
            old.tp_price = p.take_profit_price
            old.sl_price = p.stop_loss_price
            old.max_drawdown_ratio = max(old.max_drawdown_ratio or 0, abs(p.unrealized_pnl_pct) if p.unrealized_pnl < 0 else 0)
            continue
        # 新仓位
        db.add(TradePosition(
            user_id=account.user_id,
            exchange_account_id=aid,
            exchange=account.exchange,
            strategy_id=None,
            symbol=p.symbol,
            side=p.side,
            leverage=p.leverage,
            entry_price=p.entry_price,
            mark_price=p.mark_price,
            quantity_contracts=p.quantity,
            quantity_usdt=float(p.entry_price) * float(p.quantity),
            margin_used=p.margin,
            tp_price=p.take_profit_price,
            sl_price=p.stop_loss_price,
            unrealized_pnl=p.unrealized_pnl,
            realized_pnl=0,
            pnl_ratio=p.unrealized_pnl_pct,
            max_drawdown_ratio=abs(p.unrealized_pnl_pct) if p.unrealized_pnl < 0 else 0,
            fee_total=0,
            status=1,
            entry_time=datetime.fromtimestamp(p.open_timestamp_ms / 1000) if p.open_timestamp_ms > 0 else datetime.now(),
            close_time=None,
            close_price=None,
            holding_minutes=0,
        ))

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise BizException(f"持仓落库失败: {e}")

    # 3) 注册 client 到行情管理器
    mm = MarketManager.get_instance()
    mm.register_client(client)
    if not mm._running:
        mm.start([p.symbol for p in positions] or ["BTC", "ETH", "SOL", "XAU", "WTI"])

    return success({
        "balance": {
            "total": float(account.current_balance),
            "available": float(account.available_balance),
            "used_margin": bal.used_margin,
            "unrealized_pnl": float(account.unrealized_pnl),
            "balance_raw": bal.balance,
        },
        "positions": [p.to_dict() for p in positions],
        "updated_at": account.balance_updated_at.isoformat() if account.balance_updated_at else None,
    }, message="同步成功")


@router.get("/accounts/{aid}/balance")
def get_balance(aid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """查看子账号余额（DB缓存值；建议先 /sync 拉最新）"""
    account = _get_account(db, user, aid)
    return success({
        "id": account.id,
        "exchange": account.exchange,
        "sub_account_name": account.sub_account_name,
        "initial_balance": float(account.initial_balance or 0),
        "current_balance": float(account.current_balance or 0),
        "available_balance": float(account.available_balance or 0),
        "margin_balance": float(account.margin_balance or 0),
        "unrealized_pnl": float(account.unrealized_pnl or 0),
        "realized_pnl_total": float(account.realized_pnl_total or 0),
        "leverage_max": account.leverage_max,
        "testnet": account.testnet,
        "status": account.status,
        "updated_at": account.balance_updated_at.isoformat() if account.balance_updated_at else None,
    })


@router.get("/accounts/{aid}/positions")
def list_positions(
    aid: int,
    symbol: str = "",
    only_open: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查看子账号持仓"""
    _get_account(db, user, aid)  # 权限校验
    q = db.query(TradePosition).filter(TradePosition.exchange_account_id == aid)
    if only_open:
        q = q.filter(TradePosition.status == 1)
    if symbol:
        q = q.filter(TradePosition.symbol == symbol.upper())
    q = q.order_by(TradePosition.id.desc())
    items = q.limit(500).all()
    return success({
        "count": len(items),
        "items": [
            {
                "id": p.id,
                "symbol": p.symbol,
                "side": p.side,
                "side_name": "多" if p.side == 1 else "空",
                "entry_price": float(p.entry_price),
                "mark_price": float(p.mark_price),
                "quantity": float(p.quantity_contracts),
                "quantity_usdt": float(p.quantity_usdt or 0),
                "leverage": p.leverage,
                "margin": float(p.margin_used),
                "unrealized_pnl": float(p.unrealized_pnl),
                "unrealized_pnl_pct": float(p.pnl_ratio),
                "tp": float(p.tp_price or 0),
                "sl": float(p.sl_price or 0),
                "status": p.status,
                "open_time": p.entry_time.isoformat() if p.entry_time else None,
            }
            for p in items
        ]
    })


@router.post("/accounts/{aid}/cancel-all-open-orders")
def cancel_all_open(aid: int, symbol: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """撤销全部挂单（symbol为空则要求有持仓）"""
    account = _get_account(db, user, aid)
    client = _build_client(account)
    try:
        count = client.cancel_all_open_orders(symbol or None)
    except Exception as e:
        raise BizException(f"撤销失败: {e}", code=5010)
    return success({"canceled_count": count}, message="撤销完成")


# ==========================================================
#  行情（只读，跨账号）
# ==========================================================
def _refresh_ticker_cache(mm, symbol):
    try:
        if mm._primary_client:
            t = mm._primary_client.fetch_ticker(symbol)
            mm.on_ws_ticker(t)
    except Exception as e:
        logger.warning(f"[Exchange] Ticker拉取失败(symbol={symbol}): {e} — 返回模拟数据")
        t = _gen_mock_ticker(symbol)
        mm.on_ws_ticker(t)

@router.get("/ticker/{symbol}")
def get_ticker(symbol: str, account_id: int = 0, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取最新 ticker（优先缓存；缓存过期则后台刷新，先返回旧数据）"""
    symbol = symbol.upper()
    mm = MarketManager.get_instance()
    t = mm.get_ticker(symbol)
    now_ms = int(time.time() * 1000)
    if t:
        if not t.timestamp_ms or (now_ms - t.timestamp_ms) > 5000:
            threading.Thread(target=_refresh_ticker_cache, args=(mm, symbol), daemon=True).start()
        return success(t.to_dict())
    client = _get_client_by_account(db, user, account_id, allow_public=True)
    if client:
        try:
            t = client.fetch_ticker(symbol)
            mm.on_ws_ticker(t)
            return success(t.to_dict())
        except Exception as e:
            logger.warning(f"[Exchange] Ticker拉取失败(symbol={symbol}): {e} — 返回模拟数据")
            t = _gen_mock_ticker(symbol)
            mm.on_ws_ticker(t)
            return success(t.to_dict())
    raise BizException("尚未绑定任何交易所子账号，请先到[交易所子账号]页面绑定并测试连通性")


@router.get("/klines/{symbol}")
def get_klines(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 200,
    account_id: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取K线（内存/REST混合）"""
    symbol = symbol.upper()
    # 月线特殊处理
    tf_raw = timeframe
    timeframe = timeframe.lower()
    if timeframe == "1m" and tf_raw.endswith("M"):
        timeframe = "1M"
    if timeframe not in ("1m","5m","15m","1h","4h","1d","1w","1M","1y"):
        raise ParameterException("timeframe 必须为 1m/5m/15m/1h/4h/1d/1w/1M/1y")
    limit = max(10, min(500, limit))
    mm = MarketManager.get_instance()
    klines = mm.get_klines(symbol, timeframe, limit=limit)
    if len(klines) >= 50:
        return success({
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(klines),
            "items": [
                {
                    "t": c.open_time_ms,
                    "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume,
                } for c in klines
            ],
        })
    # 回退 REST（使用统一的客户端获取逻辑，含公开兜底）
    client = _get_client_by_account(db, user, account_id, allow_public=True)
    klines = _cached_fetch_klines(client, symbol, timeframe, limit=limit)
    # 回填 memory（下一次就命中内存）
    from backend.exchanges.market import _tf_bucket_ms
    now_ms = int(datetime.now().timestamp() * 1000)
    with mm._kline_lock:
        key = (symbol, timeframe)
        mm._kline_history[key] = [
            c for c in klines if c.close_time_ms < now_ms
        ]
        # 当前未闭合的那根
        last = [c for c in klines if c.close_time_ms >= now_ms]
        if last:
            from backend.exchanges.market import _KlineBucket
            mm._kline_open_bucket[key] = _KlineBucket(candle=last[-1])
    return success({
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(klines),
        "items": [
            {
                "t": c.open_time_ms,
                "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume,
            } for c in klines
        ],
    })


# ==========================================================
#  深度盘口 / 近期成交 / 持仓量
# ==========================================================

def _try_get_demo_client(db) -> 'ExchangeClientBase | None':
    """尝试从系统配置加载演示API client（兜底用）"""
    try:
        from backend.routers.settings import _get_config_value
        from backend.models.system_config import SystemConfig
        enabled = _get_config_value(db, "demo_api_enabled", False)
        if not enabled:
            return None
        exchange_str = _get_config_value(db, "demo_api_exchange", "binance") or "binance"
        api_key_enc = _get_config_value(db, "demo_api_key", "") or ""
        api_secret_enc = _get_config_value(db, "demo_api_secret", "") or ""
        testnet = _get_config_value(db, "demo_api_testnet", True)
        from backend.core.security import decrypt_api_key
        api_key = decrypt_api_key(api_key_enc) if api_key_enc.startswith("gAAAA") else api_key_enc
        api_secret = decrypt_api_key(api_secret_enc) if api_secret_enc.startswith("gAAAA") else api_secret_enc
        if not api_key or not api_secret:
            return None
        exchange_id = {"binance": 1, "okx": 2, "bybit": 3}.get(exchange_str, 2)
        client = ExchangeClientBase.create(
            exchange=exchange_id, api_key=api_key, api_secret=api_secret,
            passphrase="", testnet=bool(testnet), exchange_account_id=0,
        )
        client.connect()
        return client
    except Exception as e:
        from backend.core.logging_config import logger
        logger.warning(f"[Exchange] 演示API兜底失败: {e}")
        return None


def _get_client_by_account(db, user, account_id, allow_public: bool = True):
    """根据 account_id 获取交易所 client
    优先级：指定account_id > MarketManager主用 > 演示API兜底 > 公开行情兜底
    allow_public: 是否允许无API Key的公开客户端兜底（K线/Ticker等公开数据）
    注意：指定账号若不存在/被禁用/连接失败，不会报错，而是回退到下一级兜底
    """
    from backend.exchanges.market import MarketManager
    mm = MarketManager.get_instance()

    # 1) 指定账号（失败则回退，不抛出异常）
    if account_id > 0:
        try:
            acc = _get_account(db, user, account_id)
            from backend.exchanges.base import ExchangeClientBase
            client = ExchangeClientBase.create(
                exchange=acc.exchange, api_key=decrypt_api_key(acc.api_key), api_secret=decrypt_api_key(acc.api_secret),
                passphrase=decrypt_api_key(acc.api_passphrase) or "", testnet=bool(acc.testnet),
                exchange_account_id=acc.id,
            )
            client.connect()
            return client
        except Exception as e:
            logger.warning(f"[Exchange] 指定账号 {account_id} 不可用，回退兜底: {e}")

    # 2) MarketManager 主用
    if mm.has_client():
        return mm._primary_client

    # 3) 兜底1：演示API
    demo = _try_get_demo_client(db)
    if demo:
        mm.register_client(demo)
        if not mm._running:
            mm.start(["BTC", "ETH", "SOL"])
        return demo

    # 4) 兜底2：公开行情客户端（无需API Key，仅限K线/Ticker等公开数据）
    if allow_public:
        try:
            from backend.exchanges.base import ExchangeClientBase
            public_client = ExchangeClientBase.create(
                exchange=1, api_key="", api_secret="",
                passphrase="", testnet=True, exchange_account_id=0,
            )
            public_client.connect()
            mm.register_client(public_client)
            return public_client
        except Exception as e:
            logger.warning(f"[Exchange] 公开行情客户端兜底失败: {e}")

    raise BizException("尚未绑定任何交易所子账号，请先到[交易所子账号]页面绑定并测试连通性，或在[系统设置]中配置演示API")


@router.get("/orderbook/{symbol}")
def get_orderbook(
    symbol: str,
    limit: int = 20,
    account_id: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取深度盘口"""
    symbol = symbol.upper()
    client = _get_client_by_account(db, user, account_id)
    ob = client.fetch_orderbook(symbol, limit=max(5, min(100, limit)))
    return success(ob.to_dict())


@router.get("/trades/{symbol}")
def get_recent_trades(
    symbol: str,
    limit: int = 50,
    account_id: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取近期成交记录"""
    symbol = symbol.upper()
    client = _get_client_by_account(db, user, account_id)
    trades = client.fetch_recent_trades(symbol, limit=max(10, min(500, limit)))
    return success({
        "symbol": symbol,
        "count": len(trades),
        "items": [t.to_dict() for t in trades],
    })


@router.get("/open-interest/{symbol}")
def get_open_interest(
    symbol: str,
    account_id: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取持仓量"""
    symbol = symbol.upper()
    client = _get_client_by_account(db, user, account_id)
    oi = client.fetch_open_interest(symbol)
    return success(oi.to_dict())


# ==========================================================
#  K线综合分析：技术指标 + 支撑阻力 + 多周期高低价
# ==========================================================

def _calc_sma(closes, period):
    """简单移动平均"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i-period+1:i+1]) / period)
    return result


def _calc_ema(closes, period):
    """指数移动平均"""
    result = []
    k = 2 / (period + 1)
    ema = 0
    for i in range(len(closes)):
        if i == 0:
            ema = closes[i]
        else:
            ema = closes[i] * k + ema * (1 - k)
        result.append(ema if i >= period - 1 else None)
    return result


def _calc_boll(closes, period=20, std_mult=2):
    """布林带"""
    import math
    mid = _calc_sma(closes, period)
    upper = []
    lower = []
    for i in range(len(closes)):
        if mid[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            vals = closes[i-period+1:i+1]
            mean = mid[i]
            variance = sum((v - mean) ** 2 for v in vals) / period
            std = math.sqrt(variance)
            upper.append(mean + std_mult * std)
            lower.append(mean - std_mult * std)
    return {"mid": mid, "upper": upper, "lower": lower}


def _calc_rsi(closes, period=14):
    """RSI 相对强弱指标"""
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    rsi = [None] * len(closes)
    if len(closes) <= period:
        return rsi
    # 初始平均
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        if avg_loss == 0:
            rsi[i] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))
    return rsi


def _calc_macd(closes, fast=12, slow=26, signal=9):
    """MACD"""
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    # dif = ema_fast - ema_slow
    dif = []
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif.append(ema_fast[i] - ema_slow[i])
        else:
            dif.append(None)
    # dea = ema of dif
    valid_dif = [d for d in dif if d is not None]
    start_idx = len(dif) - len(valid_dif)
    dea_vals = _calc_ema(valid_dif, signal)
    dea = [None] * len(closes)
    for i, v in enumerate(dea_vals):
        dea[start_idx + i] = v
    # macd histogram
    macd_hist = []
    for i in range(len(closes)):
        if dif[i] is not None and dea[i] is not None:
            macd_hist.append((dif[i] - dea[i]) * 2)
        else:
            macd_hist.append(None)
    return {"dif": dif, "dea": dea, "hist": macd_hist}


def _calc_support_resistance(klines, window=20, pivot_count=5):
    """计算支撑阻力位：局部高低点聚类"""
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    closes = [k.close for k in klines]
    if len(klines) < window * 2:
        return {"supports": [], "resistances": [], "pivot_points": []}

    # 找局部高点（阻力候选）和低点（支撑候选）
    resistance_candidates = []
    support_candidates = []
    for i in range(window, len(klines) - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            resistance_candidates.append(highs[i])
        if lows[i] == min(lows[i-window:i+window+1]):
            support_candidates.append(lows[i])

    # 聚类合并（相差1%以内视为同一价位）
    def cluster_levels(vals, threshold_pct=0.01):
        if not vals:
            return []
        vals = sorted(vals)
        clusters = []
        current_cluster = [vals[0]]
        for v in vals[1:]:
            avg = sum(current_cluster) / len(current_cluster)
            if (v - avg) / avg < threshold_pct:
                current_cluster.append(v)
            else:
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [v]
        clusters.append(sum(current_cluster) / len(current_cluster))
        return clusters

    supports = cluster_levels(support_candidates)
    resistances = cluster_levels(resistance_candidates)

    # 计算枢轴点 Pivot Points (标准法)
    last_high = max(highs[-window:])
    last_low = min(lows[-window:])
    last_close = closes[-1]
    pp = (last_high + last_low + last_close) / 3
    r1 = 2 * pp - last_low
    s1 = 2 * pp - last_high
    r2 = pp + (last_high - last_low)
    s2 = pp - (last_high - last_low)
    r3 = last_high + 2 * (pp - last_low)
    s3 = last_low - 2 * (last_high - pp)

    pivot_points = [
        {"level": "R3", "price": round(r3, 4)},
        {"level": "R2", "price": round(r2, 4)},
        {"level": "R1", "price": round(r1, 4)},
        {"level": "PP", "price": round(pp, 4)},
        {"level": "S1", "price": round(s1, 4)},
        {"level": "S2", "price": round(s2, 4)},
        {"level": "S3", "price": round(s3, 4)},
    ]

    return {
        "supports": [round(s, 4) for s in sorted(supports, reverse=True)[:pivot_count]],
        "resistances": [round(r, 4) for r in sorted(resistances, reverse=True)[:pivot_count]],
        "pivot_points": pivot_points,
    }


def _calc_multi_period_lows(client, symbol):
    """计算多周期最低价/最高价
    优化：一次拉取365根日线，本地切片计算所有周期，避免7次串行网络请求
    """
    # 各周期需要的日线根数
    periods = {
        "1d": 2,
        "1w": 8,
        "1m": 32,
        "2m": 64,
        "3m": 95,
        "6m": 190,
        "1y": 365,
    }
    result = {}
    try:
        # 一次拉取最长周期（365根日线），带缓存
        all_daily = _cached_fetch_klines(client, symbol, "1d", limit=365)
        if not all_daily:
            for label in periods:
                result[label] = {"low": None, "high": None, "period": label, "candles": 0}
            return result

        # 本地切片计算各周期高低点
        for label, days in periods.items():
            kl_slice = all_daily[-days:] if len(all_daily) >= days else all_daily
            lows = [k.low for k in kl_slice]
            highs = [k.high for k in kl_slice]
            result[label] = {
                "low": min(lows),
                "high": max(highs),
                "period": label,
                "candles": len(kl_slice),
            }
    except Exception:
        for label in periods:
            result[label] = {"low": None, "high": None, "period": label, "candles": 0}
    return result


def _calc_liquidation_heatmap(klines, orderbook=None, open_interest=None):
    """
    估算清算热力图：基于波动率、成交量分布和持仓量估算多空爆仓密集区
    由于交易所不直接提供爆仓数据，使用行业通用估算方法
    """
    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    if len(closes) < 20:
        return {"long_liq": [], "short_liq": [], "danger_levels": [], "heatmap": []}

    last_price = closes[-1]
    # 计算ATR
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    atr = sum(tr_list[-14:]) / min(14, len(tr_list)) if tr_list else last_price * 0.02

    price_range = atr * 8
    num_levels = 20
    step = price_range / num_levels

    long_liq = []
    short_liq = []
    heatmap = []

    for i in range(num_levels + 1):
        price = last_price - price_range / 2 + i * step
        dist_from_last = abs(price - last_price) / last_price
        # 整数关口效应
        round_num_factor = 0.0
        for rn in [1000, 500, 100, 50, 10]:
            if price > rn:
                distance_to_round = abs(price - round(price / rn) * rn) / rn
                round_num_factor += max(0, 1 - distance_to_round * 5) * (100 / rn)
                break
        distance_factor = min(1.0, dist_from_last / 0.05) * 0.6
        vol_factor = atr / last_price / 0.02
        density = (0.3 + round_num_factor * 0.4 + distance_factor) * vol_factor
        density = min(1.0, max(0.05, density))
        heatmap.append({"price": round(price, 4), "density": round(density, 3), "type": "mixed"})
        if price < last_price:
            long_liq.append({"price": round(price, 4), "density": round(density, 3)})
        else:
            short_liq.append({"price": round(price, 4), "density": round(density, 3)})

    all_levels = sorted(heatmap, key=lambda x: x["density"], reverse=True)
    danger_levels = []
    for lv in all_levels[:5]:
        side = "short_liq" if lv["price"] > last_price else "long_liq"
        side_cn = "空头爆仓" if side == "short_liq" else "多头爆仓"
        danger_levels.append({
            "price": lv["price"],
            "density": lv["density"],
            "side": side,
            "side_cn": side_cn,
            "distance_pct": round(abs(lv["price"] - last_price) / last_price * 100, 2),
        })
    danger_levels.sort(key=lambda x: abs(x["price"] - last_price))

    return {
        "long_liq": sorted(long_liq, key=lambda x: x["price"], reverse=True),
        "short_liq": sorted(short_liq, key=lambda x: x["price"]),
        "danger_levels": danger_levels,
        "heatmap": heatmap,
        "atr": round(atr, 4),
        "last_price": round(last_price, 4),
    }


def _calc_main_force_position(orderbook_dict):
    """
    主力位置分析：基于盘口大单、买卖深度判断主力资金动向
    """
    bids = orderbook_dict.get("bids", []) if orderbook_dict else []
    asks = orderbook_dict.get("asks", []) if orderbook_dict else []
    if not bids or not asks:
        return {"walls": [], "pressure": "neutral", "pressure_cn": "多空均衡", "pressure_score": 50, "big_order_ratio": 0}

    bid_qtys = [b.get("quantity", 0) for b in bids]
    ask_qtys = [a.get("quantity", 0) for a in asks]
    avg_bid = sum(bid_qtys) / len(bid_qtys) if bid_qtys else 0
    avg_ask = sum(ask_qtys) / len(ask_qtys) if ask_qtys else 0

    walls = []
    for b in bids:
        if b.get("quantity", 0) > avg_bid * 2:
            walls.append({"price": b.get("price", 0), "quantity": b.get("quantity", 0),
                "side": "buy", "side_cn": "买盘支撑",
                "strength": round(b.get("quantity", 0) / avg_bid, 1) if avg_bid else 1})
    for a in asks:
        if a.get("quantity", 0) > avg_ask * 2:
            walls.append({"price": a.get("price", 0), "quantity": a.get("quantity", 0),
                "side": "sell", "side_cn": "卖盘压单",
                "strength": round(a.get("quantity", 0) / avg_ask, 1) if avg_ask else 1})
    walls.sort(key=lambda x: x["quantity"], reverse=True)

    total_bid = sum(b.get("total", 0) for b in bids)
    total_ask = sum(a.get("total", 0) for a in asks)
    buy_ratio = total_bid / (total_bid + total_ask) * 100 if (total_bid + total_ask) > 0 else 50

    if buy_ratio > 60:
        pressure, pressure_cn = "bullish", "多头主导"
    elif buy_ratio < 40:
        pressure, pressure_cn = "bearish", "空头主导"
    else:
        pressure, pressure_cn = "neutral", "多空均衡"

    big_bid_qty = sum(b.get("quantity", 0) for b in bids if b.get("quantity", 0) > avg_bid * 1.5)
    big_ask_qty = sum(a.get("quantity", 0) for a in asks if a.get("quantity", 0) > avg_ask * 1.5)
    total_qty = sum(bid_qtys) + sum(ask_qtys)
    big_order_ratio = round((big_bid_qty + big_ask_qty) / total_qty * 100, 1) if total_qty > 0 else 0

    return {
        "walls": walls[:6],
        "pressure": pressure,
        "pressure_cn": pressure_cn,
        "pressure_score": round(buy_ratio, 1),
        "big_order_ratio": big_order_ratio,
        "total_bid_depth": round(total_bid, 2),
        "total_ask_depth": round(total_ask, 2),
    }


def _calc_rise_fall_params(klines):
    """涨跌参数分析：ATR、波动率、涨跌幅、振幅、量比等"""
    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    if len(closes) < 2:
        return {}
    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else last_close
    change_pct = round((last_close - prev_close) / prev_close * 100, 2) if prev_close else 0
    change_abs = round(last_close - prev_close, 4)
    amplitude = round((highs[-1] - lows[-1]) / prev_close * 100, 2) if prev_close else 0

    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    atr_14 = round(sum(tr_list[-14:]) / min(14, len(tr_list)), 4) if tr_list else 0
    atr_pct = round(atr_14 / last_close * 100, 2) if last_close else 0

    rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] > 0]
    if rets:
        avg_ret = sum(rets[-20:]) / min(20, len(rets))
        variance = sum((r - avg_ret) ** 2 for r in rets[-20:]) / min(20, len(rets))
        volatility = round(variance ** 0.5 * 100, 2)
    else:
        volatility = 0

    streak = 0
    streak_dir = "up"
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i-1]:
            if streak_dir == "up": streak += 1
            else: break
        elif closes[i] < closes[i-1]:
            if streak_dir == "down": streak += 1
            else: break
        else: break
    if streak == 0: streak = 1

    volumes = [k.volume for k in klines]
    avg_vol_20 = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0
    vol_ratio = round(volumes[-1] / avg_vol_20, 2) if avg_vol_20 > 0 else 1

    up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    down_count = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1])

    return {
        "change_pct": change_pct, "change_abs": change_abs,
        "amplitude": amplitude, "atr_14": atr_14, "atr_pct": atr_pct,
        "volatility": volatility, "streak": streak, "streak_dir": streak_dir,
        "vol_ratio": vol_ratio, "up_count": up_count, "down_count": down_count,
        "up_ratio": round(up_count / max(1, up_count + down_count) * 100, 1),
        "last_close": round(last_close, 4),
    }


@router.get("/kline-analysis/{symbol}")
def kline_analysis(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 200,
    account_id: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    K线综合分析：K线数据 + 技术指标 + 支撑阻力 + 多周期高低价
    """
    symbol = symbol.upper()
    # 月线特殊：1M (大写M)，其他小写
    tf_raw = timeframe
    timeframe = timeframe.lower()
    if timeframe == "1m" and tf_raw.endswith("M"):
        timeframe = "1M"  # 月线
    if timeframe not in ("1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M", "1y"):
        raise ParameterException("timeframe 必须为 1m/5m/15m/1h/4h/1d/1w/1M/1y")
    limit = max(50, min(500, limit))

    client = _get_client_by_account(db, user, account_id)

    # 1. 主周期 K线
    klines = _cached_fetch_klines(client, symbol, timeframe, limit=limit)
    closes = [k.close for k in klines]

    # 2. 技术指标
    ma5 = _calc_sma(closes, 5)
    ma10 = _calc_sma(closes, 10)
    ma20 = _calc_sma(closes, 20)
    ma60 = _calc_sma(closes, 60) if len(closes) >= 60 else [None] * len(closes)
    boll = _calc_boll(closes, 20, 2)
    rsi = _calc_rsi(closes, 14)
    macd = _calc_macd(closes, 12, 26, 9)

    # 3. 支撑阻力
    sr = _calc_support_resistance(klines, window=10, pivot_count=5)

    # 4. 多周期高低价
    multi_period = _calc_multi_period_lows(client, symbol)

    # 5. 清算热力图估算
    liq_heatmap = _calc_liquidation_heatmap(klines)

    # 6. 涨跌参数分析
    rise_fall_params = _calc_rise_fall_params(klines)

    # 7. 趋势判断
    last_close = closes[-1] if closes else 0
    ma20_last = ma20[-1] if ma20 and ma20[-1] else 0
    ma60_last = ma60[-1] if ma60 and ma60[-1] else 0
    rsi_last = rsi[-1] if rsi and rsi[-1] else 50

    if ma20_last and last_close > ma20_last:
        trend_short = "up"
    elif ma20_last and last_close < ma20_last:
        trend_short = "down"
    else:
        trend_short = "neutral"

    if ma60_last and last_close > ma60_last:
        trend_mid = "up"
    elif ma60_last and last_close < ma60_last:
        trend_mid = "down"
    else:
        trend_mid = "neutral"

    return success({
        "symbol": symbol,
        "timeframe": timeframe,
        "kline_count": len(klines),
        "klines": [
            {
                "t": k.open_time_ms,
                "o": k.open, "h": k.high, "l": k.low, "c": k.close, "v": k.volume,
            } for k in klines
        ],
        "indicators": {
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "boll_upper": boll["upper"],
            "boll_mid": boll["mid"],
            "boll_lower": boll["lower"],
            "rsi": rsi,
            "macd_dif": macd["dif"],
            "macd_dea": macd["dea"],
            "macd_hist": macd["hist"],
        },
        "support_resistance": sr,
        "trend": {
            "short_term": trend_short,
            "mid_term": trend_mid,
            "rsi": round(rsi_last, 2) if rsi_last else 50,
            "last_price": last_close,
        },
        "multi_period": multi_period,
        "liquidation_heatmap": liq_heatmap,
        "rise_fall_params": rise_fall_params,
    })


# ==========================================================
#  大资金预警 - 邮件通知
# ==========================================================

@router.post("/whale-alert/send-email")
def send_whale_alert_email_api(
    symbol: str = "",
    side: str = "buy",
    price: float = 0,
    quote_qty: float = 0,
    timestamp_ms: int = 0,
    user: User = Depends(get_current_user),
):
    """
    手动触发大资金预警邮件（用于测试 / 前端主动调用）
    """
    from backend.utils.email_util import send_whale_alert_email
    import time

    symbol = (symbol or "BTC").upper()
    if not price:
        price = 50000.0
    if not quote_qty:
        quote_qty = 100000.0
    if not timestamp_ms:
        timestamp_ms = int(time.time() * 1000)

    ok = send_whale_alert_email(
        symbol=symbol,
        side=side,
        price=price,
        quote_qty=quote_qty,
        timestamp_ms=timestamp_ms,
    )
    return success({"sent": ok, "message": "已发送" if ok else "SMTP未配置或发送失败"})


@router.post("/email/test")
def test_email(
    user: User = Depends(get_current_user),
):
    """测试邮件发送"""
    from backend.utils.email_util import send_email

    ok = send_email(
        subject="【测试】策略交易系统邮件通知",
        body="<h3>邮件配置测试成功！</h3><p>您的SMTP配置工作正常。</p>",
        is_html=True,
    )
    if not ok:
        raise ParameterException("邮件发送失败，请检查SMTP配置")
    return success({"sent": True})


@router.post("/ai-signal/send-email")
def send_ai_signal_email(
    symbol: str = "",
    direction: str = "long",
    score: float = 0,
    reason: str = "",
    timeframe: str = "",
    user: User = Depends(get_current_user),
):
    """
    发送AI交易信号预警邮件
    """
    from backend.utils.email_util import send_email
    from datetime import datetime

    symbol = (symbol or "BTC").upper()
    direction = direction if direction in ("long", "short", "neutral") else "neutral"
    score = float(score or 0)

    direction_cn = {"long": "建议买入", "short": "建议卖出", "neutral": "观望"}[direction]
    emoji = {"long": "🚀", "short": "📉", "neutral": "⏸️"}[direction]
    color = {"long": "#4ADE80", "short": "#F87171", "neutral": "#FBBF24"}[direction]
    bg = {"long": "#052E1B", "short": "#450A0A", "neutral": "#2E2A05"}[direction]

    subject = f"{emoji} AI信号 {direction_cn} - {symbol} {score}分"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reason_html = f'<div style="margin-top: 16px; padding: 16px; background: #0A1118; border-radius: 8px;"><div style="color: #818CF8; font-size: 13px; margin-bottom: 8px; font-weight: 600;">AI分析理由</div><div style="color: #CBD5E1; line-height: 1.8; font-size: 14px;">{reason or "暂无详细理由"}</div></div>'

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0F172A; padding: 24px; border-radius: 12px; color: #E2E8F0;">
        <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #1E293B;">
            <div style="font-size: 48px; margin-bottom: 12px;">{emoji}</div>
            <div style="font-size: 14px; color: #818CF8; margin-bottom: 8px;">🤖 AI交易信号预警</div>
            <div style="display: flex; align-items: center; justify-content: center; gap: 12px;">
                <span style="font-size: 24px; font-weight: 800; font-family: monospace;">{symbol}</span>
                <span style="font-size: 18px; font-weight: 700; padding: 4px 12px; border-radius: 6px; background: {bg}; color: {color};">{direction_cn}</span>
            </div>
        </div>

        <div style="padding: 24px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 12px 0; color: #94A3B8; border-bottom: 1px solid #1E293B;">综合评分</td>
                    <td style="padding: 12px 0; text-align: right; font-weight: bold; font-size: 28px; color: {color}; font-family: monospace; border-bottom: 1px solid #1E293B;">{score}分</td>
                </tr>
                <tr>
                    <td style="padding: 12px 0; color: #94A3B8; border-bottom: 1px solid #1E293B;">分析周期</td>
                    <td style="padding: 12px 0; text-align: right; border-bottom: 1px solid #1E293B;">{timeframe or '1h'}</td>
                </tr>
                <tr>
                    <td style="padding: 12px 0; color: #94A3B8;">信号时间</td>
                    <td style="padding: 12px 0; text-align: right;">{now}</td>
                </tr>
            </table>
            {reason_html}
        </div>

        <div style="text-align: center; padding: 16px; background: #1E293B; border-radius: 8px; font-size: 12px; color: #64748B;">
            此邮件由策略交易系统自动发送，仅供参考，不构成投资建议
        </div>
    </div>
    """

    ok = send_email(subject, html, is_html=True)
    return success({"sent": ok, "message": "已发送" if ok else "SMTP未配置或发送失败"})
