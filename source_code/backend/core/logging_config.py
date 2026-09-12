"""
日志配置 + 单例 Logger
使用 loguru，结构化日志，输出到控制台+文件+JSON
"""
import sys
from loguru import logger
from pathlib import Path

from backend.config import get_settings

settings = get_settings()

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)


def setup_logger() -> None:
    """初始化全局日志（在 main.py 启动时调用一次即可）"""
    # 移除默认 handler 避免重复
    logger.remove()

    # 控制台：彩色 + 精简
    logger.add(
        sys.stdout,
        level="DEBUG" if settings.APP_DEBUG else "INFO",
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level:<7}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        enqueue=True,
        backtrace=settings.APP_DEBUG,
        diagnose=settings.APP_DEBUG,
    )

    # 普通日志文件
    logger.add(
        _LOG_DIR / "app_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation="00:00",   # 每天轮转
        retention="30 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}",
        enqueue=True,
        encoding="utf-8",
    )

    # 错误日志单独文件
    logger.add(
        _LOG_DIR / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        rotation="00:00",
        retention="90 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}\n{exception}",
        enqueue=True,
        encoding="utf-8",
    )

    # 交易日志：单独文件，便于审计
    logger.add(
        _LOG_DIR / "trade_{time:YYYY-MM-DD}.log",
        level="INFO",
        filter=lambda r: r["extra"].get("log_type") == "trade",
        rotation="00:00",
        retention="180 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        enqueue=True,
        encoding="utf-8",
    )


# 导出结构化 logger 快捷方式
trade_logger = logger.bind(log_type="trade")

__all__ = ["logger", "trade_logger", "setup_logger"]
