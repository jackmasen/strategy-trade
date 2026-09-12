"""
用户与权限相关模型
"""
from sqlalchemy import Column, Integer, String, Boolean, SmallInteger, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.db.base import Base


class User(Base):
    """系统用户表"""

    username = Column(String(64), unique=True, nullable=False, index=True, comment="登录账号")
    password_hash = Column(String(255), nullable=False, comment="密码哈希(BCrypt)")
    nickname = Column(String(64), default="", comment="昵称")
    email = Column(String(128), default="", index=True, comment="邮箱")
    phone = Column(String(32), default="", comment="手机号")
    avatar = Column(String(255), default="", comment="头像URL")
    role = Column(
        SmallInteger,
        default=1,
        comment="角色: 1-超级管理员 2-运营 3-只读访客",
    )
    two_factor_secret = Column(String(128), default="", comment="谷歌2FA密钥")
    two_factor_enabled = Column(Boolean, default=False, comment="是否启用2FA")
    must_change_password = Column(Boolean, default=False, comment="是否需要强制修改密码(默认密码/管理员重置后为True)")
    status = Column(SmallInteger, default=1, comment="状态: 1-启用 0-禁用")
    last_login_at = Column(DateTime, nullable=True, comment="最后登录时间")
    last_login_ip = Column(String(64), default="", comment="最后登录IP")
    remark = Column(Text, default="", comment="备注")

    # 关联
    exchange_accounts = relationship("ExchangeAccount", back_populates="owner", cascade="all, delete-orphan")
    strategies = relationship("StrategyConfig", back_populates="owner", cascade="all, delete-orphan")
    operation_logs = relationship("OperationLog", back_populates="user", cascade="all, delete-orphan")


class OperationLog(Base):
    """操作审计日志"""

    user_id = Column(Integer, ForeignKey("users.id"), index=True, comment="操作人ID")
    username = Column(String(64), default="", comment="冗余用户名")
    module = Column(String(64), index=True, comment="模块: user/exchange/strategy/trade/risk")
    action = Column(String(64), comment="动作: create/update/delete/login/exec")
    target = Column(String(255), default="", comment="操作对象")
    ip = Column(String(64), default="", comment="客户端IP")
    user_agent = Column(String(512), default="", comment="User-Agent")
    request_method = Column(String(16), default="", comment="HTTP方法")
    request_path = Column(String(255), default="", comment="请求路径")
    request_params = Column(Text, default="", comment="请求参数(脱敏)")
    response_code = Column(Integer, default=0, comment="响应状态码")
    cost_ms = Column(Integer, default=0, comment="耗时(毫秒)")
    detail = Column(Text, default="", comment="详细说明")

    user = relationship("User", back_populates="operation_logs")
