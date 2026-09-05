"""
交易相关异步任务 — Celery 队列: trade
用于异步下单、平仓、批量撤单等耗时操作
"""
from __future__ import annotations

from celery import current_app as celery

from backend.core.logging_config import logger
from backend.db.session import session_maker


@celery.task(name="backend.tasks.trade.place_order_async", bind=True)
def place_order_async(self, account_id: int, symbol: str, side: int,
                      quantity: float, order_type: str = "market",
                      price: float = None, leverage: int = 3,
                      take_profit_pct: float = None, stop_loss_pct: float = None):
    """异步下单（不阻塞主线程）"""
    from backend.exchanges.base import ExchangeClientBase
    from backend.models.exchange import ExchangeAccount

    try:
        with session_maker() as db:
            acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == account_id).first()
            if not acc:
                return {"status": "error", "msg": f"交易所账号 {account_id} 不存在"}

            client = ExchangeClientBase.create(
                exchange=acc.exchange,
                api_key=acc.api_key,
                api_secret=acc.api_secret_decrypted,
                passphrase=acc.passphrase or "",
                testnet=acc.testnet,
                exchange_account_id=acc.id,
            )
            client.connect()

            order = client.place_order(
                symbol=symbol, side=side, quantity=quantity,
                order_type=order_type, price=price, leverage=leverage,
                take_profit_pct=take_profit_pct, stop_loss_pct=stop_loss_pct,
                client_order_id=f"celery_{self.task_id[:16]}",
            )
            client.close()

            logger.info(f"[Trade-Task] 下单完成: {symbol} side={side} qty={quantity} status={order.status}")
            return {
                "status": "ok",
                "order_id": order.exchange_order_id,
                "filled_qty": order.filled_quantity,
                "avg_price": order.avg_fill_price,
                "order_status": order.status,
            }
    except Exception as e:
        logger.exception(f"[Trade-Task] 异步下单失败: {e}")
        return {"status": "error", "msg": str(e)}


@celery.task(name="backend.tasks.trade.close_position_async", bind=True)
def close_position_async(self, account_id: int, symbol: str, side: int,
                         quantity: float = None):
    """异步平仓"""
    from backend.exchanges.base import ExchangeClientBase
    from backend.models.exchange import ExchangeAccount

    try:
        with session_maker() as db:
            acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == account_id).first()
            if not acc:
                return {"status": "error", "msg": f"交易所账号 {account_id} 不存在"}

            client = ExchangeClientBase.create(
                exchange=acc.exchange,
                api_key=acc.api_key,
                api_secret=acc.api_secret_decrypted,
                passphrase=acc.passphrase or "",
                testnet=acc.testnet,
                exchange_account_id=acc.id,
            )
            client.connect()

            order = client.close_position(symbol=symbol, side=side, quantity=quantity)
            client.close()

            logger.info(f"[Trade-Task] 平仓完成: {symbol} side={side} qty={quantity}")
            return {
                "status": "ok",
                "order_id": order.exchange_order_id,
                "filled_qty": order.filled_quantity,
                "avg_price": order.avg_fill_price,
            }
    except Exception as e:
        logger.exception(f"[Trade-Task] 异步平仓失败: {e}")
        return {"status": "error", "msg": str(e)}


@celery.task(name="backend.tasks.trade.cancel_all_orders_async", bind=True)
def cancel_all_orders_async(self, account_id: int, symbol: str = None):
    """异步批量撤单"""
    from backend.exchanges.base import ExchangeClientBase
    from backend.models.exchange import ExchangeAccount

    try:
        with session_maker() as db:
            acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == account_id).first()
            if not acc:
                return {"status": "error", "msg": f"交易所账号 {account_id} 不存在"}

            client = ExchangeClientBase.create(
                exchange=acc.exchange,
                api_key=acc.api_key,
                api_secret=acc.api_secret_decrypted,
                passphrase=acc.passphrase or "",
                testnet=acc.testnet,
                exchange_account_id=acc.id,
            )
            client.connect()
            count = client.cancel_all_open_orders(symbol)
            client.close()

            logger.info(f"[Trade-Task] 批量撤单完成: account={account_id} symbol={symbol} count={count}")
            return {"status": "ok", "cancelled": count}
    except Exception as e:
        logger.exception(f"[Trade-Task] 异步撤单失败: {e}")
        return {"status": "error", "msg": str(e)}
