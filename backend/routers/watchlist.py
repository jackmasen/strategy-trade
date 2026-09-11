"""
自选币列表路由
- GET    /watchlist           获取当前用户自选币列表（按 sort_order 排序）
- POST   /watchlist           添加自选币 { symbol: str }
- PUT    /watchlist/{id}      更新自选币（修改 sort_order）
- DELETE /watchlist/{id}      删除自选币
- POST   /watchlist/reorder   批量重排序 [{id: int, sort_order: int}, ...]
"""
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.core.auth import get_current_user
from backend.core.exceptions import BizException, success
from backend.core.logging_config import logger
from backend.models.user import User
from backend.models.watchlist import UserWatchlist

router = APIRouter(prefix="/watchlist", tags=["自选币"])


# ============================================================
# 请求/响应模型
# ============================================================

class AddWatchlistReq(BaseModel):
    symbol: str = Field(..., description="品种代码", min_length=1, max_length=32)


class UpdateWatchlistReq(BaseModel):
    sort_order: int = Field(0, description="排序权重")


class ReorderItem(BaseModel):
    id: int = Field(..., description="自选币记录ID")
    sort_order: int = Field(..., description="排序权重")


class ReorderReq(BaseModel):
    items: List[ReorderItem] = Field(..., description="重排序列表")


def _watchlist_to_dict(item: UserWatchlist) -> Dict[str, Any]:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "symbol": item.symbol,
        "sort_order": item.sort_order,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


# ============================================================
# 1. 获取当前用户自选币列表
# ============================================================

@router.get("")
def list_watchlist(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前用户自选币列表（按 sort_order 升序排列）"""
    items = db.query(UserWatchlist).filter(
        UserWatchlist.user_id == user.id
    ).order_by(
        UserWatchlist.sort_order.asc(),
        UserWatchlist.id.asc(),
    ).all()

    return success({
        "count": len(items),
        "items": [_watchlist_to_dict(i) for i in items],
    })


# ============================================================
# 2. 添加自选币
# ============================================================

@router.post("")
def add_watchlist(
    req: AddWatchlistReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """添加自选币"""
    symbol = req.symbol.upper().strip()
    if not symbol:
        raise BizException("品种代码不能为空", code=4000)

    # 检查是否已存在
    existing = db.query(UserWatchlist).filter(
        UserWatchlist.user_id == user.id,
        UserWatchlist.symbol == symbol,
    ).first()
    if existing:
        raise BizException(f"{symbol} 已在自选列表中", code=4000)

    # 计算新的 sort_order：放在最后
    max_order = db.query(UserWatchlist).filter(
        UserWatchlist.user_id == user.id
    ).count()

    item = UserWatchlist(
        user_id=user.id,
        symbol=symbol,
        sort_order=max_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    logger.info(f"用户[{user.username}]添加自选币: {symbol}")

    return success(_watchlist_to_dict(item), message="添加成功")


# ============================================================
# 3. 更新自选币（修改 sort_order）
# ============================================================

@router.put("/{item_id}")
def update_watchlist(
    item_id: int,
    req: UpdateWatchlistReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新自选币（修改排序权重）"""
    item = db.query(UserWatchlist).filter(
        UserWatchlist.id == item_id,
        UserWatchlist.user_id == user.id,
    ).first()
    if not item:
        raise BizException("自选币记录不存在", code=4004)

    item.sort_order = req.sort_order
    db.commit()
    db.refresh(item)

    return success(_watchlist_to_dict(item), message="更新成功")


# ============================================================
# 4. 删除自选币
# ============================================================

@router.delete("/{item_id}")
def delete_watchlist(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除自选币"""
    item = db.query(UserWatchlist).filter(
        UserWatchlist.id == item_id,
        UserWatchlist.user_id == user.id,
    ).first()
    if not item:
        raise BizException("自选币记录不存在", code=4004)

    symbol = item.symbol
    db.delete(item)
    db.commit()

    logger.info(f"用户[{user.username}]删除自选币: {symbol}")

    return success({"id": item_id, "symbol": symbol}, message="删除成功")


# ============================================================
# 5. 批量重排序
# ============================================================

@router.post("/reorder")
def reorder_watchlist(
    req: ReorderReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量重排序自选币"""
    if not req.items:
        return success({"updated": 0}, message="无更新")

    # 获取所有当前用户的自选币
    items_map = {
        item.id: item
        for item in db.query(UserWatchlist).filter(
            UserWatchlist.user_id == user.id,
            UserWatchlist.id.in_([i.id for i in req.items]),
        ).all()
    }

    updated = 0
    for reorder_item in req.items:
        item = items_map.get(reorder_item.id)
        if item:
            item.sort_order = reorder_item.sort_order
            updated += 1

    db.commit()

    logger.info(f"用户[{user.username}]批量重排自选币，更新{updated}条")

    return success({"updated": updated}, message="排序已更新")
