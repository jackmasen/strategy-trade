"""
系统更新/备份/健康检测模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, BigInteger, Index
from backend.db.base import Base
from datetime import datetime


class SystemUpdateRecord(Base):
    """系统更新记录"""

    __tablename__ = "system_update_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(64), default="", comment="版本号")
    update_type = Column(String(16), default="upload", comment="更新方式: upload/github/rollback")
    source = Column(String(256), default="", comment="来源（文件名或GitHub tag）")
    status = Column(Integer, default=1, comment="状态: 1-进行中 2-成功 3-失败 4-已回滚")
    backup_id = Column(Integer, nullable=True, comment="关联备份ID")
    error_msg = Column(Text, default="", comment="错误信息")
    changelog = Column(Text, default="", comment="更新说明")
    file_size = Column(BigInteger, default=0, comment="文件大小(字节)")
    duration_sec = Column(Integer, default=0, comment="执行耗时(秒)")
    created_at = Column(DateTime, default=datetime.now, index=True)
    finished_at = Column(DateTime, nullable=True, comment="完成时间")


class SystemBackupRecord(Base):
    """系统备份记录"""

    __tablename__ = "system_backup_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backup_type = Column(String(32), default="manual", comment="类型: manual/auto/pre_update")
    file_name = Column(String(256), default="", comment="备份文件名")
    file_size = Column(BigInteger, default=0, comment="文件大小(字节)")
    includes_db = Column(Integer, default=1, comment="是否包含数据库: 1-是 0-否")
    includes_config = Column(Integer, default=1, comment="是否包含配置: 1-是 0-否")
    status = Column(Integer, default=1, comment="状态: 1-进行中 2-成功 3-失败")
    error_msg = Column(Text, default="", comment="错误信息")
    description = Column(String(256), default="", comment="备注")
    created_at = Column(DateTime, default=datetime.now, index=True)
    finished_at = Column(DateTime, nullable=True, comment="完成时间")


class SystemHealthReport(Base):
    """系统健康检测报告"""

    __tablename__ = "system_health_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    overall_status = Column(String(16), default="healthy", comment="整体状态: healthy/warning/critical")
    check_details = Column(Text, default="", comment="检测详情JSON")
    fixed_items = Column(Text, default="", comment="自动修复项JSON")
    freed_space_bytes = Column(BigInteger, default=0, comment="释放空间(字节)")
    created_at = Column(DateTime, default=datetime.now, index=True)
