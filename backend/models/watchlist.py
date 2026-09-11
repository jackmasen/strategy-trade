"""
用户自选币列表模型
- 每个用户可以维护自己的自选币种列表
- 支持排序权重 sort_order
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.db.base import Base


class UserWatchlist(Base):
    """用户自选币表"""

    __tablename__ = "user_watchlists"

    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False, comment="用户ID")
    symbol = Column(String(32), nullable=False, comment="品种代码")
    sort_order = Column(Integer, default=0, comment="排序权重（升序排列）")

    # 联合唯一约束：同一用户同一品种只能有一条记录
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_user_watchlist_user_symbol"),
    )

    # 关联
    user = relationship("User", backref="watchlists")
