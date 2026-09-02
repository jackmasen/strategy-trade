"""
K线共享布局表
管理员可以创建公共布局，所有运营用户都能选择使用
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.db.base import Base


class KlineLayout(Base):
    """
    K线页面自定义布局
    - 个人布局: user_id > 0, is_public = False
    - 公共布局: created_by 管理员, is_public = True
    """

    __tablename__ = "kline_layouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="布局名称")
    description = Column(String(256), default="", comment="布局说明")
    layout_data = Column(Text, nullable=False, comment="布局配置(JSON字符串)")

    user_id = Column(Integer, nullable=True, index=True, comment="所属用户ID (个人布局)")
    is_public = Column(Boolean, default=False, index=True, comment="是否为公共布局")
    created_by = Column(Integer, nullable=True, comment="创建者用户ID")

    # 布局统计
    use_count = Column(Integer, default=0, comment="使用次数")
    is_default = Column(Boolean, default=False, comment="是否为默认公共布局")

    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
