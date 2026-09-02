"""
SQLAlchemy 基础模型模块
声明基类 Base，所有ORM模型继承自此处
"""
from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, func
from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    """全局 ORM 基类"""

    # 通用字段：主键ID + 创建时间 + 更新时间
    id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="主键ID")
    created_at = Column(DateTime, default=datetime.now, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime,
        default=datetime.now,
        server_default=func.now(),
        onupdate=datetime.now,
        comment="更新时间",
    )

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """自动从类名推导表名：CamelCase → snake_case + s 复数"""
        name = cls.__name__
        # CamelCase 转 snake_case
        result = []
        for i, c in enumerate(name):
            if c.isupper() and i > 0:
                result.append("_")
            result.append(c.lower())
        snake = "".join(result)
        # 简单复数处理
        if snake.endswith("s"):
            return snake
        if snake.endswith("y"):
            return snake[:-1] + "ies"
        return snake + "s"
