"""
Pydantic Schema（请求/响应模型）通用基类
所有 router 的 schema 可继承自这里的基类
"""
from typing import Generic, TypeVar, Optional, Any, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ============ 统一响应结构 ============

class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: Optional[T] = None


class ListResponseData(BaseModel, Generic[T]):
    items: List[T]
    total: int = 0
    page: int = 1
    page_size: int = 20


# ============ 通用分页请求 ============

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=500, description="每页条数")
    order_by: str = Field(default="-id", description="排序字段，前缀-表示降序")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


# ============ 通用基础模型 ============

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="ignore")


class BaseWithId(BaseSchema):
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ============ 通用分页工具 ============

# 列表/分页接口默认不返回的敏感字段（密码哈希、API 密钥、2FA 密钥等）
# 安全原则：列表接口永远不暴露这些字段；详情接口如需单独显式返回
_SENSITIVE_FIELDS = frozenset({
    "password_hash", "api_key", "api_secret", "api_passphrase",
    "two_factor_secret", "secret", "token", "refresh_token",
})


def _orm_to_dict(obj) -> dict:
    """ORM 行对象转 JSON 友好 dict（遍历表列，datetime/Decimal 转基本类型；
    过滤敏感字段，避免列表接口泄露密码哈希/API 密钥）"""
    from datetime import datetime, date
    from decimal import Decimal

    out: dict = {}
    for col in obj.__table__.columns:
        if col.name in _SENSITIVE_FIELDS:
            continue
        val = getattr(obj, col.name, None)
        if isinstance(val, (datetime, date)):
            out[col.name] = val.isoformat() if val else None
        elif isinstance(val, Decimal):
            out[col.name] = float(val)
        else:
            out[col.name] = val
    return out


def paginate(
    query,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "-id",
) -> dict:
    """SQLAlchemy ORM 查询分页（items 已转为 dict 列表，便于 JSON 序列化与下标追加字段）"""
    from sqlalchemy import desc, asc

    total = query.count()

    # 排序
    if order_by.startswith("-"):
        field = order_by[1:]
        query = query.order_by(desc(field))
    else:
        query = query.order_by(asc(order_by))

    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [_orm_to_dict(r) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
