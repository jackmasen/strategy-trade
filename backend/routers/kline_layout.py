"""
K线自定义布局路由
- 个人布局保存/加载/删除
- 管理员发布公共布局
- 所有用户可查看和使用公共布局
"""
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.core.auth import get_current_user, require_admin
from backend.core.exceptions import ParameterException, BizException, success
from backend.core.logging_config import logger
from backend.models.user import User
from backend.models.kline_layout import KlineLayout

router = APIRouter(prefix="/kline-layouts", tags=["K线布局"])


# ============================================================
# 请求/响应模型
# ============================================================

class SaveLayoutReq(BaseModel):
    name: str = Field(..., description="布局名称", min_length=1, max_length=100)
    description: str = Field(default="", description="布局说明", max_length=256)
    layout_data: str = Field(..., description="布局配置JSON")
    is_public: bool = Field(default=False, description="是否发布为公共布局（仅管理员）")


class UpdateLayoutReq(BaseModel):
    name: Optional[str] = Field(None, description="布局名称", max_length=100)
    description: Optional[str] = Field(None, description="布局说明", max_length=256)
    layout_data: Optional[str] = Field(None, description="布局配置JSON")
    is_public: Optional[bool] = Field(None, description="是否公共（仅管理员可修改）")
    is_default: Optional[bool] = Field(None, description="是否设为默认公共布局（仅管理员）")


def _layout_to_dict(layout: KlineLayout) -> Dict[str, Any]:
    return {
        "id": layout.id,
        "name": layout.name,
        "description": layout.description,
        "layout_data": layout.layout_data,
        "is_public": layout.is_public,
        "created_by": layout.created_by,
        "user_id": layout.user_id,
        "use_count": layout.use_count or 0,
        "is_default": layout.is_default or False,
        "created_at": layout.created_at.isoformat() if layout.created_at else None,
        "updated_at": layout.updated_at.isoformat() if layout.updated_at else None,
    }


# ============================================================
# 1. 公共布局列表（所有用户可见）
# ============================================================

@router.get("/public")
def public_layouts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取所有公共布局列表"""
    layouts = db.query(KlineLayout).filter(
        KlineLayout.is_public == True
    ).order_by(
        KlineLayout.is_default.desc(),
        KlineLayout.use_count.desc(),
        KlineLayout.created_at.desc(),
    ).all()

    return success({
        "layouts": [_layout_to_dict(l) for l in layouts]
    })


# ============================================================
# 2. 我的布局（个人保存的布局）
# ============================================================

@router.get("/my")
def my_layouts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前用户保存的个人布局"""
    layouts = db.query(KlineLayout).filter(
        KlineLayout.user_id == user.id
    ).order_by(
        KlineLayout.updated_at.desc()
    ).all()

    return success({
        "layouts": [_layout_to_dict(l) for l in layouts]
    })


# ============================================================
# 3. 保存布局（个人 or 公共）
# ============================================================

@router.post("")
def save_layout(
    req: SaveLayoutReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存K线布局
    - 普通用户只能保存个人布局
    - 管理员可以发布公共布局
    """
    is_public = False
    user_id = user.id

    if req.is_public:
        # 只有管理员才能发布公共布局
        if user.role != 1:
            raise BizException("仅管理员可发布公共布局", code=4030)
        is_public = True
        user_id = None  # 公共布局不属于任何个人

    # 检查同名
    existing = db.query(KlineLayout).filter(
        KlineLayout.name == req.name,
        KlineLayout.user_id == user_id if not is_public else KlineLayout.is_public == True,
    ).first()
    if existing:
        raise BizException("布局名称已存在", code=4000)

    layout = KlineLayout(
        name=req.name,
        description=req.description,
        layout_data=req.layout_data,
        user_id=user_id,
        is_public=is_public,
        created_by=user.id,
        use_count=0,
        is_default=False,
    )
    db.add(layout)
    db.commit()
    db.refresh(layout)

    logger.info(f"用户[{user.username}]保存K线布局: {req.name}, 公共={is_public}")

    return success(_layout_to_dict(layout), message="布局保存成功")


# ============================================================
# 4. 更新布局
# ============================================================

@router.put("/{layout_id}")
def update_layout(
    layout_id: int,
    req: UpdateLayoutReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新布局"""
    layout = db.query(KlineLayout).filter(KlineLayout.id == layout_id).first()
    if not layout:
        raise BizException("布局不存在", code=4004)

    # 权限校验
    if layout.is_public:
        # 公共布局只有管理员可修改
        if user.role != 1:
            raise BizException("仅管理员可修改公共布局", code=4030)
    else:
        # 个人布局只有本人可修改
        if layout.user_id != user.id and user.role != 1:
            raise BizException("无权修改此布局", code=4030)

    if req.name is not None:
        # 检查重名
        existing = db.query(KlineLayout).filter(
            KlineLayout.name == req.name,
            KlineLayout.id != layout_id,
        ).first()
        if existing:
            raise BizException("布局名称已存在", code=4000)
        layout.name = req.name

    if req.description is not None:
        layout.description = req.description

    if req.layout_data is not None:
        layout.layout_data = req.layout_data

    if req.is_public is not None:
        if user.role != 1:
            raise BizException("仅管理员可修改公共状态", code=4030)
        layout.is_public = req.is_public
        if req.is_public:
            layout.user_id = None

    if req.is_default is not None:
        if user.role != 1:
            raise BizException("仅管理员可设置默认布局", code=4030)
        # 取消其他默认
        if req.is_default:
            db.query(KlineLayout).filter(
                KlineLayout.is_public == True,
                KlineLayout.is_default == True,
            ).update({"is_default": False})
        layout.is_default = req.is_default

    layout.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(layout)

    return success(_layout_to_dict(layout), message="布局已更新")


# ============================================================
# 5. 删除布局
# ============================================================

@router.delete("/{layout_id}")
def delete_layout(
    layout_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除布局"""
    layout = db.query(KlineLayout).filter(KlineLayout.id == layout_id).first()
    if not layout:
        raise BizException("布局不存在", code=4004)

    # 权限校验
    if layout.is_public:
        if user.role != 1:
            raise BizException("仅管理员可删除公共布局", code=4030)
    else:
        if layout.user_id != user.id and user.role != 1:
            raise BizException("无权删除此布局", code=4030)

    name = layout.name
    db.delete(layout)
    db.commit()

    logger.info(f"用户[{user.username}]删除K线布局: {name}")

    return success({"id": layout_id}, message="布局已删除")


# ============================================================
# 6. 应用/使用布局（增加使用计数）
# ============================================================

@router.post("/{layout_id}/apply")
def apply_layout(
    layout_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """应用布局（增加使用计数，用于排序）"""
    layout = db.query(KlineLayout).filter(KlineLayout.id == layout_id).first()
    if not layout:
        raise BizException("布局不存在", code=4004)

    layout.use_count = (layout.use_count or 0) + 1
    db.commit()
    db.refresh(layout)

    return success(_layout_to_dict(layout))


# ============================================================
# 7. 管理员：获取所有布局列表（管理用）
# ============================================================

@router.get("/admin/all")
def admin_all_layouts(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """管理员获取所有布局（公共+个人，用于管理）"""
    layouts = db.query(KlineLayout).order_by(
        KlineLayout.is_public.desc(),
        KlineLayout.created_at.desc(),
    ).all()

    return success({
        "layouts": [_layout_to_dict(l) for l in layouts]
    })
